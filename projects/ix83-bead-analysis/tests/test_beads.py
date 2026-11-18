"""Bead-in-gel naming, manifest validation and area-overlap detection (synthetic data only)."""

import json
import os
import tempfile
import unittest

import numpy as np
from scipy import ndimage as ndi

_CACHE = tempfile.mkdtemp(prefix="ix83cache-")
os.environ["IX83_CACHE_DIR"] = _CACHE

from test_data_layer import make_fake_acquisition  # noqa: E402

from ix83viewer.beads.experiment import best_nonzero_shift, check_experiment, load_experiment  # noqa: E402
from ix83viewer.beads.panels import export_panels, levels_for, load_area_images, representative  # noqa: E402
from ix83viewer.io.naming import parse_name  # noqa: E402
from ix83viewer.io.scan import scan_folder  # noqa: E402


def beads(n, size=300, seed=0):
    rng = np.random.default_rng(seed)
    img = np.zeros((size, size), np.float32)
    img[rng.integers(0, size, n), rng.integers(0, size, n)] = 5000
    return ndi.gaussian_filter(img, 2) + rng.normal(100, 1, (size, size)).astype(np.float32)


class NamingTests(unittest.TestCase):
    def test_gel_names(self):
        n = parse_name("NonHomogenizedBeadSamplea~11x_2")
        self.assertEqual((n.kind, n.sample, n.factor, n.rep, n.wavelength_nm, n.factor_is_nominal),
                         ("sample", "NonHomogenized", 11.0, 2, 561, True))
        n = parse_name("HomogenizedBeadSample1x_5")
        self.assertEqual((n.sample, n.factor, n.rep, n.factor_is_nominal), ("Homogenized", 1.0, 5, False))

    def test_laser_calibrations_stay_calibrations(self):
        self.assertEqual(parse_name("BeadSample200nmMai_1").kind, "beads")
        self.assertEqual(parse_name("BeadSample5um beads_1").kind, "beads")

    def test_older_names_unchanged(self):
        self.assertEqual(parse_name("488-Sample1-3.0x-100cts-400ms_2").factor, 3.0)
        self.assertFalse(parse_name("488-Sample1-3.0x-100cts-400ms_2").factor_is_nominal)


class OverlapTests(unittest.TestCase):
    def test_finds_true_shift(self):
        big = beads(400, 500)
        a, b = big[:300, :300], big[60:360, 80:380]
        r, shift = best_nonzero_shift(a, b)
        self.assertGreater(r, 0.9)
        self.assertAlmostEqual(shift, 100.0, delta=1.5)

    def test_unrelated_fields_do_not_match(self):
        r, _ = best_nonzero_shift(beads(200, seed=1), beads(200, seed=2))
        self.assertLess(r, 0.3)


