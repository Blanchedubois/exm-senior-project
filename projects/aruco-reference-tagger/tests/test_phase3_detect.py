"""
Phase 3 tests (docs/03_PHASE3_DETECT_STAGE.md §6): the design registry, the
ArUco Stage-2 detector on the dummy series against truth, the per-box handling
of the spectrum print, the raw second pass, photometry, and the project helper.
Every frame goes through a real Stage-1 correction (lens + vignette + a deskew
rotation) first, as in the app.
"""
from __future__ import annotations
import csv
import json
import math
import os
import shutil
import sys
import tempfile
import numpy as np
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _dummy as DM                                                    # noqa: E402
from rwtag import correct as C, designs as DS, project as PJ, io      # noqa: E402
from rwtag.aruco import ArucoParams                                    # noqa: E402
from rwtag.aruco import detect as AD                                   # noqa: E402

ROT = 6.0          # the Stage-1 deskew applied in these tests (exercises the rotation path)


def _rot_tol(n_tags):
    """Frame-rotation gate: per-tag rotation error is unbiased with sd 0.15 deg on the
    dummy frames (311 tags, three runs), so the median of n tags is good to ~0.2/sqrt(n);
    3 sigma -> 0.6/sqrt(n) deg (0.30 with the 4 tags in view at high lambda)."""
    return 0.6 / max(n_tags, 1) ** 0.5


def _detect(d, truth, fr, design_key, rotate=ROT, params=None, raw_pass=True):
    p = DM.stage1(truth, rotate)
    raw = DM.load(d, fr)
    corr = DM.corrected(raw, p)
    cam = truth["camera"]
    params = params or ArucoParams(um_per_px=cam["um_per_px"], psf_fwhm_um=cam["psf_fwhm_um"], raw_pass=raw_pass)
    design = DS.load(os.path.join(DM.DESIGNS, DM.DESIGN_DIR[design_key]))
    return AD.detect(corr, design, params, raw_img=raw, correction=p), design, p, raw


def _score_dots(det, d, fr, p, raw, params):
    """Recovery of the truth dots that have a real source in the frame."""
    _tags, traw, tbox = DM.truth_features(d, fr, "dot")
    fw = params.imaged_fwhm_px(2.125)
    use = DM.detectable(traw, raw.shape, 1.5 * fw)
    tc = C.forward_geometric(traw[use], p, raw.shape)
    tree = cKDTree(det.dots)
    dist, idx = tree.query(tc)
    found = dist < 0.5
    box_ok = det.dot_box[idx[found]] == tbox[use][found]
    # detections that match no truth dot at all (anywhere in the frame)
    tall = C.forward_geometric(traw, p, raw.shape)
    tall = tall[np.isfinite(tall).all(1)]
    dfalse, _ = cKDTree(tall).query(det.dots)
    return dict(n=int(use.sum()), found=float(found.mean()), box_ok=float(box_ok.mean()),
                rms=float(np.sqrt(np.mean(dist[found] ** 2))), false=float((dfalse > 1.5).mean()))


# ------------------------------------------------------------------ registry
def test_design_registry_loads_all_four():
    reg = DS.registry()
    assert len(reg) == 4
    for _lab, folder in reg:
        d = DS.load(folder)
        assert len(d.boxes) == 25 and len(d.node_ids) == 36 and "reference_tags.json" in d.file_sha256
    spec = DS.load(os.path.join(DM.DESIGNS, "4_spectrum"))
    boxes_csv = os.path.normpath(os.path.join(DM.ROOT, "..", "aruco-marker-design", "designs", "4_spectrum", "boxes.csv"))
    if os.path.exists(boxes_csv):
        with open(boxes_csv) as f:
            for r in csv.DictReader(f):
                b = spec.box(int(r["box"]))
                assert abs(b.dot_um - float(r["dot"])) < 1e-9 and abs(b.pitch_um - float(r["pitch"])) < 1e-9
                assert b.count == int(r["count"])
                assert sorted(b.corner_tag_ids) == sorted(int(x) for x in r["corner_tag_ids"].split())
    assert DS.meta_name(os.path.join(DM.DESIGNS, "4_spectrum")) == "spectrum"


