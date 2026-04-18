"""
Google Satellite Tile Fetcher
------------------------------
Fetches tiles from Google Satellite (mt1.google.com, undocumented), stitches
them into a single image covering a geographic bounding box, and converts
between pixel and geographic coordinates.

Notes:
- Uses Web Mercator projection (EPSG:3857), same as standard slippy map tiles.
- Parallel download with semaphore limit (20 concurrent) to avoid throttling.
- In-memory cache (TTL 1 hour) to speed up repeated captures of same area.
- Max tile count safeguarded at router level (area limit).
"""

import asyncio
import math
import time
from io import BytesIO
from typing import Tuple, Dict, Any

import httpx
from PIL import Image

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TILE_SIZE = 256  # Google uses 256x256 tiles
GOOGLE_TILE_URL = "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"
USER_AGENT = "building-viewer/1.0 (research simulation)"
CONCURRENT_LIMIT = 20
REQUEST_TIMEOUT = 15.0  # seconds per tile

# ---------------------------------------------------------------------------
# In-memory tile cache: key = (z, x, y), value = (bytes, expiry_ts)
# ---------------------------------------------------------------------------
_TILE_CACHE: Dict[Tuple[int, int, int], Tuple[bytes, float]] = {}
CACHE_TTL = 3600  # 1 hour


def _cache_get(key):
    entry = _TILE_CACHE.get(key)
    if entry is None:
        return None
    data, expiry = entry
    if time.time() > expiry:
        _TILE_CACHE.pop(key, None)
        return None
    return data


def _cache_set(key, data):
    _TILE_CACHE[key] = (data, time.time() + CACHE_TTL)


def cache_stats():
    """Return current cache size (for debugging / monitoring)."""
    return {"entries": len(_TILE_CACHE), "ttl_seconds": CACHE_TTL}


# ---------------------------------------------------------------------------
# Web Mercator math
# ---------------------------------------------------------------------------
def lnglat_to_tile(lng: float, lat: float, zoom: int) -> Tuple[int, int]:
    """Convert lng/lat to tile (x, y) at given zoom level."""
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    x = int((lng + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def lnglat_to_pixel(lng: float, lat: float, zoom: int) -> Tuple[float, float]:
    """Convert lng/lat to global pixel coordinates at given zoom."""
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    px = (lng + 180.0) / 360.0 * n * TILE_SIZE
    py = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n * TILE_SIZE
    return px, py


def pixel_to_lnglat(px: float, py: float, zoom: int) -> Tuple[float, float]:
    """Convert global pixel coordinates back to lng/lat."""
    n = 2.0 ** zoom
    lng = px / (n * TILE_SIZE) * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * py / (n * TILE_SIZE))))
    lat = math.degrees(lat_rad)
    return lng, lat


def estimate_tile_count(min_lng, min_lat, max_lng, max_lat, zoom) -> int:
    """Estimate how many tiles needed for a bounding box at given zoom."""
    x_min, y_max = lnglat_to_tile(min_lng, min_lat, zoom)
    x_max, y_min = lnglat_to_tile(max_lng, max_lat, zoom)
    return (x_max - x_min + 1) * (y_max - y_min + 1)


# ---------------------------------------------------------------------------
# Tile download
# ---------------------------------------------------------------------------
async def _fetch_tile(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    z: int, x: int, y: int,
) -> Tuple[Tuple[int, int, int], bytes]:
    """Download a single tile (with cache check and semaphore gating)."""
    key = (z, x, y)
    cached = _cache_get(key)
    if cached is not None:
        return key, cached

    async with sem:
        url = GOOGLE_TILE_URL.format(x=x, y=y, z=z)
        resp = await client.get(url, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        data = resp.content
        _cache_set(key, data)
        return key, data


# ---------------------------------------------------------------------------
# Stitch tiles into one big image cropped to bounding box
# ---------------------------------------------------------------------------
async def fetch_and_stitch(
    min_lng: float, min_lat: float,
    max_lng: float, max_lat: float,
    zoom: int = 20,
) -> Dict[str, Any]:
    """
    Download all tiles needed to cover the bbox, stitch them, and crop
    precisely to the requested bounding box.

    Returns dict with:
      - image (PIL.Image) cropped RGB
      - bbox (min_lng, min_lat, max_lng, max_lat)  <-- same as input, for reference
      - size (width, height) in pixels
      - zoom
      - tile_count (how many tiles were fetched)
    """
    # Tile range
    x_min, y_max = lnglat_to_tile(min_lng, min_lat, zoom)
    x_max, y_min = lnglat_to_tile(max_lng, max_lat, zoom)
    tile_count = (x_max - x_min + 1) * (y_max - y_min + 1)

    sem = asyncio.Semaphore(CONCURRENT_LIMIT)
    tasks = []
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        for x in range(x_min, x_max + 1):
            for y in range(y_min, y_max + 1):
                tasks.append(_fetch_tile(client, sem, zoom, x, y))
        results = await asyncio.gather(*tasks)

    # Assemble mosaic in raw tile pixel space
    width = (x_max - x_min + 1) * TILE_SIZE
    height = (y_max - y_min + 1) * TILE_SIZE
    mosaic = Image.new("RGB", (width, height), (0, 0, 0))

    for (z, x, y), data in results:
        tile_img = Image.open(BytesIO(data)).convert("RGB")
        px = (x - x_min) * TILE_SIZE
        py = (y - y_min) * TILE_SIZE
        mosaic.paste(tile_img, (px, py))

    # Crop precisely to requested bbox
    # Global pixel coords of the mosaic's top-left tile corner:
    mosaic_origin_px = x_min * TILE_SIZE
    mosaic_origin_py = y_min * TILE_SIZE

    # Global pixel coords of the bbox corners
    # NB: in Web Mercator, max_lat (north) has SMALLER y than min_lat (south)
    bbox_left, bbox_top = lnglat_to_pixel(min_lng, max_lat, zoom)
    bbox_right, bbox_bottom = lnglat_to_pixel(max_lng, min_lat, zoom)

    # Convert to local mosaic coordinates
    left = int(round(bbox_left - mosaic_origin_px))
    top = int(round(bbox_top - mosaic_origin_py))
    right = int(round(bbox_right - mosaic_origin_px))
    bottom = int(round(bbox_bottom - mosaic_origin_py))

    cropped = mosaic.crop((left, top, right, bottom))

    return {
        "image": cropped,
        "bbox": (min_lng, min_lat, max_lng, max_lat),
        "size": cropped.size,  # (width, height)
        "zoom": zoom,
        "tile_count": tile_count,
    }
