"""
gridtrack.lattice
=================
Anchor a grid from FEW ArUco tags (1 or 2), when the global fit (>=3 tags) is not
available. A single rigid tag fixes position + orientation + camera px/um; the
local dot spacing (which the tag cannot reveal, being rigid) is measured from the
detected dots. Two tags give an exact similarity directly.

Headless, pure. Used by reference.map_grid as the N=1 / N=2 tiers.
"""
from __future__ import annotations
import numpy as np


def _to_h(A2x3):
    H = np.eye(3, dtype=float)
    H[:2, :] = A2x3
    return H


def camera_ppu(corner, marker_um):
    """Image px per um from a tag's side length (magnification; independent of
    expansion because the tag is rigid)."""
    c = np.asarray(corner, float)
    sides = [np.linalg.norm(c[1] - c[0]), np.linalg.norm(c[2] - c[1]),
             np.linalg.norm(c[3] - c[2]), np.linalg.norm(c[0] - c[3])]
    return float(np.mean(sides) / marker_um)


def marker_frame(tag_id, det, reference):
    """Local grid frame from one tag: node coords, image centre, orthonormal axes
    R=[e_x|e_y] (grid +x,+y in image), and camera px/um."""
    n = reference.id_to_node[int(tag_id)]
    c = np.asarray(det.corners[int(tag_id)], float)          # TL,TR,BR,BL
    ex = c[1] - c[0]; ey = c[3] - c[0]
    ex = ex / (np.linalg.norm(ex) + 1e-9)
    ey = ey / (np.linalg.norm(ey) + 1e-9)
    return {"node": n,
            "node_um": np.array([n["x_um"], n["y_um"]], float),
            "center": np.asarray(det.centers[int(tag_id)], float).ravel(),
            "R": np.column_stack([ex, ey]),                  # 2x2
            "camera_ppu": camera_ppu(c, reference.config["marker_um"])}


def estimate_pitch(dots_xy, center=None, radius=None):
    """Local dot spacing (px) = robust median nearest-neighbour distance of the
    detected dots. For a square lattice this equals the pitch, and is invariant to
    orientation. Returns None if too few dots."""
    from scipy.spatial import cKDTree
    dots = np.asarray(dots_xy, float).reshape(-1, 2)
    if len(dots) < 8:
        return None
    if center is not None and radius:
        idx = cKDTree(dots).query_ball_point(np.asarray(center, float).ravel(), radius)
        if len(idx) >= 8:
            dots = dots[idx]
    d, _ = cKDTree(dots).query(dots, k=2)                    # nearest neighbour
    nn = d[:, 1]
    return float(np.median(nn))


def single_marker_transform(frame, scale):
    """Reference(um) -> image(px) similarity anchored at the tag:
    img = centre + scale * R * (p_um - node_um)."""
    A2 = scale * frame["R"]
    t = frame["center"] - A2 @ frame["node_um"]
    return _to_h(np.hstack([A2, t.reshape(2, 1)]))


def two_point_transform(ref_pts, img_pts):
    """Exact similarity from two node correspondences (scale+rotation+translation)."""
    r = np.asarray(ref_pts, float); q = np.asarray(img_pts, float)
    dr, dq = r[1] - r[0], q[1] - q[0]
    s = np.linalg.norm(dq) / (np.linalg.norm(dr) + 1e-9)
    ang = np.arctan2(dq[1], dq[0]) - np.arctan2(dr[1], dr[0])
    c, sn = np.cos(ang), np.sin(ang)
    R = s * np.array([[c, -sn], [sn, c]])
    t = q[0] - R @ r[0]
    return _to_h(np.hstack([R, t.reshape(2, 1)]))


def _transform(H, pts):
    pts = np.asarray(pts, float).reshape(-1, 2)
    P = np.hstack([pts, np.ones((len(pts), 1))]) @ np.asarray(H).T
    return P[:, :2] / P[:, 2:3]


def _fit_affine(ref, img):
    """Robust affine ref->img (RANSAC, rejects wrong initial matches). Returns 3x3."""
    import cv2
    ref = np.asarray(ref, np.float32); img = np.asarray(img, np.float32)
    if len(ref) >= 3:
        M, _ = cv2.estimateAffine2D(ref, img, method=cv2.RANSAC, ransacReprojThreshold=3.0)
        if M is not None:
            return _to_h(M)
    G = np.hstack([ref.astype(float), np.ones((len(ref), 1))])
    sol, *_ = np.linalg.lstsq(G, img.astype(float), rcond=None)
    return _to_h(np.hstack([sol[:2].T, sol[2].reshape(2, 1)]))


def _solve_box(dref, dots, tree, H, pitch_um, gate_frac, min_match):
    """Coarse→fine: match this box's dots to detections, refit locally each pass.
    Returns (refined H or None, confidence)."""
    from .correspond import assign_hungarian
    matches, conf = [], 0.0
    for gf in (gate_frac, gate_frac * 0.55):                 # coarse, then tighten
        pred = _transform(H, dref)
        ppu = float(np.sqrt(abs(np.linalg.det(np.asarray(H)[:2, :2]))))
        gate = gf * ppu * pitch_um
        cand = sorted({k for pp in pred for k in tree.query_ball_point(pp, gate)})
        if not cand:
            return None, 0.0
        matches = assign_hungarian(dots[cand], pred, gate)
        conf = len(matches) / max(len(dref), 1)
        if len(matches) < min_match:
            return None, conf
        H = _fit_affine(dref[[c for _, c in matches]], dots[[cand[r] for r, _ in matches]])
    return H, conf


def region_grow(reference, seed_transforms, dots_xy,
                gate_frac=0.4, accept_frac=0.30, min_match=6):
    """Spread from seed boxes across the grid, refitting each box's transform
    LOCALLY from its matched dots (so predictions follow the warp), and stopping
    where matches fail. Returns (box_transforms, box_confidence)."""
    from collections import deque
    from scipy.spatial import cKDTree

    box_by_ij = {(b["box_i"], b["box_j"]): b for b in reference.boxes}
    all_ij = set(box_by_ij)
    pitch_um = reference.config["dot_pitch_um"]
    dots = np.asarray(dots_xy, float).reshape(-1, 2)
    tree = cKDTree(dots)

    solved, conf = {}, {}
    queue = deque(seed_transforms.items())
    seen = set(seed_transforms)
    while queue:
        (bi, bj), H = queue.popleft()
        b = box_by_ij.get((bi, bj))
        if b is None:
            continue
        dref = np.array([[d["x_um"], d["y_um"]] for d in b["dots"]], float)
        Hb, c = _solve_box(dref, dots, tree, H, pitch_um, gate_frac, min_match)
        conf[(bi, bj)] = c
        if Hb is None or c < accept_frac:
            continue
        solved[(bi, bj)] = Hb                                # local transform (follows warp)
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):    # spread to neighbours
            nb = (bi + di, bj + dj)
            if nb in all_ij and nb not in seen:
                seen.add(nb); queue.append((nb, Hb))          # seed with the refined transform
    return solved, conf
