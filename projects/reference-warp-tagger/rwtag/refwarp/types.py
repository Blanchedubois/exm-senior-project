"""
rwtag.refwarp.types
===================
Stage-4 data contracts. NO GUI imports.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TagResult:
    """Stage-4 output for ONE frame: every filtered point's reference tag.
    Stored on PipelineState.tagging; series/pairing/strain consume `tags`."""
    tags: dict                       # {tag: (x_px, y_px)} on this frame (filtered points)
    warp: dict                       # {kind,H,tps,per_det_median,matched_frac,n_pairs}
    residuals: dict = None           # {tag: match residual px} (QC colouring, I4)
    source: str = "direct"           # "baseline" | "direct" | "auto<-1.5x"
    confidence: str = ""             # acceptance report (honest-confidence I6)
    per_category: dict = field(default_factory=dict)   # kind -> {n, res_median}
    label: Optional[float] = None    # expansion factor (parsed from filename / user)
