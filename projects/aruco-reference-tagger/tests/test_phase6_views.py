"""
Phase 6 tests (docs/06_PHASE6_CROSS_IMAGE_VIEWS.md §5): pairing, alignment,
overlay geometry, the local deformation gradient and its covariance, and the
recovered fields against the dummy truth.
"""
from __future__ import annotations
import math
import os
import sys
from types import SimpleNamespace
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _dummy as DM                                                            # noqa: E402
from rwtag import correct as C, designs as DS, errors as ER, series as SR, pairing as PR, deformation as DFm  # noqa: E402
from rwtag.aruco import ArucoParams                                            # noqa: E402
from rwtag.refwarp import warp as W                                            # noqa: E402
from rwtag.refwarp.types import TagResult                                      # noqa: E402

ROT = 6.0
DES = os.path.join(DM.DESIGNS, "1_optimistic")
_CACHE = {}


def _run(run, lams=(1.0, 2.0, 4.0)):
    key = (run, lams)
    if key in _CACHE:
        return _CACHE[key]
    d, truth = DM.run("optimistic", run)
    if d is None:
        return None
    frames = [(lam, DM.corrected(DM.load(d, DM.frame(truth, lam)), DM.stage1(truth, ROT)),
               DM.load(d, DM.frame(truth, lam)), DM.stage1(truth, ROT)) for lam in lams]
    out = SR.process_frames(frames, DS.load(DES), ArucoParams(psf_fwhm_um=1.91),
                            noise_model=ER.NoiseModel(gain_e_per_adu=truth["camera"]["true_gain_e_per_adu"], kappa_dot=0.9))
    _CACHE[key] = (d, truth, frames, out)
    return _CACHE[key]


def _entry(f):
    return SimpleNamespace(label=f.label, pipeline=SimpleNamespace(tagging=f.tagging, detection=f.det))


# ------------------------------------------------------------------ synthetic (ported V1 + new)
def test_pair_frames_join():
    a = TagResult(tags={"dot|B1|0_0": (1.0, 2.0), "dot|B1|0_1": (3.0, 4.0), "aruco|N0_0|3": (9.0, 9.0)}, warp={},
                  cov={"dot|B1|0_0": (0.01, 0.02, 0.0)}, label=1.0)
    b = TagResult(tags={"dot|B1|0_0": (2.0, 4.0), "aruco|N0_0|3": (18.0, 18.0), "dot|B9|1_1": (0, 0)}, warp={}, label=2.0)
    p = PR.pair_frames(a, b)
    assert p.tags == ["aruco|N0_0|3", "dot|B1|0_0"] and p.cats == ["aruco", "dot"]
    assert np.allclose(p.P1[1], [2, 4]) and np.allclose(p.C0[1], [[0.01, 0], [0, 0.02]]) and np.isnan(p.C1).all()
    assert PR.pair_tags(a.tags, b.tags, kinds=("dot",)) == {"dot|B1|0_0": (1.0, 2.0, 2.0, 4.0)}


def test_kabsch_ignores_uniform_scale():
    rng = np.random.default_rng(0)
    A = rng.normal(size=(50, 2)); th = math.radians(17)
    R = np.array([[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]])
    Rk = PR.kabsch_rotation(A, 3.0 * A @ R.T)
    assert np.allclose(Rk, R, atol=1e-9)


def test_overlay_composite_geometry():
    img0 = np.zeros((100, 120), np.uint8); img1 = np.zeros((100, 120), np.uint8)
    img0[50, 60] = 255; img1[50, 60] = 255
    align = {"R": np.eye(2), "s": 1.0, "t": np.array([10.0, -5.0])}
    rgb, origin = PR.overlay_composite(img0, img1, align)
    y0, x0 = 50 - int(origin[1]), 60 - int(origin[0])
    assert rgb[y0, x0, 1] == 255 and rgb[y0 - 5, x0 + 10, 0] > 200


