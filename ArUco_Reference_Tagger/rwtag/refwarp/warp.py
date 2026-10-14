"""
rwtag.refwarp.warp
==================
Fit the transform REFERENCE design (um) -> this image (px). Ported from
Reference_Warp_Tagger/rwtag/refwarp/warp.py.

Seed: the coarse map from the Stage-2 fit {O, U, V, box_um}, which under the
identity registration IS the tag affine (Phase 3). Then ICP a homography against
the detected dots and refine with a thin-plate spline through the matched pairs
to absorb non-uniform expansion.

Changes from V1: the 150 um / 6-line constants and the glyph-slot helpers are
gone; the ICP gate may be PER DETECTION (each dot's own box pitch, for the
spectrum print); a similarity fit (uniform expansion + rotation + translation,
reflection allowed) is provided for the "expected" positions.
"""
from __future__ import annotations
import numpy as np
import cv2


def design_to_fit(u, v, reg):
    """Design box-coordinate (u, v) -> fit box-coordinate. Identity under the V2
    registration; kept so V1-shaped callers work (negative-sign axes carry +1)."""
    ca, cs, ra, rs = reg["orient"]; off0, off1 = reg["offset"]
    fc = [None, None]
    fc[ca] = cs * (np.asarray(u) - off0) + (1.0 if cs < 0 else 0.0)
    fc[ra] = rs * (np.asarray(v) - off1) + (1.0 if rs < 0 else 0.0)
    return fc[0], fc[1]


def coarse_map(um_xy, fit, reg):
    """Seed transform design um -> image px through the box fit (vectorised)."""
    O, U, V = np.asarray(fit["O"], float), np.asarray(fit["U"], float), np.asarray(fit["V"], float)
    box = float(fit["box_um"])
    um = np.asarray(um_xy, float).reshape(-1, 2)
    f0, f1 = design_to_fit(um[:, 0] / box, um[:, 1] / box, reg)
    return O + np.outer(f0, U) + np.outer(f1, V)


def warp_points(um_xy, model):
    """Design um -> image px through a warp model (TPS if present, else H)."""
    um = np.asarray(um_xy, float).reshape(-1, 2)
    if isinstance(model, dict):
        if model.get("tps") is not None:
            return np.asarray(model["tps"](um))
        model = model["H"]
    return cv2.perspectiveTransform(um.reshape(-1, 1, 2), model).reshape(-1, 2)


def fit_warp(ref_dots_um, det_px, fit, reg, pitch, iters=6, gate=0.5, min_pairs=20, tps=True, tps_max=500):
    """Fit reference design (um) -> image (px). `pitch` is a scalar or one value
    per detected dot (px); a detection pairs with a reference dot only within
    gate x its pitch. Returns {kind, H, tps, per_det_median, matched_frac,
    n_pairs}; H None on failure."""
    from scipy.spatial import cKDTree
    ref = np.asarray(ref_dots_um, float)
    det = np.asarray(det_px, float).reshape(-1, 2)
    pitch = np.broadcast_to(np.asarray(pitch, float), (len(det),))
    if len(ref) < min_pairs or len(det) < min_pairs:
        return {"H": None, "tps": None}
    cur = coarse_map(ref, fit, reg)
    H = None
    for _ in range(iters):
        dist, idx = cKDTree(cur).query(det)
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
        dist, idx = cKDTree(cur).query(det)
        m = dist < gate * pitch
        src, dst = ref[idx[m]], det[m]
        if len(src) >= 40:
            if len(src) > tps_max:
                sel = np.linspace(0, len(src) - 1, tps_max).astype(int)
                src, dst = src[sel], dst[sel]
            from scipy.interpolate import RBFInterpolator
            model = {"kind": "tps", "H": H, "tps": RBFInterpolator(src, dst, kernel="thin_plate_spline", smoothing=1.0)}
    cur = warp_points(ref, model)
    dd, _ = cKDTree(cur).query(det)
    model.update(per_det_median=float(np.median(dd)), matched_frac=float((dd < gate * pitch).mean()),
                 n_pairs=int((dd < gate * pitch).sum()))
    return model


def cv_residuals(src_um, dst_px, tps_max=500, folds=2, model=None):
    """Two-fold cross-validated TPS residual per pair (px vector, (n,2)): each
    point's position minus the TPS fitted to the OTHER fold. A TPS through all
    points interpolates them (residual 0 whenever n <= tps_max, i.e. every
    high-expansion frame), so the in-sample residual says nothing; this one is
    the point's departure from the smooth field of its neighbours. Falls back to
    `model` (or nothing) with < 80 pairs."""
    src = np.asarray(src_um, float); dst = np.asarray(dst_px, float)
    n = len(src)
    out = np.full((n, 2), np.nan)
    if n < 80:
        if model is not None and n:
            out = dst - warp_points(src, model)
        return out
    from scipy.interpolate import RBFInterpolator
    # spatial folds: checkerboard of the points' rank in x and y, so each fold covers the field
    fold = (np.argsort(np.argsort(src[:, 0])) + np.argsort(np.argsort(src[:, 1]))) % folds
    for f in range(folds):
        tr = np.nonzero(fold != f)[0]; te = np.nonzero(fold == f)[0]
        if len(tr) > tps_max:
            tr = tr[np.linspace(0, len(tr) - 1, tps_max).astype(int)]
        rbf = RBFInterpolator(src[tr], dst[tr], kernel="thin_plate_spline", smoothing=1.0)
        out[te] = dst[te] - rbf(src[te])
    return out


def similarity(X, Y):
    """Least-squares Y ~ s R X + t with R ORTHOGONAL -- reflection allowed. Design
    (y-up) -> image (y-down) IS a reflection; forcing a proper rotation fits s ~ 0
    (the 0d / Phase-B / W8 handedness bug). Returns dict(s, R, t, sign, angle_deg,
    rms, n). angle_deg is counter-clockwise on screen of the design +x axis."""
    X = np.asarray(X, float); Y = np.asarray(Y, float)
    mx, my = X.mean(0), Y.mean(0)
    A, B = X - mx, Y - my
    U, sv, Vt = np.linalg.svd(A.T @ B)
    R = (U @ Vt).T
    s = float(sv.sum() / (A ** 2).sum())
    t = my - s * R @ mx
    res = np.hypot(*((X @ R.T) * s + t - Y).T)
    ex = R @ np.array([1.0, 0.0])
    return {"s": s, "R": R, "t": t, "sign": float(np.sign(np.linalg.det(R))),
            "angle_deg": -float(np.degrees(np.arctan2(ex[1], ex[0]))),
            "rms": float(np.sqrt(np.mean(res ** 2))), "n": int(len(X))}


def similarity_points(um_xy, sim):
    P = np.asarray(um_xy, float).reshape(-1, 2)
    return sim["s"] * P @ np.asarray(sim["R"]).T + np.asarray(sim["t"])
