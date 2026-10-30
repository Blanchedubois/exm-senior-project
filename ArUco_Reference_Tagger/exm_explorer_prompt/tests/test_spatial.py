"""Checks of the spatial-structure statistics on fields with a known answer."""

import numpy as np
from scipy import ndimage

from exm_explorer import spatial


def test_correlation_length_of_smoothed_noise():
    # white noise smoothed by a Gaussian of sigma has ACF exp(-r^2 / (4 sigma^2)):
    # it falls to 1/e at r = 2 sigma
    rng = np.random.default_rng(0)
    sigma = 6.0
    f = ndimage.gaussian_filter(rng.standard_normal((512, 512)), sigma, mode="wrap")
    xi, _, _ = spatial.correlation_length(f, np.ones_like(f, bool), step=1.0, maxlag=60)
    assert abs(xi / (2 * sigma) - 1) < 0.08


def test_axial_stats():
    rng = np.random.default_rng(1)
    random = spatial.axial_stats(rng.uniform(0, 180, 2000))
    aligned = spatial.axial_stats(rng.normal(30, 8, 2000) % 180)
    assert random["R"] < 0.08 and random["p"] > 0.01
    assert aligned["R"] > 0.9 and aligned["p"] < 1e-6
    assert abs(aligned["mean_deg"] - 30) < 2
    # 170 and 10 deg are 20 deg apart for axial data: mean near 0/180
    m = spatial.axial_stats([170, 10])["mean_deg"]
    assert min(m, 180 - m) < 1e-6


def test_rms_error_vs_length():
    rng = np.random.default_rng(2)
    xy = rng.uniform(0, 100, (3000, 2))
    eps = 0.01                                   # uniform 1 % stretch along x
    r = np.c_[eps * xy[:, 0], np.zeros(len(xy))]
    L, rms, n = spatial.rms_error_vs_length(xy, r, np.arange(0, 101, 10.0))
    # error of a pair = eps * |dx|; RMS over random directions = eps * L / sqrt(2)
    ok = (n > 1000) & (L > 10)            # first bin: its pairs sit above the bin centre
    assert np.allclose(rms[ok] / (eps * L[ok] / np.sqrt(2)), 1, atol=0.06)


def test_remove_similarity():
    rng = np.random.default_rng(3)
    src = rng.uniform(0, 100, (200, 2))
    t = np.deg2rad(7.0)
    R = 4.0 * np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
    res, s = spatial.remove_similarity(src, src @ R.T + [3, -5])
    assert abs(s - 4.0) < 1e-9 and np.abs(res).max() < 1e-9
