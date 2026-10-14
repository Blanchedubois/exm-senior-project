"""
Phase 5 tests (docs/05_PHASE5_ERROR_MODEL.md §6): the localisation formula against
simulated spots, the noise and photometry estimates, repeat-frame calibration on
held-out frames, coverage of the error ellipses against the dummy truth for dots,
tag centres and rotations, frame consistency of the covariances, the alignment
bootstrap and the significance flag rate.
"""
from __future__ import annotations
import math
import os
import sys
import tempfile
import numpy as np
from scipy.special import erf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _dummy as DM                                                            # noqa: E402
from rwtag import correct as C, designs as DS, errors as ER, series as SR, project as PJ   # noqa: E402
from rwtag.types import LevelsParams                                           # noqa: E402
from rwtag.aruco import ArucoParams                                            # noqa: E402
from rwtag.aruco import detect as AD                                           # noqa: E402
from rwtag.refwarp import warp as W                                            # noqa: E402

ROT = 6.0
DES = os.path.join(DM.DESIGNS, "1_optimistic")


def _spot(rng, N, b, s, R=15):
    yy, xx = np.mgrid[0:2 * R + 1, 0:2 * R + 1]
    cx, cy = R + rng.uniform(-0.5, 0.5), R + rng.uniform(-0.5, 0.5)
    fx = 0.5 * (erf((xx + 0.5 - cx) / (math.sqrt(2) * s)) - erf((xx - 0.5 - cx) / (math.sqrt(2) * s)))
    fy = 0.5 * (erf((yy + 0.5 - cy) / (math.sqrt(2) * s)) - erf((yy - 0.5 - cy) / (math.sqrt(2) * s)))
    img = rng.poisson(N * fx * fy).astype(float) + rng.normal(0, math.sqrt(b), xx.shape) + 100
    return img, np.array([cx, cy])


# ------------------------------------------------------------------ formula, noise, photometry
def test_mortensen_predicts_estimator():
    """The least-squares formula predicts the Gaussian-mask centroid's scatter."""
    rng = np.random.default_rng(0)
    for N, b, s in ((4000, 45.0, 2.2), (800, 45.0, 2.2), (20000, 10.0, 1.6)):
        errs = []
        for _ in range(1500):
            img, c = _spot(rng, N, b, s)
            p = AD.refine_gauss(img, np.round(c)[None], s, 6)[0]
            errs.append(p - c)
        emp = np.asarray(errs).var(0).mean()
        model = float(ER.mortensen_var(N, b, math.sqrt(s * s + 1 / 12)))
        print(f"  info  N {N} b {b} s {s}: empirical/model variance {emp / model:.2f}")
        assert 0.75 < emp / model < 1.3


def test_background_noise_and_photometry():
    rng = np.random.default_rng(1)
    big = rng.normal(100, 6.0, (500, 500)); big[::20, ::20] += 3000
    assert abs(AD.background_noise(big) / 6.0 - 1) < 0.05
    S = []
    for _ in range(400):
        img, c = _spot(rng, 4000, 45.0, 2.2)
        S.append(AD.spot_photometry(img, c[None], 2.2, math.sqrt(45.0))[0][0])
    assert abs(np.median(S) / 4000 - 1) < 0.15, np.median(S)


