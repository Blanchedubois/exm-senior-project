"""
rwtag.refwarp — Stage 4, reference-warp tagging (port Phase 4). NO Qt.

Ported from reference-warp-tagger/rwtag/refwarp: warp (ICP homography -> TPS,
plus the similarity fit), tagmatch (nearest same-category reference, ArUco by
id), tagframe (tag one frame), strain (local deformation gradient), io_csv.
Dropped: reftags (the V1 STL builder; V2 designs ship their tag map), coreg (the
box-number rescue; ArUco ids register every frame on their own), series (V1's
glyph driver; see rwtag.series).
"""
from __future__ import annotations

from . import warp, tagmatch, tagframe, strain, io_csv
from .types import TagResult

__all__ = ["warp", "tagmatch", "tagframe", "strain", "io_csv", "TagResult"]
