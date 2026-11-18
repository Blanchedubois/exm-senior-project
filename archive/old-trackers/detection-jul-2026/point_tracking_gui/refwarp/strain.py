"""
refwarp.strain
==============
Per-point expansion from tag-paired dots (initial -> one expansion). Local
deformation gradient F is fit from each dot's k nearest paired neighbours
(Δx_exp ≈ F·Δx_init); areal J = det F (rotation-invariant), linear expansion =
sqrt(J). Measured expansion = mean ± σ over points, vs the expected label ratio.
Handedness is already validated per frame (session.ref_sign) so det>0 throughout.
"""
from __future__ import annotations
import numpy as np


def _local_F(P0, P1, k=8):
    from scipy.spatial import cKDTree
    n = len(P0)
    J = np.full(n, np.nan); lin = np.full(n, np.nan)
    if n < k + 1:
        return J, lin
    _, idx = cKDTree(P0).query(P0, k=k + 1)
    for i in range(n):
        nb = idx[i, 1:]
        F, *_ = np.linalg.lstsq(P0[nb] - P0[i], P1[nb] - P1[i], rcond=None)
        det = F[0, 0] * F[1, 1] - F[0, 1] * F[1, 0]
        if det > 0:
            J[i] = det; lin[i] = np.sqrt(det)
    return J, lin


def strain(init_tags, exp_tags, init_label, exp_label, k=8, kinds=("dot",),
           lo=0.3, hi=8.0):
    """Measured linear expansion of `exp` relative to `init`, from shared-tag dots.
    Returns dict(n_pairs, n, mean, sigma, median, expected, P0, P1, lin)."""
    shared = [t for t in exp_tags if t in init_tags and t.split("|")[0] in kinds]
    expected = exp_label / init_label if init_label else float("nan")
    out = {"n_pairs": len(shared), "expected": expected,
           "mean": float("nan"), "sigma": float("nan"), "median": float("nan"), "n": 0}
    if len(shared) < k + 2:
        return out
    P0 = np.array([init_tags[t] for t in shared], float)
    P1 = np.array([exp_tags[t] for t in shared], float)
    J, lin = _local_F(P0, P1, k)
    out["P0"], out["P1"], out["lin"] = P0, P1, lin
    v = lin[np.isfinite(lin)]; v = v[(v > lo) & (v < hi)]
    if len(v) >= 3:
        out.update(mean=float(v.mean()), sigma=float(v.std()),
                   median=float(np.median(v)), n=int(len(v)))
    return out
