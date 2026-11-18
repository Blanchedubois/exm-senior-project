"""Phase 4: processing, brightness/contrast maths, settings persistence."""

import os
import tempfile
import unittest

import numpy as np
from scipy import ndimage

from ix83viewer.core.adjust import (
    ChannelSettings, bc_from_levels, gamma_to_slider, levels_from_bc, slider_to_gamma, tone_curve,
)
from ix83viewer.core.processing import Processing, apply_processing, background_image
from ix83viewer.core.settings_store import LevelStore, SettingsStore


class ProcessingTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(0)
        self.img = (300 + rng.normal(0, 5, (200, 200))).astype(np.float32)
        self.img[90:110, 90:110] += 1000  # one bright "cell"

    def test_identity_returns_input(self):
        self.assertIs(apply_processing(self.img, Processing()), self.img)

    def test_percentile_background(self):
        out = apply_processing(self.img, Processing(background="percentile", bg_param=50))
        self.assertAlmostEqual(float(np.median(out[:50, :50])), 0, delta=5)
        self.assertGreater(out[100, 100], 900)
        self.assertGreaterEqual(out.min(), 0)

    def test_region_background(self):
        p = Processing(background="region", roi=(0, 0, 40, 40))
        self.assertAlmostEqual(background_image(self.img, p), 300, delta=2)
        self.assertEqual(background_image(self.img, Processing(background="region")), 0.0)

    def test_rolling_ball_removes_gradient_keeps_cell(self):
        yy, xx = np.mgrid[0:200, 0:200]
        img = self.img + xx * 2.0  # illumination ramp 0..400
        out = apply_processing(img.astype(np.float32), Processing(background="rolling_ball", bg_param=40))
        self.assertLess(abs(float(out[20, 180]) - float(out[20, 20])), 40)  # ramp gone
        self.assertGreater(out[100, 100], 700)  # cell kept

    def test_dark_then_denoise(self):
        dark = np.full_like(self.img, 100)
        out = apply_processing(self.img, Processing(dark=True, denoise="median", denoise_param=3), dark)
        self.assertAlmostEqual(float(np.median(out[:50, :50])), 200, delta=3)
        self.assertLess(out[:50, :50].std(), self.img[:50, :50].std())
        g = apply_processing(self.img, Processing(denoise="gaussian", denoise_param=2))
        np.testing.assert_allclose(g, ndimage.gaussian_filter(self.img, 2), rtol=1e-5)

    def test_key_and_roundtrip(self):
        p = Processing(dark=True, background="rolling_ball", bg_param=50, denoise="median", denoise_param=3)
        self.assertEqual(p.key(), "dark+bg=rolling_ball50+dn=median3")
        self.assertEqual(Processing().key(), "raw")
        q = Processing(background="region", roi=(1, 2, 3, 4))
        self.assertEqual(Processing.from_dict(q.to_dict()), q)


class AdjustMathTests(unittest.TestCase):
    def test_bc_roundtrip(self):
        rng = (100.0, 5100.0)
        for levels in [(100, 5100), (600, 1600), (2000, 2100), (-500, 9000)]:
            b, c = bc_from_levels(levels, rng)
            lo, hi = levels_from_bc(b, c, rng)
            self.assertAlmostEqual(lo, levels[0], delta=1e-6 * 5000 + 1e-6)
            self.assertAlmostEqual(hi, levels[1], delta=1e-6 * 5000 + 1e-6)
        self.assertEqual(bc_from_levels(rng, rng), (0.0, 0.0))
        b, _ = bc_from_levels((100, 1100), rng)  # window low in range -> bright image
        self.assertGreater(b, 0)

    def test_tone_curve_and_gamma_slider(self):
        t = np.array([0, 0.25, 1.0])
        np.testing.assert_allclose(tone_curve(t, 2.0), [0, 0.0625, 1])
        np.testing.assert_allclose(tone_curve(t, 1.0, invert=True), [1, 0.75, 0])
        self.assertEqual(gamma_to_slider(1.0), 0)
        self.assertAlmostEqual(slider_to_gamma(100), 5.0)
        self.assertAlmostEqual(slider_to_gamma(-100), 0.2)
        self.assertEqual(gamma_to_slider(slider_to_gamma(37)), 37)


class _Ds:
    def __init__(self, folder):
        self.folder = folder


class SettingsStoreTests(unittest.TestCase):
    def test_persistence_and_presets(self):
        with tempfile.TemporaryDirectory() as d:
            s = SettingsStore(d)
            ds = _Ds("/data/633_1")
            cs = ChannelSettings(Processing(background="percentile", bg_param=5), gamma=0.7, color=(1, 0, 1))
            s.set(ds, cs)
            s.levels[LevelStore.key(ds, "Mean", cs.processing)] = (0.0, 250.0)
            s.save()
            s2 = SettingsStore(d)
            self.assertEqual(s2.get(ds), cs)
            self.assertEqual(s2.levels[LevelStore.key(ds, "Mean", cs.processing)], (0.0, 250.0))
            self.assertEqual(s2.get(_Ds("/other")), ChannelSettings())
            s2.set(ds, ChannelSettings())  # default settings are not stored
            self.assertNotIn(ds.folder, s2.channels)

            s2.save_preset("Nice / 633", {"633": {"settings": cs, "levels": {"Mean": (0, 250)}}})
            self.assertEqual(s2.list_presets(), ["Nice _ 633"])
            loaded = s2.load_preset("Nice / 633")
            self.assertEqual(loaded["633"]["settings"], cs)
            self.assertEqual(loaded["633"]["levels"]["Mean"], (0, 250))
            s2.delete_preset("Nice / 633")
            self.assertEqual(s2.list_presets(), [])


if __name__ == "__main__":
    unittest.main()
