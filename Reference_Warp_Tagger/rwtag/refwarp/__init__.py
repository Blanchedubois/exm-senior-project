"""
rwtag.refwarp — Stage 4 headless core (reference-warp tagging).

Ported from the validated `refwarp` package: build/load the canonical STL tag map
(reftags), fit the design->image warp (affine seed -> ICP homography -> TPS),
assign every detected point the nearest same-category reference tag (tagmatch),
rescue mis-registered high-expansion frames from a lower frame (coreg), and
measure expansion from tag-paired dots (strain). NO Qt here.

New in this port: `tagframe` (tag one frame from Stage 1-3 state) and `series`
(sidecar-driven batch over the sibling expansion frames).
"""
from __future__ import annotations

from . import reftags, warp, tagmatch, coreg, strain, io_csv, tagframe, series
from .types import TagResult

__all__ = ["reftags", "warp", "tagmatch", "coreg", "strain", "io_csv",
           "tagframe", "series", "TagResult"]
