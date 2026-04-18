"""
AI Detection Service — Vertex AI Gemini 2.5 Flash
--------------------------------------------------
Detect building rooftops in aerial imagery using Google's Gemini 2.5 Flash
multimodal model. Returns segmentation masks per building, which we convert
to WKT polygons.

Pipeline:
  1. Encode stitched satellite image as base64
  2. Send to Gemini 2.5 Flash with structured prompt
  3. Parse JSON response (list of {box_2d, mask, label})
  4. Decode each base64 PNG mask
  5. Resize mask to match its bounding box in original image
  6. Find contours -> pixel polygons
  7. Convert pixel polygons to lng/lat polygons

Retry: 2 retries with 5-second delay on timeout/transient errors.
Fallback: raises VertexAIError after retries exhausted (caller handles 503).
"""

import asyncio
import base64
import json
import logging
import re
from dataclasses import dataclass
from io import BytesIO
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image
from shapely.geometry import Polygon
from shapely.validation import make_valid

# Vertex AI — imported lazily to avoid import cost if not used
# and to make testing easier
try:
    from google import genai
    from google.genai import types as genai_types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_LOCATION = "asia-southeast1"  # Jakarta region for low latency
MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 5
REQUEST_TIMEOUT = 60  # seconds per attempt


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------
class VertexAIError(Exception):
    """Raised when Vertex AI fails after all retries."""
    pass


class VertexAINotConfigured(Exception):
    """Raised when google-genai library is not installed."""
    pass


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class DetectedBuilding:
    """One building detected by Gemini."""
    bbox: Tuple[int, int, int, int]  # (x0, y0, x1, y1) in ORIGINAL image pixels
    mask_pixels: Optional[np.ndarray]  # 2D uint8 array, 0/255, same size as bbox
    label: str
    confidence: float = 1.0


# ---------------------------------------------------------------------------
# Prompt engineering
# ---------------------------------------------------------------------------
DETECTION_PROMPT = """You are analyzing a high-resolution Google satellite image of a residential area in Indonesia (aerial view, top-down).

Task: Detect EVERY building rooftop visible in this image, no matter how many. This is a building census.

What COUNTS as a rooftop:
- House roofs (any color: black, red, grey, blue, white, brown)
- Commercial building roofs
- Shophouse (ruko) roofs
- Warehouse roofs

What does NOT count:
- Roads, paths, driveways
- Trees, vegetation, grass, shrubs
- Empty land, dirt, sand
- Construction sites WITHOUT completed roofs (only foundations/walls)
- Water (rivers, pools, ponds)
- Vehicles, cars, motorcycles
- Shadows on the ground

For each rooftop, return:
- box_2d: [y0, x0, y1, x1] normalized 0-1000
- mask: base64-encoded PNG segmentation mask (covering only the roof)
- label: "rooftop"

Important: Return ALL rooftops you can see, even small ones. A typical residential area has DOZENS to HUNDREDS of buildings. Do not stop at 5 or 10.

Mask size: KEEP MASKS SMALL to fit many buildings in response. Resolution 32x32 or 64x64 is enough — we'll resize on our end.

Output format: JSON array only, no markdown code fences, no commentary.
Example:
[{"box_2d": [120, 340, 180, 420], "mask": "iVBORw0KGgoAAAANS...", "label": "rooftop"}]
"""

# Prompt variant for bbox-only fallback (no mask, fits many more buildings)
DETECTION_PROMPT_BBOX_ONLY = """You are analyzing a high-resolution Google satellite image of a residential area in Indonesia (aerial view, top-down).

Task: Detect EVERY building rooftop visible in this image. This is a building census.

What COUNTS as a rooftop:
- House roofs (any color: black, red, grey, blue, white, brown)
- Commercial building roofs
- Shophouse (ruko) roofs
- Warehouse roofs

What does NOT count:
- Roads, paths, driveways
- Trees, vegetation, grass
- Empty land, dirt, sand
- Construction sites WITHOUT completed roofs
- Water, vehicles, shadows

For each rooftop, return ONLY the bounding box (no mask):
- box_2d: [y0, x0, y1, x1] normalized 0-1000
- label: "rooftop"

Important: Return ALL rooftops you can see — dozens to hundreds. Do not stop early.

Output: JSON array ONLY, no markdown, no commentary.
Example:
[{"box_2d": [120, 340, 180, 420], "label": "rooftop"}]
"""