# ------------------------------------------------------------------ detection vs truth
def test_detect_optimistic_warped_series():
    d, truth = DM.run("optimistic", "opt_warp")
    if d is None:
        return
    cam = truth["camera"]
    for fr in truth["frames"]:
        det, design, p, raw = _detect(d, truth, fr, "optimistic")
        assert det.model["registered"] and det.model["sign"] == -1.0, fr["label"]
        s = _score_dots(det, d, fr, p, raw, ArucoParams(um_per_px=cam["um_per_px"], psf_fwhm_um=cam["psf_fwhm_um"]))
        print(f"  info  λ {fr['label']:g}: λ tags {det.lam_tags:.4f} dots {det.lam_dots:.4f} · rot {det.rot_raw_deg:+.2f} "
              f"(applied {fr['rotation_deg']:+.1f}) · {s['n']} truth dots: found {s['found']:.2%}, box {s['box_ok']:.2%}, "
              f"rms {s['rms']:.3f} px, false {s['false']:.2%}")
        # the injected warp shifts the best-fit expansion by up to ~0.2 % (Phase D)
        assert abs(det.lam_tags / fr["label"] - 1) < 0.005, (fr["label"], det.lam_tags)
        assert abs(det.lam_dots / fr["label"] - 1) < 0.01, (fr["label"], det.lam_dots)
        assert abs(det.rot_raw_deg - fr["rotation_deg"]) < _rot_tol(det.frame_pose.n_tags), (fr["label"], det.rot_raw_deg)
        assert s["found"] >= 0.99 and s["box_ok"] >= 0.999 and s["rms"] < 0.35 and s["false"] < 0.01, s


def test_detect_sparse_dim_conservative():
    d, truth = DM.run("conservative", "cons_dim")
    if d is None:
        return
    cam = truth["camera"]
    for fr in truth["frames"]:
        det, design, p, raw = _detect(d, truth, fr, "conservative")
        s = _score_dots(det, d, fr, p, raw, ArucoParams(um_per_px=cam["um_per_px"], psf_fwhm_um=cam["psf_fwhm_um"]))
        print(f"  info  conservative λ {fr['label']:g}: {s['n']} dots, found {s['found']:.2%}, rms {s['rms']:.3f}, λ {det.lam_tags:.4f}")
        assert det.model["registered"] and abs(det.lam_tags / fr["label"] - 1) < 0.005
        assert s["found"] >= 0.97 and s["box_ok"] >= 0.999


def test_per_box_spectrum_clean():
    """Every box of the spectrum print, with its own dot size and pitch, at a PSF
    that resolves them: each box recovers its dots and its own lattice pitch."""
    d, truth = DM.run("spectrum", "spectrum_clean")
    if d is None:
        return
    fr = DM.frame(truth, 1.0)
    det, design, p, raw = _detect(d, truth, fr, "spectrum")
    _t, traw, tbox = DM.truth_features(d, fr, "dot")
    tc = C.forward_geometric(traw, p, raw.shape)
    dist, idx = cKDTree(det.dots).query(tc)
    for b in design.boxes:
        m = tbox == b.N
        f = float(np.mean((dist[m] < 0.5) & (det.dot_box[idx[m]] == b.N)))
        lam = det.per_box[b.N]["lam"]
        assert f >= 0.98, (b.N, f)
        assert abs(lam - 1.0) < 0.005, (b.N, lam)
    assert abs(det.lam_tags - 1.0) < 0.005


