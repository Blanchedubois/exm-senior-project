"""
rwtag.refwarp.series
====================
Sidecar-driven batch over a folder of expansion frames (the series half of Stage
4). Adapted from the old validated `refwarp.session`:

  * frames process in ASCENDING expansion order;
  * the lowest frame with a valid warp is the BASELINE — it sets the handedness
    sign every later frame must match;
  * each later frame offers candidates: its own (digit-read) registration, plus a
    coreg auto-alignment to every lower accepted frame (the high-expansion rescue:
    FOV-constrained design overlap + handedness + residual);
  * the candidate sharing the most tags with the accepted frames wins; accept only
    if it clears `min_share` — otherwise the frame is REJECTED LOUDLY with the
    reason (decision: no best-guess numbering ever enters pairing/strain).

Differences from the old session: Stage-1 params come from each frame's sidecar
session (`<image>.rwsession.json`); detection is our staged rwtag.glyph pipeline;
tagging runs on the Stage-3 FILTERED points (I1).
"""
from __future__ import annotations
from dataclasses import dataclass, field, replace
import os
import re
import numpy as np

from rwtag import io, correct as C
from rwtag.glyph import detect as D, dotfilter as gdf, lattice as lt, reader as gr
from rwtag.glyph.types import DetectResult
from . import warp as W, coreg, tagmatch
from .types import TagResult
from . import tagframe as TF

IMG_EXTS = (".tif", ".tiff", ".png", ".jpg", ".jpeg")


def parse_label(filename):
    """'1.5XMISTstitched...' -> 1.5 (I3). None if no leading <float>X pattern."""
    m = re.match(r"^([0-9]+(?:\.[0-9]+)?)[xX]", os.path.basename(filename))
    return float(m.group(1)) if m else None


def find_series(folder):
    """[(path, label)] for every image in `folder` with a parsable label, ascending."""
    out = []
    for f in sorted(os.listdir(folder)):
        if f.lower().endswith(IMG_EXTS) and not f.startswith("."):
            lab = parse_label(f)
            if lab is not None:
                out.append((os.path.join(folder, f), lab))
    return sorted(out, key=lambda t: t[1])


@dataclass
class SeriesFrame:
    path: str
    label: float
    d: dict = None                    # detection dict view (tagmatch/coreg shape)
    det: DetectResult = None
    tags: dict = None                 # {tag: (x_px, y_px)}
    warp: dict = None
    source: str = ""
    ok: bool = False
    confidence: str = ""
    reason: str = ""                  # rejection reason (when not ok)
    n_tags: int = 0


def _prepare_frame(path, clf, dot_params, dash_params):
    """Load raw -> sidecar Stage-1 params -> corrected u8 -> detect -> filter.
    Returns (det, dict_view) with the dict view carrying the FILTERED points."""
    raw = io.load_tiff(path)
    side = io.sidecar_path(path)
    if os.path.exists(side):
        _, corr, lv, _flags = io.load_session(side)
    else:
        from rwtag.types import CorrectionParams, LevelsParams
        corr, lv = CorrectionParams(), LevelsParams()
    if not corr.rotate_deg:                       # no tuned rotation -> auto-deskew
        base = C.apply(raw, replace(corr, rotate_deg=0.0))
        corr.rotate_deg = float(gr.estimate_deskew(io.to_uint8(base), clf))
    u8 = io.to_uint8(C.process(raw, corr, lv))
    det = D.detect(u8, clf)
    # Stage-3 filtering (calibrated defaults unless overridden)
    drecs, _ = gdf.filter_dots(det.dots, det.basis, det.glyphs, det.glyph_h, dot_params)
    dash_grid = lt.grid_from_fit(det.fit) if det.fit is not None else det.grid
    hrecs, _ = gdf.filter_dashes(det.dashes_all, dash_grid, dash_params)
    kept_dots = np.array([[r["x"], r["y"]] for r in drecs if r["keep"]], float)
    kept_dashes = np.array([[r["x"], r["y"]] for r in hrecs if r["keep"]], float)
    return det, TF.detection_view(det, kept_dots, kept_dashes)


