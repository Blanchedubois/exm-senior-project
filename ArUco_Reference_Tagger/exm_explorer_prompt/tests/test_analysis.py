"""Acceptance tests 5-7: no sites, regression vs the batch run, fast vs faithful."""

import json
import os

import numpy as np
import pytest

from exm_explorer import analysis as an
from exm_explorer import pipeline, scenario
from exm_explorer.grid import reference_dir


# ------------------------------------------------------------------ unit checks
def test_acf_overlap_matches_fft_version():
    rng = np.random.default_rng(0)
    img = rng.random((60, 80)).astype(np.float32)
    L = 15
    f = img - img.mean()
    shape = (60 + L, 80 + L)
    F = np.fft.rfft2(f, s=shape)
    ac = np.fft.irfft2(F * np.conj(F), s=shape)
    O = np.fft.rfft2(np.ones_like(f), s=shape)
    ov = np.fft.irfft2(O * np.conj(O), s=shape)
    ac = np.roll(ac, (L, L), (0, 1))[:2 * L + 1, :2 * L + 1]
    ov = np.roll(ov, (L, L), (0, 1))[:2 * L + 1, :2 * L + 1]
    ref = ac / np.maximum(ov, 1)
    assert np.allclose(an.acf(img, L), ref / ref[L, L], atol=1e-5)


def test_vectorised_local_scale_matches_loop():
    rng = np.random.default_rng(1)
    d = rng.normal(0, 1, (12, 14, 2))
    d[3, 4] = np.nan
    d[0, :3] = np.nan
    vec, _ = an.local_scale_fit(d, 24, 4.0)
    ny, nx, _ = d.shape
    oy, ox = np.mgrid[-2:3, -2:3]
    for a in range(ny):
        for c in range(nx):
            if not np.isfinite(d[a, c, 0]):
                assert np.isnan(vec[a, c]); continue
            ys, xs = a + oy.ravel(), c + ox.ravel()
            m = (ys >= 0) & (ys < ny) & (xs >= 0) & (xs < nx)
            ys, xs = ys[m], xs[m]
            dd = d[ys, xs]
            g = np.isfinite(dd[:, 0])
            if g.sum() < 9:
                assert np.isnan(vec[a, c]); continue
            M = np.c_[(xs[g] - c) * 24, (ys[g] - a) * 24, np.ones(g.sum())]
            cf, *_ = np.linalg.lstsq(M, dd[g], rcond=None)
            assert np.isclose(vec[a, c], 4.0 * np.sqrt(abs(np.linalg.det(np.eye(2) + cf[:2].T))))


# ------------------------------------------------------------------ test 5
@pytest.mark.slow
def test_no_sites(grid):
    sc = scenario.Scenario()                 # Navier, no sites, lambda = 4
    res, ex = pipeline.run_faithful(sc, grid)
    lam = sc.imaging.lam
    assert abs(res["acf_global"]["scale"] / lam - 1) < 1e-3
    assert abs(res["aruco_tags"]["global_"]["scale"] / lam - 1) < 5e-4
    assert res["aruco_tags"]["n_tags"] == 36
    st = res["ccf_after_tags_correction"]
    # scored on windows holding only dots (agreed 2026-10-30): windows with a
    # tag or dash carry a shape bias the reference method does not remove
    assert st["dots_only_windows"] > 2000
    assert st["dots_only_unwrapped_rms_err_px"] < 0.3
    assert st["dots_only_unwrapped_frac_off_by_a_cell"] < 0.005
    # all windows, for the record (reference method, as in the batch run)
    assert st["unwrapped_frac_off_by_a_cell"] < 0.02


# ------------------------------------------------------------------ test 6
@pytest.mark.slow
def test_regression_vs_batch_run(legacy_faithful):
    res, _ = legacy_faithful
    ref = json.load(open(os.path.join(reference_dir(), "results.json")))
    assert abs(res["truth_global"]["scale"] - ref["truth_global"]["scale"]) < 1e-9
    assert abs(res["acf_global"]["scale"] - 4.006) < 0.002
    assert abs(res["aruco_tags"]["global_"]["scale"] - 3.979) < 0.002
    for g in (res["acf_global"], res["aruco_tags"]["global_"]):
        assert abs(g["rotation_deg"] - 3.39) < 0.02
    st = res["ccf_after_tags_correction"]
    assert st["unwrapped_rms_err_px"] < 1.2
    assert st["unwrapped_frac_off_by_a_cell"] < 0.02
    assert st["naive_frac_off_by_a_cell"] > 0.05
    assert st["local_scale_corr"] > 0.93
    # and the reference numbers themselves, closely
    rs = ref["ccf_after_tag_correction"]
    assert st["windows"] == rs["windows"]
    assert abs(st["ccf_peak"] - rs["ccf_peak"]) < 1e-6
    assert abs(st["unwrapped_rms_err_px"] - rs["unwrapped_rms_err_px"]) < 0.01


# ------------------------------------------------------------------ test 7
def _compare(P, Q, pitch):
    tw = P["true_win"]
    ok = np.isfinite(P["unwrapped"][..., 0]) & np.isfinite(Q["unwrapped"][..., 0]) & np.isfinite(tw[..., 0])
    ef = np.hypot(*(P["unwrapped"] - tw)[ok].T)
    eq = np.hypot(*(Q["unwrapped"] - tw)[ok].T)
    same_cell = (ef < 0.5 * pitch) & (eq < 0.5 * pitch)
    d = np.hypot(*(P["unwrapped"] - Q["unwrapped"])[ok].T)[same_cell]
    return float(np.sqrt(np.mean(d ** 2))), float(np.median(d)), same_cell.mean()


@pytest.mark.slow
def test_fast_matches_faithful_noise_free(grid):
    """Rendering fidelity: with noise off and the same registration, the
    in-pre-frame render gives the same windowed displacements."""
    sc = scenario.legacy_scenario()
    sc.imaging.noise = False
    res, ex = pipeline.run_faithful(sc, grid)
    P = ex["runs"]["tags"]
    Q = pipeline.run_fast(sc, grid, A_b=ex["registrations"]["tags"])["ccf"]
    pitch = np.sqrt(abs(np.linalg.det(ex["pre_state"].Bpre)))
    rms, med, frac = _compare(P, Q, pitch)
    assert rms < 0.3 and med < 0.05 and frac > 0.98


@pytest.mark.slow
def test_fast_matches_faithful_statistics_with_noise(grid, legacy_faithful):
    """With noise the two paths draw different noise, so compare what they
    measure against the truth rather than window by window."""
    res, ex = legacy_faithful
    P = ex["runs"]["tags"]
    Q = pipeline.run_fast(ex["sim"].scenario, grid, A_b=ex["registrations"]["tags"])["ccf"]
    a, b = P["stats"], Q["stats"]
    assert abs(a["unwrapped_rms_err_px"] - b["unwrapped_rms_err_px"]) < 0.15
    assert abs(a["unwrapped_frac_off_by_a_cell"] - b["unwrapped_frac_off_by_a_cell"]) < 0.005
    assert abs(a["naive_frac_off_by_a_cell"] - b["naive_frac_off_by_a_cell"]) < 0.02
    assert abs(a["local_scale_corr"] - b["local_scale_corr"]) < 0.02
    pitch = np.sqrt(abs(np.linalg.det(ex["pre_state"].Bpre)))
    _, med, _ = _compare(P, Q, pitch)
    assert med < 0.05
