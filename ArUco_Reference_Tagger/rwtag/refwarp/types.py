"""
rwtag.refwarp.types
===================
Stage-4 data contract. Ported from Reference_Warp_Tagger/rwtag/refwarp/types.py
with what the ArUco export needs: where each tag came from (`src`), the
uniform-expansion fit that defines the expected positions (`similarity`), the
features that did not get a tag (`unmatched`), and the acceptance decision.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TagResult:
    tags: dict                       # {tag: (x_px, y_px)} in the corrected frame
    warp: dict                       # {kind, H, tps, per_det_median, matched_frac, n_pairs}
    residuals: dict = None           # {tag: distance to its warped reference, px}
    source: str = "direct"           # "baseline" | "direct"
    confidence: str = ""
    per_category: dict = field(default_factory=dict)   # kind -> {n, res_median}
    label: Optional[float] = None
    # ---- ArUco port ----
    src: dict = field(default_factory=dict)            # {tag: ("dot", i) | ("dash", j) | ("aruco", id)}, i/j index DetectResult arrays
    per_box: dict = field(default_factory=dict)        # {N: {n_tagged, res_median}}
    similarity: dict = field(default_factory=dict)     # design um -> px: {s, R, t, sign, angle_deg, rms, n}
    unmatched: dict = field(default_factory=dict)      # {"dot": [i], "dash": [j], "box_mismatch": [i]}
    accepted: bool = True
    reason: str = ""                                   # why not accepted
    design_sha: dict = field(default_factory=dict)
    cov: dict = field(default_factory=dict)            # {tag: (sxx, syy, sxy)} corrected-frame px^2 (port Phase 5)
