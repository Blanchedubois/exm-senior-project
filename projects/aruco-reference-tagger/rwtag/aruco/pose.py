"""
rwtag.aruco.pose
================
Frame-level pose from the decoded tags: rotation (median over tags, with
spread), handedness against the design (the y-up design seen in a y-down image
must give -1 on every tag), and the PRINT scale from the rigid tag sides.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np

from .design import Design


@dataclass
class FramePose:
    n_tags: int                      # usable tags
    n_in_design: int                 # of those, ids that exist in the design
    frame_rot_deg: float             # median tag rotation
    rot_spread_deg: float            # median absolute deviation
    handedness: float                # design->image sign: -1 expected (y-up design), +1 mirrored, 0 undetermined
    n_hand_agree: int
    scale_px_per_um_print: float     # median side_px / tag_um (tags are rigid)
    scale_spread: float
    handedness_source: str = ""      # "affine" (>= 3 tags) | "bits" | "none"
    unknown_ids: list = field(default_factory=list)
    missing_nodes: list = field(default_factory=list)   # (i, j, id) in design, not seen

    def summary(self):
        hand = ("undetermined" if self.handedness == 0 else
                "-1 (expected)" if self.handedness < 0 else "+1 MIRRORED — check the image")
        return (f"{self.n_tags} usable tags ({self.n_in_design} in design) · rot "
                f"{self.frame_rot_deg:+.2f} ± {self.rot_spread_deg:.2f} deg · handedness {hand} "
                f"[{self.handedness_source} {self.n_hand_agree}/{self.n_tags}] · print scale "
                f"{self.scale_px_per_um_print:.3f} px/um"
                + (f" · unknown ids {self.unknown_ids}" if self.unknown_ids else ""))


def tag_handedness(design: Design, tags: dict):
    """Frame handedness voted from the tags' BIT patterns (a mirrored frame reads
    better mirrored), expressed as the sign of the design -> image map: the
    design corner sign (-1 for a y-up design) when the bits read directly, its
    negative when they read mirrored. Returns (majority sign, n_agree, n_voting);
    (0, 0, 0) when no usable tag votes."""
    ds = design.design_corner_sign
    known = {v for _i, _j, v in design.node_ids}
    per = [t.bits_handedness * ds for i, t in tags.items()
           if t.usable and i in known and t.bits_handedness != 0.0]
    if not per:
        return 0.0, 0, 0
    sign = float(np.sign(sum(per))) or ds
    return sign, int(sum(1 for p in per if p == sign)), len(per)


def _wrap(deg):
    return (np.asarray(deg, float) + 180.0) % 360.0 - 180.0


def frame_pose(tags: dict, design: Design | None = None, affine_sign: float | None = None) -> FramePose:
    """`affine_sign`: sign(det) of the design->image affine when >= 3 tags fitted
    it (fit.fit_affine info["sign"]); it overrides the bit vote."""
    usable = {i: t for i, t in tags.items() if t.usable}
    known = {v for _i, _j, v in design.node_ids} if design is not None else None
    in_design = {i: t for i, t in usable.items() if known is None or i in known}
    rots = _wrap([t.rot_deg for t in in_design.values()])
    if len(rots):
        # circular-safe median: unwrap around the first value
        rots = _wrap(rots - rots[0]) + rots[0]
        rot = float(np.median(rots)); spread = float(np.median(np.abs(rots - rot)))
    else:
        rot, spread = float("nan"), float("nan")
    src = "none"
    if design is not None:
        hand, n_agree, _n = tag_handedness(design, usable)
        src = "bits" if hand != 0.0 else "none"
        if affine_sign is not None and affine_sign != 0.0:
            hand, src = float(affine_sign), "affine"
        sides = np.array([t.side_px for t in in_design.values()]) / design.tag_um
        unknown = sorted(i for i in usable if i not in known)
        missing = [(i, j, v) for i, j, v in design.node_ids if v not in usable]
    else:
        votes = [t.bits_handedness for t in usable.values() if t.bits_handedness != 0.0]
        hand = float(np.sign(sum(votes))) if votes else 0.0        # +1 proper, -1 mirrored (no design)
        n_agree = sum(1 for s in votes if s == hand)
        src = "bits" if hand != 0.0 else "none"
        sides = np.array([t.side_px for t in usable.values()])
        unknown, missing = [], []
    scale = float(np.median(sides)) if len(sides) else float("nan")
    spread_s = float(np.median(np.abs(sides - scale))) if len(sides) else float("nan")
    return FramePose(n_tags=len(usable), n_in_design=len(in_design), frame_rot_deg=rot,
                     rot_spread_deg=spread, handedness=hand, n_hand_agree=n_agree, handedness_source=src,
                     scale_px_per_um_print=scale, scale_spread=spread_s,
                     unknown_ids=unknown, missing_nodes=missing)