def test_spectrum_blur_discriminates():
    """At PSF 3.4 the per-box recovery must follow the design rule: the known-bad
    bottom-left box fails, the widest-gap boxes pass, and the top row names the
    6.5-7 um spacings. (Scored against the drawn-position truth the detector
    resolves 6.5 um at this blur, slightly tighter than the 1.75x design rule
    predicts -- consistent with W5's measured 1.64x at PSF 3.18.)"""
    d, truth = DM.run("spectrum", "spectrum_blur")
    if d is None:
        return
    fr = DM.frame(truth, 1.0)
    det, design, p, raw = _detect(d, truth, fr, "spectrum")
    _t, traw, tbox = DM.truth_features(d, fr, "dot")
    tc = C.forward_geometric(traw, p, raw.shape)
    dist, idx = cKDTree(det.dots).query(tc)
    spec = {int(b["box"]): b for b in json.load(open(os.path.join(DM.DESIGNS, "4_spectrum", "spec_sheet.json")))["boxes"]}
    found = {}
    for b in design.boxes:
        m = tbox == b.N
        found[b.N] = float(np.mean((dist[m] < 0.5) & (det.dot_box[idx[m]] == b.N)))
    psfmax = np.array([spec[N]["psf_fwhm_max_predicted"] for N in sorted(found)])
    f = np.array([found[N] for N in sorted(found)])
    from scipy.stats import spearmanr
    rho = spearmanr(psfmax, f).correlation
    top = {spec[N]["pitch"]: found[N] for N in found if spec[N]["row"] == 4}
    tight = min(pp for pp, v in top.items() if v >= 0.95 and all(top[q] >= 0.95 for q in top if q > pp))
    print(f"  info  spectrum PSF 3.4: box 1 {found[1]:.1%}, box 21 {found[21]:.1%}, rank corr with design rule "
          f"{rho:.2f}; top row {[f'{k:g}:{v:.0%}' for k, v in sorted(top.items())]} -> tightest {tight:g} um")
    assert found[1] < 0.2 and found[21] >= 0.97 and rho > 0.8
    pitches = sorted(top)
    assert all(top[b] >= top[a] - 0.02 for a, b in zip(pitches, pitches[1:]))     # recovery rises with spacing
    assert tight <= 7.0 and top[5.0] < 0.9


def test_rejects_unregistered():
    d, truth = DM.run("optimistic", "opt_clean")
    if d is None:
        return
    fr = DM.frame(truth, 1.0)
    p = DM.stage1(truth, 0.0)
    raw = DM.load(d, fr)
    corr = DM.corrected(raw, p)
    bg = float(np.median(corr))
    for t in fr["tags"].values():                              # paint every tag out
        c = C.forward_geometric(np.array(t["corners_raw"]), p, raw.shape)
        x0, y0 = np.floor(c.min(0) - 6).astype(int); x1, y1 = np.ceil(c.max(0) + 6).astype(int)
        corr[max(0, y0):y1, max(0, x0):x1] = bg
    design = DS.load(os.path.join(DM.DESIGNS, "1_optimistic"))
    det = AD.detect(corr, design, ArucoParams(um_per_px=0.51, psf_fwhm_um=1.91), raw_img=raw, correction=p)
    assert not det.model["registered"] and "no ArUco tag" in det.model["reason"]
    assert len(det.dots) > 1000                              # dots are still shown, unregistered


# ------------------------------------------------------------------ raw pass, edge, photometry
def test_raw_second_pass():
    d, truth = DM.run("optimistic", "opt_warp")
    if d is None:
        return
    for lam in (1.0, 4.0):
        fr = DM.frame(truth, lam)
        det, design, p, raw = _detect(d, truth, fr, "optimistic")
        rp = det.raw_pass
        assert rp is not None and not rp["geometric_identity"]
        # the raw-frame detections land on the truth raw positions
        _t, traw, _b = DM.truth_features(d, fr, "dot")
        dd, _ = cKDTree(traw).query(rp["dots_det"][rp["dots_found"]])
        print(f"  info  λ {lam:g}: raw pass re-found {rp['dot_match_frac']:.2%} · median |det-map| "
              f"{rp['median_det_minus_map_px']:.3f} px · raw det vs truth median {np.median(dd):.3f} px · "
              f"tags {len(rp['tags_det'])}/{len(det.tags)} · raw rot {rp['rot_deg']:+.2f}")
        assert rp["dot_match_frac"] >= 0.99 and rp["median_det_minus_map_px"] < 0.1
        assert np.median(dd) < 0.3 and len(rp["tags_det"]) == len(det.tags)
        assert abs(rp["rot_deg"] - fr["rotation_deg"]) < _rot_tol(len(rp["tags_det"]))
        for i, xy in rp["tags_det"].items():
            tr = fr["tags"][str(i)]
            assert np.hypot(xy[0] - tr["x_raw"], xy[1] - tr["y_raw"]) < 0.8


