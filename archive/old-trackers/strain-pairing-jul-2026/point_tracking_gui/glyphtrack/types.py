"""
glyphtrack.types
================
Headless data contracts for the glyph (number/letter) marker pipeline.
NO GUI, NO OpenCV imports here.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import numpy as np

CLASSES = list("0123456789ABCD")           # closed alphabet: digits + A/B/C/D
LETTERS = list("ABCD")


@dataclass
class GlyphDetection:
    x: float                                # centroid, image px
    y: float
    kind: str                               # "digit" | "letter"
    value: str                              # "0".."9" | "A".."D"
    angle_deg: float                        # glyph orientation (from grid deskew)
    confidence: float                       # 0..1
    bbox: tuple                             # (x, y, w, h) image px


@dataclass
class NumberToken:
    value: int                              # grouped digits -> a box number (1..25)
    x: float                                # token centroid
    y: float
    members: list = field(default_factory=list)   # [GlyphDetection] left-to-right
    confidence: float = 0.0


@dataclass
class OrientationResult:
    angle_deg: float                        # rotation applied to bring the grid upright
    flip: bool
    oriented_image: Optional[np.ndarray] = None
    letters: list = field(default_factory=list)   # [GlyphDetection] A/B/C/D, oriented coords


@dataclass
class GlyphDetectParams:
    deskew: bool = True
    clahe_clip: float = 3.0
    thresh_block: int = 51                  # adaptive-threshold window (odd)
    thresh_C: float = -8.0
    min_glyph_area: int = 150               # px, real-image scale
    max_glyph_area: int = 4000
    min_glyph_h: int = 18
    max_glyph_h: int = 60
    max_fill: float = 0.80                  # reject solid dashes (extent >= this)
    confidence_min: float = 0.45            # reject low-confidence blobs
