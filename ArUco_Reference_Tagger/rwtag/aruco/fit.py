"""
rwtag.aruco.fit
===============
Design (um, y-up) -> image (px) affine from the decoded tags. Ported from
Reference_Warp_Tagger/rwtag/aruco/detect.py::fit_affine.

RIGID ISLANDS: a tag keeps its printed size while the pattern expands, so its
CORNERS are not affine images of the design corners for lambda != 1. The
expansion is carried by the tag CENTRES:
  >= 3 tags  full affine through the centres (RANSAC), handedness checked
             against the corner order;
  2 tags     similarity with the corner-order handedness through the centres;
  1 tag      rotation + handedness from the tag's corners, translation from its
             centre, and the expansion scale from the DOT LATTICE pitch when
             dots are given (Phase 3); else the print scale, flagged.
"""
from __future__ import annotations
import numpy as np
import cv2

from .design import Design
from .pose import tag_handedness


def _rot_scale(design: Design, tags: dict, sign):
    """Rotation + PRINT scale from the tags' own (rigid) corners: Kabsch fit of
    design corner vectors (y flipped if sign < 0) to image corner vectors."""
    S, D = [], []
    F = np.diag([1.0, sign])
    for r in design.tag_records():
        aid = int(r["meta"]["aruco_id"])
        if aid in tags:
            dc = design.design_corners(r); ic = tags[aid].corners_px
            S.append((dc - dc.mean(0)) @ F.T); D.append(ic - ic.mean(0))
    S = np.concatenate(S); D = np.concatenate(D)
    U, sv, Vt = np.linalg.svd(S.T @ D)
    d = np.sign(np.linalg.det(U @ Vt)) or 1.0
    R = (U @ np.diag([1.0, d]) @ Vt).T
    return R, float(sv.sum() / (S ** 2).sum())


def fit_affine(design: Design, tags: dict, ransac_px=None, dots=None, dot_pitch_px=None):
    """Returns (A 2x3, info) or (None, info). `tags` = {id: TagObservation};
    only usable tags whose id is in the design are used. `ransac_px` defaults to
    half a tag side: a misdecoded id lands a whole box away and is still rejected,
    while gel warp and residual lens distortion (tens of px) are kept."""
    usable = {i: t for i, t in tags.items() if t.usable}
    if ransac_px is None:
        ransac_px = 0.5 * float(np.median([t.side_px for t in usable.values()])) if usable else 12.0
    sign, n_agree, n_tot = tag_handedness(design, usable)       # bit-pattern vote
    if sign == 0.0:
        sign = design.design_corner_sign                          # no vote: assume the expected orientation
    src, dst, used = [], [], []
    for r in design.tag_records():
        aid = int(r["meta"]["aruco_id"])
        if aid in usable:
            src.append([float(r["x_um"]), float(r["y_um"])]); dst.append(usable[aid].centre_px); used.append(aid)
    info = {"n_matched": len(used), "ids": used, "n_unknown": len(set(usable) - set(used)),
            "sign": sign, "handedness_agree": f"{n_agree}/{n_tot}", "method": None,
            "scale_from_dots": False}
    if not used:
        return None, info
    src = np.asarray(src, float); dst = np.asarray(dst, float)
    A = None
    if len(used) >= 3:
        Af, inl = cv2.estimateAffine2D(src, dst, method=cv2.RANSAC,
                                       ransacReprojThreshold=ransac_px, maxIters=2000,
                                       confidence=0.999, refineIters=20)
        if Af is not None:
            sv = np.linalg.svd(Af[:, :2], compute_uv=False)
            if sv[1] / sv[0] > 0.5:                  # three nearly collinear tags -> similarity
                A = Af; info["method"] = "affine(centres)"; info["n_inliers"] = int(inl.sum())
                # with >= 3 centres the affine's own determinant is the handedness
                sign = float(np.sign(np.linalg.det(Af[:, :2]))); info["sign"] = sign
                info["sign_source"] = "affine"
    if A is None:
        R, print_scale = _rot_scale(design, usable, sign)
        F = np.diag([1.0, sign])
        if len(used) >= 2:
            S = (src - src.mean(0)) @ F.T @ R.T; D = dst - dst.mean(0)
            scale = float((S * D).sum() / (S ** 2).sum())
            info["method"] = "similarity(centres)"
        else:
            scale = print_scale
            if dot_pitch_px is not None:
                scale = float(dot_pitch_px) / design.dot_pitch_um
                info["scale_from_dots"] = True
            info["method"] = "single tag" + (" (scale from dot lattice)" if info["scale_from_dots"]
                                             else " (PRINT scale — expansion unknown)")
        Al = scale * R @ F
        t = dst.mean(0) - src.mean(0) @ Al.T
        A = np.column_stack([Al, t])
    info.setdefault("sign_source", "bits" if n_tot else "assumed")
    res = np.hypot(*((src @ A[:, :2].T + A[:, 2]) - dst).T)
    info.update(centre_rms_px=float(np.sqrt(np.mean(res ** 2))),
                scale_px_per_um=float(np.sqrt(abs(np.linalg.det(A[:, :2])))),
                rot_deg=float(np.degrees(np.arctan2(A[1, 0], A[0, 0]))))
    return A, info


def apply_affine(A, xy_um):
    P = np.asarray(xy_um, float).reshape(-1, 2)
    return P @ A[:, :2].T + A[:, 2]
