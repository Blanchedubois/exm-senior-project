"""
Phase 2 tests for rwtag.correct (no Qt). The first eight are the V1 suite, ported verbatim.

The optics functions are numeric inverses of real distortions, so we round-trip:
apply a known vignette / barrel distortion to a synthetic frame and confirm the
correction brings it back. Plus rotation round-trip and levels monotonicity.
"""
from __future__ import annotations
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rwtag import correct
from rwtag.types import CorrectionParams, LevelsParams


def _checker(h=240, w=320, sq=16):
    yy, xx = np.mgrid[0:h, 0:w]
    return (((xx // sq + yy // sq) % 2) * 200 + 30).astype(np.float32)


def test_apply_default_is_noop():
    img = _checker()
    out = correct.apply(img, CorrectionParams())
    assert np.allclose(out, img, atol=1e-4), "default apply() must be a no-op"


def test_vignette_roundtrip():
    img = _checker()
    p = CorrectionParams(vig_strength=0.6, vig_power=2.0)
    darkened = img * correct.vignette_mask(img.shape, p)        # simulate vignette
    restored = correct.correct_vignette(darkened, p)            # invert it
    m = img > 60                                                # ignore near-zero pixels
    rel = np.abs(restored[m] - img[m]) / img[m]
    assert np.median(rel) < 0.02, f"vignette not recovered (median rel err {np.median(rel):.3f})"


def test_distortion_roundtrip_center_stable():
    """The distortion centre pixel must be a fixed point of un-distortion."""
    img = _checker()
    p = CorrectionParams(k1=-0.12)
    out = correct.correct_distortion(img, p)
    h, w = img.shape
    assert abs(float(out[h // 2, w // 2]) - float(img[h // 2, w // 2])) < 5.0


def test_rotation_roundtrip():
    img = _checker()
    there = correct.rotate(img, 20.0)
    back = correct.rotate(there, -20.0)
    h, w = img.shape
    c = (slice(h // 4, 3 * h // 4), slice(w // 4, 3 * w // 4))   # interior avoids border fill
    diff = np.abs(back[c] - img[c])
    assert np.median(diff) < 5.0, f"rotation not invertible (median diff {np.median(diff):.2f})"


def test_levels_disabled_is_noop():
    img = _checker()
    assert np.allclose(correct.levels(img, LevelsParams(lv_enable=False)), img)


def test_levels_black_white_gamma():
    img = _checker()                                            # values in [30, 230]
    scale = correct._value_scale(img)                           # == 230 here
    p = LevelsParams(lv_enable=True, lv_black_mode="value",
                     lv_black=30.0 / scale, lv_white=230.0 / scale, lv_gamma=1.0)
    out = correct.levels(img, p)
    assert out.min() < 1.0, "black point should map to ~0"
    assert out.max() > scale - 1.0, "white point should map to ~full scale"
    # gamma < 1 lifts mid-tones (brighter), gamma > 1 darkens them
    mid = _checker() * 0 + 0.5 * scale
    lo = correct.levels(mid, LevelsParams(lv_enable=True, lv_black_mode="value",
                                          lv_black=0.0, lv_white=1.0, lv_gamma=0.5))
    hi = correct.levels(mid, LevelsParams(lv_enable=True, lv_black_mode="value",
                                          lv_black=0.0, lv_white=1.0, lv_gamma=2.0))
    assert lo.mean() > mid.mean() > hi.mean(), "gamma ordering wrong"


def test_lowpass_preserves_dc_and_shape():
    img = _checker()
    p = CorrectionParams(lp_enable=True, lp_cutoff=0.3, lp_shape="gaussian")
    out = correct.lowpass(img, p)
    assert out.shape == img.shape
    assert abs(out.mean() - img.mean()) < 1.0, "low-pass must preserve DC (mean)"
    assert out.std() < img.std(), "low-pass should reduce high-frequency contrast"


def test_process_equals_apply_then_levels():
    img = _checker()
    c = CorrectionParams(vig_strength=0.3, rotate_deg=5.0)
    lv = LevelsParams(lv_enable=True, lv_gamma=0.8)
    a = correct.levels(correct.apply(img, c), lv)
    b = correct.process(img, c, lv)
    assert np.allclose(a, b)


# ------------------------------------------------------------ point geometry (Phase 2)
def _params():
    return CorrectionParams(k1=-0.05, k2=-0.01, rotate_deg=7.0, dist_cx=0.47, dist_cy=0.53)


def test_inverse_geometric_roundtrip():
    rng = np.random.default_rng(0)
    shape = (2676, 2678)
    pts = rng.uniform(0, 2676, (5000, 2))
    for p in (_params(), CorrectionParams(k1=-0.12), CorrectionParams(rotate_deg=-33.5), CorrectionParams()):
        back = correct.inverse_geometric(correct.forward_geometric(pts, p, shape), p, shape)
        assert np.isfinite(back).all() and np.abs(back - pts).max() < 1e-3, p
        inv = correct.inverse_geometric(pts, p, shape)
        ok = np.isfinite(inv).all(1)
        fwd = correct.forward_geometric(inv[ok], p, shape)
        assert np.abs(fwd - pts[ok]).max() < 1e-3, p
        if p.k1 or p.k2:
            # NaN exactly where the corrected point lies beyond the lens model's range
            _r, rho_max = correct.lens_range(p.k1, p.k2)
            und = pts if not p.rotate_deg else (pts - correct._rot_affine(p, shape)[1]) @ np.linalg.inv(correct._rot_affine(p, shape)[0]).T
            c, f = correct._lens_frame(p, shape)
            beyond = np.hypot(*((und - c) / f).T) > rho_max
            assert (~ok == beyond).all() and beyond.any(), p
        else:
            assert ok.all()


def test_geometric_jacobians_match_finite_differences():
    rng = np.random.default_rng(1)
    shape = (2676, 2678); p = _params(); e = 1e-3
    pts = rng.uniform(100, 2500, (50, 2))
    for fn, jac in ((correct.forward_geometric, correct.forward_jacobian),
                    (correct.inverse_geometric, correct.inverse_jacobian)):
        J = jac(pts, p, shape)
        fd = np.stack([(fn(pts + [e, 0], p, shape) - fn(pts - [e, 0], p, shape)) / (2 * e),
                       (fn(pts + [0, e], p, shape) - fn(pts - [0, e], p, shape)) / (2 * e)], axis=2)
        assert np.abs(J - fd).max() < 1e-4, fn.__name__
    q = correct.forward_geometric(pts, p, shape)
    prod = np.einsum("nij,njk->nik", correct.inverse_jacobian(q, p, shape), correct.forward_jacobian(pts, p, shape))
    assert np.abs(prod - np.eye(2)).max() < 1e-9


def test_point_mapping_matches_image_correction():
    """A bright spot moved by correct.apply lands where forward_geometric says."""
    import cv2
    shape = (600, 800); p = CorrectionParams(k1=-0.08, k2=-0.02, rotate_deg=12.0)
    pts = np.array([[120.3, 90.7], [400.0, 300.0], [690.2, 510.6], [250.5, 450.1]])
    img = np.zeros(shape, np.float32)
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    for x, y in pts:
        img += np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 2.0 ** 2)).astype(np.float32) * 1000
    out = correct.apply(img, p)
    pred = correct.forward_geometric(pts, p, shape)
    for (px, py) in pred:
        x0, y0 = int(round(px)), int(round(py))
        win = out[y0 - 8:y0 + 9, x0 - 8:x0 + 9].astype(float)
        gy, gx = np.mgrid[-8:9, -8:9]
        cx = x0 + (win * gx).sum() / win.sum(); cy = y0 + (win * gy).sum() / win.sum()
        assert np.hypot(cx - px, cy - py) < 0.15, (px, py, cx, cy)


def test_propagate_cov_roundtrip():
    rng = np.random.default_rng(2)
    shape = (2676, 2678); p = _params()
    pts = rng.uniform(100, 2500, (20, 2))
    A = rng.normal(size=(20, 2, 2)); C = A @ np.transpose(A, (0, 2, 1)) + 0.01 * np.eye(2)
    q = correct.forward_geometric(pts, p, shape)
    Cq = correct.propagate_cov(C, correct.forward_jacobian(pts, p, shape))
    Cb = correct.propagate_cov(Cq, correct.inverse_jacobian(q, p, shape))
    assert np.abs(Cb - C).max() < 1e-6
