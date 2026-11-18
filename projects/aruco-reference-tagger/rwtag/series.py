"""
rwtag.series
============
Acceptance of tagged frames across a series. Ported from
reference-warp-tagger/rwtag/aruco/series.py (the V2 driver); the V1 glyph driver
with its coreg rescue is gone because every frame registers on its own from ids.

Gates, applied in ascending expansion order:
  HANDEDNESS  the design -> image sign must equal the baseline's (-1 for the y-up
              design); a mirrored frame is rejected;
  RESIDUAL    the median CROSS-VALIDATED dot residual < max_resid x max(1, lambda/2)
              (the in-sample TPS residual is ~0 whenever every dot is a control
              point, so it cannot reject anything);
  SHARE       a later frame must share >= min_share tags with the frames already
              accepted, OR >= 2 ArUco ids (at lambda 6 only ~4 tags are in view);
              with ids this only fails on a nearly empty or wrong-design frame.
The lowest accepted frame is the baseline. A rejected frame keeps its results
for inspection but is marked `accepted = False` with the reason, and nothing
downstream (pairing, export) uses it.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np

from .dotfilter import filter_frame
from .refwarp import tagframe as TF

MAX_RESID = 10.0
MIN_SHARE = 40


def validate(tr, det, label, accepted, max_resid=MAX_RESID, min_share=MIN_SHARE):
    """(ok, reason, share). `accepted` = TagResults already accepted (any order);
    the lowest-label one sets the handedness."""
    if det is None or not (det.model and det.model.get("registered")):
        return False, (det.model or {}).get("reason", "not registered") if det else "no detection", 0
    if tr is None or tr.warp.get("H") is None:
        return False, "warp fit failed (too few dots?)", 0
    sign = float(det.model["sign"])
    acc = [a for a in accepted if a is not None and a.accepted]
    if acc:
        base = min(acc, key=lambda a: a.label if a.label is not None else 0.0)
        ref_sign = float(base.similarity.get("sign", -1.0)) if base.similarity else -1.0
    else:
        ref_sign = None
    if ref_sign is not None and sign != ref_sign:
        return False, (f"handedness {sign:+.0f} differs from the baseline {ref_sign:+.0f} — "
                       "the frame is mirrored, or a y-flip is missing"), 0
    if ref_sign is None and sign > 0:
        return False, "handedness +1 on the baseline: the image is mirrored (design y-up must map to -1)", 0
    lam = float(label) if label else 1.0
    gate = max_resid * max(1.0, lam / 2.0)
    resid = tr.warp.get("cv_median", tr.warp["per_det_median"])
    if not np.isfinite(resid):
        resid = tr.warp["per_det_median"]
    if resid > gate:
        return False, f"warp residual {resid:.1f} px > {gate:.1f}", 0
    if not acc:
        return True, "baseline", None
    union = set().union(*[set(a.tags) for a in acc])
    shared = set(tr.tags) & union
    share = len(shared)
    n_ids = sum(1 for t in shared if t.startswith("aruco|"))
    if share < min_share and n_ids < 2:
        return False, f"only {share} tags ({n_ids} ArUco) shared with accepted frames", share
    return True, f"{share} shared tags ({n_ids} ArUco)", share


@dataclass
class SeriesFrame:
    label: float
    det: object = None
    filt: object = None
    tagging: object = None
    ok: bool = False
    reason: str = ""


def process_frames(frames, design, params=None, dot_params=None, dash_params=None,
                   max_resid=MAX_RESID, min_share=MIN_SHARE, tps=True, progress=None, noise_model=None):
    """Headless series on in-memory frames: `frames` = [(label, corr_img, raw_img
    or None, CorrectionParams or None)]. Returns [SeriesFrame] ascending by label."""
    from .aruco import detect as AD
    out = []
    accepted = []
    for k, (label, corr, raw, corrp) in enumerate(sorted(frames, key=lambda f: f[0])):
        f = SeriesFrame(label=float(label))
        f.det = AD.detect(corr, design, params, raw_img=raw, correction=corrp, noise_model=noise_model)
        if f.det.model.get("registered"):
            f.filt = filter_frame(f.det, dot_params, dash_params, design)
            f.tagging = TF.tag_frame(f.det, f.filt, design, tps=tps)
        ok, reason, _share = validate(f.tagging, f.det, f.label, accepted, max_resid, min_share)
        if f.tagging is not None:
            f.tagging.label = f.label
            f.tagging.accepted, f.tagging.reason = ok, ("" if ok else reason)
            f.tagging.source = "baseline" if ok and not accepted else "direct"
        f.ok, f.reason = ok, reason
        if ok:
            accepted.append(f.tagging)
        out.append(f)
        if progress:
            progress(k + 1, len(frames), f)
    return out


def pair_table(frames):
    """{tag: {label: (x, y)}} over accepted frames."""
    table = {}
    for f in frames:
        tr = getattr(f, "tagging", None)
        if tr is not None and tr.accepted:
            for tag, xy in tr.tags.items():
                table.setdefault(tag, {})[f.label] = xy
    return table
