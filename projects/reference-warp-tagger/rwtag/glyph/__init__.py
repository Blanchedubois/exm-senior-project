"""
rwtag.glyph — Stage 2 headless core (detect & identify).

Ported verbatim from the Point-Tracking GUI's `glyphtrack` package: recover the
marker geometry from the fine dot lattice, lock the box grid to the boundary
dashes, read digits/letters at the fiducial slots, then register the 5x5 grid
(orientation + offset from the numbering rule N=col*5+row+1) and auto-complete
every box number. NO Qt here.
"""
from __future__ import annotations

from . import lattice, reader, classifier, gridmodel, types, detect
from .types import CLASSES, DetectResult

__all__ = ["lattice", "reader", "classifier", "gridmodel", "types", "detect",
           "CLASSES", "DetectResult"]
