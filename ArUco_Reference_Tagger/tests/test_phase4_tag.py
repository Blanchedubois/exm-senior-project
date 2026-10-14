"""
Phase 4 tests (docs/04_PHASE4_FILTER_AND_TAG.md §6): per-box filtering, tag
identity against truth, the series gates, the uniform-expansion fit, the
cross-validated residual, and the project runner. Frames go through a real
Stage-1 correction (lens + vignette + a 6 deg deskew) first.
"""
from __future__ import annotations
import os
import shutil
import sys
import tempfile
import numpy as np
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _dummy as DM                                                            # noqa: E402
from rwtag import correct as C, designs as DS, series as SR, project as PJ     # noqa: E402
from rwtag import dotfilter as DF                                              # noqa: E402
from rwtag.aruco import ArucoParams                                            # noqa: E402
from rwtag.aruco import detect as AD                                           # noqa: E402
from rwtag.refwarp import warp as W, tagframe as TF, tagmatch                  # noqa: E402

ROT = 6.0


def _series(design_key, run, rotate=ROT):
    d, truth = DM.run(design_key, run)
    if d is None:
        return None, None, None
    des = DS.load(os.path.join(DM.DESIGNS, DM.DESIGN_DIR[design_key]))
    frames = []
    for fr in truth["frames"]:
        p = DM.stage1(truth, rotate); raw = DM.load(d, fr)
        frames.append((fr["label"], DM.corrected(raw, p), raw, p))
    out = SR.process_frames(frames, des, ArucoParams(psf_fwhm_um=truth["camera"]["psf_fwhm_um"]))
    return (d, truth, des), out, frames


def _identity(d, fr, tr, p, shape, category="dot"):
    """(n_truth_in, n_correct, n_wrong) for one category. Correct = tagged within
    1 px of that tag's truth position; wrong = tagged farther (a neighbour's
    identity). Truth 'in' = raw source at least 3 spot widths inside the frame."""
    tags, traw, _box = DM.truth_features(d, fr, category)
    tc = C.forward_geometric(traw, p, shape)
    truth_xy = dict(zip(tags, tc))
    use = set(np.asarray(tags)[DM.detectable(traw, shape, 18.0)])
    got = {t: xy for t, xy in tr.tags.items() if t.startswith(category + "|")}
    err = {t: float(np.hypot(*(np.asarray(xy) - truth_xy[t]))) for t, xy in got.items()}
    correct = sum(1 for t in use if t in err and err[t] < 1.0)
    wrong = sum(1 for e in err.values() if e >= 1.0)
    return len(use), correct, wrong


# ------------------------------------------------------------------ unit
def test_coarse_map_reproduces_affine():
    A = np.array([[1.7, 0.2, 310.0], [0.1, -1.8, 900.0]])
    box = 145.4
    fit = {"O": A[:, 2], "U": A[:, :2] @ [box, 0], "V": A[:, :2] @ [0, box], "box_um": box}
    um = np.array([[0.0, 0.0], [750.0, 0.0], [12.3, 456.7], [700.0, 700.0]])
    got = W.coarse_map(um, fit, TF.IDENTITY_REG)
    assert np.allclose(got, um @ A[:, :2].T + A[:, 2])


def test_similarity_recovers_reflection():
    rng = np.random.default_rng(0)
    X = rng.uniform(0, 750, (200, 2))
    th = np.radians(7.0); R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]]) @ np.diag([1, -1])
    Y = 2.5 * X @ R.T + [100, 2000] + rng.normal(0, 0.2, X.shape)
    s = W.similarity(X, Y)
    assert abs(s["s"] - 2.5) < 1e-3 and s["sign"] == -1.0 and s["rms"] < 0.4
    assert np.allclose(W.similarity_points(X, s), Y, atol=1.0)


def test_cv_residual_is_not_zero_with_few_points():
    """A TPS through every control point has residual 0; the cross-validated one
    reports the noise."""
    rng = np.random.default_rng(1)
    X = rng.uniform(0, 750, (300, 2)); Y = 2.0 * X + rng.normal(0, 0.3, X.shape)
    cv = W.cv_residuals(X, Y)
    r = np.hypot(*cv.T)
    assert 0.2 < np.median(r) < 0.8, np.median(r)


def test_tagmatch_aruco_by_id_and_box_check():
    recs = [dict(tag="aruco|N0_0|10", category="aruco", x_um=11.5, y_um=11.5, meta={"aruco_id": 10}),
            dict(tag="dot|B1|0_0", category="dot", x_um=30.0, y_um=30.0, meta={"box": 1}),
            dict(tag="dot|B2|0_0", category="dot", x_um=30.0, y_um=180.0, meta={"box": 2})]
    H = np.array([[2.0, 0, 5.0], [0, -2.0, 400.0], [0, 0, 1.0]])
    d = {"dots": np.array([[65.0, 340.0], [65.0, 40.0]]), "dot_pitch_px": np.array([10.0, 10.0]),
         "dot_box": np.array([1, 1]), "dashes": np.zeros((0, 2)), "pitch": 10.0,
         "aruco": {10: (11.0, 22.0), 99: (1.0, 1.0)}}
    res = tagmatch.tag_image(d, {"H": H, "tps": None}, recs)
    assert res["tag_xy"]["aruco|N0_0|10"] == (11.0, 22.0) and not any(t.endswith("|99") for t in res["tag_xy"])
    assert "dot|B1|0_0" in res["tag_xy"] and "dot|B2|0_0" not in res["tag_xy"]
    assert res["box_mismatch"] == [1]                     # the second dot sits on box 2's dot but was found in box 1


