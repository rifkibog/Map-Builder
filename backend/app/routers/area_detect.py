"""
Area Detect Router
-------------------
POST /api/area-detect

Accepts a user-drawn area polygon (WKT or list of [lng, lat] points),
fetches Google satellite tiles covering it, runs image processing to
detect roofs, and returns detected building polygons as WKT with
Plus-Code building_ids.

Safety limits:
- Max area: 4 km² (bounding box area)
- Max tile count hard cap: 3000 (safety net)
- Timeout-aware: asyncio tasks limited to 20 concurrent
"""

import math
import time
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from PIL import Image, ImageDraw
from io import BytesIO
from pydantic import BaseModel, Field
from shapely.geometry import Polygon, mapping

from app.services.tile_fetcher import (
    fetch_and_stitch,
    estimate_tile_count,
    cache_stats,
)
from app.services.image_processing import (
    DetectionParams,
    detect_roofs,
    contours_to_polygons,
)
from app.services.ai_detection import (
    detect_buildings_with_gemini,
    buildings_to_polygons,
    VertexAIError,
    VertexAINotConfigured,
)
from app.config import settings
from app.services.geo_transform import (
    make_pixel_to_lnglat,
    polygon_to_wkt,
    polygon_building_id,
    make_area_id,
)

# ---------------------------------------------------------------------------
MAX_AREA_KM2 = 1.0
MAX_TILE_COUNT = 800
DEFAULT_ZOOM = 20  # Google satellite detail zoom
MIN_ZOOM = 18
MAX_ZOOM = 21

