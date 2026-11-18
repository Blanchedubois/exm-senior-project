"""
refwarp.coreg
=============
Register a high-expansion image whose printed digits the classifier can't read,
by aligning its (mis-numbered) dot pattern to the REFERENCE and transferring box
numbers — then re-registering with those as trusted anchors so the normal warp fit
works.

The image's dots, expressed in DESIGN box-coordinates via its own (wrong)
registration, are the same physical lattice as the reference up to a grid symmetry
S (signed permutation) + integer box offset t. Brute-force S x t, score by overlap
with the reference lattice, then ACCEPT the candidate whose re-fit warp has low
residual AND the same handedness as a known-correct frame (rejecting the mirror
solutions the square grid admits).
"""
from __future__ import annotations
import numpy as np

from glyphtrack import gridmodel as gm
from . import warp

_ORIENTS = [np.array(m) for m in (
    ((1, 0), (0, 1)), ((0, -1), (1, 0)), ((-1, 0), (0, -1)), ((0, 1), (-1, 0)),
    ((1, 0), (0, -1)), ((-1, 0), (0, 1)), ((0, 1), (1, 0)), ((0, -1), (-1, 0)),
)]


def homography_sign(H):
    """Handedness of a warp model's linear part (det sign) — +/-1."""
    if isinstance(H, dict):
        H = H["H"]
    return float(np.sign(H[0, 0] * H[1, 1] - H[0, 1] * H[1, 0]))


def design_coords(d):
    """Each detected dot's design box-coord (u,v) under the image's registration,
    plus its fit box-node (bi,bj). Returns (uv (N,2), nodes (N,2) int)."""
    fit = d["fit"]; reg = d["model"]["reg"]
    O, U, V = fit["O"], fit["U"], fit["V"]
    Minv = np.linalg.inv(np.column_stack([U, V]))
    ca, cs, ra, rs = reg["orient"]; o0, o1 = reg["offset"]
    bc = (d["dots"] - O) @ Minv.T
    u = cs * bc[:, ca] + o0
    v = rs * bc[:, ra] + o1
    return np.column_stack([u, v]), np.floor(bc).astype(int)


def _anchors(uv, nodes, S, t):
    """Corrected box anchors [[ (bi,bj), N ]] from a candidate (S,t)."""
    cc = uv @ S.T + t                                     # corrected (col,row) per dot
    col = np.floor(cc[:, 0]).astype(int); row = np.floor(cc[:, 1]).astype(int)
    votes = {}                                            # fit node -> Counter(N)
    for k in range(len(uv)):
        if 0 <= col[k] < 5 and 0 <= row[k] < 5:
            N = col[k] * 5 + row[k] + 1
            votes.setdefault(tuple(nodes[k]), {}).setdefault(N, 0)
            votes[tuple(nodes[k])][N] += 1
    out = []
    for node, cnt in votes.items():
        N = max(cnt, key=cnt.get)
        out.append([list(node), int(N)])
    return out


def auto_register(d, lower_d, refdot_um, ref_sign, pitch, tol=0.05, tmax=7, top=8,
                  min_frac=0.35, max_resid=14.0):
    """Re-register `d` by transferring box numbers from a correctly-registered LOWER
    expansion `lower_d`. Aligning to the lower image's design coords (not the full
    reference) constrains the box offset via its limited FOV — the full reference is
    box-periodic and cannot fix the offset. Returns (model2, warp_model) or (None,None)."""
    from scipy.spatial import cKDTree
    low_uv, _ = design_coords(lower_d)                    # correct design coords, limited FOV
    uv, nodes = design_coords(d)                          # this image's WRONG design coords
    if len(uv) < 30 or len(low_uv) < 30:
        return None, None
    treeL = cKDTree(low_uv)
    sel = uv if len(uv) <= 400 else uv[np.linspace(0, len(uv) - 1, 400).astype(int)]
    cands = []
    off = range(-tmax, tmax + 1)
    for si, S in enumerate(_ORIENTS):
        hs = sel @ S.T
        for tx in off:
            for ty in off:
                dd, _ = treeL.query(hs + (tx, ty))
                cands.append((int((dd < tol).sum()), si, tx, ty))
    cands.sort(reverse=True)
    floor = min_frac * len(sel)
    for score, si, tx, ty in cands[: max(top, 1)]:
        if score < floor:
            break
        anchors = _anchors(uv, nodes, _ORIENTS[si], np.array([tx, ty]))
        if len(anchors) < 2:
            continue
        model2 = gm.build_grid_model(d["reads"], d["fit"], dots=d["dots"],
                                     manual={"numbers": anchors, "letters": []})
        if not model2.get("registered"):
            continue
        wm = warp.fit_warp(refdot_um, d["dots"], d["fit"], model2["reg"], pitch)
        if wm.get("H") is None:
            continue
        if (wm["per_det_median"] <= max_resid
                and wm["matched_frac"] >= 0.55
                and homography_sign(wm["H"]) == ref_sign):
            return model2, wm
    return None, None
