"""
gridtrack.reference  (Stage 3)
=============================
Tie the detected ArUco tags to the predefined reference (grid_metadata.json):
fit a reference->image transform, label every tag by its (node_i,node_j), and
predict where undetected nodes should be. Also builds a per-box homography that
Stage 4 uses to place the interior dots.

Headless: a MarkerDetection + a Reference in, a GridModel out.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
import numpy as np
import cv2

from .types import MarkerDetection, NodeRecord, GridModel
from . import lattice


@dataclass
class Reference:
    config: dict
    field_um: tuple
    aruco_dict: str
    nodes: list                             # list of {node_i,node_j,aruco_id,x_um,y_um}
    boxes: list                             # list of {box_i,box_j,corner_aruco_ids,dots,...}
    id_to_node: dict                        # aruco_id -> node dict
    ij_to_id: dict                          # (node_i,node_j) -> aruco_id


def load(path: str) -> Reference:
    with open(path) as f:
        m = json.load(f)
    id_to_node = {int(n["aruco_id"]): n for n in m["nodes"]}
    ij_to_id = {(n["node_i"], n["node_j"]): int(n["aruco_id"]) for n in m["nodes"]}
    return Reference(m["config"], tuple(m["field_um"]), m.get("aruco_dict", "DICT_6X6_1000"),
                     m["nodes"], m["boxes"], id_to_node, ij_to_id)


# ---------------------------------------------------------------- transforms
def _to_h(M):                               # 2x3 affine -> 3x3
    H = np.eye(3, dtype=np.float64)
    H[:2, :] = M
    return H


def transform_points(H: np.ndarray, pts) -> np.ndarray:
    """Apply a 3x3 homography to (N,2) points."""
    pts = np.asarray(pts, float).reshape(-1, 2)
    P = np.hstack([pts, np.ones((len(pts), 1))]) @ np.asarray(H).T
    return P[:, :2] / P[:, 2:3]


def fit_global_transform(ref_pts, img_pts, model="similarity", ransac_thresh=4.0):
    """Robustly fit reference(um) -> image(px). Returns (H 3x3, inlier mask)."""
    ref = np.asarray(ref_pts, np.float32)
    img = np.asarray(img_pts, np.float32)
    if model == "homography":
        H, mask = cv2.findHomography(ref, img, cv2.RANSAC, ransac_thresh)
    elif model == "affine":
        M, mask = cv2.estimateAffine2D(ref, img, method=cv2.RANSAC,
                                       ransacReprojThreshold=ransac_thresh)
        H = _to_h(M)
    else:                                   # similarity (rotation+uniform scale+translation)
        M, mask = cv2.estimateAffinePartial2D(ref, img, method=cv2.RANSAC,
                                              ransacReprojThreshold=ransac_thresh)
        H = _to_h(M)
    if mask is None:
        mask = np.ones(len(ref), bool)
    return np.asarray(H, float), mask.ravel().astype(bool)


# ---------------------------------------------------------------- map the grid
def map_grid(det: MarkerDetection, reference: Reference,
             model="similarity", ransac_thresh=4.0, dots_xy=None) -> GridModel:
    """The one Stage-3 entry point. Tiered by the number of tags matched to the
    reference: >=3 global fit, ==2 exact two-point similarity, ==1 single-marker
    local lattice (needs `dots_xy` to measure the local spacing), ==0 unanchored.
    All tiers produce a transform H; node prediction + box homographies are shared."""
    ref_pts, img_pts, det_ids = [], [], []
    for i in det.ids:
        i = int(i)
        if i in reference.id_to_node:
            n = reference.id_to_node[i]
            ref_pts.append([n["x_um"], n["y_um"]])
            img_pts.append(list(det.centers[i]))
            det_ids.append(i)
    n_tags = len(det_ids)

    if n_tags == 0:                                    # no anchor -> flag (require >=1 tag)
        return GridModel([], np.eye(3), {}, float("nan"), float("nan"), 0,
                         len(reference.nodes), method="unanchored")

    cam_ppu = lattice.camera_ppu(det.corners[det_ids[0]], reference.config["marker_um"])
    if n_tags >= 3:
        H, inliers = fit_global_transform(ref_pts, img_pts, model, ransac_thresh)
        method = "global"
    elif n_tags == 2:
        H = lattice.two_point_transform(ref_pts, img_pts)
        inliers = np.ones(2, bool); method = "two_point"
    else:                                              # n_tags == 1
        frame = lattice.marker_frame(det_ids[0], det, reference)
        pitch = lattice.estimate_pitch(dots_xy) if dots_xy is not None else None
        scale = pitch / reference.config["dot_pitch_um"] if pitch else frame["camera_ppu"]
        H = lattice.single_marker_transform(frame, scale)
        inliers = np.ones(1, bool)
        method = "single_marker" if pitch else "single_marker_noscale"

    img_arr = np.asarray(img_pts, float)
    pred = transform_points(H, ref_pts)
    resid = np.linalg.norm(pred - img_arr, axis=1)
    rms = float(np.sqrt((resid[inliers] ** 2).mean())) if inliers.any() else float(resid.mean())
    px_per_um = float(np.sqrt(abs(np.linalg.det(H[:2, :2]))))
    lam = px_per_um / cam_ppu if cam_ppu > 0 else float("nan")
    resid_by_id = {det_ids[k]: float(resid[k]) for k in range(n_tags)}

    detset = set(det_ids)
    nodes = []
    for n in reference.nodes:
        i = int(n["aruco_id"])
        refxy = (float(n["x_um"]), float(n["y_um"]))
        if i in detset:
            nodes.append(NodeRecord(i, n["node_i"], n["node_j"], refxy,
                                    tuple(map(float, det.centers[i])), "detected",
                                    resid_by_id.get(i, 0.0)))
        else:                                # predict from the global transform
            p = transform_points(H, [refxy])[0]
            nodes.append(NodeRecord(i, n["node_i"], n["node_j"], refxy,
                                    (float(p[0]), float(p[1])), "predicted", 0.0))

    node_by_id = {nd.aruco_id: nd for nd in nodes}
    box_h = box_homographies(reference, node_by_id)

    # Region-grow from the tags' boxes, refitting each box locally so predictions
    # follow the warp. This is what makes a single tag tag the dots correctly, and
    # it also fixes the global tier -- a single global transform cannot track the
    # warp once the local displacement approaches half the dot pitch.
    box_conf = {}
    if dots_xy is not None:
        seeds = {(b["box_i"], b["box_j"]): H for b in reference.boxes
                 if any(int(cid) in detset for cid in b["corner_aruco_ids"].values())}
        if seeds:
            grown, box_conf = lattice.region_grow(reference, seeds, dots_xy)
            box_h.update(grown)                        # local fits follow the warp interior
            # re-predict node positions from the region-grown transforms so the box
            # EDGES (used to tag the dashed boundary) follow the warp too, not just
            # the dots -- this is what makes single-tag dash tagging accurate.
            for nd in nodes:
                if nd.status == "detected":
                    continue
                ni, nj = nd.node_i, nd.node_j
                ps = [transform_points(grown[b], [nd.ref_xy_um])[0]
                      for b in ((ni, nj), (ni - 1, nj), (ni, nj - 1), (ni - 1, nj - 1))
                      if b in grown]
                if ps:
                    p = np.mean(ps, axis=0)
                    nd.img_xy_px = (float(p[0]), float(p[1]))
                    nd.status = "region_predicted"

    return GridModel(nodes, H, box_h, px_per_um, rms, n_tags, len(reference.nodes),
                     method=method, lambda_local=lam, box_confidence=box_conf)


def box_homographies(reference: Reference, node_by_id: dict) -> dict:
    """Per-box 3x3 (reference um -> image px) from that box's 4 corner tags
    (detected where available, else the globally-predicted positions)."""
    out = {}
    for b in reference.boxes:
        c = b["corner_aruco_ids"]
        ids4 = [c["tl"], c["tr"], c["br"], c["bl"]]
        refc, imgc = [], []
        ok = True
        for cid in ids4:
            nd = node_by_id.get(int(cid))
            if nd is None:
                ok = False
                break
            refc.append(nd.ref_xy_um)
            imgc.append(nd.img_xy_px)
        if ok:
            Hb, _ = cv2.findHomography(np.array(refc, np.float32), np.array(imgc, np.float32))
            if Hb is not None:
                out[(b["box_i"], b["box_j"])] = np.asarray(Hb, float)
    return out