# ------------------------------------------------------------------ calibration on held-out frames
def test_kappa_calibration_holds_out_of_sample():
    d, truth = DM.run("optimistic", "opt_noise")
    if d is None:
        return
    fr = DM.frame(truth, 2.0); p = DM.stage1(truth, ROT)
    g = truth["camera"]["true_gain_e_per_adu"]
    design = DS.load(DES)
    params = ArucoParams(psf_fwhm_um=1.91, raw_pass=False)
    paths = [os.path.join(d, f + ".ome.tif") for f in fr["files"]]
    cal = PJ.calibrate_noise_from_files(paths[:5], p, LevelsParams(), design, params, gain=g)
    print(f"  info  calibrated on 5 frames: κ dots {cal['kappa_dot']:.2f} · tags {cal['kappa_tag']:.2f} · rotation {cal['kappa_rot']:.2f}")
    assert 0.7 < cal["kappa_dot"] < 1.2 and 1.5 < cal["kappa_tag"] < 4 and 1.5 < cal["kappa_rot"] < 5
    # apply to the OTHER five: model (calibrated, no floor) vs their scatter
    nm = ER.NoiseModel(gain_e_per_adu=g, kappa_dot=cal["kappa_dot"], kappa_tag=cal["kappa_tag"],
                       kappa_rot=cal["kappa_rot"], floor_px=0, tag_floor_px=0, rot_floor_deg=0)
    from rwtag.dotfilter import filter_frame
    from rwtag.refwarp import tagframe as TF
    res = []
    for path in paths[5:]:
        raw = DM.io.load_tiff(path)
        det = AD.detect(DM.corrected(raw, p), design, params, raw_img=raw, correction=p, noise_model=nm)
        res.append((det, TF.tag_frame(det, filter_frame(det, design=design), design)))
    check = ER.calibrate_from_repeats(res)
    print(f"  info  held-out frames, scatter / calibrated model: dots {check['kappa_dot']:.2f} · tags "
          f"{check['kappa_tag']:.2f} · rotation {check['kappa_rot']:.2f}")
    assert abs(check["kappa_dot"] - 1) < 0.15 and abs(check["kappa_tag"] - 1) < 0.35


def test_relative_without_gain():
    d, truth = DM.run("optimistic", "opt_clean")
    if d is None:
        return
    fr = DM.frame(truth, 1.0); p = DM.stage1(truth, 0.0); raw = DM.load(d, fr)
    design = DS.load(DES)
    a = AD.detect(DM.corrected(raw, p), design, ArucoParams(psf_fwhm_um=1.91, raw_pass=False), raw_img=raw, correction=p)
    b = AD.detect(DM.corrected(raw, p), design, ArucoParams(psf_fwhm_um=1.91, raw_pass=False), raw_img=raw, correction=p,
                  noise_model=ER.NoiseModel(gain_e_per_adu=truth["camera"]["true_gain_e_per_adu"]))
    assert a.noise["relative"] and not b.noise["relative"]
    assert np.nanmedian(b.dot_cov_corr[:, 0, 0]) > np.nanmedian(a.dot_cov_corr[:, 0, 0])   # fewer photons -> larger


def test_cov_frames_consistent():
    """Corrected-frame covariances are the raw ones pushed through the Jacobian."""
    d, truth = DM.run("optimistic", "opt_warp")
    if d is None:
        return
    fr = DM.frame(truth, 2.0); p = DM.stage1(truth, ROT); raw = DM.load(d, fr)
    det = AD.detect(DM.corrected(raw, p), DS.load(DES), ArucoParams(psf_fwhm_um=1.91, raw_pass=False), raw_img=raw, correction=p)
    ok = np.isfinite(det.dot_cov_corr).all((1, 2))
    back = C.propagate_cov(det.dot_cov_corr[ok], C.inverse_jacobian(det.dots[ok], p, raw.shape))
    assert np.allclose(back, det.dot_cov_raw[ok], rtol=1e-6, atol=1e-12)
    assert ok.mean() > 0.99
    for v in det.tag_cov.values():
        assert v is not None and np.isfinite(v["centre_corr"]).all() and v["rot_sigma_deg"] > 0