# ------------------------------------------------------------------ filter
def test_filter_per_box_lattice_spectrum():
    """On the spectrum print no dot in a resolvable box is dropped as off-lattice
    (each box is tested against ITS lattice), and injected strays are."""
    d, truth = DM.run("spectrum", "spectrum_clean")
    if d is None:
        return
    fr = DM.frame(truth, 1.0); p = DM.stage1(truth, ROT); raw = DM.load(d, fr)
    des = DS.load(os.path.join(DM.DESIGNS, "4_spectrum"))
    det = AD.detect(DM.corrected(raw, p), des, ArucoParams(psf_fwhm_um=2.0), raw_img=raw, correction=p)
    fr0 = DF.filter_frame(det, design=des)
    assert fr0.dot_counts["off_lattice"] <= 0.002 * len(det.dots), fr0.dot_counts
    # inject 40 strays half-way between lattice nodes of box 13
    b = det.basis_by_box[13]
    nodes = b["origin"] + np.arange(3, 13)[:, None] * b["v1"] + 5 * b["v2"]
    strays = nodes + 0.5 * (b["v1"] + b["v2"])
    det.dots = np.vstack([det.dots, strays]); det.dot_box = np.concatenate([det.dot_box, np.full(len(strays), 13)])
    det.dot_flag = np.concatenate([det.dot_flag, np.array([""] * len(strays), dtype=object)])
    fr1 = DF.filter_frame(det, design=des)
    reasons = [r["reason"] for r in fr1.dot_recs[-len(strays):]]
    assert all(r in ("off_lattice", "too_close") for r in reasons), reasons
    print(f"  info  spectrum filter: {fr0.dot_counts} · injected strays -> {set(reasons)}")


def test_filter_tag_quiet_zone():
    d, truth = DM.run("optimistic", "opt_clean")
    if d is None:
        return
    fr = DM.frame(truth, 1.0); p = DM.stage1(truth, 0.0); raw = DM.load(d, fr)
    des = DS.load(os.path.join(DM.DESIGNS, "1_optimistic"))
    det = AD.detect(DM.corrected(raw, p), des, ArucoParams(psf_fwhm_um=1.91), raw_img=raw, correction=p)
    t = next(iter(det.tags.values()))
    fake = t.centre_px + 0.55 * (t.corners_px[1] - t.corners_px[0])        # just outside the tag edge
    det.dots = np.vstack([det.dots, fake]); det.dot_box = np.concatenate([det.dot_box, [1]])
    det.dot_flag = np.concatenate([det.dot_flag, np.array([""], dtype=object)])
    recs, counts = DF.filter_dots(det, DF.DotFilterParams())
    assert recs[-1]["reason"] == "near_tag" and counts["near_tag"] >= 1
    recs2, _ = DF.filter_dots(det, DF.DotFilterParams(tag_enable=False))
    assert recs2[-1]["reason"] != "near_tag"


# ------------------------------------------------------------------ identity vs truth
def test_identity_recovery_clean_and_warped():
    for run, min_correct in (("opt_clean", 0.99), ("opt_warp", 0.97)):
        ctx, out, frames = _series("optimistic", run)
        if ctx is None:
            return
        d, truth, des = ctx
        for f, fr, (_l, _c, raw, p) in zip(out, truth["frames"], frames):
            assert f.ok, (run, f.label, f.reason)
            n, ok, wrong = _identity(d, fr, f.tagging, p, raw.shape, "dot")
            nh, okh, wrongh = _identity(d, fr, f.tagging, p, raw.shape, "dash")
            in_view = [i for i, t in fr["tags"].items() if t["in_frame"]]
            tagged_ids = [t for t in f.tagging.tags if t.startswith("aruco|")]
            print(f"  info  {run} λ {f.label:g}: dots {ok}/{n} correct ({ok / n:.2%}), {wrong} wrong · dashes "
                  f"{okh}/{nh}, {wrongh} wrong · ArUco {len(tagged_ids)}/{len(in_view)} · cv resid "
                  f"{f.tagging.per_category['dot']['res_median']:.2f} px")
            assert ok / n >= min_correct and wrong == 0, (run, f.label, ok / n, wrong)
            assert wrongh == 0 and len(tagged_ids) >= len(in_view)