# ---------------------------------------------------------------------------
# Client initialization
# ---------------------------------------------------------------------------
_client = None

def get_client(project: str):
    """Lazy-init Vertex AI client. Reuses connection across calls."""
    global _client
    if _client is not None:
        return _client
    if not GENAI_AVAILABLE:
        raise VertexAINotConfigured(
            "google-genai library not installed. "
            "Add 'google-genai' to requirements.txt"
        )
    _client = genai.Client(
        vertexai=True,
        project=project,
        location=GEMINI_LOCATION,
    )
    return _client


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
async def detect_buildings_with_gemini(
    image: Image.Image,
    project: str,
) -> List[DetectedBuilding]:
    """Detect buildings in image using Gemini 2.5 Flash with retry logic.

    Args:
        image: PIL Image (RGB) of the stitched satellite area
        project: GCP project ID

    Returns:
        List of DetectedBuilding. May be empty if Gemini returns nothing,
        but NOT if API fails — in that case VertexAIError is raised.

    Raises:
        VertexAIError: After all retries exhausted.
        VertexAINotConfigured: If google-genai is not installed.
    """
    client = get_client(project)
    width, height = image.size

    # Encode image as PNG bytes (Gemini accepts PNG/JPEG inline)
    buf = BytesIO()
    image.save(buf, format="PNG", optimize=True)
    image_bytes = buf.getvalue()

    last_error: Optional[Exception] = None

    # Strategy: try with mask first. If response is truncated / 0 buildings
    # recovered AFTER parsing, fall back to bbox-only prompt on retry.
    attempt_configs = [
        {"prompt": DETECTION_PROMPT, "mode": "mask"},           # attempt 1
        {"prompt": DETECTION_PROMPT, "mode": "mask"},           # attempt 2 (retry)
        {"prompt": DETECTION_PROMPT_BBOX_ONLY, "mode": "bbox"}, # attempt 3 fallback
    ]

    for attempt, cfg in enumerate(attempt_configs):
        try:
            logger.info(
                f"Gemini detection attempt {attempt + 1}/{len(attempt_configs)} "
                f"(mode={cfg['mode']})"
            )
            response = await _call_gemini(client, image_bytes, prompt=cfg["prompt"])
            buildings = _parse_response(response, width, height)

            if buildings:
                logger.info(f"Gemini detected {len(buildings)} buildings "
                            f"(mode={cfg['mode']}, attempt={attempt + 1})")
                return buildings

            # 0 buildings returned — treat as soft failure, try again
            logger.warning(f"Gemini returned 0 buildings on attempt {attempt + 1}")
            last_error = RuntimeError(f"Empty result in mode={cfg['mode']}")

        except VertexAINotConfigured:
            raise  # don't retry, it's a config issue

        except Exception as e:
            last_error = e
            logger.warning(f"Gemini attempt {attempt + 1} failed: {e}")

        # Sleep before next attempt (except after last)
        if attempt < len(attempt_configs) - 1:
            await asyncio.sleep(RETRY_DELAY_SECONDS)

    # Even bbox-only returned 0 or failed — surface as VertexAIError
    raise VertexAIError(
        f"Vertex AI returned no buildings after {len(attempt_configs)} attempts "
        f"(including bbox-only fallback). Last error: {last_error}"
    )


