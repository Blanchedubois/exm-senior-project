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


@dataclass
class DetectResult:
    """Stage-2 output: everything detection recovers about one frame. Stored on
    PipelineState.detection; Stages 3-4 read dots/dashes/grid/fit/model from here."""
    u8: np.ndarray                          # the 8-bit image detection ran on (Stage-1 corrected)
    dots: np.ndarray                        # (N,2) fine-dot centroids (ALL detected)
    basis: dict                             # v1,v2,pitch,angle_deg,origin (refined lattice)
    dashes_all: np.ndarray                  # (M,2) all detected dash centres
    dashes_on_grid: np.ndarray              # (m,2) dash centres lying ON a box boundary
    glyphs: np.ndarray                      # (K,2) all glyph-blob positions
    grid: dict                              # dash-locked box grid: u,v,box_pitch,phase_u/v,*_vec
    fit: Optional[dict] = None              # fiducial lattice: O,U,V,box_pitch (box-coord frame)
    reads: list = field(default_factory=list)   # per-glyph slot reads
    model: Optional[dict] = None            # build_grid_model output: labels, reg, node_num, summary
    glyph_h: float = 30.0                   # median glyph height px (for the on-glyph dot filter)
    n_dashes_dropped: int = 0
    stage: str = "grid"                     # "grid" | "read" | "solved" — how far detection got


@dataclass
class FilterResult:
    """Stage-3 output: the quality-filtered dots & dashes. Stored on
    PipelineState.features; Stage 4 tags only the kept points."""
    dot_recs: list                          # [{x,y,keep,reason}, ...] every dot
    dash_recs: list                         # [{x,y,keep,reason}, ...] every dash
    dot_counts: dict                        # {kept, too_close, on_glyph, off_lattice}
    dash_counts: dict                       # {kept, off_grid, intersection, too_close}
    kept_dots: np.ndarray                   # (n,2) surviving dot centres -> Stage 4 input
    kept_dashes: np.ndarray                 # (m,2) surviving dash centres -> Stage 4 input
    dot_params: dict = field(default_factory=dict)
    dash_params: dict = field(default_factory=dict)
