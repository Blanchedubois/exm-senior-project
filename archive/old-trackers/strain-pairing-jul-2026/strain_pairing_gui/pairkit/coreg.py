"""
pairkit.coreg
=============
Auto-register a high-expansion image whose printed box numbers the classifier
can't read, by GEOMETRICALLY aligning it to an already-correct lower expansion
and transferring the box numbers.

Both images, once each dot is expressed in DESIGN box-coordinates
`(col + fx, row + fy)` (box units, from that image's own registration), are the
SAME physical dot lattice — related only by a signed permutation S (one of the 8
grid symmetries) plus an INTEGER box offset t (the numbering error). Neither
scale nor sub-box phase differs (each image's fit normalises its own box pitch,
and the design dot phase is shared). So we brute-force the 8 orientations × a
bounded integer offset, score by how many high dots land on a reference dot, and
from the winning (S, t) emit trusted per-box anchors `(node, N)` that feed the
normal registration — no digit reading involved.
"""
from __future__ import annotations
import numpy as np
import cv2

from . import tags as T

# all 8 elements of D4 (4 rotations + 4 reflections). We keep the reflections
# because a mis-registered high image can itself sit in a reflected frame, so its
# CORRECT alignment to the reference may be a reflection. Chirality is instead
# enforced downstream: we accept only the (S,t) whose actual pixel correspondence
# is orientation-preserving (det>0) — a mirror numbering would make every strain
# gradient det<0 and be rejected.
_ORIENTS = [np.array(m) for m in (
    ((1, 0), (0, 1)), ((0, -1), (1, 0)), ((-1, 0), (0, -1)), ((0, 1), (-1, 0)),
    ((1, 0), (0, -1)), ((-1, 0), (0, 1)), ((0, 1), (1, 0)), ((0, -1), (-1, 0)),
)]


def _design_dots(table):
    """(P design box-coords, boxes, nodes, px pixel coords) for a table's dots."""
    P, boxes, nodes, px = [], [], [], []
    for p in table.points:
        if p.type != "dot" or p.box_number is None:
            continue
        c, r = T.box_colrow(p.box_number)
        P.append((c + p.fx, r + p.fy)); boxes.append(p.box_number)
        nodes.append(p.node); px.append((p.x, p.y))
    return (np.array(P, float).reshape(-1, 2), np.array(boxes), nodes,
            np.array(px, float).reshape(-1, 2))


def candidates(ref_table, high_table, tol=0.03, tmax=7, min_frac=0.5, top=6):
    """Ranked list of plausible (S, t, score) mappings of HIGH design box-coords
    onto REF's — best dot-overlap first, keeping only those whose matched pixel
    correspondence is proper (local det>0). The FINAL chirality can still flip when
    register() re-solves, so the caller must validate each post-reprocess."""
    from scipy.spatial import cKDTree
    R, _, _, Rpx = _design_dots(ref_table)
    H, _, _, Hpx = _design_dots(high_table)
    if len(R) < 20 or len(H) < 20:
        return []
    treeR = cKDTree(R)
    sel = H if len(H) <= 400 else H[np.linspace(0, len(H) - 1, 400).astype(int)]
    off = np.arange(-tmax, tmax + 1)
    scored = []
    for si, S in enumerate(_ORIENTS):
        hs = sel @ S.T
        for tx in off:
            for ty in off:
                d, _ = treeR.query(hs + (tx, ty))
                scored.append((int((d < tol).sum()), si, tx, ty))
    scored.sort(reverse=True)
    floor = min_frac * len(sel)
    out = []
    for score, si, tx, ty in scored:
        if score < floor or len(out) >= top:
            break
        S, t = _ORIENTS[si], np.array([tx, ty])
        d, idx = treeR.query(H @ S.T + t)
        m = d < tol
        if m.sum() >= 12 and _proper_fraction(Hpx[m], Rpx[idx[m]]) > 0.6:
            out.append((score, S, t))
    return out


def anchors_for(high_table, S, t):
    """Trusted `[[node, N], ...]` box anchors for HIGH from one (S, t) mapping."""
    _, boxes, nodes, _ = _design_dots(high_table)
    anchors = {}
    for box, node in zip(boxes, nodes):
        if node is None:
            continue
        c, r = T.box_colrow(int(box))
        cc = S @ np.array([c + 0.5, r + 0.5]) + t
        col, row = int(np.floor(cc[0])), int(np.floor(cc[1]))
        if 0 <= col < 5 and 0 <= row < 5:
            anchors[tuple(node)] = col * 5 + row + 1
    return [[list(k), int(v)] for k, v in anchors.items()]


def strain_is_proper(ref_table, high_table, min_pairs=12):
    """After HIGH is (re)registered: is the HIGH->REF deformation orientation-
    preserving? Pairs by shared canonical tag and checks the local det sign — the
    exact criterion the strain step uses. Returns (ok, n_shared)."""
    ha = {p.tag: (p.x, p.y) for p in high_table.points if p.tag and p.type == "dot"}
    ra = {p.tag: (p.x, p.y) for p in ref_table.points if p.tag and p.type == "dot"}
    sh = [k for k in ha if k in ra]
    if len(sh) < min_pairs:
        return False, len(sh)
    hp = np.array([ha[k] for k in sh]); rp = np.array([ra[k] for k in sh])
    return _proper_fraction(hp, rp) > 0.6, len(sh)


def _proper_fraction(hp, rp, k=8):
    """Fraction of matched dots whose LOCAL deformation gradient (high_px ->
    ref_px, from k nearest neighbours) is orientation-preserving (det>0). This is
    the exact criterion the strain step applies, so a mirror numbering — which
    yields det<0 everywhere — is caught here rather than downstream."""
    from scipy.spatial import cKDTree
    n = len(hp)
    if n < k + 2:
        return 0.0
    _, ii = cKDTree(hp).query(hp, k=k + 1)
    pos = tot = 0
    for i in range(n):
        nb = ii[i, 1:]
        F, *_ = np.linalg.lstsq(hp[nb] - hp[i], rp[nb] - rp[i], rcond=None)
        det = F[0, 0] * F[1, 1] - F[0, 1] * F[1, 0]
        if np.isfinite(det):
            tot += 1; pos += det > 0
    return pos / tot if tot else 0.0


