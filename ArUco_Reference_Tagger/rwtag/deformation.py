"""
rwtag.deformation
=================
Per-feature local deformation between two tagged frames (docs/06 §3). For every
paired dot i, the affine  d1 = F d0  is fitted over its k nearest paired
neighbours (d = neighbour - i, in each frame's corrected px), and F is decomposed:

  J = det F                 areal expansion          lin = sqrt(J)   linear expansion
  F = R U (polar)           R_rot rotation, U_stretch symmetric stretch (keys avoid the
                            displacement 'U' of pairing.field)
  lam1 >= lam2              principal stretches (singular values of F)
  phi                       first principal axis in the INITIAL frame, deg ccw on screen
  anisotropy = lam1/lam2 - 1
  rot_deg                   local rotation, deg ccw on screen
  resid_rms                 RMS misfit of the neighbours to the affine (px) -- local warping
                            the affine cannot describe
  F_cov (4x4)               covariance of (F11, F12, F21, F22) propagated from the
                            position covariances of i and its neighbours in BOTH frames
                            (first order; the shared centre point correlates the rows)
  *_sigma                   1-sigma of lin, lam1, lam2, anisotropy, rot_deg, phi, J from F_cov

These are the rawest per-feature forms of the proposal's three modes: anisotropy
(stretch varying with direction), inhomogeneity (lin varying with position) and
local warping (resid_rms). The tool exports them; aggregation is downstream.
Generalises V1's refwarp.strain._local_F (which returned J and lin only).
"""
from __future__ import annotations
import numpy as np


def _decompose(F):
    """(n,2,2) -> dict of per-point quantities (no sigmas)."""
    W, S, Vt = np.linalg.svd(F)
    R = W @ Vt
    J = F[:, 0, 0] * F[:, 1, 1] - F[:, 0, 1] * F[:, 1, 0]
    lam1, lam2 = S[:, 0], S[:, 1]
    v1 = Vt[:, 0, :]                                        # first right-singular vector = principal axis, initial frame
    phi = (-np.degrees(np.arctan2(v1[:, 1], v1[:, 0]))) % 180.0
    rot = -np.degrees(np.arctan2(R[:, 1, 0], R[:, 0, 0]))
    with np.errstate(invalid="ignore", divide="ignore"):
        lin = np.sqrt(np.where(J > 0, J, np.nan))
        aniso = lam1 / lam2 - 1.0
    U = np.einsum("nji,nj,njk->nik", Vt, S, Vt)             # V S V^T
    return {"J": J, "lin": lin, "lam1": lam1, "lam2": lam2, "phi_deg": phi, "rot_deg": rot,
            "anisotropy": aniso, "R_rot": R, "U_stretch": U}


def _sigmas(F, Fcov, base):
    """Propagate F_cov to the derived quantities by central finite differences."""
    n = len(F)
    keys = ("J", "lin", "lam1", "lam2", "anisotropy", "rot_deg", "phi_deg")
    G = {k: np.zeros((n, 4)) for k in keys}
    h = 1e-6
    for p in range(4):
        dF = np.zeros((n, 2, 2)); dF[:, p // 2, p % 2] = h
        up, dn = _decompose(F + dF), _decompose(F - dF)
        for k in keys:
            d = up[k] - dn[k]
            if k in ("rot_deg",):
                d = (d + 180) % 360 - 180
            if k == "phi_deg":
                d = (d + 90) % 180 - 90
            G[k][:, p] = d / (2 * h)
    out = {}
    for k in keys:
        v = np.einsum("ni,nij,nj->n", G[k], Fcov, G[k])
        out[k + "_sigma"] = np.sqrt(np.maximum(v, 0))
    return out


def local_gradient(P0, P1, C0=None, C1=None, k=8, radius=None, min_nb=4):
    """Fit F per point. P0, P1 (n,2) paired positions in the initial and compared
    frames (px); C0, C1 (n,2,2) their covariances (optional). Neighbours: the k
    nearest in P0, or all within `radius` px (at least min_nb). Returns a dict of
    (n,)-arrays plus F (n,2,2), F_cov (n,4,4), R_rot, U_stretch, n_nb."""
    from scipy.spatial import cKDTree
    P0 = np.asarray(P0, float); P1 = np.asarray(P1, float)
    n = len(P0)
    F = np.full((n, 2, 2), np.nan); Fcov = np.full((n, 4, 4), np.nan)
    resid = np.full(n, np.nan); nnb = np.zeros(n, int)
    if n < min_nb + 1:
        out = {key: np.full(n, np.nan) for key in ("J", "lin", "lam1", "lam2", "phi_deg", "rot_deg", "anisotropy")}
        out.update(F=F, F_cov=Fcov, resid_rms=resid, n_nb=nnb)
        return out
    tree = cKDTree(P0)
    if radius is None:
        _d, idx = tree.query(P0, k=min(k + 1, n))
        nbs = [row[1:] for row in idx]
    else:
        nbs = [np.array([j for j in tree.query_ball_point(P0[i], radius) if j != i]) for i in range(n)]
    have_cov = C0 is not None and C1 is not None
    for i in range(n):
        nb = np.asarray(nbs[i], int)
        if len(nb) < min_nb:
            continue
        d0 = P0[nb] - P0[i]; d1 = P1[nb] - P1[i]
        m = len(nb)
        X = np.zeros((2 * m, 4)); X[0::2, 0:2] = d0; X[1::2, 2:4] = d0
        y = d1.reshape(-1)
        XtX = X.T @ X
        if np.linalg.cond(XtX) > 1e10:
            continue
        B = np.linalg.solve(XtX, X.T)
        f = B @ y
        Fi = f.reshape(2, 2)
        F[i] = Fi
        r = y - X @ f
        resid[i] = float(np.sqrt(np.mean(r.reshape(-1, 2) ** 2) * 2 / 2)) if m else np.nan
        nnb[i] = m
        if have_cov:
            # effective covariance of d1_j = (p1_j - p1_i) - F (p0_j - p0_i): both frames' errors
            Ce1 = C1[nb] + np.einsum("ab,nbc,dc->nad", Fi, C0[nb], Fi)
            Ci = C1[i] + Fi @ C0[i] @ Fi.T
            Sy = np.zeros((2 * m, 2 * m))
            for a in range(m):
                Sy[2 * a:2 * a + 2, 2 * a:2 * a + 2] = Ce1[a]
            Sy += np.kron(np.ones((m, m)), Ci)                      # the shared centre point
            Fcov[i] = B @ Sy @ B.T
    ok = np.isfinite(F).all((1, 2))
    out = {key: np.full(n, np.nan) for key in ("J", "lin", "lam1", "lam2", "phi_deg", "rot_deg", "anisotropy")}
    out["R_rot"] = np.full((n, 2, 2), np.nan); out["U_stretch"] = np.full((n, 2, 2), np.nan)
    if ok.any():
        dec = _decompose(F[ok])
        for key, v in dec.items():
            out[key][ok] = v
        if have_cov:
            sg = _sigmas(F[ok], Fcov[ok], dec)
            for key, v in sg.items():
                out.setdefault(key, np.full(n, np.nan))[ok] = v
    if not have_cov:
        for key in ("J", "lin", "lam1", "lam2", "anisotropy", "rot_deg", "phi_deg"):
            out[key + "_sigma"] = np.full(n, np.nan)
    out.update(F=F, F_cov=Fcov, resid_rms=resid, n_nb=nnb)
    return out
