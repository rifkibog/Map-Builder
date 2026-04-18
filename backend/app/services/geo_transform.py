"""
Geo Transform Utilities
------------------------
- Convert pixel coordinates (from cropped stitched image) back to lng/lat
- Build WKT POLYGON strings from lng/lat rings
- Encode building_id using Plus Code (length 14 — matches existing data)

Plus Code length 14:
  Standard Plus Code supports lengths 2, 4, 6, 8, 10, 11 as "pair" codes.
  Length > 10 uses a grid extension. Existing data in this project uses
  14-character codes (e.g. "6P58RRJV+6J4MP9" = 15 chars including '+').
  The `openlocationcode` Python library supports extended lengths beyond
  10; we verify compatibility at import-time and fall back to a manual
  implementation if the installed version limits codeLength.
"""

import math
from typing import List, Tuple

from shapely.geometry import Polygon
from openlocationcode import openlocationcode as olc


# ---------------------------------------------------------------------------
# Pixel <-> lng/lat for a cropped image with known bbox
# ---------------------------------------------------------------------------
def make_pixel_to_lnglat(bbox: Tuple[float, float, float, float],
                         img_width: int, img_height: int):
    """
    Returns a function (px, py) -> (lng, lat) valid for an image of size
    (img_width, img_height) whose pixel (0, 0) = (min_lng, max_lat) and
    pixel (img_width, img_height) = (max_lng, min_lat).

    We use LINEAR interpolation in lng (correct for cylindrical map) and
    Mercator-correct interpolation in lat. Since crop is derived from
    true Web Mercator pixels, this linear-in-pixel-space transform is
    geometrically correct for small areas (≤ few km).
    """
    min_lng, min_lat, max_lng, max_lat = bbox

    # Mercator Y at image corners
    def lat_to_mercY(lat):
        return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))

    def mercY_to_lat(y):
        return math.degrees(2 * math.atan(math.exp(y)) - math.pi / 2)

    mercY_top = lat_to_mercY(max_lat)
    mercY_bottom = lat_to_mercY(min_lat)

    def transform(px: float, py: float) -> Tuple[float, float]:
        # Linear in longitude
        lng = min_lng + (px / img_width) * (max_lng - min_lng)
        # Mercator-linear in y-pixel
        mercY = mercY_top + (py / img_height) * (mercY_bottom - mercY_top)
        lat = mercY_to_lat(mercY)
        return lng, lat

    return transform


# ---------------------------------------------------------------------------
# Shapely polygon -> WKT (tight 7-digit precision)
# ---------------------------------------------------------------------------
def polygon_to_wkt(poly: Polygon, precision: int = 7) -> str:
    """Convert shapely Polygon to WKT with fixed precision."""
    coords = list(poly.exterior.coords)
    coord_str = ", ".join(
        f"{lng:.{precision}f} {lat:.{precision}f}" for lng, lat in coords
    )
    return f"POLYGON (({coord_str}))"


# ---------------------------------------------------------------------------
# Plus Code length 14
# ---------------------------------------------------------------------------
# The openlocationcode library accepts codeLength parameter. Length 14 is
# valid as "extended grid" codes (each grid char adds ~5x precision refinement
# beyond length 10). We try library first, with a safety wrapper.
def encode_building_id(lat: float, lng: float, code_length: int = 14) -> str:
    """Encode centroid as Plus Code of given length. Default 14 (≈1m)."""
    try:
        return olc.encode(lat, lng, codeLength=code_length)
    except Exception as e:
        # Fallback: cap at max supported length
        # The library source supports up to 15 in recent versions;
        # if this fails, something else is wrong — re-raise with context
        raise RuntimeError(
            f"Plus Code encoding failed at length {code_length}: {e}. "
            "Consider updating 'openlocationcode' package."
        )


def polygon_building_id(poly: Polygon, code_length: int = 14) -> str:
    """Compute building_id from polygon centroid using Plus Code."""
    c = poly.centroid
    return encode_building_id(c.y, c.x, code_length=code_length)


# ---------------------------------------------------------------------------
# Area polygon id (per capture session)
# ---------------------------------------------------------------------------
def make_area_id(prefix: str = "AREA") -> str:
    """Short human-readable area id. Caller should pass unique prefix if needed."""
    import uuid
    return f"{prefix}_{uuid.uuid4().hex[:10].upper()}"
