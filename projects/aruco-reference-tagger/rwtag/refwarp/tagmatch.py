"""
rwtag.refwarp.tagmatch
======================
Push every reference tag through the fitted warp and give each detected feature
the tag of its nearest warped reference point of the SAME category -- one to
one. Ported from reference-warp-tagger/rwtag/refwarp/tagmatch.py.

  detected dots   <- reference 'dot', gate 0.45 x THAT dot's box pitch, and the
                     tag's box must equal the box Stage 2 gave the dot
  detected dashes <- reference 'dash', gate `dash_gate_px` when given (0.4 x the
                     design's smallest dot-to-dash clearance: a blob that close to
                     a dash position can only be a dash), else 0.9 x the dot pitch
  decoded ArUco   <- reference 'aruco' BY ID; position never used

The V1 glyph category (numbers / letters) is gone.
"""
from __future__ import annotations
import numpy as np

from . import warp

GATE = {"dot": 0.45, "dash": 0.9}


def _by_category(records):
    out = {"dot": [], "dash": []}
    for r in records:
        if r["category"] in out:
            out[r["category"]].append((r["tag"], float(r["x_um"]), float(r["y_um"]), r.get("meta", {})))
    return out


def _match(ref_rows, det_px, model, tol):
    """{det_index: (ref_row_index, residual_px)} one-to-one, greedy by distance."""
    if not ref_rows or det_px is None or not len(det_px):
        return {}
    from scipy.spatial import cKDTree
    ref_px = warp.warp_points(np.array([[r[1], r[2]] for r in ref_rows]), model)
    det = np.asarray(det_px, float).reshape(-1, 2)
    tol = np.broadcast_to(np.asarray(tol, float), (len(det),))
    dist, idx = cKDTree(ref_px).query(det)
    cand = sorted((dist[i], i, int(idx[i])) for i in range(len(det)) if dist[i] < tol[i])
    used, out = set(), {}
    for d, i, ri in cand:
        if ri not in used:
            used.add(ri); out[i] = (ri, float(d))
    return out


def tag_image(d, model, records, gate=None):
    """Tag one frame. `d`: dots (n,2), dot_pitch_px (n,), dot_box (n,) or None,
    dashes (m,2), pitch (frame dot pitch px), aruco {id: (x, y)}.
    Returns {'dot': {i: (tag, res)}, 'dash': {...}, 'aruco': {id: (tag, 0)},
    'tag_xy': {tag: (x, y)}, 'box_mismatch': [i, ...]}."""
    gate = gate or GATE
    rows = _by_category(records)
    dots = d.get("dots")
    res = {"box_mismatch": []}
    m = _match(rows["dot"], dots, model, gate["dot"] * np.asarray(d["dot_pitch_px"], float))
    dot_out = {}
    box = d.get("dot_box")
    for i, (ri, r) in m.items():
        tag, _x, _y, meta = rows["dot"][ri]
        if box is not None and box[i] and int(meta.get("box", 0)) != int(box[i]):
            res["box_mismatch"].append(i); continue
        dot_out[i] = (tag, r)
    res["dot"] = dot_out
    dg = d.get("dash_gate_px") or gate["dash"] * float(d["pitch"])
    mh = _match(rows["dash"], d.get("dashes"), model, dg)
    res["dash"] = {i: (rows["dash"][ri][0], r) for i, (ri, r) in mh.items()}
    flat = {}
    for cat, key in (("dot", "dots"), ("dash", "dashes")):
        pts = d.get(key)
        for i, (tag, _r) in res[cat].items():
            flat[tag] = (float(pts[i][0]), float(pts[i][1]))
    ar = {}
    xy = d.get("aruco") or {}
    for r in records:
        if r["category"] == "aruco":
            aid = int(r["meta"]["aruco_id"])
            if aid in xy:
                ar[aid] = (r["tag"], 0.0)
                flat[r["tag"]] = (float(xy[aid][0]), float(xy[aid][1]))
    res["aruco"] = ar
    res["tag_xy"] = flat
    return res