# ---------------------------------------------------------------------------
# Gemini API call
# ---------------------------------------------------------------------------
async def _call_gemini(client, image_bytes: bytes,
                       prompt: str = None) -> str:
    """Single call to Gemini — returns raw text response.

    Args:
        prompt: Override prompt (e.g. DETECTION_PROMPT_BBOX_ONLY for fallback)
    """
    if prompt is None:
        prompt = DETECTION_PROMPT

    # Build request parts: image + prompt
    image_part = genai_types.Part.from_bytes(
        data=image_bytes,
        mime_type="image/png",
    )

    # Configure to encourage reasonable output length & temperature
    config = genai_types.GenerateContentConfig(
        temperature=0.2,   # low temp for deterministic detection
        max_output_tokens=65536,  # max for Gemini 2.5 Flash; prevents mask truncation
        response_mime_type="application/json",
    )

    # Run blocking SDK call in executor to not block asyncio loop
    loop = asyncio.get_event_loop()
    response = await asyncio.wait_for(
        loop.run_in_executor(
            None,
            lambda: client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[image_part, prompt],
                config=config,
            )
        ),
        timeout=REQUEST_TIMEOUT,
    )

    if not response.text:
        raise RuntimeError("Gemini returned empty response")

    return response.text


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------
def _extract_partial_json_objects(text: str) -> list:
    """Recover valid JSON objects from truncated text.

    Scans for balanced {...} braces (ignoring braces inside strings)
    and attempts to json.loads each. Returns list of successfully
    parsed objects. Used when the full JSON array is truncated.
    """
    items = []
    depth = 0
    start = -1
    in_string = False
    escape = False

    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                snippet = text[start : i + 1]
                try:
                    obj = json.loads(snippet)
                    if isinstance(obj, dict):
                        items.append(obj)
                except json.JSONDecodeError:
                    pass
                start = -1

    return items


def _parse_response(raw_text: str, img_width: int, img_height: int) -> List[DetectedBuilding]:
    """Parse Gemini JSON response into DetectedBuilding list.

    Robust to response truncation: if the full JSON fails to parse,
    tries to extract as many valid {...} objects as possible from the
    partial response.
    """
    # Strip markdown fences if Gemini didn't follow instructions
    text = raw_text.strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    items = None
    try:
        items = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"Gemini JSON parse failed ({e}). Attempting recovery...")

        # Strategy 1: maybe wrapped in {"detections": [...]}
        try:
            wrapped = json.loads(text)
            items = wrapped.get("detections") or wrapped.get("rooftops") or []
        except Exception:
            pass

        # Strategy 2: partial-recovery — extract valid {...} objects
        # one by one using a bracket-balanced scanner
        if items is None:
            items = _extract_partial_json_objects(text)
            if items:
                logger.info(f"Recovered {len(items)} buildings from truncated response")
            else:
                logger.error(f"Recovery failed. Raw (first 300 chars): {text[:300]}")
                return []

    if not isinstance(items, list):
        logger.error(f"Expected list from Gemini, got {type(items)}")
        return []

    buildings: List[DetectedBuilding] = []
    for item in items:
        if not isinstance(item, dict):
            continue

        box_2d = item.get("box_2d") or item.get("bbox")
        if not box_2d or len(box_2d) != 4:
            continue

        # Convert from normalized 0-1000 to original image pixels
        # Gemini format: [y0, x0, y1, x1] normalized to 0-1000
        y0_norm, x0_norm, y1_norm, x1_norm = box_2d
        x0 = int(x0_norm / 1000.0 * img_width)
        y0 = int(y0_norm / 1000.0 * img_height)
        x1 = int(x1_norm / 1000.0 * img_width)
        y1 = int(y1_norm / 1000.0 * img_height)

        # Clamp to image bounds
        x0 = max(0, min(x0, img_width - 1))
        x1 = max(0, min(x1, img_width - 1))
        y0 = max(0, min(y0, img_height - 1))
        y1 = max(0, min(y1, img_height - 1))

        if x1 <= x0 or y1 <= y0:
            continue

        # Decode mask if present
        mask_pixels = None
        mask_str = item.get("mask")
        if mask_str and isinstance(mask_str, str):
            mask_pixels = _decode_mask(mask_str, (x1 - x0, y1 - y0))

        label = item.get("label") or "rooftop"

        buildings.append(DetectedBuilding(
            bbox=(x0, y0, x1, y1),
            mask_pixels=mask_pixels,
            label=label,
        ))

    return buildings


