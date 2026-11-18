"""
rwtag.refwarp.tagframe
======================
Tag ONE frame from its Stage-2 DetectResult and Stage-3 FilterResult against the
loaded design. Ported from reference-warp-tagger/rwtag/refwarp/tagframe.py.

  1. warp control points: every design dot; detections: the KEPT dots, each with
     its own box pitch as the ICP / match gate;
  2. ICP homography -> thin-plate spline (warp.fit_warp), seeded by the tag affine;
  3. tagmatch: dots and dashes by nearest warped reference of the same category
     (dots must agree with their Stage-2 box), ArUco by id;
  4. the similarity design -> image through every tagged feature: the
     uniform-expansion model whose residual is the distortion signal.
"""
from __future__ import annotations
import numpy as np

from . import warp as W, tagmatch
from .types import TagResult

IDENTITY_REG = {"orient": (0, 1, 1, 1), "offset": (0, 0)}


def ref_dots_um(records):
    return np.array([[r["x_um"], r["y_um"]] for r in records if r["category"] == "dot"])


def _dot_pitch_px(det, box):
    scale = float(det.model.get("scale_px_per_um", 1.0))
    out = np.empty(len(box))
    for k, N in enumerate(box):
        r = det.per_box.get(int(N)) if det.per_box else None
        if r is not None and np.isfinite(r.get("pitch_px", np.nan)):
            out[k] = r["pitch_px"]
        elif r is not None:
            out[k] = r["pitch_um"] * scale
        else:
            out[k] = float(det.basis["pitch"])
    return out


def _dash_clear_um(design):
    """Smallest designed clearance between a dot centre and a dash line (um).
    Spectrum boxes carry it; designs 1-3 use the Rev D rule (pitch / 2 + dash
    width / 2, about 5 um)."""
    v = [b.dash_clear_um for b in design.boxes if b.dash_clear_um > 0]
    return float(min(v)) if v else float(min(b.pitch_um for b in design.boxes) / 2 + 2.125 / 2)


