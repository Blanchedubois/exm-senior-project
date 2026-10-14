"""
rwtag.lattice
=============
Dot-lattice geometry, ported from Reference_Warp_Tagger/rwtag/glyph/lattice.py.
Only the design-independent parts are kept: blob detection, the lattice basis
estimate and its refinement, and the dash-on-grid test. Every V1 constant
(150 um boxes, 8 um dots, the glyph fiducial slots) is gone -- the design file
supplies the geometry now. Headless: numpy + OpenCV + scipy.
"""
from __future__ import annotations
import numpy as np
import cv2


def detect_blobs(u8, tophat=15, area=(12, 220), max_aspect=1.7, min_extent=0.55, noise_k=5.0,
                 mask=None):
    """Centroids (N,2) and areas (N,) of small, round, bright blobs.

    White top-hat -> threshold -> connected components -> size / roundness gates.
    The threshold is max(Otsu, median + noise_k * 1.4826 * MAD) of the top-hat
    image (V2 workshop, Phase C): Stage 1 flat-fielding amplifies the read noise
    in the vignetted corners, and in a SPARSE frame (few dots, high expansion)
    plain Otsu loses its bimodal histogram and drops into the noise. Dense frames
    are unaffected (their Otsu is far above the floor). noise_k = 0 gives the V1
    behaviour. `mask` (uint8, nonzero = allowed) restricts where blobs count."""
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(tophat) | 1, int(tophat) | 1))
    th = cv2.morphologyEx(np.asarray(u8, np.uint8), cv2.MORPH_TOPHAT, se)
    otsu, _ = cv2.threshold(th, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    thr = float(otsu)
    if noise_k > 0:
        med = float(np.median(th))
        mad = float(np.median(np.abs(th.astype(np.int16) - med))) * 1.4826
        thr = max(thr, med + noise_k * mad)
    b = (th > thr).astype(np.uint8) * 255
    if mask is not None:
        b[np.asarray(mask) == 0] = 0
    n, _lab, st, cen = cv2.connectedComponentsWithStats(b, 8)
    a = st[1:, cv2.CC_STAT_AREA]; w = st[1:, cv2.CC_STAT_WIDTH]; h = st[1:, cv2.CC_STAT_HEIGHT]
    ok = ((a >= area[0]) & (a <= area[1])
          & (np.maximum(w, h) / np.maximum(np.minimum(w, h), 1) <= max_aspect)
          & (a / np.maximum(w * h, 1) >= min_extent))
    return cen[1:][ok].astype(float).reshape(-1, 2), a[ok].astype(float)


def estimate_basis(pts, k=6):
    """Two shortest lattice vectors + pitch from a point set, via a histogram of
    nearest-neighbour vectors folded to [0, 90) deg. Returns dict(v1, v2, pitch,
    angle_deg)."""
    from scipy.spatial import cKDTree
    pts = np.asarray(pts, float)
    tree = cKDTree(pts)
    d, idx = tree.query(pts, k=min(k + 1, len(pts)))
    pitch = float(np.median(d[:, 1]))
    vecs = (pts[idx[:, 1:]] - pts[:, None, :]).reshape(-1, 2)
    lens = np.hypot(vecs[:, 0], vecs[:, 1])
    keep = vecs[(lens > 0.8 * pitch) & (lens < 1.2 * pitch)]
    ang = np.degrees(np.arctan2(keep[:, 1], keep[:, 0])) % 90.0
    hist, edges = np.histogram(ang, bins=180, range=(0, 90))
    pk = int(np.argmax(hist))
    a0 = float(edges[pk] + (edges[1] - edges[0]) / 2)
    th = np.radians(a0)
    return {"v1": np.array([np.cos(th), np.sin(th)]) * pitch,
            "v2": np.array([-np.sin(th), np.cos(th)]) * pitch, "pitch": pitch, "angle_deg": a0}


def refine_basis(pts, basis, iters=6, origin=None):
    """Iterated closest-node least squares: assign each dot to its integer lattice
    node, re-fit (origin, v1, v2) to the inliers, repeat. `origin` seeds the
    lattice phase (default: the dot nearest the centroid)."""
    pts = np.asarray(pts, float)
    if origin is None:
        origin = pts[np.argmin(np.hypot(*(pts - pts.mean(0)).T))]
    origin = np.asarray(origin, float).copy()
    v1, v2 = np.asarray(basis["v1"], float).copy(), np.asarray(basis["v2"], float).copy()
    good = np.zeros(len(pts), bool)
    for _ in range(iters):
        Binv = np.linalg.inv(np.column_stack([v1, v2]))
        ij = np.round((pts - origin) @ Binv.T)
        A = np.column_stack([np.ones(len(pts)), ij[:, 0], ij[:, 1]])
        pred = A @ np.column_stack([origin, v1, v2]).T
        good = np.hypot(*(pts - pred).T) < 0.35 * np.hypot(*v1)
        if good.sum() < 12:
            break
        sol, *_ = np.linalg.lstsq(A[good], pts[good], rcond=None)
        origin, v1, v2 = sol[0], sol[1], sol[2]
    return {"v1": v1, "v2": v2, "origin": origin, "pitch": float(0.5 * (np.hypot(*v1) + np.hypot(*v2))),
            "angle_deg": float(np.degrees(np.arctan2(v1[1], v1[0])) % 90), "n_inliers": int(good.sum())}


def lattice_deviation(pts, basis):
    """Distance of each point from its nearest node of `basis` (px)."""
    B = np.column_stack([basis["v1"], basis["v2"]])
    ij = np.round((np.asarray(pts, float) - basis["origin"]) @ np.linalg.inv(B).T)
    return np.hypot(*(pts - (basis["origin"] + ij @ B.T)).T)


def dashes_on_grid(dash_pts, grid, tol_frac=0.15):
    """Dash centres within tol_frac x box pitch of a box-boundary line.
    Returns (kept (n,2), n_dropped)."""
    dash_pts = np.asarray(dash_pts, float).reshape(-1, 2)
    if len(dash_pts) == 0:
        return dash_pts, 0
    P = grid["box_pitch"]
    pu = dash_pts @ grid["u"] - grid["phase_u"]
    pv = dash_pts @ grid["v"] - grid["phase_v"]
    du = np.abs((pu + P / 2) % P - P / 2)
    dv = np.abs((pv + P / 2) % P - P / 2)
    keep = np.minimum(du, dv) < tol_frac * P
    return dash_pts[keep], int((~keep).sum())