def test_identity_spectrum_every_box():
    ctx, out, frames = _series("spectrum", "spectrum_clean")
    if ctx is None:
        return
    d, truth, des = ctx
    f, fr, (_l, _c, raw, p) = out[0], truth["frames"][0], frames[0]
    tags, traw, tbox = DM.truth_features(d, fr, "dot")
    tc = C.forward_geometric(traw, p, raw.shape)
    for b in des.boxes:
        m = tbox == b.N
        ok = sum(1 for t, xy in zip(np.asarray(tags)[m], tc[m]) if t in f.tagging.tags and
                 np.hypot(*(np.asarray(f.tagging.tags[t]) - xy)) < 1.0)
        assert ok / m.sum() >= 0.98, (b.N, ok / m.sum())


def test_similarity_vs_truth():
    """The uniform-expansion fit's scale is lambda x the print scale (px / um)."""
    ctx, out, frames = _series("optimistic", "opt_clean")
    if ctx is None:
        return
    for f in out:
        lam = f.tagging.similarity["s"] * 0.51
        assert abs(lam / f.label - 1) < 0.002, (f.label, lam)
        assert f.tagging.similarity["sign"] == -1.0
        assert abs(f.tagging.similarity["angle_deg"] - ROT) < 0.1          # opt_clean has no rotation of its own


# ------------------------------------------------------------------ series gates
def test_series_gates():
    ctx, out, frames = _series("conservative", "cons_dim")
    if ctx is None:
        return
    d, truth, des = ctx
    assert all(f.ok for f in out), [(f.label, f.reason) for f in out]
    assert out[0].tagging.source == "baseline" and all(f.tagging.source == "direct" for f in out[1:])
    # a mirrored frame after an accepted baseline is rejected
    lab, corr, raw, p = frames[1]
    bad = [(frames[0][0], frames[0][1], frames[0][2], frames[0][3]),
           (lab, corr[:, ::-1].copy(), raw[:, ::-1].copy(), p)]
    o2 = SR.process_frames(bad, des, ArucoParams(psf_fwhm_um=truth["camera"]["psf_fwhm_um"]))
    print(f"  info  mirrored frame: {o2[1].reason}")
    assert o2[0].ok and not o2[1].ok
    assert ("handedness" in o2[1].reason or "no ArUco" in o2[1].reason or "no usable tag" in o2[1].reason)
    # a frame with every tag painted out is rejected as unregistered
    corr2 = frames[2][1].copy()
    for t in out[2].det.tags.values():
        x0, y0 = np.floor(t.corners_px.min(0) - 8).astype(int); x1, y1 = np.ceil(t.corners_px.max(0) + 8).astype(int)
        corr2[max(0, y0):y1, max(0, x0):x1] = float(np.median(corr2))
    o3 = SR.process_frames([frames[0], (frames[2][0], corr2, None, frames[2][3])], des,
                           ArucoParams(psf_fwhm_um=truth["camera"]["psf_fwhm_um"]))
    assert not o3[1].ok and "no ArUco tag" in o3[1].reason


def test_validate_residual_gate():
    ctx, out, frames = _series("optimistic", "opt_clean")
    if ctx is None:
        return
    f = out[2]
    f.tagging.warp["cv_median"] = 50.0
    ok, reason, _s = SR.validate(f.tagging, f.det, f.label, [out[0].tagging])
    assert not ok and "warp residual" in reason


# ------------------------------------------------------------------ project runner
def test_project_run_stages_validated():
    d, truth = DM.run("optimistic", "opt_warp")
    if d is None:
        return
    des = DS.load(os.path.join(DM.DESIGNS, "1_optimistic"))
    with tempfile.TemporaryDirectory() as tmp:
        proj = PJ.Project(folder=tmp)
        for lam in (2.0, 1.0, 4.0):
            src = os.path.join(d, DM.frame(truth, lam)["files"][0] + ".ome.tif")
            dst = os.path.join(tmp, os.path.basename(src))
            try:
                os.symlink(src, dst)
            except OSError:
                shutil.copy(src, dst)
            e = proj.add(dst, lam)
            p = DM.stage1(truth, 0.0)
            for k in ("k1", "k2", "vig_strength", "vig_power"):
                setattr(e.pipeline.correction, k, getattr(p, k))
        accepted = []
        for e in sorted(proj.images, key=lambda e: e.label):
            ok, msg = PJ.run_stages_validated(e, accepted, des, ArucoParams(psf_fwhm_um=1.91))
            print(f"  info  run_stages {e.label:g}x: {msg}")
            assert ok, msg
            accepted.append(e)
            assert e.stage_status() == (True, True, True, True)
            assert e.pipeline.raw_image is None                   # unloaded after the run
        assert proj.initial().pipeline.tagging.source == "baseline"
        # results survive; the expanded frame shares tags with the initial
        a, b = proj.initial().pipeline.tagging, proj.expanded()[-1].pipeline.tagging
        assert len(set(a.tags) & set(b.tags)) > 1000
        # tag -> detection index round trip
        tag, (kind, i) = next((t, s) for t, s in b.src.items() if s[0] == "dot")
        det = proj.expanded()[-1].pipeline.detection
        assert np.allclose(det.dots[i], b.tags[tag])
