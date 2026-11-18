"""
rwtag.aruco.series
==================
Series driver for the V2 (ArUco) print. Same contract as refwarp.series --
frames in ascending expansion order, a baseline, per-frame validation, loud
rejection -- but every frame registers on its own from decoded ids, so there is
no coreg rescue and no shared-tag voting between candidates. What is kept:

  * HANDEDNESS: the baseline's affine sign is the series' sign; a frame whose
    fit has the other sign is rejected (design y-up vs image y-down, see detect.py);
  * RESIDUAL: the warp's per-detection median must clear `max_resid`;
  * SHARE: a later frame must share >= `min_share` tags with the accepted frames
    (with ids this only fails when a frame is nearly empty or a tag misdecoded).

`process_frames` works on in-memory images (tests, simulator); `process_series`
loads a folder with the same sidecar Stage-1 handling as the V1 driver.
"""
from __future__ import annotations
import numpy as np

from rwtag import io, correct as C
from rwtag.glyph import dotfilter as gdf
from rwtag.glyph.types import FilterResult
from rwtag.refwarp import tagframe as TF, series as S1
from .detect import ArucoParams, Design, detect

SeriesFrame = S1.SeriesFrame


def default_dot_params():
    # No glyphs on V2 (tags are masked in detect); the off-lattice gate is OFF
    # because V2 boxes are not a whole number of dot pitches, so the lattice
    # phase steps by (box mod pitch) from box to box -- a global lattice test would
    # cull good dots in the far boxes. The tagmatch gate (0.45 pitch) does that job.
    return gdf.DotFilterParams(glyph_enable=False, dev_enable=False)


def default_dash_params():
    return gdf.DashFilterParams(dashes_per_edge=10)


def filter_frame(det, dot_params=None, dash_params=None):
    dot_params = dot_params or default_dot_params()
    dash_params = dash_params or default_dash_params()
    drecs, dcounts = gdf.filter_dots(det.dots, det.basis, None, 0.0, dot_params)
    if det.grid is not None and len(det.dashes_all):
        hrecs, hcounts = gdf.filter_dashes(det.dashes_all, det.grid, dash_params)
    else:
        hrecs, hcounts = [], {"kept": 0, "off_grid": 0, "intersection": 0, "too_close": 0}
    kept_dots = np.array([[r["x"], r["y"]] for r in drecs if r["keep"]], float).reshape(-1, 2)
    kept_dashes = np.array([[r["x"], r["y"]] for r in hrecs if r["keep"]], float).reshape(-1, 2)
    return FilterResult(dot_recs=drecs, dash_recs=hrecs, dot_counts=dcounts, dash_counts=hcounts,
                        kept_dots=kept_dots, kept_dashes=kept_dashes,
                        dot_params=dot_params.__dict__, dash_params=dash_params.__dict__)


def prepare_frame(path, params: ArucoParams):
    """Load raw -> sidecar Stage-1 params (or defaults) -> corrected u8."""
    raw = io.load_tiff(path)
    side = io.sidecar_path(path)
    if __import__("os").path.exists(side):
        _, corr, lv, _flags = io.load_session(side)
    else:
        from rwtag.types import CorrectionParams, LevelsParams
        corr, lv = CorrectionParams(), LevelsParams()
    return io.to_uint8(C.process(raw, corr, lv))


def process_frames(frames, design: Design, params: ArucoParams = None, dot_params=None,
                   dash_params=None, max_resid=10.0, min_share=40, tps=True, progress=None):
    """`frames` = [(label, u8_or_float_image)] in any order. Returns list[SeriesFrame]
    ascending by label; check .ok / .reason. Each ok frame carries .det, .filt, .tags,
    .warp, .n_tags, .source ('baseline' | 'direct')."""
    params = params or ArucoParams()
    out = [SeriesFrame(path=str(lab), label=float(lab)) for lab, _ in sorted(frames, key=lambda t: t[0])]
    imgs = [img for _, img in sorted(frames, key=lambda t: t[0])]
    good, ref_sign = [], None
    for k, (f, img) in enumerate(zip(out, imgs)):
        try:
            f.det = detect(img, design, params)
        except Exception as e:                      # noqa: BLE001
            f.reason = f"detect failed: {e}"
            if progress: progress(k + 1, len(out), f)
            continue
        m = f.det.model
        if not m.get("registered"):
            f.reason = m.get("reason", "not registered")
            if progress: progress(k + 1, len(out), f)
            continue
        f.filt = filter_frame(f.det, dot_params, dash_params)
        tr = TF.tag_frame(f.det, f.filt, design.records, tps=tps)
        if tr is None or tr.warp.get("H") is None:
            f.reason = "warp fit failed (too few dots?)"
            if progress: progress(k + 1, len(out), f)
            continue
        sign = float(m["sign"])
        if ref_sign is None:
            ref_sign = sign
        if sign != ref_sign:
            f.reason = (f"handedness {sign:+.0f} differs from the baseline {ref_sign:+.0f} "
                        "— a y-flip is missing or present on one frame")
        elif tr.warp["per_det_median"] > max_resid:
            f.reason = f"warp residual {tr.warp['per_det_median']:.1f} px > {max_resid}"
        else:
            share = (len(set(tr.tags) & set().union(*[set(g.tags) for g in good]))
                     if good else None)
            if good and share < min_share:
                f.reason = f"only {share} tags shared with accepted frames (< {min_share})"
            else:
                f.tags, f.warp, f.ok = tr.tags, tr.warp, True
                f.source = "baseline" if not good else "direct"
                f.n_tags = len(tr.tags)
                f.d = TF.detection_view(f.det, f.filt.kept_dots, f.filt.kept_dashes)
                f.confidence = (f"{m['affine_info']['n_matched']} ArUco · "
                                f"resid {tr.warp['per_det_median']:.2f} px · "
                                f"matched {tr.warp['matched_frac']:.0%}"
                                + (f" · {share} shared" if share is not None else ""))
                good.append(f)
        if progress: progress(k + 1, len(out), f)
    return out


def process_series(frames, design: Design, params: ArucoParams = None, **kw):
    """`frames` = [(path, label)] as refwarp.series.find_series returns."""
    params = params or ArucoParams()
    loaded = [(lab, prepare_frame(p, params)) for p, lab in frames]
    out = process_frames(loaded, design, params, **kw)
    for f, (p, _lab) in zip(out, sorted(frames, key=lambda t: t[1])):
        f.path = p
    return out


pair_table = S1.pair_table
