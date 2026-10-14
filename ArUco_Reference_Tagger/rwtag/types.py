"""
rwtag.types
===========
Plain dataclasses shared across the headless pipeline. NO GUI, NO OpenCV imports
here -- just the data contracts every stage reads and writes.

Ported from Reference_Warp_Tagger/rwtag/types.py, which came from the Point-Tracking
GUI (`gridtrack/types.py`). ArUco port: `PipelineState.meta` holds the image's
acquisition-metadata record (rwtag.meta.ImageMeta). The V1 notes below still hold:
  * `LevelsParams` is promoted into `PipelineState` (was panel-local before) so the
    corrected image is fully reproducible from state alone -- Stage 4 must be able to
    reconstruct the exact processed image the points were tagged on.
  * `PipelineState` carries explicit forward slots (detection/grid/features) so
    stages 2-4 attach without reshaping state or the session schema.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional
import numpy as np

from .meta import ImageMeta


@dataclass
class CorrectionParams:
    """Stage-1 optics correction parameters (all serialisable to JSON).

    These are the SHARED optics: properties of the microscope/lens that are the
    same across a series of frames (vignette, distortion, denoise). `rotate_deg`
    is the exception -- it is tuned per-image (each expansion frame is tilted
    differently) but lives here so the whole geometric correction travels together.
    """
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
    # 2-D FFT low-pass denoise (applied LAST of the optics chain, before rotation)
    lp_enable: bool = False          # off -> apply() is bit-identical to no-LP
    lp_cutoff: float = 0.50          # cut-off as a fraction of Nyquist, in (0, 1]
    lp_shape: str = "gaussian"       # "gaussian" | "butterworth" | "ideal"
    lp_order: int = 2                # Butterworth roll-off order (ignored otherwise)
    # deskew: rotate the whole frame so the marker grid is upright (helps recognition)
    rotate_deg: float = 0.0          # applied last in Stage 1; 0 = no rotation
    # forward hints (carried so the whole correction travels together; not Stage-1 UI)
    invert: bool = True              # fluorescence: bright-on-dark -> invert for Stage-2 detect
    clahe_clip: float = 2.0          # reserved (CLAHE deferred out of Stage 1)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CorrectionParams":
        return cls(**{k: d[k] for k in d if k in cls.__dataclass_fields__})


@dataclass
class LevelsParams:
    """Stage-1 contrast / noise-floor 'levels' remap. PER-IMAGE (unlike the shared
    optics in CorrectionParams): each frame adapts its own contrast/threshold.
    Applied after the shared vignette/lens/low-pass/rotate correction, before any
    detection. black point -> 0 (noise floor), white point -> full, gamma shapes
    the mid-tones. Essential on this data: high-expansion frames are much dimmer
    (max intensity falls as material spreads), so a single global contrast fails."""
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
class PipelineState:
    """The single object the GUI mutates; later stages fill in their forward slots."""
    source_path: Optional[str] = None
    raw_image: Optional[np.ndarray] = None            # float32, original value scale
    correction: CorrectionParams = field(default_factory=CorrectionParams)   # shared optics
    levels: LevelsParams = field(default_factory=LevelsParams)                # per-image
    meta: ImageMeta = field(default_factory=ImageMeta)                        # acquisition metadata
    corrected_image: Optional[np.ndarray] = None      # float32, after apply()+levels() -> feeds Stage 2
    corrected_key: Optional[str] = None               # stage1_key() of the params that produced corrected_image
    # forward slots (unused in Stage 1, present so later stages don't reshape state):
    detection: object = None       # Stage 2: DetectResult (ArUco decode + dots + dashes)
    grid: object = None            # Stage 2: design-driven grid
    features: object = None        # Stage 3: FilterResult (kept dots/dashes)
    tagging: object = None         # Stage 4: TagResult (reference-warp tags)

    def stage1_key(self) -> str:
        """Fingerprint of the Stage-1 parameters (correction + levels)."""
        import json
        return json.dumps([self.correction.to_dict(), self.levels.to_dict()], sort_keys=True)

    def corrected_is_current(self) -> bool:
        return self.corrected_image is not None and self.corrected_key == self.stage1_key()

    def working_image(self) -> Optional[np.ndarray]:
        """Best available image: corrected if Stage 1 ran, else raw."""
        return self.corrected_image if self.corrected_image is not None else self.raw_image


# ================================================================ Stage 2-3 results
@dataclass
class DetectResult:
    """Stage-2 output for one frame (port Phase 3). Positions are in the Stage-1
    CORRECTED frame (px) unless a field says raw. The first block keeps the V1
    shape that the ported tagging code reads; the second is new for the ArUco
    print (tags, per-box dots, photometry, the raw second pass)."""
    u8: np.ndarray                          # 8-bit corrected frame the detection ran on (display)
    dots: np.ndarray                        # (N,2) refined dot centres
    basis: dict                             # frame-level lattice (the box with most dots)
    dashes_all: np.ndarray                  # (M,2) every detected dash centre
    dashes_on_grid: np.ndarray              # (m,2) dash centres on a box-boundary line
    glyphs: np.ndarray = None               # V1 compatibility: always empty
    grid: Optional[dict] = None             # node lattice from the tag affine (u, v, box_pitch, phase)
    fit: Optional[dict] = None              # {O, U, V, box_um}: coarse_map == the tag affine
    reads: list = field(default_factory=list)
    model: Optional[dict] = None            # registered, kind "aruco", reg, affine, sign, aruco_xy, summary
    glyph_h: float = 0.0
    n_dashes_dropped: int = 0
    stage: str = "solved"
    # ---- ArUco port ----
    tags: dict = field(default_factory=dict)            # {id: TagObservation} (corrected frame)
    frame_pose: object = None                           # FramePose (corrected frame)
    dot_box: np.ndarray = None                          # (N,) box number per dot
    dot_flag: np.ndarray = None                         # (N,) "" | "edge" (no valid raw source nearby)
    dash_flag: np.ndarray = None                        # (M,) same, for dashes_all
    dot_signal: np.ndarray = None                       # (N,) integrated signal above background, raw ADU
    dot_bg: np.ndarray = None                           # (N,) background per pixel, raw ADU
    dot_sigma_px: np.ndarray = None                     # (N,) measured spot sigma (corrected frame px)
    basis_by_box: dict = field(default_factory=dict)    # {N: refined lattice basis}
    per_box: dict = field(default_factory=dict)         # {N: {design, detected, dot_um, pitch_um, pitch_px}}
    lam_tags: float = float("nan")                      # expansion from the tag centres
    lam_tags_sigma: float = float("nan")                # jackknife over tags (>= 4)
    lam_dots: float = float("nan")                      # expansion from the per-box dot pitch (cross-check)
    rot_raw_deg: float = float("nan")                   # gel rotation in the RAW frame (as acquired)
    design_name: str = ""
    design_sha: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)          # ArucoParams used
    raw_pass: dict = None                               # second detection on the raw frame, see aruco.detect
    # ---- error model (port Phase 5, rwtag.errors) ----
    dot_cov_raw: np.ndarray = None                      # (N,2,2) raw-frame px^2
    dot_cov_corr: np.ndarray = None                     # (N,2,2) corrected-frame px^2
    dot_cov_flag: np.ndarray = None                     # (N,) "" | "border_estimate"
    dash_cov_raw: np.ndarray = None                     # (M,2,2) for dashes_all
    dash_cov_corr: np.ndarray = None
    tag_cov: dict = field(default_factory=dict)         # {id: {centre_corr, centre_raw, corners_*, rot_sigma_deg, side_sigma_px}}
    noise: dict = field(default_factory=dict)           # the NoiseModel used + measured pixel noise


@dataclass
class FilterResult:
    """Stage-3 output: the quality-filtered dots & dashes."""
    dot_recs: list
    dash_recs: list
    dot_counts: dict
    dash_counts: dict
    kept_dots: np.ndarray
    kept_dashes: np.ndarray
    dot_params: dict = field(default_factory=dict)
    dash_params: dict = field(default_factory=dict)
    kept_dot_index: np.ndarray = None       # indices into DetectResult.dots of the kept dots
    kept_dash_index: np.ndarray = None
