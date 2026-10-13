"""
rwtag.types
===========
Plain dataclasses shared across the headless pipeline. NO GUI, NO OpenCV imports
here -- just the data contracts every stage reads and writes.

Ported from the Point-Tracking GUI (`gridtrack/types.py`). Stage-1 subset, with
two deliberate changes for the Reference-Warp Tagger:
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
    corrected_image: Optional[np.ndarray] = None      # float32, after apply()+levels() -> feeds Stage 2
    # forward slots (unused in Stage 1, present so later stages don't reshape state):
    detection: object = None       # Stage 2: DetectResult
    grid: object = None            # Stage 2: box numbering / warped reference
    features: object = None        # Stage 3: FilterResult (kept dots/dashes)
    tagging: object = None         # Stage 4: TagResult (reference-warp tags)

    def working_image(self) -> Optional[np.ndarray]:
        """Best available image: corrected if Stage 1 ran, else raw."""
        return self.corrected_image if self.corrected_image is not None else self.raw_image
