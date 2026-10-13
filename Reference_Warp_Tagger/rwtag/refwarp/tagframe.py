"""
rwtag.refwarp.tagframe
======================
Tag ONE frame from the app's Stage 1-3 state: build the dict view the ported
refwarp modules expect, fit the design->image warp against the FILTERED dots
(user requirement: tagging runs on the processed image and filtered points),
push the reference tags through it, and assign per-category nearest tags.
"""
from __future__ import annotations
import numpy as np

from . import warp as W, tagmatch, reftags
from .types import TagResult

_REF_CACHE = {}


def load_records(path=None):
    """Reference tag records (cached)."""
    key = path or "default"
    if key not in _REF_CACHE:
        data = reftags.load(path) if path else reftags.load()
        _REF_CACHE[key] = data["records"]
    return _REF_CACHE[key]


def ref_dots_um(records):
    """Interior-dot design positions (the warp control points)."""
    return np.array([[r["x_um"], r["y_um"]] for r in records if r["category"] == "dot"])


def detection_view(det, kept_dots=None, kept_dashes=None):
    """Dict view of a DetectResult (+ Stage-3 kept points) in the shape the ported
    refwarp modules (tagmatch/coreg) consume. Filtered points take the place of the
    raw detections when provided (I1)."""
    return {
        "u8": det.u8,
        "dots": np.asarray(kept_dots if kept_dots is not None else det.dots, float),
        "dashes": np.asarray(kept_dashes if kept_dashes is not None else det.dashes_all, float),
        "glyphs": np.asarray(det.glyphs, float),
        "basis": det.basis, "fit": det.fit, "model": det.model, "reads": det.reads,
        # V2: decoded ArUco centres by id (None on the V1 glyph path)
        "aruco": (det.model or {}).get("aruco_xy"),
    }


def tag_frame(det, filt=None, records=None, tps=True) -> TagResult | None:
    """Fit the warp + tag one frame. `det` = Stage-2 DetectResult (must be solved /
    registered), `filt` = Stage-3 FilterResult (optional -> falls back to raw).
    Returns a TagResult, or None with no possible fit (unregistered / too few dots)."""
    records = records if records is not None else load_records()
    if det is None or det.fit is None or not (det.model and det.model.get("registered")):
        return None
    kept_dots = filt.kept_dots if filt is not None else None
    kept_dashes = filt.kept_dashes if filt is not None else None
    d = detection_view(det, kept_dots, kept_dashes)
    pitch = float(det.basis["pitch"])
    model = W.fit_warp(ref_dots_um(records), d["dots"], det.fit, det.model["reg"],
                       pitch, tps=tps)
    if model.get("H") is None:
        return None
    res = tagmatch.tag_image(d, model, records)
    per, residuals = {}, {}
    for cat in ("dot", "dash", "glyph", "aruco"):
        rr = [v[1] for v in res.get(cat, {}).values()]
        per[cat] = {"n": len(rr), "res_median": float(np.median(rr)) if rr else float("nan")}
        for tag, r in res[cat].values():
            residuals[tag] = float(r)
    return TagResult(tags=res["tag_xy"], warp=model, residuals=residuals, source="direct",
                     confidence=(f"median resid {model['per_det_median']:.1f}px · "
                                 f"matched {model['matched_frac']:.0%}"),
                     per_category=per)


def warped_grid_segments(model, box_um=150.0, n_lines=6, span=(0.0, 750.0), pts=120,
                         origin=0.0):
    """The 6+6 reference grid lines pushed through the warp -> list of (N,2) px
    polylines. This is the definitive 'grid following the dashes' overlay (I2).
    `origin`: design coordinate of grid line 0 (V2 insets the lattice by tag/2)."""
    t = np.linspace(span[0], span[1], pts)
    out = []
    for c in range(n_lines):
        for line in (np.column_stack([np.full_like(t, origin + c * box_um), t]),
                     np.column_stack([t, np.full_like(t, origin + c * box_um)])):
            out.append(np.asarray(W.warp_points(line, model)))
    return out


def warped_box_centers(model, tags=None, box_um=150.0, grid_n=5, origin=0.0):
    """{N: (x_px, y_px)} for the 25 box centres pushed through the warp. If `tags`
    given, restrict to boxes that actually have tagged dots on this frame."""
    boxes = range(1, grid_n * grid_n + 1)
    if tags:
        seen = {int(t.split("|")[1][1:]) for t in tags if t.startswith("dot|")}
        boxes = sorted(seen)
    out = {}
    for N in boxes:
        col, row = (N - 1) // grid_n, (N - 1) % grid_n
        c = W.warp_points(np.array([[origin + (col + 0.5) * box_um,
                                     origin + (row + 0.5) * box_um]]), model)[0]
        out[N] = (float(c[0]), float(c[1]))
    return out
