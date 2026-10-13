"""
refwarp.warp
============
Fit the transform REFERENCE design (um) -> this image (px), so the tagged reference
can be pushed onto the image and matched.

Empirically (P2): the sparse corner *intersection dots* are NOT reliably detected on
real prints, so they make poor control points. The dense **interior dot lattice**
(~2500 well-detected dots) does far better: seed a global affine from the box-grid
fit + registration, then ICP-refine a homography against the detected dots
(median residual ~3 px = <0.1 dot pitch on 1.5x). P4 swaps the homography for a
thin-plate spline to absorb non-uniform expansion at the larger factors.
"""
from __future__ import annotations
import numpy as np
import cv2

from rwtag.glyph import lattice as lt

BOX_UM = 150.0
LINE_N = 6


# ------------------------------------------------------- registration inverse
def design_to_fit(u, v, reg):
    """Design box-coordinate (u,v) -> fit box-coordinate (continuous).

    The registration equates design BOX (col,row) with the fit box whose MIN
    corner is node n (col = cs*n + off). On a negative-sign axis the box region
    is traversed in reverse: design [col, col+1] maps to fit [n, n+1] with
    u=col -> n+1 and u=col+1 -> n, so the sign flip needs a +1 — without it the
    whole design seeds ONE BOX OFF along that axis (box numbers off by one row/
    column vs the printed digits)."""
    ca, cs, ra, rs = reg["orient"]; off0, off1 = reg["offset"]
    fc = [0.0, 0.0]
    fc[ca] = cs * (u - off0) + (1.0 if cs < 0 else 0.0)
    fc[ra] = rs * (v - off1) + (1.0 if rs < 0 else 0.0)
    return fc[0], fc[1]


def coarse_map(um_xy, fit, reg):
    """Seed transform: reference design um -> image px via the box-grid fit + reg
    (a single global affine). Good to ~5 px on 1.5x; ICP refines it."""
    O, U, V = fit["O"], fit["U"], fit["V"]
    # V2 (ArUco) fits carry their own box size -- (750 - tag) / 5, not 150 -- and
    # anchor O at design (0,0); with the identity reg this map is then EXACTLY the
    # tag-fitted affine. V1 fits have no "box_um" and keep the 150 um default.
    box = float(fit.get("box_um", BOX_UM))
    um = np.asarray(um_xy, float).reshape(-1, 2)
    out = np.empty_like(um)
    for k, (x, y) in enumerate(um):
        f0, f1 = design_to_fit(x / box, y / box, reg)
        out[k] = O + f0 * U + f1 * V
    return out


def warp_points(um_xy, model):
    """Push design um points -> image px through a warp model (homography or TPS)."""
    if isinstance(model, dict):
        if model.get("tps") is not None:
            return np.asarray(model["tps"](np.asarray(um_xy, float).reshape(-1, 2)))
        model = model["H"]
    um = np.asarray(um_xy, float).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(um, model).reshape(-1, 2)


# ------------------------------------------------------------------ fit warp
def fit_warp(ref_dots_um, det_px, fit, reg, pitch, iters=6, gate=0.5, min_pairs=20,
             tps=True, tps_max=500):
    """Fit reference design (um) -> image (px).
    1. ICP a global homography (seeded by the box-grid affine) against the dots.
    2. If `tps`, refine with a thin-plate spline through the homography-matched dot
       correspondences (absorbs non-uniform expansion at the larger factors).
    Returns a warp MODEL dict {kind, H, tps, per_det_median, matched_frac, n_pairs}
    consumable by warp_points(); H=None on failure."""
    from scipy.spatial import cKDTree
    ref = np.asarray(ref_dots_um, float)
    det = np.asarray(det_px, float)
    if len(ref) < min_pairs or len(det) < min_pairs:
        return {"H": None, "tps": None}
    cur = coarse_map(ref, fit, reg)
    H = None
    for _ in range(iters):
        t = cKDTree(cur)
        dist, idx = t.query(det)
        m = dist < gate * pitch
        if m.sum() < min_pairs:
            break
        Hn, _ = cv2.findHomography(ref[idx[m]], det[m], cv2.RANSAC, 4.0)
        if Hn is None:
            break
        H = Hn
        cur = warp_points(ref, H)
    if H is None:
        return {"H": None, "tps": None}

    model = {"kind": "homography", "H": H, "tps": None}
    if tps:
        t = cKDTree(cur); dist, idx = t.query(det); m = dist < gate * pitch
        src = ref[idx[m]]; dst = det[m]                    # design um -> px, correct pairs
        if len(src) >= 40:
            if len(src) > tps_max:                         # thin, keep it well-conditioned
                sel = np.linspace(0, len(src) - 1, tps_max).astype(int)
                src, dst = src[sel], dst[sel]
            from scipy.interpolate import RBFInterpolator
            rbf = RBFInterpolator(src, dst, kernel="thin_plate_spline", smoothing=1.0)
            model = {"kind": "tps", "H": H, "tps": rbf}

    cur = warp_points(ref, model)
    t = cKDTree(cur); dd, _ = t.query(det)
    model.update(per_det_median=float(np.median(dd)),
                 matched_frac=float((dd < gate * pitch).mean()),
                 n_pairs=int((dd < gate * pitch).sum()))
    return model


def fit_homography(*a, **k):
    """Back-compat: homography-only fit."""
    return fit_warp(*a, tps=False, **k)


# ------------------------------------------------------ node prediction (aux)
def design_node_to_fit(i, j, reg):
    """Design grid node (i,j) -> fit node (the f=0 boundary case of design_to_fit;
    same +1 on negative-sign axes)."""
    ca, cs, ra, rs = reg["orient"]; off0, off1 = reg["offset"]
    node = [0, 0]
    node[ca] = cs * (i - off0) + (1.0 if cs < 0 else 0.0)
    node[ra] = rs * (j - off1) + (1.0 if rs < 0 else 0.0)
    return node[0], node[1]


def predicted_nodes(fit, reg, shape, margin=60):
    """{(i,j): (px,py)} for grid nodes whose predicted pixel is in view — used for
    overlays / seeding, not as warp control points (corner dots detect poorly)."""
    H, W = shape[:2]
    out = {}
    for i in range(LINE_N):
        for j in range(LINE_N):
            bi, bj = design_node_to_fit(i, j, reg)
            p = lt.fslot_point(fit, bi, bj, (0.0, 0.0))
            if -margin <= p[0] <= W + margin and -margin <= p[1] <= H + margin:
                out[(i, j)] = (float(p[0]), float(p[1]))
    return out
