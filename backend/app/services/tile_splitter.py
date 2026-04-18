"""
Tile Splitter Service
---------------------
Split a stitched satellite image into NxN grid of overlapping tiles.
Each tile carries its own geographic bbox (sub-region of the original)
so pixel->lnglat can be computed correctly per tile.

Why overlapping tiles?
  Buildings on tile boundaries would be cut in half without overlap.
  10% overlap ensures buildings straddling the edge get fully captured
  in at least one tile.

Output dedup via IoU is handled in polygon_dedup.py.
"""

import math
from dataclasses import dataclass
from typing import List, Tuple

from PIL import Image


@dataclass
class ImageTile:
    """A sub-region of the stitched image with its geographic footprint."""
    tile_id: str                          # e.g. "r1c2" (row 1, col 2)
    image: Image.Image                    # cropped PIL image
    bbox_geo: Tuple[float, float, float, float]  # (min_lng, min_lat, max_lng, max_lat)
    size: Tuple[int, int]                 # (width, height) pixels
    row: int
    col: int


def lat_to_mercY(lat: float) -> float:
    """Mercator Y projection."""
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def mercY_to_lat(y: float) -> float:
    """Inverse Mercator Y."""
    return math.degrees(2 * math.atan(math.exp(y)) - math.pi / 2)


def split_image_into_tiles(
    image: Image.Image,
    bbox_full: Tuple[float, float, float, float],
    grid_size: int = 3,
    overlap_ratio: float = 0.10,
) -> List[ImageTile]:
    """
    Split a stitched image into grid_size x grid_size tiles with overlap.

    Args:
        image: Full stitched PIL image (RGB)
        bbox_full: (min_lng, min_lat, max_lng, max_lat) of the full image
        grid_size: N for NxN grid (default 3 = 9 tiles)
        overlap_ratio: fraction of tile size to overlap (0.10 = 10%)

    Returns:
        List of ImageTile (length = grid_size^2)

    Pixel layout (horizontal, same logic for vertical):
      Full width = W. Tile size = w_tile. Step = w_step.
      w_step = W / grid_size     (spacing between tile left-edges)
      w_tile = w_step * (1 + overlap_ratio)
      Last tile may extend past W; we clamp to image bounds.
    """
    if grid_size < 1:
        raise ValueError("grid_size must be >= 1")

    W, H = image.size
    min_lng, min_lat, max_lng, max_lat = bbox_full

    # Step = non-overlapping part of each tile
    # Tile dim = step * (1 + overlap) so neighboring tiles share `step * overlap` pixels
    w_step = W / grid_size
    h_step = H / grid_size
    w_tile = int(round(w_step * (1 + overlap_ratio)))
    h_tile = int(round(h_step * (1 + overlap_ratio)))

    # For geographic conversion — Mercator Y at bbox edges
    mY_top = lat_to_mercY(max_lat)     # top of image = north (smaller pixel y)
    mY_bot = lat_to_mercY(min_lat)     # bottom = south

    def px_to_lnglat(px: float, py: float) -> Tuple[float, float]:
        """Full-image pixel (px,py) → lng,lat."""
        lng = min_lng + (px / W) * (max_lng - min_lng)
        mY = mY_top + (py / H) * (mY_bot - mY_top)
        lat = mercY_to_lat(mY)
        return lng, lat

    tiles: List[ImageTile] = []
    for row in range(grid_size):
        for col in range(grid_size):
            # Tile pixel bounds (in FULL image coords)
            px_left = int(round(col * w_step))
            py_top = int(round(row * h_step))
            px_right = min(px_left + w_tile, W)
            py_bottom = min(py_top + h_tile, H)

            # Crop the tile image
            tile_img = image.crop((px_left, py_top, px_right, py_bottom))
            tile_w = px_right - px_left
            tile_h = py_bottom - py_top

            # Compute tile's geographic bbox
            tile_min_lng, tile_max_lat = px_to_lnglat(px_left, py_top)
            tile_max_lng, tile_min_lat = px_to_lnglat(px_right, py_bottom)

            tiles.append(ImageTile(
                tile_id=f"r{row}c{col}",
                image=tile_img,
                bbox_geo=(tile_min_lng, tile_min_lat, tile_max_lng, tile_max_lat),
                size=(tile_w, tile_h),
                row=row,
                col=col,
            ))

    return tiles