def test_edge_flags_are_exact():
    """No dot with a real raw source is flagged 'edge'; every flagged dot lacks one."""
    d, truth = DM.run("optimistic", "opt_clean")
    if d is None:
        return
    fr = DM.frame(truth, 2.0)
    det, design, p, raw = _detect(d, truth, fr, "optimistic", rotate=12.0)
    edge = det.dot_flag == "edge"
    fw = 2.35482 * np.asarray(det.dot_sigma_px)
    m = C.inverse_geometric(det.dots, p, raw.shape)
    H, W = raw.shape
    margin = ArucoParams(um_per_px=0.51, psf_fwhm_um=truth["camera"]["psf_fwhm_um"]).imaged_fwhm_px(2.125)
    inside = np.isfinite(m).all(1)
    inside[inside] = ((m[inside, 0] >= margin + 1) & (m[inside, 0] <= W - 2 - margin) &
                      (m[inside, 1] >= margin + 1) & (m[inside, 1] <= H - 2 - margin))
    print(f"  info  rotated 12°: {edge.sum()} edge dots of {len(edge)}")
    assert edge.sum() > 0 and not (edge & inside).any()


def test_photometry_matches_truth_width():
    d, truth = DM.run("optimistic", "opt_warp")
    if d is None:
        return
    psf = truth["camera"]["psf_fwhm_um"]; um = truth["camera"]["um_per_px"]
    # a 2.125 um square convolved with a Gaussian PSF: sigma^2 = sigma_psf^2 + side^2 / 12
    s_true = math.sqrt((psf / 2.35482) ** 2 + 2.125 ** 2 / 12) / um
    for lam in (1.0, 2.0):
        det, *_ = _detect(d, truth, DM.frame(truth, lam), "optimistic")
        s = float(np.nanmedian(det.dot_sigma_px))
        print(f"  info  λ {lam:g}: spot sigma {s:.2f} px (printed dot ⊗ PSF {s_true:.2f}) · signal "
              f"{np.nanmedian(det.dot_signal):.0f} ADU · background {np.nanmedian(det.dot_bg):.1f} ADU")
        assert abs(s / s_true - 1) < 0.2
        assert np.isfinite(det.dot_signal).mean() > 0.99 and np.nanmedian(det.dot_signal) > 20 * np.nanmedian(det.dot_bg)


# ------------------------------------------------------------------ project helper
def test_project_run_detect_sets_meta():
    d, truth = DM.run("optimistic", "opt_warp")
    if d is None:
        return
    fr = DM.frame(truth, 2.0)
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(d, fr["files"][0] + ".ome.tif")
        dst = os.path.join(tmp, os.path.basename(src))
        try:
            os.symlink(src, dst)
        except OSError:
            shutil.copy(src, dst)
        proj = PJ.Project(folder=tmp)
        e = proj.add(dst, 2.0)
        p = DM.stage1(truth, 0.0)
        for k in ("k1", "k2", "vig_strength", "vig_power"):
            setattr(e.pipeline.correction, k, getattr(p, k))
        design = DS.load(os.path.join(DM.DESIGNS, "1_optimistic"))
        det = PJ.run_detect(e, design, ArucoParams(psf_fwhm_um=truth["camera"]["psf_fwhm_um"]))
        assert det.model["registered"] and e.stage_status()[1]
        m = e.meta
        assert abs(m.expansion_derived - 2.0) < 0.01 and m.source("expansion_derived") == "pipeline"
        assert abs(m.rotation_derived_deg - fr["rotation_deg"]) < 0.15 and m.handedness == -1.0
        assert m.print_design == "optimistic" and m.expansion_derived_sigma is not None
        assert det.params["um_per_px"] == 0.51 and det.params["photometry_on"] == "raw"
