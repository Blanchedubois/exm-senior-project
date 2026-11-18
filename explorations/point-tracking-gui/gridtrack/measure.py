"""
gridtrack.measure  (Stage 4)
============================
Detect and TAG every interior feature:

  * dots  -> trackpy sub-pixel localisation, tagged (box_i,box_j,local_i,local_j)
             by Hungarian assignment to the reference dot list (mapped through
             each box's homography). Dots are the measurement workhorse.
  * dashes -> elongated marks (skimage regionprops), tagged by nearest box edge.

Headless: a corrected+oriented image + a GridModel + a Reference in, a tidy
`FeatureTable` (pandas DataFrame) out. Nothing is silently dropped -- undetected
reference dots are recorded with status "predicted_missing".
"""
from __future__ import annotations
import logging
import warnings
import numpy as np
import pandas as pd

from .types import MeasureParams
from .reference import transform_points
from .correspond import assign_hungarian
from .io import to_uint8

logging.getLogger("trackpy").setLevel(logging.ERROR)

COLUMNS = ["type", "box_i", "box_j", "local_i", "local_j", "edge",
           "ref_x_um", "ref_y_um", "img_x_px", "img_y_px",
           "mass", "size", "ecc", "angle_deg", "status"]


# ---------------------------------------------------------------- detection
def detect_dots(img, params: MeasureParams) -> pd.DataFrame:
    """trackpy sub-pixel localisation of round bright features."""
    import trackpy as tp
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        f = tp.locate(np.asarray(img, float), params.diameter,
                      minmass=params.minmass, invert=False)
    if len(f):
        f = f[f["ecc"] < params.ecc_max]
    return f.reset_index(drop=True)


def detect_dashes(img, params: MeasureParams, bbox=None) -> pd.DataFrame:
    """Elongated boundary marks via threshold + region shape. `bbox`
    (x0,y0,x1,y1) restricts to the grid interior to avoid edge noise."""
    from skimage.measure import label, regionprops
    u8 = to_uint8(img)
    mask = u8 > max(45, int(u8.mean() + 1.5 * u8.std()))
    if bbox is not None:
        x0, y0, x1, y1 = [int(v) for v in bbox]
        keep = np.zeros_like(mask)
        keep[max(0, y0):y1, max(0, x0):x1] = 1
        mask &= keep.astype(bool)
    rows = []
    for r in regionprops(label(mask)):
        major = getattr(r, "axis_major_length", None)
        minor = getattr(r, "axis_minor_length", None)
        if major is None:                                     # older scikit-image
            major, minor = r.major_axis_length, r.minor_axis_length
        elong = major / max(minor, 1e-6)
        if elong >= params.dash_min_elong and params.dash_area_min <= r.area <= params.dash_area_max:
            cy, cx = r.centroid
            rows.append((cx, cy, major, np.degrees(r.orientation)))
    return pd.DataFrame(rows, columns=["x", "y", "length", "angle"])


# ---------------------------------------------------------------- tagging
def _row(**kw):
    r = {c: kw.get(c, np.nan) for c in COLUMNS}
    r.update({k: kw[k] for k in kw if k in COLUMNS})
    return r


def tag_dots(dots: pd.DataFrame, grid, reference, params: MeasureParams):
    """Hungarian-assign detected dots to each box's reference dot list."""
    from scipy.spatial import cKDTree
    rows = []
    det_xy = dots[["x", "y"]].to_numpy() if len(dots) else np.zeros((0, 2))
    tree = cKDTree(det_xy) if len(det_xy) else None
    used = np.zeros(len(dots), bool)
    pitch_px = reference.config["dot_pitch_um"] * grid.px_per_um
    max_r = params.gate_frac * pitch_px
    box_by_ij = {(b["box_i"], b["box_j"]): b for b in reference.boxes}
    n_matched = 0

    for (bi, bj), Hb in grid.box_homographies.items():
        b = box_by_ij[(bi, bj)]
        dref = np.array([[d["x_um"], d["y_um"]] for d in b["dots"]], float)
        pred = transform_points(Hb, dref)                     # (M,2) image px
        cand = sorted({k for p in pred for k in (tree.query_ball_point(p, max_r) if tree else [])
                       if not used[k]})
        matched_pred = {}
        if cand:
            for r, c in assign_hungarian(det_xy[cand], pred, max_r):
                k = cand[r]
                used[k] = True
                matched_pred[c] = k
        for c, d in enumerate(b["dots"]):
            if c in matched_pred:
                k = matched_pred[c]
                rows.append(_row(type="dot", box_i=bi, box_j=bj, local_i=d["i"], local_j=d["j"],
                                 ref_x_um=d["x_um"], ref_y_um=d["y_um"],
                                 img_x_px=det_xy[k, 0], img_y_px=det_xy[k, 1],
                                 mass=dots["mass"].iloc[k], size=dots["size"].iloc[k],
                                 ecc=dots["ecc"].iloc[k], status="matched"))
                n_matched += 1
            else:                                             # record, never drop silently
                rows.append(_row(type="dot", box_i=bi, box_j=bj, local_i=d["i"], local_j=d["j"],
                                 ref_x_um=d["x_um"], ref_y_um=d["y_um"],
                                 img_x_px=pred[c, 0], img_y_px=pred[c, 1],
                                 status="predicted_missing"))
    n_unmatched_det = int((~used).sum())
    return rows, n_matched, n_unmatched_det