def test_heat_grid_masks_voids():
    rng = np.random.default_rng(1)
    P = rng.uniform(0, 200, (400, 2)); P = P[(P[:, 0] < 80) | (P[:, 0] > 140)]
    g, (w, h) = PR.heat_grid(P, np.ones(len(P)), (200, 220), step=10)
    assert np.isnan(g[:, 11]).all() and np.isfinite(g[:, 3]).any()


def test_local_gradient_recovers_affine_and_covariance():
    rng = np.random.default_rng(2)
    A = np.array([[2.03, 0.04], [-0.02, 1.97]])
    sv = np.linalg.svd(A, compute_uv=False)
    inside, za = 0, []
    for _ in range(25):
        P0 = rng.uniform(0, 600, (300, 2)); s = 0.15
        P1 = P0 @ A.T + [5, 7] + rng.normal(0, s, P0.shape); P0n = P0 + rng.normal(0, s, P0.shape)
        Cs = np.repeat((s ** 2 * np.eye(2))[None], len(P0), 0)
        o = DFm.local_gradient(P0n, P1, Cs, Cs, k=8)
        inside += np.sum(np.abs(o["F"][:, 0, 0] - A[0, 0]) < 1.96 * np.sqrt(o["F_cov"][:, 0, 0]))
        za.append((o["lam1"] - sv[0]) / o["lam1_sigma"])
    frac = inside / (25 * 300)
    print(f"  info  F11 inside its 95 % interval {frac:.1%}; lam1 z-score sd {np.std(np.concatenate(za)):.2f}")
    assert 0.92 < frac < 0.98 and 0.85 < np.std(np.concatenate(za)) < 1.2
    assert abs(np.median(o["lin"]) - math.sqrt(np.linalg.det(A))) < 0.005


def test_polar_decomposition():
    rng = np.random.default_rng(3)
    F = rng.normal(size=(200, 2, 2)) * 0.2 + np.eye(2)[None] * 2
    F = F[np.linalg.det(F) > 0]
    d = DFm._decompose(F)
    assert np.allclose(np.einsum("nij,njk->nik", d["R_rot"], d["U_stretch"]), F, atol=1e-10)
    assert np.allclose(d["U_stretch"], np.transpose(d["U_stretch"], (0, 2, 1)))
    assert np.allclose(np.linalg.det(d["R_rot"]), 1.0)
    sv = np.linalg.svd(F, compute_uv=False)
    assert np.allclose(d["lam1"], sv[:, 0]) and np.allclose(d["J"], np.linalg.det(F))


# ------------------------------------------------------------------ dummy series
def test_warp_field_vs_truth():
    """The distortion field (similarity-aligned displacement) of the warped series
    against the truth computed the same way: Phase-D gate (RMS < 0.35 um, corr >
    0.9) and the displacement covariance covering the error."""
    r = _run("opt_warp")
    if r is None:
        return
    d, truth, frames, out = r
    tags0, traw0, _ = DM.truth_features(d, DM.frame(truth, 1.0), "dot")
    for f, (lam, _c, raw, p) in zip(out[1:], frames[1:]):
        pairs = PR.pair_frames(out[0].tagging, f.tagging)
        sim = PR.similarity_align(pairs)
        fd = PR.field(pairs, sim)
        tags1, traw1, _ = DM.truth_features(d, DM.frame(truth, lam), "dot")
        T0 = dict(zip(tags0, C.forward_geometric(traw0, p, raw.shape)))
        T1 = dict(zip(tags1, C.forward_geometric(traw1, p, raw.shape)))
        Q0 = np.array([T0[t] for t in fd["tags"]]); Q1 = np.array([T1[t] for t in fd["tags"]])
        Ut = W.similarity_points(Q1, W.similarity(Q1, Q0)) - Q0
        err = fd["U"] - Ut
        rms_um = float(np.sqrt(np.mean((err ** 2).sum(1)))) * 0.51          # reference frame is lambda 1: 0.51 um/px
        corr = float(np.corrcoef(fd["U"].ravel(), Ut.ravel())[0, 1])
        cover = float(np.mean(ER.mahalanobis2(err, fd["Cu"]) < 5.991))
        print(f"  info  λ {lam:g} vs 1: true distortion RMS {np.sqrt(np.mean((Ut ** 2).sum(1))) * 0.51:.3f} µm · "
              f"recovered to {rms_um:.3f} µm · corr {corr:.3f} · inside 95 % {cover:.1%} · expansion {sim['expansion']:.4f}")
        assert rms_um < 0.35 and corr > 0.9 and 0.9 < cover < 0.99
        assert abs(sim["expansion"] / lam - 1) < 0.003


