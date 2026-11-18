"""
pairkit.strain
=============
Per-point strain / expansion from paired points (initial -> one expansion).

- Local deformation gradient F is fit from each point's k nearest paired
  neighbours (Δx_exp ≈ F · Δx_init); areal expansion J = det F (rotation-
  invariant, so no global alignment needed); local LINEAR expansion = sqrt(J).
- For the displacement vector field, the expansion image is rigidly aligned
  (rotation + translation, scale kept) into the initial's frame, centred on a
  common reference box, so the vectors show the expansion radiating outward.
- Measured expansion = distribution of per-point linear expansion (mean ± σ),
  compared to the expected label ratio.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from collections import defaultdict
import numpy as np
import cv2


@dataclass
class StrainField:
    e: int
    label_init: float
    label_exp: float
    expected: float                    # label_exp / label_init
    ref_box: int
    P0: np.ndarray = None              # (N,2) initial positions (paired subset)
    P1: np.ndarray = None              # (N,2) matched expansion positions
    types: list = field(default_factory=list)
    J: np.ndarray = None               # (N,) areal expansion det F
    lin: np.ndarray = None             # (N,) linear expansion sqrt(J)
    disp: np.ndarray = None            # (N,2) displacement in aligned/centred init frame
    global_scale: float = float("nan")
    n_pairs: int = 0

    def stats(self, lo=0.3, hi=6.0):
        if self.lin is None:
            return {"n": 0, "mean": float("nan"), "sigma": float("nan"), "median": float("nan")}
        v = self.lin[np.isfinite(self.lin)]
        v = v[(v > lo) & (v < hi)]
        if len(v) < 3:
            return {"n": len(v), "mean": float("nan"), "sigma": float("nan"),
                    "median": float("nan")}
        return {"n": int(len(v)), "mean": float(np.mean(v)), "sigma": float(np.std(v)),
                "median": float(np.median(v))}


def _local_F(P0, P1, k=8):
    """Per-point deformation gradient J and linear expansion from k-NN."""
    from scipy.spatial import cKDTree
    n = len(P0)
    J = np.full(n, np.nan); lin = np.full(n, np.nan)
    if n < k + 1:
        return J, lin
    d, idx = cKDTree(P0).query(P0, k=k + 1)
    for i in range(n):
        nb = idx[i, 1:]
        dX = P0[nb] - P0[i]
        dx = P1[nb] - P1[i]
        F, *_ = np.linalg.lstsq(dX, dx, rcond=None)      # dx ≈ dX @ F  (F = grad^T)
        det = float(F[0, 0] * F[1, 1] - F[0, 1] * F[1, 0])
        if det > 0:
            J[i] = det; lin[i] = np.sqrt(det)
    return J, lin


def _pick_ref_box(pairing, e):
    """Box number (present in both) with the most paired points."""
    cnt = defaultdict(int)
    for i, ip in enumerate(pairing.initial.points):
        if pairing.matches[e][i] is not None:
            cnt[ip.box_number] += 1
    return max(cnt, key=cnt.get) if cnt else None


def compute_strain(pairing, e, k=8, ref_box=None):
    init = pairing.initial
    exp = pairing.expansions[e]
    ref_box = ref_box if ref_box is not None else _pick_ref_box(pairing, e)

    P0, P1, types, in_ref = [], [], [], []
    for i, ip in enumerate(init.points):
        mp = pairing.matches[e][i]
        if mp is None:
            continue
        P0.append([ip.x, ip.y]); P1.append([mp.x, mp.y]); types.append(ip.type)
        in_ref.append(ip.box_number == ref_box)
    sf = StrainField(e=e, label_init=init.label, label_exp=exp.label,
                     expected=(exp.label / init.label if init.label else float("nan")),
                     ref_box=ref_box)
    sf.P0 = np.array(P0, float); sf.P1 = np.array(P1, float)
    sf.types = types; sf.n_pairs = len(P0)
    if len(P0) < k + 1:
        return sf
    P0, P1, in_ref = sf.P0, sf.P1, np.array(in_ref)

    sf.J, sf.lin = _local_F(P0, P1, k)                   # areal J, linear = sqrt(J)

    M, _ = cv2.estimateAffinePartial2D(P0, P1, method=cv2.RANSAC)   # init -> exp similarity
    if M is not None:
        s = float(np.hypot(M[0, 0], M[1, 0]))
        sf.global_scale = s
        R = M[:, :2] / max(s, 1e-9)                       # rotation part
        c0 = P0[in_ref].mean(0) if in_ref.any() else P0.mean(0)   # ref-box centres
        c1 = P1[in_ref].mean(0) if in_ref.any() else P1.mean(0)
        q = (P1 - c1) @ R + c0            # exp de-rotated into init frame (scale kept), centred on ref box
        sf.disp = q - P0                  # displacement: radiates outward = the expansion
    return sf
