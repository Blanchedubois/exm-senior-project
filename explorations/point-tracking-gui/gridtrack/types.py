"""
gridtrack.types
===============
Plain dataclasses shared across the headless pipeline. NO GUI, NO OpenCV imports
here -- just the data contracts every stage reads and writes.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional
import numpy as np


@dataclass
class CorrectionParams:
    """Stage-1 optics correction parameters (all serialisable to JSON)."""
    # vignette flat-field:  V(r) = 1 - strength * (r/r_max)^power , centre fractional
    vig_strength: float = 0.0
    vig_power: float = 2.0
    vig_cx: float = 0.5
    vig_cy: float = 0.5
    vig_floor: float = 0.08          # clamp on the mask so division never explodes
    # Brown-Conrady radial lens distortion (centre fractional, k relative to half-width)
    k1: float = 0.0
    k2: float = 0.0
    dist_cx: float = 0.5
    dist_cy: float = 0.5
    # 2-D FFT low-pass denoise (applied LAST in Stage 1; shared optics for all images)
    lp_enable: bool = False          # off -> apply() is bit-identical to no-LP
    lp_cutoff: float = 0.50          # cut-off as a fraction of Nyquist, in (0, 1]
    lp_shape: str = "gaussian"       # "gaussian" | "butterworth" | "ideal"
    lp_order: int = 2                # Butterworth roll-off order (ignored otherwise)
    # Stage-2 preprocessing hints (kept here so the whole correction travels together)
    invert: bool = True              # fluorescence: bright-on-dark -> invert for ArUco
    clahe_clip: float = 2.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CorrectionParams":
        return cls(**{k: d[k] for k in d if k in cls.__dataclass_fields__})


@dataclass
class LevelsParams:
    """Stage-1 contrast / noise-floor 'levels' remap. PER-IMAGE (unlike the shared
    optics in CorrectionParams): each frame adapts its own contrast/threshold.
    Applied after the shared vignette/lens/low-pass correction, before detection.
    black point -> 0 (noise floor), white point -> full, gamma shapes mid-tones."""
    lv_enable: bool = False
    lv_white: float = 1.0            # white point, normalised [0,1]
    lv_gamma: float = 1.0            # mid-tone shaping (1 = linear)
    lv_black_mode: str = "auto"      # "auto" (bg + k*sigma) | "percentile" | "value"
    lv_black_k: float = 3.0          # auto mode: black = background + k*sigma
    lv_black_pct: float = 40.0       # percentile mode: black = this percentile
    lv_black: float = 0.0            # value mode: black point, normalised [0,1]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "LevelsParams":
        return cls(**{k: d[k] for k in d if k in cls.__dataclass_fields__})


@dataclass
class MarkerDetection:
    """Stage-2 output: tags found + the image rotated so they are upright."""
    image: np.ndarray                      # oriented (upright) image, float32
    ids: np.ndarray                        # (N,) int aruco ids, sorted
    corners: dict                          # id -> (4,2) float subpixel corners (oriented frame)
    centers: dict                          # id -> (2,) float centre (oriented frame)
    theta_deg: float                       # global rotation removed to make tags upright
    dict_name: str
    residual_deg: float = 0.0              # tag tilt still present after orienting (upright check)


@dataclass
class NodeRecord:
    """One grid node (tag position) tied to the reference."""
    aruco_id: int
    node_i: int
    node_j: int
    ref_xy_um: tuple                       # expected position from the reference
    img_xy_px: tuple                       # measured (detected) or predicted position
    status: str                            # "detected" | "predicted"
    residual_px: float = 0.0               # detected only: distance from the fitted prediction


@dataclass
class GridModel:
    """Stage-3 output: the detected tags mapped onto the reference lattice."""
    nodes: list                            # list[NodeRecord] for ALL reference nodes
    ref_to_img: np.ndarray                 # global 3x3 homography reference(um) -> image(px)
    box_homographies: dict                 # (box_i,box_j) -> 3x3 (ref um -> image px), Stage 4
    px_per_um: float                       # recovered image scale
    rms_residual_px: float                 # global fit residual (~ the warpage)
    n_detected: int
    n_total: int
    method: str = "global"                 # "global" | "two_point" | "single_marker" | "unanchored"
    lambda_local: float = float("nan")     # recovered local expansion (px_per_um / camera_ppu)
    box_confidence: dict = field(default_factory=dict)   # (bi,bj) -> region-grow match rate


@dataclass
class MeasureParams:
    """Stage-4 dot/dash detection parameters."""
    diameter: int = 9                      # trackpy feature diameter (odd, px)
    minmass: float = 150.0                 # trackpy min integrated intensity
    ecc_max: float = 0.35                  # dots: keep round features (ecc below this)
    gate_frac: float = 0.5                 # match radius = gate_frac * dot pitch (px)
    dash_min_elong: float = 1.8            # dashes: min major/minor axis ratio
    dash_area_min: float = 15.0            # dashes: min region area (px)
    dash_area_max: float = 600.0           # dashes: max region area (px; excludes tags)
    detect_dashes: bool = True


@dataclass
class FilterParams:
    """Stage-5 quality filters. Each can be toggled; thresholds are robust
    (median/MAD) unless an absolute value is given."""
    # 1. minimum separation: discard dots closer than min_sep_frac * expected pitch
    enable_proximity: bool = True
    min_sep_frac: float = 0.5              # expected pitch = dot_pitch_um * px_per_um
    # 2. blob quality: robust MAD gate on trackpy mass & size
    enable_quality: bool = True
    quality_mad: float = 5.0
    # 3. prediction residual: distance from the box-homography prediction
    enable_residual: bool = True
    residual_mad: float = 6.0
    residual_max_px: float = 0.0          # >0 overrides the MAD gate with an absolute px cap
    # 4. neighbourhood smoothness: displacement vs local neighbour median
    enable_smoothness: bool = False
    neighbor_k: int = 8
    neighbor_mad: float = 6.0
    # 5. border proximity: discard dots within border_px of the image edge
    enable_border: bool = True
    border_px: float = 8.0


@dataclass
class PipelineState:
    """The single object the GUI mutates; later stages fill in their fields."""
    source_path: Optional[str] = None
    raw_image: Optional[np.ndarray] = None          # float32, original value scale
    correction: CorrectionParams = field(default_factory=CorrectionParams)
    corrected_image: Optional[np.ndarray] = None     # float32, after Stage 1
    # forward slots for later stages (unused in Stage 1)
    detection: object = None
    grid: object = None
    features: object = None
    reference: object = None
