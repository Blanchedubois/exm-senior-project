"""
Headless tests for rwtag.correct (no Qt / no display needed).

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


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fails = 0
    for fn in fns:
        try:
            fn(); print(f"  PASS  {fn.__name__}")
        except AssertionError as e:
            fails += 1; print(f"  FAIL  {fn.__name__}: {e}")
        except Exception as e:
            fails += 1; print(f"  ERR   {fn.__name__}: {e!r}")
    print(f"\n{len(fns) - fails}/{len(fns)} passed")
    sys.exit(1 if fails else 0)