router = APIRouter(prefix="/api/area-detect", tags=["area-detect"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------
class AreaPoint(BaseModel):
    lng: float
    lat: float


class DetectionOverrides(BaseModel):
    """Optional detection parameter overrides. Anything not set uses defaults."""
    # Backend selection: "gemini" (default) | "classical" (fallback CV)
    backend: Optional[str] = None
    min_area_m2: Optional[float] = None
    max_area_m2: Optional[float] = None
    min_aspect_ratio: Optional[float] = None
    max_aspect_ratio: Optional[float] = None
    min_solidity: Optional[float] = None
    canny_low: Optional[int] = None
    canny_high: Optional[int] = None
    approx_epsilon_frac: Optional[float] = None


class AreaDetectRequest(BaseModel):
    points: List[AreaPoint] = Field(..., min_items=3,
                                    description="Polygon vertices (lng/lat)")
    zoom: int = Field(DEFAULT_ZOOM, ge=MIN_ZOOM, le=MAX_ZOOM)
    params: Optional[DetectionOverrides] = None


class DetectedBuilding(BaseModel):
    polygon_area_id: str
    building_id: str
    polygon_rumah: str  # WKT


class AreaDetectResponse(BaseModel):
    area_id: str
    area_wkt: str
    bbox: List[float]  # [min_lng, min_lat, max_lng, max_lat]
    zoom: int
    tile_count: int
    image_size: List[int]  # [width, height]
    detected_count: int
    buildings: List[DetectedBuilding]
    timing_ms: dict  # { "fetch": ..., "process": ..., "total": ... }
    cache: dict


# ---------------------------------------------------------------------------
def _area_km2(min_lng, min_lat, max_lng, max_lat) -> float:
    """Rough area in km² for a lng/lat bounding box (mid-latitude)."""
    mid_lat = (min_lat + max_lat) / 2.0
    m_per_deg_lat = 111_320.0
    m_per_deg_lng = 111_320.0 * math.cos(math.radians(mid_lat))
    span_x_m = (max_lng - min_lng) * m_per_deg_lng
    span_y_m = (max_lat - min_lat) * m_per_deg_lat
    return (span_x_m * span_y_m) / 1_000_000.0


def _apply_overrides(base: DetectionParams,
                     ov: Optional[DetectionOverrides]) -> DetectionParams:
    if ov is None:
        return base
    updated = DetectionParams(**{**base.__dict__})
    # Copy fields that are not None
    for k in ("min_area_m2", "max_area_m2", "min_aspect_ratio",
              "max_aspect_ratio", "min_solidity", "canny_low", "canny_high",
              "approx_epsilon_frac"):
        v = getattr(ov, k, None)
        if v is not None:
            setattr(updated, k, v)
    return updated


# ---------------------------------------------------------------------------
# Main endpoint
# ---------------------------------------------------------------------------
@router.post("", response_model=AreaDetectResponse)
async def area_detect(req: AreaDetectRequest):
    t0 = time.time()

    # Build shapely polygon from user points
    ring = [(p.lng, p.lat) for p in req.points]
    # Ensure closed ring
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    area_poly = Polygon(ring)
    if not area_poly.is_valid or area_poly.area <= 0:
        raise HTTPException(status_code=400,
                            detail="Invalid polygon (self-intersection or zero area)")

    # Bounding box
    min_lng, min_lat, max_lng, max_lat = area_poly.bounds

    # Safety: max area
    area_km2 = _area_km2(min_lng, min_lat, max_lng, max_lat)
    if area_km2 > MAX_AREA_KM2:
        raise HTTPException(
            status_code=413,
            detail=f"Area {area_km2:.2f} km² exceeds max {MAX_AREA_KM2} km²",
        )

    # Safety: tile count
    tile_count = estimate_tile_count(min_lng, min_lat, max_lng, max_lat, req.zoom)
    if tile_count > MAX_TILE_COUNT:
        raise HTTPException(
            status_code=413,
            detail=(f"Estimated tile count {tile_count} exceeds cap "
                    f"{MAX_TILE_COUNT}. Reduce area or zoom."),
        )

    # ---------------- Fetch & stitch ----------------
    t_fetch_start = time.time()
    try:
        stitched = await fetch_and_stitch(min_lng, min_lat, max_lng, max_lat,
                                          zoom=req.zoom)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Tile fetch failed: {e}")
    t_fetch = time.time() - t_fetch_start

    image = stitched["image"]
    width, height = stitched["size"]

    # ---------------- Detection: Gemini AI by default, classical CV fallback ----------------
    t_proc_start = time.time()
    pixel_to_lnglat_fn = make_pixel_to_lnglat(stitched["bbox"], width, height)

    # Pick backend: "gemini" (default) | "classical"
    backend_choice = "gemini"
    if req.params and req.params.backend:
        backend_choice = req.params.backend.lower()

    detection_backend_used = backend_choice

    if backend_choice == "gemini":
        try:
            detected = await detect_buildings_with_gemini(
                image, project=settings.GCP_PROJECT
            )
            polygons = buildings_to_polygons(
                detected, pixel_to_lnglat_fn, clip_polygon=area_poly, use_mask=True
            )
        except VertexAINotConfigured as e:
            raise HTTPException(
                status_code=500,
                detail=f"Vertex AI not configured: {e}",
            )
        except VertexAIError as e:
            raise HTTPException(
                status_code=503,
                detail=f"AI detection service unavailable after retries: {e}",
            )
    else:
        # Classical CV fallback (legacy HSV+Canny pipeline)
        params = _apply_overrides(DetectionParams(), req.params)
        contours = detect_roofs(image, stitched["bbox"], params=params)
        polygons = contours_to_polygons(contours, pixel_to_lnglat_fn,
                                        clip_polygon=area_poly)

    t_proc = time.time() - t_proc_start

    # ---------------- Build response ----------------
    area_id = make_area_id()
    detected: List[DetectedBuilding] = []
    for poly in polygons:
        try:
            bid = polygon_building_id(poly, code_length=14)
        except Exception:
            continue
        detected.append(DetectedBuilding(
            polygon_area_id=area_id,
            building_id=bid,
            polygon_rumah=polygon_to_wkt(poly),
        ))

    return AreaDetectResponse(
        area_id=area_id,
        area_wkt=polygon_to_wkt(area_poly),
        bbox=[min_lng, min_lat, max_lng, max_lat],
        zoom=req.zoom,
        tile_count=tile_count,
        image_size=[width, height],
        detected_count=len(detected),
        buildings=detected,
        timing_ms={
            "fetch": int(t_fetch * 1000),
            "process": int(t_proc * 1000),
            "total": int((time.time() - t0) * 1000),
        },
        cache=cache_stats(),
    )


# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Preview endpoint — returns PNG with red polygon overlay for visual debug
# ---------------------------------------------------------------------------
@router.post("/preview", responses={200: {"content": {"image/png": {}}}})
async def area_detect_preview(req: AreaDetectRequest):
    """Same pipeline as /api/area-detect but returns PNG with overlay.

    Useful for visual debugging: see exactly which rooftops were detected
    and how well the polygons align with the actual buildings.
    """
    # Build shapely polygon
    ring = [(p.lng, p.lat) for p in req.points]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    area_poly = Polygon(ring)
    if not area_poly.is_valid or area_poly.area <= 0:
        raise HTTPException(status_code=400, detail="Invalid polygon")

    min_lng, min_lat, max_lng, max_lat = area_poly.bounds
    area_km2 = _area_km2(min_lng, min_lat, max_lng, max_lat)
    if area_km2 > MAX_AREA_KM2:
        raise HTTPException(status_code=413,
                            detail=f"Area {area_km2:.2f} km² exceeds max {MAX_AREA_KM2} km²")

    tile_count = estimate_tile_count(min_lng, min_lat, max_lng, max_lat, req.zoom)
    if tile_count > MAX_TILE_COUNT:
        raise HTTPException(status_code=413,
                            detail=f"Tile count {tile_count} > cap {MAX_TILE_COUNT}")

    # Fetch tiles
    try:
        stitched = await fetch_and_stitch(min_lng, min_lat, max_lng, max_lat,
                                          zoom=req.zoom)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Tile fetch failed: {e}")

    image = stitched["image"]
    width, height = stitched["size"]

    # Run detection — Gemini by default, classical CV if requested
    backend_choice = "gemini"
    if req.params and req.params.backend:
        backend_choice = req.params.backend.lower()

    # Contours: for preview we need pixel contours to draw on image
    from app.services.ai_detection import buildings_to_pixel_contours_for_preview
    contours = []

    if backend_choice == "gemini":
        try:
            detected = await detect_buildings_with_gemini(
                image, project=settings.GCP_PROJECT
            )
            contours = buildings_to_pixel_contours_for_preview(detected, use_mask=True)
        except (VertexAIError, VertexAINotConfigured) as e:
            # For preview, don't 503 — draw "Gemini failed" label on image
            import logging
            logging.warning(f"Gemini failed in preview, falling back: {e}")
            params = _apply_overrides(DetectionParams(), req.params)
            contours = detect_roofs(image, stitched["bbox"], params=params)
            backend_choice = "classical (fallback)"
    else:
        params = _apply_overrides(DetectionParams(), req.params)
        contours = detect_roofs(image, stitched["bbox"], params=params)

    # ---------------- Draw overlay ----------------
    # Use RGBA for semi-transparent red fill
    overlay = image.convert("RGBA").copy()
    draw = ImageDraw.Draw(overlay, "RGBA")

    # Draw user area polygon (yellow outline, thick)
    # Convert lng/lat -> pixel space using same inverse math
    from app.services.geo_transform import make_pixel_to_lnglat
    # We need the INVERSE: lnglat -> pixel. Since pixel_to_lnglat is linear
    # in pixel space, invert it directly.
    def lnglat_to_pixel(lng, lat):
        # Linear in longitude
        px = (lng - min_lng) / (max_lng - min_lng) * width
        # Mercator in latitude
        def lat_to_mercY(lt):
            return math.log(math.tan(math.pi / 4 + math.radians(lt) / 2))
        mY_top = lat_to_mercY(max_lat)
        mY_bot = lat_to_mercY(min_lat)
        py = (lat_to_mercY(lat) - mY_top) / (mY_bot - mY_top) * height
        return (px, py)

    # User area — yellow outline
    user_pts_px = [lnglat_to_pixel(lng, lat) for (lng, lat) in area_poly.exterior.coords]
    draw.line(user_pts_px, fill=(255, 255, 0, 255), width=3)

    # Detected roofs — red with semi-transparent fill
    detected_count = 0
    for cnt in contours:
        pts = [(float(px), float(py)) for px, py in cnt]
        # Close polygon for PIL
        if pts[0] != pts[-1]:
            pts.append(pts[0])
        # Semi-transparent red fill
        draw.polygon(pts, fill=(255, 0, 0, 100), outline=(255, 0, 0, 255))
        detected_count += 1

    # Composite overlay on base image
    final = Image.alpha_composite(image.convert("RGBA"), overlay)
    final = final.convert("RGB")

    # Add text label with count
    draw_final = ImageDraw.Draw(final)
    label = f"Detected: {detected_count} | Backend: {backend_choice} | Zoom: {req.zoom} | {width}x{height}px"
    # Draw shadow + text for readability
    draw_final.text((12, 12), label, fill=(0, 0, 0))
    draw_final.text((10, 10), label, fill=(255, 255, 255))

    # Encode PNG
    buf = BytesIO()
    final.save(buf, format="PNG", optimize=True)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="image/png",
        headers={
            "X-Detected-Count": str(detected_count),
            "X-Tile-Count": str(tile_count),
            "X-Image-Size": f"{width}x{height}",
            "Cache-Control": "no-cache",
        },
    )


# ---------------------------------------------------------------------------
@router.get("/health")
async def health():
    return {"status": "ok", "service": "area-detect", "cache": cache_stats()}
