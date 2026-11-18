"""
pairkit.process
==============
Run the four glyph stages headlessly on ONE image and return a PointTable of the
filtered, box-tagged fiducials (dots / dashes / numbers / letters). Reuses the
copied glyph pipeline exactly as the GUI stages do.
"""
from __future__ import annotations
from dataclasses import replace
import numpy as np

from .types import PointRecord, PointTable


def _clf(path):
    from glyphtrack.classifier import GlyphClassifier
    return GlyphClassifier.load(path)


def process_image(path, clf, correction=None, dot_params=None, dash_params=None,
                  manual=None, auto_deskew=True):
    """Stages 1-4 on `path` -> PointTable. `clf` is a loaded GlyphClassifier."""
    from gridtrack import io, correct
    from gridtrack.types import CorrectionParams
    from glyphtrack import lattice as lt, reader as gr, gridmodel as gm, results as gres
    from glyphtrack import dotfilter as gdf

    dot_params = dot_params or gdf.DotFilterParams()
    dash_params = dash_params or gdf.DashFilterParams()
    manual = manual or {"numbers": [], "letters": []}

    img = io.load_tiff(path)
    c = correction or CorrectionParams()
    if auto_deskew and not c.rotate_deg:                    # Stage 1: correct + deskew
        base = correct.apply(img, replace(c, rotate_deg=0.0))
        c = replace(c, rotate_deg=gr.estimate_deskew(io.to_uint8(base), clf))
    u8 = io.to_uint8(correct.apply(img, c))

    dots = lt.detect_dots(u8)                               # Stage 2: geometry
    if len(dots) < 30:
        return PointTable(path=path, deskew_deg=c.rotate_deg, registered=False)
    basis = lt.refine_basis(dots, lt.estimate_basis(dots))
    dashes = lt.detect_dashes(u8)
    grid = lt.fit_box_grid(basis, dashes)
    crops, gpos = gr.detect_glyph_blobs(u8)
    glyph_h = float(np.median([g.shape[0] for g in crops]) / 1.4) if crops else 30.0
    _c, fit = gr.read_glyphs(u8, clf, grid)
    reads = gr.read_slots(u8, clf, fit)
    model = gm.build_grid_model(reads, fit, dots=dots, manual=manual)   # Stage 3
    result = gres.finalize(model, fit, dots, dashes=dashes)

    drecs, _ = gdf.filter_dots(dots, basis, gpos, glyph_h, dot_params)   # Stage 4
    hrecs, _ = gdf.filter_dashes(dashes, grid, dash_params)

    Minv = np.linalg.inv(np.column_stack([fit["U"], fit["V"]]))
    orient = model["reg"]["orient"] if model.get("registered") else None

    def dfrac(x, y):
        """Box-local fraction in the DESIGN frame (+col, +row) — comparable across
        images regardless of each fit's arbitrary U/V orientation."""
        bc = (np.array([x, y]) - fit["O"]) @ Minv.T
        fx, fy = bc[0] - np.floor(bc[0]), bc[1] - np.floor(bc[1])
        if orient is None:
            return float(fx), float(fy)
        ca, cs, ra, rs = orient
        dfx = fx if ca == 0 else fy
        dfy = fx if ra == 0 else fy
        return float(dfx if cs > 0 else 1 - dfx), float(dfy if rs > 0 else 1 - dfy)

    from . import tags
    per_edge = dash_params.dashes_per_edge
    slots = list(lt.SLOT_FRACS.items())
    pts = []

    # --- kept dots: index off the image's OWN dot lattice, anchored per box ---
    # (the fiducial-fit fraction is too coarse to quantise an 8um lattice across
    #  tilted/shifted images; the detected lattice is sub-pixel exact.)
    kept = []
    for tag, rec in zip(result.dots, drecs):
        if not rec["keep"] or tag.box_number is None:
            continue
        dfx, dfy = dfrac(tag.x, tag.y)
        col, row = tags.box_colrow(int(tag.box_number))
        Di0 = ((col + dfx) * tags.BOX_UM - tags.DOT_PHASE) / tags.DOT_PITCH
        Dj0 = ((row + dfy) * tags.BOX_UM - tags.DOT_PHASE) / tags.DOT_PITCH
        kept.append((int(tag.box_number), float(tag.x), float(tag.y), dfx, dfy, Di0, Dj0,
                     (int(tag.box_i), int(tag.box_j))))
    if kept:
        idx, snap, ok = tags.robust_dot_indices(
            [[d[1], d[2]] for d in kept], [d[0] for d in kept],
            [[d[5], d[6]] for d in kept], basis["v1"], basis["v2"], basis["origin"])
        best = {}                                           # (box,Di,Dj) -> (k, snap)
        for k, ((Di, Dj), sn) in enumerate(zip(idx, snap)):
            key = (kept[k][0], int(Di), int(Dj))
            if key not in best or sn < best[key][1]:
                best[key] = (k, sn)
        winners = {v[0] for v in best.values()}             # one dot per lattice node
        for k, (box, x, y, dfx, dfy, _, _, node) in enumerate(kept):
            Di, Dj = int(idx[k][0]), int(idx[k][1])
            r = PointRecord("dot", box, f"{Di}_{Dj}", "", x, y, dfx, dfy, node=node)
            if k in winners:
                r.tag = tags.dot_tag(box, Di, Dj)           # exact tag (dedup handled)
            pts.append(r)

    for tag, rec in zip(result.dashes, hrecs):              # kept dashes
        if not rec["keep"] or tag.box_number is None:
            continue
        dfx, dfy = dfrac(tag.x, tag.y)
        if min(dfx, 1 - dfx) <= min(dfy, 1 - dfy):
            edge, along = ("L" if dfx < 0.5 else "R"), dfy
        else:
            edge, along = ("B" if dfy < 0.5 else "T"), dfx
        pts.append(PointRecord("dash", int(tag.box_number), f"{edge}{round(along * per_edge)}",
                               "", tag.x, tag.y, dfx, dfy))

    if model.get("registered"):                             # glyphs (numbers/letters)
        node_num = model["node_num"]
        for r in reads:
            N = node_num.get(r["box"])
            if N is None:
                continue
            dfx, dfy = dfrac(r["x"], r["y"])
            slot = min(slots, key=lambda kv: (dfx - kv[1][0]) ** 2 + (dfy - kv[1][1]) ** 2)[0]
            pts.append(PointRecord(r["kind"], int(N), slot, r["char"],
                                   r["x"], r["y"], dfx, dfy))

    table = PointTable(path=path, points=pts, box_pitch=float(grid["box_pitch"]),
                       dot_pitch=float(basis["pitch"]), deskew_deg=float(c.rotate_deg),
                       registered=bool(model.get("registered")))
    tags.assign_tags(table)                                  # dashes/glyphs; dots already exact
    return table