def _decode_mask(mask_str: str, target_size: Tuple[int, int]) -> Optional[np.ndarray]:
    """Decode base64 PNG mask, resize to target bbox size.

    Args:
        mask_str: base64 string (may include data:image/png;base64, prefix)
        target_size: (width, height) in pixels

    Returns:
        2D uint8 array (0 = background, 255 = building), or None on failure
    """
    try:
        # Strip data URL prefix if present
        if mask_str.startswith("data:"):
            mask_str = mask_str.split(",", 1)[1]

        raw = base64.b64decode(mask_str)
        mask_img = Image.open(BytesIO(raw)).convert("L")  # grayscale

        # Resize to match bbox dimensions
        tw, th = target_size
        if tw > 0 and th > 0:
            mask_img = mask_img.resize((tw, th), Image.NEAREST)

        arr = np.array(mask_img, dtype=np.uint8)
        # Threshold to binary: > 127 = foreground
        arr = (arr > 127).astype(np.uint8) * 255
        return arr

    except Exception as e:
        logger.warning(f"Mask decode failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Convert detected buildings -> shapely Polygons in lng/lat
# ---------------------------------------------------------------------------
def buildings_to_polygons(
    buildings: List[DetectedBuilding],
    pixel_to_lnglat_fn,
    clip_polygon: Polygon = None,
    use_mask: bool = True,
) -> List[Polygon]:
    """Convert DetectedBuilding list -> list of shapely Polygons (lng/lat).

    Args:
        buildings: from detect_buildings_with_gemini()
        pixel_to_lnglat_fn: (px, py) -> (lng, lat) for full image
        clip_polygon: clip to user's drawn area (optional)
        use_mask: if True, use segmentation contour; if False, use bbox rectangle

    Returns:
        List of valid shapely Polygons in lng/lat coordinates.
    """
    polygons: List[Polygon] = []

    for b in buildings:
        x0, y0, x1, y1 = b.bbox
        pixel_contours: List[np.ndarray] = []

        if use_mask and b.mask_pixels is not None:
            # Find contours on the mask (coords relative to bbox)
            contours, _ = cv2.findContours(
                b.mask_pixels, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            if contours:
                # Use largest contour
                largest = max(contours, key=cv2.contourArea)
                if cv2.contourArea(largest) >= 9:  # min 9 pixels
                    # Simplify polygon
                    eps = 0.01 * cv2.arcLength(largest, True)
                    approx = cv2.approxPolyDP(largest, eps, True)
                    if len(approx) >= 3:
                        # Shift to global image coords
                        shifted = approx.reshape(-1, 2) + np.array([x0, y0])
                        pixel_contours.append(shifted)

        if not pixel_contours:
            # Fallback to bbox rectangle
            rect = np.array([
                [x0, y0], [x1, y0], [x1, y1], [x0, y1]
            ], dtype=np.int32)
            pixel_contours.append(rect)

        for cnt in pixel_contours:
            coords = [pixel_to_lnglat_fn(float(px), float(py)) for px, py in cnt]
            if len(coords) < 3:
                continue
            poly = Polygon(coords)

            if not poly.is_valid:
                poly = make_valid(poly)
                if poly.geom_type == "MultiPolygon":
                    poly = max(poly.geoms, key=lambda g: g.area)
                elif poly.geom_type != "Polygon":
                    continue

            if poly.is_empty or poly.area <= 0:
                continue

            # Clip to user area
            if clip_polygon is not None:
                clipped = poly.intersection(clip_polygon)
                if clipped.is_empty:
                    continue
                if clipped.geom_type == "Polygon":
                    poly = clipped
                elif clipped.geom_type == "MultiPolygon":
                    poly = max(clipped.geoms, key=lambda g: g.area)
                else:
                    continue

            polygons.append(poly)

    return polygons


# ---------------------------------------------------------------------------
# Preview helper: return pixel contours (for drawing overlay on image)
# ---------------------------------------------------------------------------
def buildings_to_pixel_contours_for_preview(
    buildings: List[DetectedBuilding],
    use_mask: bool = True,
) -> List[np.ndarray]:
    """Extract pixel contours (in original image pixel coords) for preview overlay.

    Returns list of (N, 2) ndarrays for drawing polygons on the image.
    """
    out: List[np.ndarray] = []
    for b in buildings:
        x0, y0, x1, y1 = b.bbox

        if use_mask and b.mask_pixels is not None:
            contours, _ = cv2.findContours(
                b.mask_pixels, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            if contours:
                largest = max(contours, key=cv2.contourArea)
                if cv2.contourArea(largest) >= 9:
                    eps = 0.01 * cv2.arcLength(largest, True)
                    approx = cv2.approxPolyDP(largest, eps, True)
                    if len(approx) >= 3:
                        shifted = approx.reshape(-1, 2) + np.array([x0, y0])
                        out.append(shifted)
                        continue

        # Fallback: bbox rectangle
        rect = np.array([
            [x0, y0], [x1, y0], [x1, y1], [x0, y1]
        ], dtype=np.int32)
        out.append(rect)

    return out


# ===========================================================================
# Phase 1.5 — Tiled detection (Plan C)
# ===========================================================================
from app.services.tile_splitter import ImageTile, split_image_into_tiles


async def _detect_one_tile(
    client,
    tile: ImageTile,
    semaphore: asyncio.Semaphore,
) -> List[DetectedBuilding]:
    """Call Gemini for a single tile, bounded by semaphore."""
    async with semaphore:
        tile_w, tile_h = tile.size
        logger.info(f"Tile {tile.tile_id}: starting Gemini detection ({tile_w}x{tile_h})")

        # Encode tile image
        buf = BytesIO()
        tile.image.save(buf, format="PNG", optimize=True)
        image_bytes = buf.getvalue()

        # Use main detection logic (retry + fallback), but on tile image
        # We reuse _call_gemini + _parse_response, not detect_buildings_with_gemini
        # because we want per-tile control
        attempt_configs = [
            {"prompt": DETECTION_PROMPT, "mode": "mask"},
            {"prompt": DETECTION_PROMPT_BBOX_ONLY, "mode": "bbox"},  # skip mask-retry, go straight to bbox fallback
        ]

        for attempt, cfg in enumerate(attempt_configs):
            try:
                response = await _call_gemini(client, image_bytes, prompt=cfg["prompt"])
                buildings = _parse_response(response, tile_w, tile_h)
                if buildings:
                    logger.info(f"Tile {tile.tile_id}: detected {len(buildings)} (mode={cfg['mode']}, attempt={attempt + 1})")
                    return buildings
                logger.warning(f"Tile {tile.tile_id}: attempt {attempt + 1} returned 0 buildings")
            except Exception as e:
                logger.warning(f"Tile {tile.tile_id}: attempt {attempt + 1} failed: {e!r} (type={type(e).__name__})")
            if attempt < len(attempt_configs) - 1:
                await asyncio.sleep(2)  # shorter delay for tile-level retry

        logger.warning(f"Tile {tile.tile_id}: all attempts failed, returning 0")
        return []


async def detect_buildings_tiled(
    image: Image.Image,
    bbox_full: tuple,
    project: str,
    grid_size: int = 3,
    overlap_ratio: float = 0.10,
    concurrency: int = 3,
) -> List[DetectedBuilding]:
    """
    Detect buildings in a large image by splitting into grid_size^2 tiles
    and calling Gemini per tile in parallel (concurrency-limited).

    Returns list of DetectedBuilding with bbox/mask in GLOBAL (full-image)
    pixel coordinates, so downstream polygon conversion can use the
    full-image pixel_to_lnglat function.

    Args:
        image: full stitched satellite image (RGB)
        bbox_full: (min_lng, min_lat, max_lng, max_lat) of full image
        project: GCP project ID
        grid_size: N for NxN grid (default 3 = 9 tiles)
        overlap_ratio: tile overlap ratio (default 0.10 = 10%)
        concurrency: max parallel Gemini calls (default 3)

    Raises:
        VertexAIError: if ALL tiles fail (catastrophic).
        VertexAINotConfigured: if google-genai not installed.
    """
    client = get_client(project)
    width, height = image.size

    # Split image into tiles
    tiles = split_image_into_tiles(image, bbox_full, grid_size, overlap_ratio)
    logger.info(f"Split {width}x{height} image into {len(tiles)} tiles ({grid_size}x{grid_size}, overlap={overlap_ratio:.0%})")

    # Parallel Gemini calls with concurrency limit
    sem = asyncio.Semaphore(concurrency)
    tasks = [_detect_one_tile(client, tile, sem) for tile in tiles]
    tile_results: List[List[DetectedBuilding]] = await asyncio.gather(*tasks, return_exceptions=False)

    # Check if all tiles failed
    total_detections = sum(len(r) for r in tile_results)
    successful_tiles = sum(1 for r in tile_results if len(r) > 0)
    logger.info(f"Tiled detection: {successful_tiles}/{len(tiles)} tiles returned buildings, total raw = {total_detections}")

    if total_detections == 0:
        raise VertexAIError(
            f"All {len(tiles)} tiles returned 0 buildings. "
            "Gemini may be rate-limited or image content unsupported."
        )

    # Convert tile-local bboxes/masks → GLOBAL image coords
    # Each tile's (x0, y0, x1, y1) are in tile-local pixels, starting from (0,0).
    # Global position: add tile's pixel offset within full image.
    all_detections: List[DetectedBuilding] = []

    # Compute tile pixel offset from its geo bbox
    # (inverse of what tile_splitter did: tile bbox → pixel offset in full image)
    full_min_lng, full_min_lat, full_max_lng, full_max_lat = bbox_full

    def lnglat_to_fullpx(lng, lat):
        """Map lng/lat → full image pixel coord."""
        import math as _math
        px = (lng - full_min_lng) / (full_max_lng - full_min_lng) * width
        def _lat_to_mY(lt):
            return _math.log(_math.tan(_math.pi / 4 + _math.radians(lt) / 2))
        mY_top = _lat_to_mY(full_max_lat)
        mY_bot = _lat_to_mY(full_min_lat)
        py = (_lat_to_mY(lat) - mY_top) / (mY_bot - mY_top) * height
        return px, py

    for tile, detections in zip(tiles, tile_results):
        if not detections:
            continue
        # Get tile's top-left pixel offset in full image
        tmin_lng, tmin_lat, tmax_lng, tmax_lat = tile.bbox_geo
        ox, oy = lnglat_to_fullpx(tmin_lng, tmax_lat)  # top-left of tile (north-west corner)

        for d in detections:
            # Shift bbox from tile-local → full-image coords
            x0, y0, x1, y1 = d.bbox
            new_bbox = (
                int(round(x0 + ox)),
                int(round(y0 + oy)),
                int(round(x1 + ox)),
                int(round(y1 + oy)),
            )
            # mask_pixels stays the same size — it's relative to bbox
            all_detections.append(DetectedBuilding(
                bbox=new_bbox,
                mask_pixels=d.mask_pixels,
                label=d.label,
                confidence=d.confidence,
            ))

    logger.info(f"After coord shift: {len(all_detections)} detections in full image space")
    return all_detections
