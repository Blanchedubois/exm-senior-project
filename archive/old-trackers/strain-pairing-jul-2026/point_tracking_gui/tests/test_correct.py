"""
Validate Stage-1 correction against the simulator's ground truth.

The strongest end-to-end check: correct a synthetic frame with the SAME optics
the simulator applied, then run a PLAIN ArUco detector (no flat-field, no
un-distort in the decoder). If Stage 1 truly undid the optics, the tags decode.
"""
import numpy as np
import cv2
import cv2.aruco as aruco

from gridtrack import io, correct
from gridtrack.types import CorrectionParams, LevelsParams


def _detect_count(img_float):
    u8 = io.to_uint8(img_float)
    inv = 255 - u8                                   # fluorescence -> dark tags on light
    inv = cv2.createCLAHE(2.0, (8, 8)).apply(inv)
    det = aruco.ArucoDetector(aruco.getPredefinedDictionary(aruco.DICT_6X6_1000),
                              aruco.DetectorParameters())
    _, ids, _ = det.detectMarkers(inv)
    return 0 if ids is None else len(ids)


def test_vignette_flattens_a_synthetic_field():
    h = w = 400
    p = CorrectionParams(vig_strength=0.7, vig_power=2.0)
    flat = np.full((h, w), 200.0, np.float32)
    vig = flat * correct.vignette_mask((h, w), p)    # simulate vignetting
    corr = correct.correct_vignette(vig, p)
    # corners should be back near the centre value
    assert abs(corr[0, 0] - corr[h // 2, w // 2]) < 2.0


def _forward_distort(img, k1, k2):
    """Same radial model the simulator applies: destination pixel at radius r
    samples the source at r*(1 + k1 r^2 + k2 r^4)."""
    h, w = img.shape
    cx, cy, fnorm = (w - 1) / 2.0, (h - 1) / 2.0, w / 2.0
    xs, ys = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    nx, ny = (xs - cx) / fnorm, (ys - cy) / fnorm
    factor = 1.0 + k1 * (nx * nx + ny * ny) + k2 * (nx * nx + ny * ny) ** 2
    mapx = (cx + nx * factor * fnorm).astype(np.float32)
    mapy = (cy + ny * factor * fnorm).astype(np.float32)
    return cv2.remap(img, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def test_distortion_correction_inverts_the_forward_model():
    # forward-distort a grid with barrel k, then correct with the SAME k -> recover
    h = w = 400
    img = np.zeros((h, w), np.float32)
    img[::20, :] = 255; img[:, ::20] = 255
    k1, k2 = -0.08, -0.01
    dist = _forward_distort(img, k1, k2)
    back = correct.correct_distortion(dist, CorrectionParams(k1=k1, k2=k2))
    c = slice(60, 340)                               # ignore border-replicate edges
    assert np.corrcoef(img[c, c].ravel(), back[c, c].ravel())[0, 1] > 0.9


# ------------------------------------------------------------ FFT low-pass
def _grating(h, w, cycles_per_px, axis=1):
    """A cosine grating at a given spatial frequency (cycles/pixel)."""
    n = np.arange(w if axis == 1 else h, dtype=np.float32)
    line = 128.0 + 100.0 * np.cos(2 * np.pi * cycles_per_px * n)
    return np.tile(line, (h, 1)) if axis == 1 else np.tile(line[:, None], (1, w))


def test_lowpass_disabled_is_identity():
    img = _grating(200, 200, 0.3).astype(np.float32)
    out = correct.lowpass(img, CorrectionParams(lp_enable=False))
    assert np.allclose(out, img)                      # no-op when off


def test_lowpass_preserves_dc_and_low_frequencies():
    img = np.full((256, 256), 123.0, np.float32)
    for shape in ("gaussian", "butterworth", "ideal"):
        out = correct.lowpass(img, CorrectionParams(lp_enable=True, lp_cutoff=0.3,
                                                    lp_shape=shape))
        assert abs(out.mean() - 123.0) < 1e-2         # DC gain == 1
    # a below-cutoff grating passes ~unchanged (Gaussian)
    low = _grating(256, 256, 0.05)                    # 0.05 cyc/px = 0.1 of Nyquist
    kept = correct.lowpass(low, CorrectionParams(lp_enable=True, lp_cutoff=0.5))
    c = slice(40, 216)
    amp_in = low[c, c].std(); amp_out = kept[c, c].std()
    assert amp_out > 0.85 * amp_in


def test_lowpass_attenuates_high_frequencies():
    # a grating well above the cut-off should be strongly suppressed
    high = _grating(256, 256, 0.4)                     # 0.4 cyc/px = 0.8 of Nyquist
    for shape in ("gaussian", "butterworth", "ideal"):
        out = correct.lowpass(high, CorrectionParams(lp_enable=True, lp_cutoff=0.2,
                                                     lp_shape=shape))
        c = slice(40, 216)
        assert out[c, c].std() < 0.2 * high[c, c].std()


def test_lowpass_mask_is_monotone_decreasing():
    for shape in ("gaussian", "butterworth", "ideal"):
        H = correct._lowpass_mask((128, 128), CorrectionParams(lp_cutoff=0.3, lp_shape=shape))
        Hs = np.fft.fftshift(H)
        mid = Hs[64, 64:]                             # DC outward along +x
        assert Hs[64, 64] >= Hs.max() - 1e-6          # peak at DC
        assert np.all(np.diff(mid) <= 1e-6)           # never increases outward


def test_apply_with_lowpass_off_matches_no_lowpass():
    from gridtrack import io
    img = _grating(200, 200, 0.3)
    base = CorrectionParams(vig_strength=0.4, k1=-0.03)
    with_off = correct.apply(img, base)               # lp_enable defaults False
    manual = correct.correct_distortion(correct.correct_vignette(img, base), base)
    assert np.allclose(with_off, manual)


# ------------------------------------------------------------ contrast / levels
def _field_with_disks(bg=14.0, sigma=4.0, peak=200.0, seed=0):
    rng = np.random.default_rng(seed)
    img = bg + rng.normal(0, sigma, (200, 200)).astype(np.float32)   # noisy dark field
    yy, xx = np.ogrid[:200, :200]
    for cy, cx in ((60, 60), (140, 150), (100, 40)):                 # a few bright disks
        img[(yy - cy) ** 2 + (xx - cx) ** 2 <= 36] = peak
    return img


def test_levels_disabled_is_identity():
    img = _field_with_disks()
    assert np.allclose(correct.levels(img, LevelsParams(lv_enable=False)), img)


def test_levels_auto_drops_noise_floor_to_black():
    img = _field_with_disks()
    p = LevelsParams(lv_enable=True, lv_black_mode="auto", lv_black_k=3.0)
    out = correct.levels(img, p)
    disk = (slice(54, 66), slice(54, 66))
    assert out.min() == 0.0                                  # floor cut to black
    # the vast majority of the dark field is now exactly 0
    assert (out == 0).mean() > 0.9
    # bright disks survive (still bright after the floor cut + stretch)
    assert out[disk].max() > 150.0


def test_levels_stretch_increases_contrast():
    # a low-contrast band [100,140] mapped with black=100/255, white=140/255 -> full range
    band = np.linspace(100, 140, 256, dtype=np.float32)[None, :].repeat(64, 0)
    p = LevelsParams(lv_enable=True, lv_black_mode="value",
                     lv_black=100 / 255.0, lv_white=140 / 255.0)
    out = correct.levels(band, p)
    assert out.max() > 250.0 and out.min() < 5.0             # spans ~full 8-bit range
    assert out.std() > 4 * band.std()                        # contrast strongly increased


def test_levels_auto_black_scales_with_noise():
    lo = correct.resolve_black_level(_field_with_disks(sigma=3.0),
                                     LevelsParams(lv_black_mode="auto", lv_black_k=3.0))
    hi = correct.resolve_black_level(_field_with_disks(sigma=9.0),
                                     LevelsParams(lv_black_mode="auto", lv_black_k=3.0))
    assert hi > lo                                           # noisier field -> higher floor


def test_levels_gamma_monotone():
    band = np.linspace(0, 255, 256, dtype=np.float32)[None, :].repeat(8, 0)
    base = LevelsParams(lv_enable=True, lv_black_mode="value", lv_black=0.0, lv_white=1.0)
    lift = correct.levels(band, LevelsParams(**{**base.to_dict(), "lv_gamma": 0.5}))
    drop = correct.levels(band, LevelsParams(**{**base.to_dict(), "lv_gamma": 2.0}))
    mid = 128
    assert lift[0, mid] > band[0, mid] > drop[0, mid]        # gamma<1 lifts, >1 lowers mids
    assert abs(lift[0, 0]) < 1 and abs(drop[0, 0]) < 1       # endpoints fixed at 0
    assert lift[0, -1] > 250 and drop[0, -1] > 250           # and at full scale


def test_end_to_end_correction_enables_plain_decode(sim_frame_path, sim_optics):
    raw = io.load_tiff(sim_frame_path)
    before = _detect_count(raw)                      # uncorrected: optics hurt decode
    p = CorrectionParams(**sim_optics)
    corrected = correct.apply(raw, p)
    after = _detect_count(corrected)
    print(f"decoded before={before}  after={after}")
    assert after >= 24                               # ~all 25 in-frame tags recover
    assert after >= before
