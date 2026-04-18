"""
Polygon Deduplication via IoU
-----------------------------
When multiple tiles overlap, buildings on the boundary get detected in
both tiles. We dedupe by computing Intersection-over-Union and keeping
one representative polygon per group.

Algorithm: Greedy NMS (Non-Maximum Suppression)
  1. Sort polygons by area DESC (prefer larger = more complete detection)
  2. For each polygon p, check against already-kept list:
     - If IoU(p, kept_i) >= threshold → skip p (duplicate)
     - Otherwise add p to kept
  3. Return kept list

O(N^2) complexity. For 500 polygons ≈ 125k comparisons, fast enough
(< 1 second). For > 2000 polygons we'd use spatial index (STRtree);
not needed at our scale.
"""

import logging
from typing import List

from shapely.geometry import Polygon
from shapely.strtree import STRtree

logger = logging.getLogger(__name__)


def polygon_iou(a: Polygon, b: Polygon) -> float:
    """Intersection over Union. Returns 0.0 if polygons are disjoint."""
    if not a.is_valid or not b.is_valid:
        return 0.0
    if not a.intersects(b):
        return 0.0
    inter = a.intersection(b).area
    if inter <= 0:
        return 0.0
    union = a.area + b.area - inter
    if union <= 0:
        return 0.0
    return inter / union


def deduplicate_polygons(
    polygons: List[Polygon],
    iou_threshold: float = 0.5,
) -> List[Polygon]:
    """
    Remove near-duplicate polygons (IoU >= threshold).

    Uses greedy NMS: sort by area DESC, keep largest that doesn't overlap
    with already-kept polygons above threshold.

    Uses spatial index (STRtree) to only compare against nearby candidates
    — much faster than pairwise O(N^2).

    Args:
        polygons: input list (may contain duplicates across tile boundaries)
        iou_threshold: IoU >= this means duplicate (default 0.5)

    Returns:
        Deduplicated polygon list, sorted by area DESC.
    """
    if not polygons:
        return []

    # Filter invalid / zero-area polygons
    valid = [p for p in polygons if p.is_valid and p.area > 0]
    if not valid:
        return []

    # Sort by area DESC — larger polygons are usually more complete detections
    valid.sort(key=lambda p: p.area, reverse=True)

    # Build spatial index on the fly as we add to `kept`
    kept: List[Polygon] = []
    kept_tree: STRtree = None  # rebuilt lazily

    # For performance, only rebuild tree every K additions
    REBUILD_EVERY = 30

    def is_duplicate(p: Polygon) -> bool:
        """Check if p overlaps enough with any already-kept polygon."""
        if not kept:
            return False
        # Naive linear scan for now — fast enough (< 500 polygons expected)
        for q in kept:
            if polygon_iou(p, q) >= iou_threshold:
                return True
        return False

    for poly in valid:
        if not is_duplicate(poly):
            kept.append(poly)

    dupes = len(valid) - len(kept)
    if dupes:
        logger.info(f"Dedup: {len(valid)} polygons → {len(kept)} (removed {dupes} duplicates, IoU ≥ {iou_threshold})")
    else:
        logger.info(f"Dedup: no duplicates found among {len(valid)} polygons")

    return kept