class ManifestTests(unittest.TestCase):
    NAMES = {"H_1x": "HomogenizedBeadSample1x_%d", "H_11x": "HomogenizedBeadSamplea~11x_%d"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "data")
        os.makedirs(self.root)
        k = 0
        for pattern in self.NAMES.values():
            for rep in (1, 2, 3):
                k += 1
                stack = np.stack([beads(50, seed=k)] * 2).astype(np.uint16)
                make_fake_acquisition(self.root, pattern % rep, stack, xyz=(10000.0 * k, 0.0, 0.0), exposure=20.0)
        make_fake_acquisition(self.root, "DarkCount_1", np.full((2, 300, 300), 100, np.uint16), exposure=10.0)
        self.manifest = {
            "name": "test", "data_root": self.root, "dark_folder": "DarkCount_1", "wavelength_nm": 561,
            "laser_power_mw": 3.03, "bead": "2 um Nile Red", "nominal_expansion": 11,
            "conditions": [
                {"key": "H_1x", "label": "a", "preparation": "Homogenized", "factor": 1,
                 "areas": [self.NAMES["H_1x"] % r for r in (1, 2, 3)]},
                {"key": "H_11x", "label": "b", "preparation": "Homogenized", "factor": 11,
                 "areas": [self.NAMES["H_11x"] % r for r in (1, 2, 3)]},
            ],
            "excluded": {},
        }

    def check(self):
        path = os.path.join(self.tmp.name, "exp.json")
        with open(path, "w") as f:
            json.dump(self.manifest, f)
        return check_experiment(load_experiment(path), overlap=False)

    def test_expansion_basis_defaults_to_linear_and_is_checked(self):
        report = self.check()
        self.assertEqual(report.experiment.expansion_basis, "linear")
        self.assertEqual(report.experiment.area_factor(11), 121)
        self.manifest["expansion_basis"] = "volume"
        with self.assertRaises(ValueError):
            self.check()

    def test_good_manifest_passes(self):
        report = self.check()
        self.assertEqual(report.errors, [])
        self.assertEqual(len(report.rows), 6)
        self.assertTrue(all(p.expected_overlap == 0 for p in report.pairs))

    def test_unaccounted_folder_is_an_error(self):
        make_fake_acquisition(self.root, "Mystery_1", np.zeros((1, 300, 300), np.uint16))
        self.assertTrue(any("Mystery_1" in e for e in self.check().errors))

    def test_wrong_condition_is_an_error(self):
        c = self.manifest["conditions"]
        c[0]["areas"], c[1]["areas"] = c[1]["areas"], c[0]["areas"]
        self.assertTrue(any("does not match" in e for e in self.check().errors))

    def test_too_few_areas_is_an_error(self):
        removed = self.manifest["conditions"][0]["areas"].pop()
        self.manifest["excluded"][removed] = "test"
        self.assertTrue(any("need at least" in e for e in self.check().errors))

    def test_mixed_exposure_is_an_error(self):
        name = self.NAMES["H_1x"] % 1
        path = os.path.join(self.root, name, f"{name}_MMStack_Pos0_metadata.txt")
        with open(path) as f:
            meta = json.load(f)
        meta["FrameKey-0-0-0"]["Exposure-ms"] = 150.0
        with open(path, "w") as f:
            json.dump(meta, f)
        self.assertTrue(any("exposure" in e for e in self.check().errors))

    def test_scan_counts_gels_as_samples(self):
        self.assertEqual(len(scan_folder(self.root).samples), 6)



class PanelTests(unittest.TestCase):
    NAMES = ManifestTests.NAMES

    def setUp(self):
        ManifestTests.setUp(self)
        path = os.path.join(self.tmp.name, "exp.json")
        with open(path, "w") as f:
            json.dump(self.manifest, f)
        self.exp = load_experiment(path)

    def test_dark_subtracted_without_clipping(self):
        by_key = load_area_images(self.exp)
        a = by_key["H_1x"][0]
        raw = a.ds.frame(0).astype(np.float32)
        np.testing.assert_allclose(a.image, raw - 100, atol=1e-3)
        self.assertLess(a.image.min(), 0)  # read noise below the dark level is kept, not clipped to 0

    def test_representative_is_middle_brightness(self):
        areas = load_area_images(self.exp)["H_1x"]
        means = sorted(float(a.image.mean()) for a in areas)
        self.assertEqual(float(representative(areas).image.mean()), means[1])

    def test_levels_shared_across_images(self):
        lo, hi = levels_for([np.zeros((8, 8)), np.full((8, 8), 10.0)])
        self.assertLess(lo, 1)
        self.assertGreater(hi, 9)

    def test_export_writes_everything(self):
        out = os.path.join(self.tmp.name, "out")
        written = export_panels(self.exp, out)
        names = {os.path.relpath(p, out) for p in written}
        for expected in ("row_H_1x.png", "row_H_11x.png", "comparison_2x2_shared.png",
                         "comparison_2x2_own.png", "all_areas.png", "panels.json"):
            self.assertIn(expected, names)
        self.assertEqual(sum(n.startswith("images/") for n in names), 6)
        with open(os.path.join(out, "panels.json")) as f:
            self.assertEqual(len(json.load(f)["areas"]), 6)


if __name__ == "__main__":
    unittest.main()
