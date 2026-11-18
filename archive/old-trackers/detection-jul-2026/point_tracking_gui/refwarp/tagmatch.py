"""
refwarp.tagmatch
================
Given a fitted reference->image warp, push every reference tag point into the image
and assign each detected feature the tag of its nearest warped reference point of the
SAME category — one-to-one (no double counting). Glyphs are tagged by POSITION, so a
digit that the classifier can't read still gets the right tag.

Categories paired:
  detected dots   <- reference 'dot' + 'node'    (both are physical dots)
  detected dashes <- reference 'dash'
  detected glyphs <- reference 'number' + 'letter'
"""
from __future__ import annotations
import numpy as np

from . import warp

# nearest-neighbour gate as a fraction of the local dot pitch, per category
GATE = {"dot": 0.45, "dash": 0.9, "glyph": 1.2}


def _by_category(records):
    dots, dashes, glyphs = [], [], []
    for r in records:
        c = r["category"]
        row = (r["tag"], r["x_um"], r["y_um"])
        if c in ("dot", "node"):
            dots.append(row)
        elif c == "dash":
            dashes.append(row)
        elif c in ("number", "letter"):
            glyphs.append(row)
    return dots, dashes, glyphs


def _match(ref_rows, det_px, H, tol):
    """One-to-one: each detected feature <- nearest warped reference tag within tol.
    Returns {det_index: (tag, residual_px)} (greedy nearest, one ref per feature)."""
    if not len(ref_rows) or det_px is None or not len(det_px):
        return {}
    from scipy.spatial import cKDTree
    tags = [r[0] for r in ref_rows]
    ref_um = np.array([[r[1], r[2]] for r in ref_rows], float)
    ref_px = warp.warp_points(ref_um, H)
    tree = cKDTree(ref_px)
    det = np.asarray(det_px, float)
    dist, idx = tree.query(det)
    cand = sorted((dist[i], i, int(idx[i])) for i in range(len(det)) if dist[i] < tol)
    used, out = set(), {}
    for d, i, ri in cand:
        if ri in used:
            continue
        used.add(ri); out[i] = (tags[ri], float(d))
    return out


def tag_image(d, H, records, gate=None):
    """Tag one detected image. Returns dict with per-category assignments:
    {'dot': {i:(tag,res)}, 'dash': {...}, 'glyph': {...}} indexed into
    d['dots'] / d['dashes'] / d['glyphs'], plus a flat tag->(x,y) map."""
    gate = gate or GATE
    pitch = float(d["basis"]["pitch"])
    rdot, rdash, rglyph = _by_category(records)
    res = {
        "dot": _match(rdot, d.get("dots"), H, gate["dot"] * pitch),
        "dash": _match(rdash, d.get("dashes"), H, gate["dash"] * pitch),
        "glyph": _match(rglyph, d.get("glyphs"), H, gate["glyph"] * pitch),
    }
    flat = {}
    for cat, det_key in (("dot", "dots"), ("dash", "dashes"), ("glyph", "glyphs")):
        pts = d.get(det_key)
        for i, (tag, _r) in res[cat].items():
            flat[tag] = (float(pts[i][0]), float(pts[i][1]))
    res["tag_xy"] = flat
    return res