# ------------------------------------------------------------------ coverage against truth
def test_error_ellipses_cover_truth():
    """With the true gain, the calibrated dot kappa and the shipped defaults, the
    95 % error ellipses contain ~95 % of the true positions."""
    d, truth = DM.run("optimistic", "opt_warp")
    if d is None:
        return
    nm = ER.NoiseModel(gain_e_per_adu=truth["camera"]["true_gain_e_per_adu"], kappa_dot=0.9)
    design = DS.load(DES)
    frames = [(fr["label"], DM.corrected(DM.load(d, fr), DM.stage1(truth, ROT)), DM.load(d, fr), DM.stage1(truth, ROT))
              for fr in truth["frames"]]
    out = SR.process_frames(frames, design, ArucoParams(psf_fwhm_um=1.91), noise_model=nm)
    tz, rz = [], []
    for f, fr, (_l, _c, raw, p) in zip(out, truth["frames"], frames):
        tags, traw, _b = DM.truth_features(d, fr, "dot")
        tc = dict(zip(tags, C.forward_geometric(traw, p, raw.shape)))
        dts = [t for t in f.tagging.tags if t.startswith("dot|")]
        err = np.array([np.asarray(f.tagging.tags[t]) - tc[t] for t in dts])
        cov = np.array([f.tagging.cov[t] for t in dts])
        cov = np.stack([np.column_stack([cov[:, 0], cov[:, 2]]), np.column_stack([cov[:, 2], cov[:, 1]])], axis=1)
        cover = float(np.mean(ER.mahalanobis2(err, cov) < 5.991))
        print(f"  info  λ {f.label:g}: dot σ {np.sqrt(np.median(cov[:, 0, 0])):.3f} px, error RMS/axis "
              f"{np.sqrt(np.mean(err ** 2)):.3f} px, inside the 95 % ellipse {cover:.1%}")
        assert 0.90 < cover < 0.99, (f.label, cover)
        for t in f.tagging.tags:
            if t.startswith("aruco|"):
                i = int(t.split("|")[2]); tt = fr["tags"][str(i)]
                e = np.asarray(f.tagging.tags[t]) - C.forward_geometric([[tt["x_raw"], tt["y_raw"]]], p, raw.shape)[0]
                tz.append(ER.mahalanobis2(e[None], f.det.tag_cov[i]["centre_corr"][None])[0])
                rz.append(((f.det.tags[i].rot_deg - p.rotate_deg - tt["rot_deg"]) / f.det.tag_cov[i]["rot_sigma_deg"]) ** 2)
    tc_, rc_ = float(np.mean(np.array(tz) < 5.991)), float(np.mean(np.array(rz) < 3.841))
    print(f"  info  tags: centre inside 95 % ellipse {tc_:.1%}, rotation inside ±1.96σ {rc_:.1%} (n {len(tz)})")
    assert tc_ > 0.8 and rc_ > 0.8


def _flag_rates(design_key, run, design):
    """(vs design, detected/true deviation correlation, vs initial) for the
    lambda-2 frame of a run, with the 99 % bound (chi-square 2 dof 9.21)."""
    pos = {r["tag"]: (r["x_um"], r["y_um"]) for r in design.records}
    d, truth = DM.run(design_key, run)
    if d is None:
        return None
    nm = ER.NoiseModel(gain_e_per_adu=truth["camera"]["true_gain_e_per_adu"], kappa_dot=0.9)
    frames = []
    for lam in (1.0, 2.0):
        fr = DM.frame(truth, lam); p = DM.stage1(truth, ROT); raw = DM.load(d, fr)
        frames.append((lam, DM.corrected(raw, p), raw, p))
    out = SR.process_frames(frames, design, ArucoParams(psf_fwhm_um=1.91), noise_model=nm)
    t1, t2 = out[0].tagging, out[1].tagging
    cov = lambda tr, t: np.array([[tr.cov[t][0], tr.cov[t][2]], [tr.cov[t][2], tr.cov[t][1]]])
    fr2 = DM.frame(truth, 2.0); p = frames[1][3]
    tags, traw, _b = DM.truth_features(d, fr2, "dot")
    tc = dict(zip(tags, C.forward_geometric(traw, p, frames[1][2].shape)))
    dts = [t for t in t2.tags if t.startswith("dot|") and t in t1.tags]
    X = np.array([pos[t] for t in dts])
    dev = np.array([t2.tags[t] for t in dts]) - W.similarity_points(X, t2.similarity)
    Tt = np.array([tc[t] for t in dts])
    dev_true = Tt - W.similarity_points(X, W.similarity(X, Tt))
    vs_design = float(np.mean(ER.mahalanobis2(dev, np.array([cov(t2, t) for t in dts])) > 9.21))
    corr = float(np.corrcoef(dev.ravel(), dev_true.ravel())[0, 1])
    P1 = np.array([t1.tags[t] for t in dts]); P2 = np.array([t2.tags[t] for t in dts])
    sim = W.similarity(P1, P2); Rm = np.asarray(sim["R"]); sc = sim["s"]
    r = P2 - W.similarity_points(P1, sim)
    cr = np.array([cov(t2, t) + sc ** 2 * Rm @ cov(t1, t) @ Rm.T for t in dts])
    vs_initial = float(np.mean(ER.mahalanobis2(r, cr) > 9.21))
    print(f"  info  {run}: beyond the 99 % bound vs DESIGN {vs_design:.1%} (detected vs true deviation "
          f"correlation {corr:.2f}) · vs the INITIAL frame {vs_initial:.1%}")
    return vs_design, corr, vs_initial


