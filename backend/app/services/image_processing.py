"""
Image Processing Pipeline for Roof Detection
---------------------------------------------
Level 1+2: Color segmentation (HSV) + edge detection + shape filters.

Pipeline:
  1. Convert to HSV
  2. Build exclusion mask (brown/tan, green, light-blue, very dark shadows)
  3. Invert -> candidate roof pixels
  4. Morphology opening + closing to clean
  5. Canny edge detection on grayscale
  6. Combine mask with edge-enhanced regions
  7. findContours
  8. Filter contours by area / aspect ratio / solidity
  9. approxPolyDP to simplify polygons

All thresholds are CONFIGURABLE via the `DetectionParams` object so the
router can accept tuning from the frontend without redeploy.
"""

from dataclasses import dataclass, field
from typing import List, Tuple

import cv2
import numpy as np
from PIL import Image
from shapely.geometry import Polygon
from shapely.validation import make_valid


# ---------------------------------------------------------------------------
# Tunable parameters (sane defaults for Indonesian residential imagery)
# ---------------------------------------------------------------------------
@dataclass
class DetectionParams:
    # HSV exclusion ranges (pixels matching ANY of these are NOT roofs)
    # Each range: ((H_low, S_low, V_low), (H_high, S_high, V_high))
    exclude_ranges: List[Tuple[Tuple[int, int, int], Tuple[int, int, int]]] = field(
        default_factory=lambda: [
            # Green (vegetation, grass, trees)
            ((35, 30, 30), (90, 255, 255)),
            # Brown / tan (dirt, unpaved road, bare ground)
            ((10, 40, 40), (25, 200, 200)),
            # Light blue (water, pools)  — note: OpenCV H range 0..179
            ((95, 50, 50), (125, 255, 255)),
            # Very dark (strong shadows) — exclude to reduce false positives
            ((0, 0, 0), (179, 255, 40)),
        ]
    )

    # Morphology kernel sizes (pixels)
    morph_open_kernel: int = 3
    morph_close_kernel: int = 5

    # Canny edge thresholds
    canny_low: int = 50
    canny_high: int = 150

    # Contour shape filters
    # At zoom 20, ~0.3m/pixel -> 15m² ≈ 167 px², 500m² ≈ 5555 px²
    # Using pixel area, translated from meters_per_pixel if provided
    min_area_m2: float = 15.0
    max_area_m2: float = 500.0
    min_aspect_ratio: float = 0.3
    max_aspect_ratio: float = 3.3
    min_solidity: float = 0.60

    # Douglas-Peucker simplification (fraction of perimeter)
    approx_epsilon_frac: float = 0.015


# ---------------------------------------------------------------------------
# Resolution helper
# ---------------------------------------------------------------------------
def estimate_meters_per_pixel(bbox: Tuple[float, float, float, float],
                              img_width: int, img_height: int) -> float:
    """
    Rough ground sampling distance (m/pixel) at image center.
    Good enough for filter thresholds; not used for coordinate conversion.
    """
    import math
    min_lng, min_lat, max_lng, max_lat = bbox
    mid_lat = (min_lat + max_lat) / 2.0
    # meters per degree at mid latitude
    m_per_deg_lat = 111_320.0
    m_per_deg_lng = 111_320.0 * math.cos(math.radians(mid_lat))
    # physical span
    span_m_x = (max_lng - min_lng) * m_per_deg_lng
    span_m_y = (max_lat - min_lat) * m_per_deg_lat
    mpp_x = span_m_x / img_width
    mpp_y = span_m_y / img_height
    return (mpp_x + mpp_y) / 2.0


