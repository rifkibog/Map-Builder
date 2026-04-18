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
from app.services.geo_transform import (
    make_pixel_to_lnglat,
    polygon_to_wkt,
    polygon_building_id,
    make_area_id,
)

# ---------------------------------------------------------------------------
MAX_AREA_KM2 = 4.0
MAX_TILE_COUNT = 3000
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

    # ---------------- Image processing ----------------
    t_proc_start = time.time()
    params = _apply_overrides(DetectionParams(), req.params)
    contours = detect_roofs(image, stitched["bbox"], params=params)

    pixel_to_lnglat_fn = make_pixel_to_lnglat(stitched["bbox"], width, height)
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
@router.get("/health")
async def health():
    return {"status": "ok", "service": "area-detect", "cache": cache_stats()}
