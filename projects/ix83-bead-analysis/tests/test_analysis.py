"""Phase 6: measurements."""

import os
import unittest

import numpy as np

from ix83viewer.core.analysis import (
    bleach_curve, clip_rect, clipping_overlay, colocalization, fit_bleaching, joint_histogram, line_profile,
    rect_mask, region_stats,
)

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.environ.get("IX83_DATA_ROOT",
                           os.path.join(HERE, "..", "..", "..", "Experimentation", "IX83 Data", "16Oct26"))


class ProfileTests(unittest.TestCase):
    def test_horizontal_ramp(self):
        img = np.tile(np.arange(10, dtype=np.float32), (5, 1))  # value = column
        d, v = line_profile(img, (0.5, 2.5), (9.5, 2.5))
        self.assertAlmostEqual(d[-1], 9.0)
        np.testing.assert_allclose(v, np.arange(10), atol=1e-5)  # pixel centres sample exactly

    def test_outside_is_nan(self):
        d, v = line_profile(np.ones((5, 5)), (2.5, 2.5), (20.5, 2.5))
        self.assertTrue(np.isnan(v[-1]))
        self.assertEqual(v[0], 1)


class StatsTests(unittest.TestCase):
    def test_region(self):
        img = np.zeros((20, 20), np.float32)
        img[5:10, 5:10] = 100
        raw = img.copy()
        raw[6, 6] = 65535
        s = region_stats(img, (5, 5, 5, 5), raw, pixel_size_um=1.1)
        self.assertEqual((s["pixels"], s["mean"], s["std"], s["saturated"]), (25, 100.0, 0.0, 1))
        self.assertAlmostEqual(s["area_um2"], 25 * 1.21)
        self.assertEqual(region_stats(img)["pixels"], 400)
        self.assertEqual(region_stats(img, (50, 50, 5, 5)), {})

    def test_clip_rect_and_mask(self):
        self.assertEqual(clip_rect((-3.2, 2.5, 10, 4), (8, 8)), (0, 3, 7, 4))
        # a fractional shift keeps the pixel count
        self.assertEqual(clip_rect((10.4, 10.6, 30, 30), (100, 100))[2:], (30, 30))
        self.assertIsNone(clip_rect((10, 10, 2, 2), (8, 8)))
        self.assertEqual(rect_mask((8, 8), (2, 2, 3, 3)).sum(), 9)


class BleachTests(unittest.TestCase):
    def test_recovers_time_constant(self):
        t = np.arange(100) * 0.4
        values = 300 * np.exp(-t / 12.0) + 500
        frames = [np.full((8, 8), v) for v in values]
        curve = bleach_curve(frames, (2, 2, 4, 4))
        np.testing.assert_allclose(curve, values)
        fit = fit_bleaching(t, curve + np.random.default_rng(0).normal(0, 1, 100))
        self.assertAlmostEqual(fit.tau_s, 12.0, delta=0.5)
        self.assertAlmostEqual(fit.half_life_s, 12.0 * np.log(2), delta=0.4)
        self.assertGreater(fit.r2, 0.99)

    def test_no_decay_no_fit(self):
        self.assertIsNone(fit_bleaching(np.arange(10.0), np.linspace(1, 2, 10)))
        self.assertIsNone(fit_bleaching(np.arange(10.0), np.linspace(100, 99, 10)))  # 1% drop


class ColocTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(1)
        self.a = rng.normal(100, 5, (100, 100))
        self.a[20:40, 20:40] += 500

    def test_identical_channels(self):
        c = colocalization(self.a, self.a)
        self.assertAlmostEqual(c.pearson, 1.0)
        self.assertAlmostEqual(c.manders_m1, 1.0)
        self.assertAlmostEqual(c.manders_m2, 1.0)

    def test_disjoint_channels(self):
        b = np.roll(self.a, 50, axis=1)  # bright square moved away
        c = colocalization(self.a, b)
        self.assertLess(c.pearson, 0)
        self.assertAlmostEqual(c.manders_m1, 0.0)
        self.assertAlmostEqual(c.manders_m2, 0.0)

    def test_mask_and_manual_thresholds(self):
        mask = rect_mask(self.a.shape, (0, 0, 50, 50))
        c = colocalization(self.a, self.a * 2, mask, threshold_a=300, threshold_b=600)
        self.assertEqual(c.pixels, 2500)
        self.assertEqual((c.threshold_a, c.threshold_b), (300, 600))
        h = joint_histogram(self.a, self.a, (0, 700), (0, 700), bins=32)
        self.assertEqual(h.shape, (32, 32))


class OverlayTests(unittest.TestCase):
    def test_colors(self):
        shown = np.array([[10, 500, 70000]], np.float32)
        raw = np.array([[10, 500, 65535]], np.uint16)
        o = clipping_overlay(shown, raw, (0, 400))
        self.assertEqual(o[0, 0, 3], 0)
        self.assertEqual(tuple(o[0, 1]), (255, 220, 0, 110))
        self.assertEqual(tuple(o[0, 2]), (255, 0, 255, 230))


@unittest.skipUnless(os.path.isdir(DATA_ROOT), "real data not found")
class RealBleachTests(unittest.TestCase):
    def test_488_bleaches_about_20_percent(self):
        from ix83viewer.io.mm_dataset import MMDataset
        ds = MMDataset.open(os.path.join(DATA_ROOT, "488-Sample1-100cts-400ms_1"))
        curve = bleach_curve(ds.iter_frames(range(0, 100, 11)))
        loss = 1 - curve[-1] / curve[0]
        self.assertGreater(loss, 0.1)
        self.assertLess(loss, 0.35)


@unittest.skipUnless(os.path.isdir(DATA_ROOT), "real data not found")
class RealChecksTests(unittest.TestCase):
    def test_findings_and_thumbnail(self):
        import tempfile
        from ix83viewer.core.checks import check_scan, make_thumbnail
        from ix83viewer.io.scan import scan_folder
        scan = scan_folder(DATA_ROOT)
        text = [f"{f.level}|{f.subject}|{f.message}" for f in check_scan(scan)]
        self.assertTrue(any("34.2" in t and "implausible" in t for t in text))
        self.assertTrue(any("633-Sample1-3.0x-100cts-400ms_2" in t and "prefix" in t for t in text))
        self.assertTrue(any("mixed exposures" in t and t.startswith("warning") for t in text))
        self.assertTrue(any("Bead images have no wavelength" in t for t in text))
        with tempfile.TemporaryDirectory() as d:
            from PIL import Image
            p = make_thumbnail(scan.samples[0], d, (0, 0, 1))
            with Image.open(p) as im:
                self.assertEqual(im.size[0], 176)
            self.assertEqual(make_thumbnail(scan.samples[0], d, (0, 0, 1)), p)  # cached


if __name__ == "__main__":
    unittest.main()