def process_series(frames, clf, records=None, dot_params=None, dash_params=None,
                   max_resid=10.0, min_share=40, support_min=25, progress=None):
    """Run the whole series. `frames` = [(path, label)] ascending (see find_series).
    Returns list[SeriesFrame] (all frames; check .ok / .reason)."""
    records = records if records is not None else TF.load_records()
    dot_params = dot_params or gdf.DotFilterParams()
    dash_params = dash_params or gdf.DashFilterParams()
    refdot = TF.ref_dots_um(records)
    out = [SeriesFrame(path=p, label=l) for p, l in sorted(frames, key=lambda t: t[1])]
    good, ref_sign = [], None

    def _tags(d, m):
        return tagmatch.tag_image(d, m, records)["tag_xy"]

    for k, f in enumerate(out):
        try:
            f.det, f.d = _prepare_frame(f.path, clf, dot_params, dash_params)
        except Exception as e:
            f.reason = f"prepare failed: {e}"
            if progress: progress(k + 1, len(out), f)
            continue
        registered = bool(f.det.model and f.det.model.get("registered"))
        pitch = float(f.det.basis["pitch"])
        md = (W.fit_warp(refdot, f.d["dots"], f.det.fit, f.det.model["reg"], pitch)
              if registered else {"H": None})

        if not good:                              # ---- baseline (lowest expansion)
            if md.get("H") is None:
                f.reason = ("baseline frame failed to register/warp — "
                            "tune Stages 1–3 on it (or add a manual anchor)")
            else:
                ref_sign = coreg.homography_sign(md["H"])
                f.tags, f.warp, f.source, f.ok = _tags(f.d, md), md, "baseline", True
                f.confidence = "baseline"
                f.n_tags = len(f.tags)
                good.append(f)
            if progress: progress(k + 1, len(out), f)
            continue

        def _valid(m):
            return (m.get("H") is not None and m.get("per_det_median", 9e9) < max_resid
                    and coreg.homography_sign(m["H"]) == ref_sign)

        lower_tags = set().union(*[set(g.tags) for g in good])
        cands = []
        if _valid(md):
            cands.append((_tags(f.d, md), md, "direct"))
        if registered:                            # coreg needs SOME registration to remap
            for g in good:
                _, m2 = coreg.auto_register(f.d, g.d, refdot, ref_sign, pitch)
                if m2 is not None and _valid(m2):
                    cands.append((_tags(f.d, m2), m2, f"auto<-{g.label:g}x"))
        if not cands:
            f.reason = ("no valid candidate (bad residual / handedness / unregistered) — "
                        "add a manual box anchor in Stage 2 and re-run")
        else:
            tags, m, src = max(cands, key=lambda c: len(set(c[0]) & lower_tags))
            share = len(set(tags) & lower_tags)
            n_support = sum(1 for g in good if len(set(tags) & set(g.tags)) >= support_min)
            if share >= min_share:
                f.tags, f.warp, f.source, f.ok = tags, m, src, True
                f.confidence = f"supported by {n_support} frame(s) · {share} shared tags"
                f.n_tags = len(tags)
                good.append(f)
            else:
                f.reason = (f"only {share} shared tags with accepted frames "
                            f"(< {min_share}) — likely wrong box offset; "
                            "add a manual anchor in Stage 2")
        if progress: progress(k + 1, len(out), f)
    return out


def pair_table(frames):
    """Wide pairing over accepted frames: {tag: {label: (x_px, y_px)}}."""
    table = {}
    for f in frames:
        if getattr(f, "ok", False) and f.tags:
            for tag, xy in f.tags.items():
                table.setdefault(tag, {})[f.label] = xy
    return table