def test_significance_flag_rates():
    """The significance test is calibrated: on an undistorted series ~1 % of dots
    exceed the 99 % bound, against the design and against the initial frame; on
    the warped series almost all do."""
    design = DS.load(DES)
    clean = _flag_rates("optimistic", "opt_clean", design)
    warp = _flag_rates("optimistic", "opt_warp", design)
    if clean is None or warp is None:
        return
    assert clean[0] < 0.03 and clean[2] < 0.03
    assert warp[0] > 0.5 and warp[2] > 0.5 and warp[1] > 0.9


def test_print_error_cancels_against_initial():
    """A FIXED print error (50 nm per feature, the same in every frame, as on a real
    Nanoscribe print) makes dots deviate from the DESIGN -- and the detector
    measures exactly that deviation -- but it cancels when the expanded frame is
    compared with the INITIAL frame, because the same printed dot is in both.
    Hence the export reports both: deviation from the design (includes print
    error) and positions relative to the initial image (print error cancelled)."""
    r = _flag_rates("optimistic", "opt_print", DS.load(DES))
    if r is None:
        return
    vs_design, corr, vs_initial = r
    assert vs_design > 0.3 and corr > 0.85 and vs_initial < 0.03


# ------------------------------------------------------------------ alignment, persistence
def test_alignment_bootstrap_coverage():
    rng = np.random.default_rng(3)
    inside = 0
    for _ in range(60):
        A = rng.uniform(0, 1000, (150, 2))
        th = rng.uniform(-10, 10); R = np.array([[math.cos(math.radians(th)), -math.sin(math.radians(th))],
                                                 [math.sin(math.radians(th)), math.cos(math.radians(th))]])
        B = A @ R.T + [30, -20] + rng.normal(0, 0.5, A.shape)
        fit = ER.bootstrap_alignment(A, B, "rigid", n_boot=150, seed=int(rng.integers(1e9)))
        z = (fit["params"][0] - th) / math.sqrt(fit["cov"][0, 0])
        inside += abs(z) < 1.96
    print(f"  info  rotation inside its bootstrap 95 % interval in {inside}/60 trials")
    assert inside >= 51


def test_project_noise_persisted():
    with tempfile.TemporaryDirectory() as tmp:
        proj = PJ.Project(folder=tmp)
        proj.noise = {"kappa_dot": 0.88, "kappa_source": "repeat images: 10 frames"}
        path = proj.save()
        p2 = PJ.Project.load(path)
        assert p2.noise["kappa_dot"] == 0.88
        m = ER.NoiseModel.from_dict(p2.noise)
        assert m.kappa_dot == 0.88 and m.kappa_tag == ER.DEFAULTS["kappa_tag"]