# ---------------------------------------------------------------------------
# Core detection
# ---------------------------------------------------------------------------
def detect_roofs(pil_image: Image.Image,
                 bbox: Tuple[float, float, float, float],
                 params: DetectionParams = None) -> List[np.ndarray]:
    """
    Run the full detection pipeline.
    Returns a list of contours (each an (N, 2) ndarray of image pixels
    in (x, y) order).
    """
    if params is None:
        params = DetectionParams()

    # PIL -> OpenCV BGR
    img_rgb = np.array(pil_image.convert("RGB"))
    img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
    height, width = img_bgr.shape[:2]

    # Meters per pixel for area filters
    mpp = estimate_meters_per_pixel(bbox, width, height)
    min_area_px = params.min_area_m2 / (mpp * mpp)
    max_area_px = params.max_area_m2 / (mpp * mpp)

    # ---------------- Step 1-3: HSV exclusion mask ----------------
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    exclusion = np.zeros((height, width), dtype=np.uint8)
    for low, high in params.exclude_ranges:
        m = cv2.inRange(hsv, np.array(low), np.array(high))
        exclusion = cv2.bitwise_or(exclusion, m)
    candidate = cv2.bitwise_not(exclusion)  # non-excluded = candidate roof

    # ---------------- Step 4: Morphology ----------------
    k_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                       (params.morph_open_kernel,) * 2)
    k_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                        (params.morph_close_kernel,) * 2)
    candidate = cv2.morphologyEx(candidate, cv2.MORPH_OPEN, k_open)
    candidate = cv2.morphologyEx(candidate, cv2.MORPH_CLOSE, k_close)

    # ---------------- Step 5: Canny edges ----------------
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, params.canny_low, params.canny_high)
    # Dilate edges slightly so they form closed boundaries
    edges = cv2.dilate(edges, np.ones((2, 2), np.uint8), iterations=1)

    # ---------------- Step 6: Combine ----------------
    # Subtract strong edges FROM candidate to split touching roofs
    separated = cv2.subtract(candidate, edges)
    # Final closing to heal over-segmentation
    separated = cv2.morphologyEx(separated, cv2.MORPH_CLOSE, k_close)

    # ---------------- Step 7: Contours ----------------
    contours, _ = cv2.findContours(separated, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)

    # ---------------- Step 8: Shape filters ----------------
    kept = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area_px or area > max_area_px:
            continue

        x, y, w, h = cv2.boundingRect(cnt)
        if w == 0 or h == 0:
            continue
        ar = w / h
        if ar < params.min_aspect_ratio or ar > params.max_aspect_ratio:
            continue

        hull = cv2.convexHull(cnt)
        hull_area = cv2.contourArea(hull)
        if hull_area <= 0:
            continue
        solidity = area / hull_area
        if solidity < params.min_solidity:
            continue

        # ---------------- Step 9: Simplify ----------------
        perimeter = cv2.arcLength(cnt, True)
        eps = params.approx_epsilon_frac * perimeter
        approx = cv2.approxPolyDP(cnt, eps, True)
        if len(approx) < 3:
            continue
        kept.append(approx.reshape(-1, 2))

    return kept


# ---------------------------------------------------------------------------
# Convert detected pixel contours -> shapely Polygons in lng/lat,
# clipped to the user's drawn area polygon.
# ---------------------------------------------------------------------------
def contours_to_polygons(contours: List[np.ndarray],
                         pixel_to_lnglat_fn,
                         clip_polygon: Polygon = None) -> List[Polygon]:
    """
    Args:
      contours: list of (N, 2) ndarrays in (px, py)
      pixel_to_lnglat_fn: (px, py) -> (lng, lat)
      clip_polygon: shapely Polygon in lng/lat; only parts INSIDE are kept
    Returns:
      list of valid shapely Polygons (at least 3 vertices, area > 0)
    """
    polygons: List[Polygon] = []
    for cnt in contours:
        coords = [pixel_to_lnglat_fn(float(px), float(py)) for px, py in cnt]
        if len(coords) < 3:
            continue
        poly = Polygon(coords)
        if not poly.is_valid:
            poly = make_valid(poly)
            # make_valid may return a MultiPolygon or GeometryCollection
            if poly.geom_type == "Polygon":
                pass
            elif poly.geom_type == "MultiPolygon":
                # Use the largest piece
                poly = max(poly.geoms, key=lambda g: g.area)
            else:
                continue
        if poly.is_empty or poly.area <= 0:
            continue

        # Clip to user area if provided
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