def tag_frame(det, filt, design, tps=True) -> TagResult | None:
    """Returns a TagResult, or None when the frame is unregistered or the warp
    cannot be fitted (too few dots)."""
    if det is None or det.fit is None or not (det.model and det.model.get("registered")):
        return None
    n = len(det.dots)
    if filt is not None and filt.kept_dot_index is not None:
        ki = np.asarray(filt.kept_dot_index, int)
        hi = np.asarray(filt.kept_dash_index, int)
    else:
        ki = np.nonzero(det.dot_flag != "edge")[0] if det.dot_flag is not None else np.arange(n)
        hi = np.arange(len(det.dashes_all))
    dots = np.asarray(det.dots, float).reshape(-1, 2)[ki]
    box = np.asarray(det.dot_box, int)[ki] if det.dot_box is not None else np.zeros(len(ki), int)
    pitch = _dot_pitch_px(det, box)
    dashes = np.asarray(det.dashes_all, float).reshape(-1, 2)[hi] if len(hi) else np.zeros((0, 2))
    records = design.records
    model = W.fit_warp(ref_dots_um(records), dots, det.fit, IDENTITY_REG, pitch, tps=tps)
    if model.get("H") is None:
        return None
    d = {"dots": dots, "dot_pitch_px": pitch, "dot_box": box, "dashes": dashes,
         "pitch": float(np.median(pitch)) if len(pitch) else float(det.basis["pitch"]),
         "aruco": det.model.get("aruco_xy"),
         "dash_gate_px": 0.4 * _dash_clear_um(design) * float(det.model.get("scale_px_per_um", 1.0))}
    res = tagmatch.tag_image(d, model, records)
    src, residuals = {}, {}
    pos_um = {r["tag"]: (r["x_um"], r["y_um"]) for r in records}
    for j, (tag, r) in res["dash"].items():
        src[tag] = ("dash", int(hi[j])); residuals[tag] = r
    for aid, (tag, _r) in res["aruco"].items():
        src[tag] = ("aruco", int(aid))
        residuals[tag] = float(np.hypot(*(np.asarray(res["tag_xy"][tag]) - W.warp_points([pos_um[tag]], model)[0])))
    # dots: cross-validated residual (the in-sample TPS residual is ~0 for its control points)
    dot_items = list(res["dot"].items())
    if dot_items:
        su = np.array([pos_um[tag] for _i, (tag, _r) in dot_items])
        dp = np.array([dots[i] for i, _t in dot_items])
        cv = W.cv_residuals(su, dp, model=model)
        for (i, (tag, r)), v in zip(dot_items, cv):
            src[tag] = ("dot", int(ki[i]))
            residuals[tag] = float(np.hypot(*v)) if np.isfinite(v).all() else r
    per = {}
    for cat in ("dot", "dash", "aruco"):
        rr = [residuals[tag] for tag, s in src.items() if s[0] == cat]
        per[cat] = {"n": len(rr), "res_median": float(np.median(rr)) if rr else float("nan")}
    model["cv_median"] = per["dot"]["res_median"]
    per_box = {}
    for i, (tag, _r) in res["dot"].items():
        N = int(box[i]); per_box.setdefault(N, []).append(residuals[tag])
    per_box = {N: {"n_tagged": len(v), "res_median": float(np.median(v))} for N, v in sorted(per_box.items())}
    # uniform-expansion model through every tagged feature (design um -> corrected px)
    pos = {r["tag"]: (r["x_um"], r["y_um"]) for r in records}
    tags = res["tag_xy"]
    X = np.array([pos[t] for t in tags]); Y = np.array([tags[t] for t in tags])
    sim = W.similarity(X, Y) if len(X) >= 3 else {}
    if sim:
        sim = {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in sim.items()}
    unmatched = {"dot": [int(ki[i]) for i in range(len(ki)) if i not in res["dot"] and i not in res["box_mismatch"]],
                 "dash": [int(hi[j]) for j in range(len(hi)) if j not in res["dash"]],
                 "box_mismatch": [int(ki[i]) for i in res["box_mismatch"]]}
    cov = {}
    for tag, (kind, j) in src.items():
        c = None
        if kind == "dot" and det.dot_cov_corr is not None:
            c = det.dot_cov_corr[j]
        elif kind == "dash" and det.dash_cov_corr is not None:
            c = det.dash_cov_corr[j]
        elif kind == "aruco" and det.tag_cov.get(j):
            c = det.tag_cov[j]["centre_corr"]
        if c is not None and np.isfinite(c).all():
            cov[tag] = (float(c[0, 0]), float(c[1, 1]), float(c[0, 1]))
    return TagResult(tags=tags, warp=model, residuals=residuals, source="direct", cov=cov,
                     confidence=(f"cross-validated resid {per['dot']['res_median']:.2f} px · matched {model['matched_frac']:.0%}"),
                     per_category=per, src=src, per_box=per_box, similarity=sim, unmatched=unmatched,
                     design_sha=dict(det.design_sha))


def warped_grid_segments(model, design, pts=120, through=W.warp_points):
    """The node-lattice lines (grid_n + 1 each way) pushed through the warp ->
    list of (pts, 2) px polylines: the definitive 'grid following the dashes'."""
    o, b, n = design.origin_um, design.box_um, design.grid_n
    t = np.linspace(o, o + n * b, pts)
    out = []
    for c in range(n + 1):
        for line in (np.column_stack([np.full_like(t, o + c * b), t]), np.column_stack([t, np.full_like(t, o + c * b)])):
            out.append(np.asarray(through(line, model)))
    return out


def expected_grid_segments(similarity, design, pts=2):
    """The same lattice under the uniform-expansion (similarity) model."""
    return warped_grid_segments(similarity, design, pts=pts, through=W.similarity_points)


def warped_box_centers(model, design, tags=None):
    """{N: (x, y)} box centres through the warp; restricted to boxes with tagged
    dots when `tags` is given."""
    boxes = [b for b in design.boxes]
    if tags:
        seen = {int(t.split("|")[1][1:]) for t in tags if t.startswith("dot|")}
        boxes = [b for b in boxes if b.N in seen]
    if not boxes:
        return {}
    c = W.warp_points(np.array([[b.x0_um + b.side_um / 2, b.y0_um + b.side_um / 2] for b in boxes]), model)
    return {b.N: (float(x), float(y)) for b, (x, y) in zip(boxes, c)}