def _edge_specs(ni, nj, nbx, nby):
    """Edges anchored at node (ni,nj) going right/down (each edge once), with the
    box + edge-name they belong to."""
    specs = []
    if ni < nbx:                                          # horizontal edge (ni,nj)->(ni+1,nj)
        specs.append((1, 0, "top", ni, nj) if nj < nby else (1, 0, "bottom", ni, nj - 1))
    if nj < nby:                                          # vertical edge (ni,nj)->(ni,nj+1)
        specs.append((0, 1, "left", ni, nj) if ni < nbx else (0, 1, "right", ni - 1, nj))
    return specs


def tag_dashes(dashes: pd.DataFrame, grid, reference):
    """Tag each dash by its box edge, indexed 1-D from the node anchor.

    Uses the region-predicted node positions (so edges follow the warp) and indexes
    each dash by its ORDER from the node along the edge -- robust to the dash
    offset/expansion model -- with gap-aware spacing so a dropout skips an index
    rather than shifting every later label."""
    if len(dashes) == 0:
        return []
    gc = reference.config
    box_um = gc["box_um"]; period0 = gc["boundary_dash_um"] + gc["boundary_gap_um"]
    nbx, nby = gc["n_boxes_x"], gc["n_boxes_y"]
    node_by_id = {nd.aruco_id: nd for nd in grid.nodes}
    idx_by_ij = reference.ij_to_id
    det = dashes[["x", "y"]].to_numpy(float)
    ang = dashes["angle"].to_numpy(float) if "angle" in dashes.columns else np.zeros(len(dashes))
    used = np.zeros(len(dashes), bool)
    rows = []

    for nj in range(nby + 1):
        for ni in range(nbx + 1):
            aid = idx_by_ij.get((ni, nj))
            if aid is None:
                continue
            for di, dj, edge, bi, bj in _edge_specs(ni, nj, nbx, nby):
                bid = idx_by_ij.get((ni + di, nj + dj))
                A, B = node_by_id.get(aid), node_by_id.get(bid) if bid is not None else None
                if A is None or B is None:
                    continue
                pA = np.array(A.img_xy_px, float); pB = np.array(B.img_xy_px, float)
                v = pB - pA; L = float(np.linalg.norm(v))
                if L < 1:
                    continue
                u = v / L
                eang = np.degrees(np.arctan2(u[1], u[0]))
                period_px = period0 * (L / box_um)
                cand = []
                for m in np.where(~used)[0]:
                    q = det[m] - pA
                    t = float(q @ u)
                    perp = float(np.linalg.norm(q - t * u))
                    if -0.3 * period_px <= t <= L + 0.3 * period_px and perp < 0.5 * period_px:
                        # skimage orientation is from the row axis -> convert to x-axis
                        dash_ang_x = 90.0 - ang[m]
                        da = abs(((dash_ang_x - eang + 90) % 180) - 90)  # dash ∥ edge?
                        if da < 30:
                            cand.append((int(m), t))
                if not cand:
                    continue
                cand.sort(key=lambda x: x[1])
                ts = np.array([t for _, t in cand])
                per = float(np.median(np.diff(ts))) if len(ts) >= 2 else period_px
                if not (0.5 * period_px < per < 2.0 * period_px):
                    per = period_px
                k = 0
                for i, (m, t) in enumerate(cand):
                    if i > 0:
                        k += max(1, int(round((t - ts[i - 1]) / per)))  # gap-aware
                    used[m] = True
                    rows.append(_row(type="dash", box_i=bi, box_j=bj, edge=edge, local_i=k,
                                     img_x_px=det[m, 0], img_y_px=det[m, 1],
                                     angle_deg=ang[m], status="matched"))
    return rows


# ---------------------------------------------------------------- entry point
def detect_features(img, grid, reference, params: MeasureParams = None) -> pd.DataFrame:
    params = params or MeasureParams()
    dots = detect_dots(img, params)
    rows, n_matched, n_unmatched = tag_dots(dots, grid, reference, params)

    if params.detect_dashes:
        # detect dashes over the whole solved grid region: use every node with a
        # real position (detected OR region-predicted), so a single tag whose
        # region-grow spread across the frame still covers all its edges.
        node_xy = np.array([n.img_xy_px for n in grid.nodes
                            if n.status in ("detected", "region_predicted")])
        bbox = None
        if len(node_xy):
            x0, y0 = node_xy.min(0) - 20; x1, y1 = node_xy.max(0) + 20
            bbox = (x0, y0, x1, y1)
        dashes = detect_dashes(img, params, bbox=bbox)
        rows += tag_dashes(dashes, grid, reference)

    df = pd.DataFrame(rows, columns=COLUMNS)
    df.attrs["n_dot_detections"] = int(len(dots))
    df.attrs["n_dots_matched"] = n_matched
    df.attrs["n_dot_unmatched_detections"] = n_unmatched
    return df