def test_clean_series_is_flat():
    r = _run("opt_clean")
    if r is None:
        return
    d, truth, frames, out = r
    for f in out[1:]:
        pairs = PR.pair_frames(out[0].tagging, f.tagging)
        sim = PR.similarity_align(pairs)
        fd = PR.field(pairs, sim)
        an, asg = np.nanmedian(fd["anisotropy"]), np.nanmedian(fd["anisotropy_sigma"])
        cover = float(np.mean(ER.mahalanobis2(fd["U"], fd["Cu"]) < 5.991))
        print(f"  info  clean λ {f.label:g}: anisotropy median {an:.4f} (per-dot σ {asg:.4f}, the positive-bias floor) · "
              f"|u| inside its 95 % ellipse {cover:.1%} · lin {np.nanmedian(fd['lin']):.4f}")
        assert an < 2.0 * asg and cover > 0.93 and abs(sim["expansion"] / f.label - 1) < 0.001


def test_rigid_alignment_rotation():
    """opt_warp rotates the gel +2 deg at lambda 1 and +5 at lambda 2 (ccw), and the
    injected warp adds its own small net rotation in view; the rigid map compared ->
    reference must equal the rotation the TRUTH positions give about the same box
    centres (about -3 deg)."""
    r = _run("opt_warp")
    if r is None:
        return
    d, truth, frames, out = r
    design = DS.load(DES)
    from gui.field_panel import compute
    pairs, align, sim, fd = compute(_entry(out[0]), _entry(out[1]), design, "rigid")
    _l, _c, raw, p = frames[1]
    tags0, traw0, _ = DM.truth_features(d, DM.frame(truth, 1.0), "dot")
    tags1, traw1, _ = DM.truth_features(d, DM.frame(truth, 2.0), "dot")
    T0 = dict(zip(tags0, C.forward_geometric(traw0, p, raw.shape))); T1 = dict(zip(tags1, C.forward_geometric(traw1, p, raw.shape)))
    dp = pairs.select(("dot",))
    Q0 = np.array([T0[t] for t in dp.tags]); Q1 = np.array([T1[t] for t in dp.tags])
    Rt = PR.kabsch_rotation(Q1 - align["c1"], Q0 - align["c0"])
    true_ang = -math.degrees(math.atan2(Rt[1, 0], Rt[0, 0]))
    rel = DM.frame(truth, 1.0)["rotation_deg"] - DM.frame(truth, 2.0)["rotation_deg"]
    print(f"  info  rigid: rotation {align['angle_deg']:+.4f}° ± {align['angle_sigma_deg']:.4f} · truth {true_ang:+.4f}° "
          f"(applied {rel:+.1f}, the rest is the warp's net rotation) about B{align['box']}")
    assert abs(align["angle_deg"] - true_ang) < 0.005 and abs(true_ang - rel) < 0.2
    assert np.median(fd["umag"]) > 10                                # rigid keeps the growth


def test_pair_two_expanded_images():
    r = _run("opt_warp")
    if r is None:
        return
    d, truth, frames, out = r
    pairs = PR.pair_frames(out[1].tagging, out[2].tagging)          # lambda 2 <-> 4
    sim = PR.similarity_align(pairs)
    assert len(pairs.tags) > 3000 and abs(sim["expansion"] - 2.0) < 0.01
