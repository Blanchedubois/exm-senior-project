"""Phase 3: shift estimation, shifting, offset storage."""

import os
import tempfile
import unittest

import numpy as np
from scipy import ndimage

from ix83viewer.core.composite import Layer, composite
from ix83viewer.core.offsets import Offset, OffsetStore
from ix83viewer.core.registration import MAX_SHIFT_PX, ShiftEstimate, apply_shift, estimate_shift

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.environ.get("IX83_DATA_ROOT",
                           os.path.join(HERE, "..", "..", "..", "Experimentation", "IX83 Data", "16Oct26"))


def blobs(shape=(600, 600), seed=1):
    """Dense random texture at roughly cell scale, plus camera-like noise."""
    rng = np.random.default_rng(seed)
    tex = ndimage.gaussian_filter(rng.normal(0, 1, shape), 4).astype(np.float32)
    return 500 + 4000 * tex + rng.normal(0, 5, shape).astype(np.float32)


class ShiftTests(unittest.TestCase):
    def test_recovers_subpixel_shift(self):
        ref = blobs()
        for dy, dx in [(3.3, -1.7), (0.4, 0.6), (-8.0, 5.0)]:
            moving = ndimage.shift(ref, (dy, dx), order=3, mode="nearest")
            e = estimate_shift(ref, moving)
            # The correction is the opposite of the applied displacement.
            self.assertAlmostEqual(e.dy, -dy, delta=0.15)
            self.assertAlmostEqual(e.dx, -dx, delta=0.15)
            self.assertTrue(e.reliable, e)

    def test_unrelated_images_are_uncertain(self):
        e = estimate_shift(blobs(seed=1), blobs(seed=2))
        self.assertFalse(e.reliable, e)

    def test_reliability_rules(self):
        self.assertFalse(ShiftEstimate(MAX_SHIFT_PX + 1, 0, 500).reliable)
        self.assertFalse(ShiftEstimate(1, 1, 5).reliable)
        self.assertTrue(ShiftEstimate(1, 1, 50).reliable)

    def test_apply_shift(self):
        img = np.arange(25, dtype=np.float32).reshape(5, 5)
        out = apply_shift(img, 1, -2)
        self.assertEqual(out[1, 0], img[0, 2])
        self.assertEqual(out[0].sum(), 0)
        self.assertIs(apply_shift(img, 0, 0), img)
        np.testing.assert_allclose(apply_shift(img, 0.5, 0)[2, 2], (img[1, 2] + img[2, 2]) / 2)
        self.assertEqual(apply_shift(img, 9, 0).sum(), 0)
        rgb = np.ones((4, 4, 3), np.float32)
        self.assertEqual(apply_shift(rgb, 0.5, 0.5).shape, (4, 4, 3))

    def test_composite_applies_offset(self):
        a = np.zeros((5, 5), np.float32)
        a[2, 2] = 1
        rgb = composite([Layer(a, (0, 1), (1, 0, 0), offset=(1, 1))])
        self.assertEqual(rgb[3, 3, 0], 1)
        self.assertEqual(rgb[2, 2, 0], 0)


class _FakeDs:
    def __init__(self, folder, wl, objective="10X"):
        self.folder, self.wavelength_nm, self.objective = folder, wl, objective


class OffsetStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "offsets.json")
        self.ref, self.mov = _FakeDs("/a/561", 561), _FakeDs("/a/488", 488)

    def tearDown(self):
        self.tmp.cleanup()

    def test_lookup_order_and_persistence(self):
        s = OffsetStore(self.path)
        self.assertTrue(s.get(self.mov, self.ref).is_zero)
        s.save_calibration(_FakeDs("/b/488", 488), _FakeDs("/b/561", 561), Offset(1.0, 2.0, "auto", 80))
        cal = s.get(self.mov, self.ref)
        self.assertEqual((cal.dy, cal.dx, cal.source), (1.0, 2.0, "calibration"))
        self.assertIsNone(s.calibration_for(_FakeDs("/c/488", 488, "100X"), self.ref))
        s.set(self.mov, self.ref, Offset(3.0, 4.0, "auto", 50), is_auto_result=True)
        s.set(self.mov, self.ref, Offset(3.5, 4.0, "manual"))
        s2 = OffsetStore(self.path)  # reload from disk
        self.assertEqual(s2.get(self.mov, self.ref), Offset(3.5, 4.0, "manual"))
        self.assertEqual(s2.auto_result(self.mov, self.ref), Offset(3.0, 4.0, "auto", 50))
        # reverse direction is the negated pair offset
        rev = s2.get(self.ref, self.mov)
        self.assertEqual((rev.dy, rev.dx, rev.source), (-3.5, -4.0, "manual"))
        s2.clear(self.mov, self.ref)
        self.assertEqual(s2.get(self.mov, self.ref).source, "calibration")
        rev_cal = s2.get(self.ref, self.mov)
        self.assertEqual((rev_cal.dy, rev_cal.dx, rev_cal.source), (-1.0, -2.0, "calibration"))
        self.assertTrue(s2.get(self.ref, self.ref).is_zero)


@unittest.skipUnless(os.path.isdir(DATA_ROOT), "real data not found")
class RealAlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("IX83_CACHE_DIR", tempfile.mkdtemp(prefix="ix83cache-"))
        from ix83viewer.core.projection import project
        from ix83viewer.io.mm_dataset import MMDataset
        cls.mean = {}
        for name in ("561-Sample1-100cts-150ms_1", "488-Sample1-100cts-150ms_2",
                     "561-Sample1-100cts-400ms_2", "561-Sample1-3.0x-100cts-400ms_1",
                     "488-Sample1-3.0x-100cts-400ms_2"):
            cls.mean[name] = project(MMDataset.open(os.path.join(DATA_ROOT, name)), "mean")

    def test_set_a_488_to_561_is_reliable_and_near_zero(self):
        e = estimate_shift(self.mean["561-Sample1-100cts-150ms_1"], self.mean["488-Sample1-100cts-150ms_2"])
        self.assertTrue(e.reliable, e)
        self.assertLess(abs(e.dy) + abs(e.dx), 1.0)

    def test_different_fields_of_view_are_not_reliable(self):
        e = estimate_shift(self.mean["561-Sample1-100cts-400ms_2"], self.mean["561-Sample1-3.0x-100cts-400ms_1"])
        self.assertFalse(e.reliable, e)

    def test_weak_cross_channel_pair_is_flagged(self):
        # 3.0x set: 488 cytoplasm vs 561 nuclei share too little structure.
        e = estimate_shift(self.mean["561-Sample1-3.0x-100cts-400ms_1"], self.mean["488-Sample1-3.0x-100cts-400ms_2"])
        self.assertFalse(e.reliable, e)


if __name__ == "__main__":
    unittest.main()
