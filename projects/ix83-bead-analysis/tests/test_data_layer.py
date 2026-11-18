"""Phase 0 tests.  Run from the project folder:

    python3 -m unittest discover -s tests -v

Synthetic tests always run.  RealDataTests use the 16Oct26 folders and are
skipped when IX83_DATA_ROOT (default: ../../Experimentation/IX83 Data/16Oct26)
is missing.
"""

import json
import os
import tempfile
import unittest

import numpy as np
import tifffile

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.environ.get(
    "IX83_DATA_ROOT",
    os.path.join(HERE, "..", "..", "..", "Experimentation", "IX83 Data", "16Oct26"),
)

# Keep test caches out of the user's real cache.
_CACHE = tempfile.mkdtemp(prefix="ix83cache-")
os.environ["IX83_CACHE_DIR"] = _CACHE

from ix83viewer.core.corrections import subtract_dark  # noqa: E402
from ix83viewer.core.projection import frame_indices, project  # noqa: E402
from ix83viewer.io.mm_dataset import MMDataset  # noqa: E402
from ix83viewer.io.naming import parse_name  # noqa: E402
from ix83viewer.io.scan import group_by_position, scan_folder  # noqa: E402


def make_fake_acquisition(parent, name, stack, xyz=(0.0, 0.0, 0.0), prefix=None, intended=None,
                          objective="3-UPLFLN10X2PH", exposure=400.0, start="2026-10-16 17:00:00.000 -0400"):
    folder = os.path.join(parent, name)
    os.makedirs(folder)
    prefix = prefix or name
    tifffile.imwrite(os.path.join(folder, f"{prefix}_MMStack_Pos0.ome.tif"), stack)
    meta = {"Summary": {"Prefix": prefix, "StartTime": start,
                        "IntendedDimensions": {"time": intended or len(stack)}}}
    for t in range(len(stack)):
        meta[f"FrameKey-{t}-0-0"] = {
            "Exposure-ms": exposure, "ElapsedTime-ms": 400.0 * t, "Objective-Label": objective,
            "PixelSizeUm": 0.102, "XPositionUm": xyz[0], "YPositionUm": xyz[1], "ZPositionUm": xyz[2],
        }
    with open(os.path.join(folder, f"{prefix}_MMStack_Pos0_metadata.txt"), "w") as f:
        json.dump(meta, f)
    return folder


class NamingTests(unittest.TestCase):
    def test_full_name(self):
        n = parse_name("488-Sample1-3.0x-100cts-400ms_2")
        self.assertEqual((n.kind, n.wavelength_nm, n.sample, n.factor, n.counts, n.exposure_ms, n.rep),
                         ("sample", 488, "Sample1", 3.0, 100, 400.0, 2))

    def test_no_factor(self):
        n = parse_name("561-Sample1-100cts-150ms_1")
        self.assertEqual((n.wavelength_nm, n.factor, n.exposure_ms), (561, None, 150.0))

    def test_odd_factor(self):
        self.assertEqual(parse_name("488-Sample1-34.2x-100cts-400ms_1").factor, 34.2)

    def test_calibration(self):
        self.assertEqual(parse_name("DarkCount_1").kind, "dark")
        self.assertEqual(parse_name("Bead-Calibration_1").kind, "beads")
        self.assertEqual(parse_name("random folder").kind, "unknown")


class SyntheticDatasetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        rng = np.random.default_rng(0)
        self.stack = rng.integers(90, 2000, size=(6, 16, 20), dtype=np.uint16)

    def tearDown(self):
        self.tmp.cleanup()

    def test_open_and_frames(self):
        ds = MMDataset.open(make_fake_acquisition(self.tmp.name, "633-S-100cts-400ms_1", self.stack))
        self.assertEqual((ds.n_frames, ds.shape_yx, ds.wavelength_nm), (6, (16, 20), 633))
        np.testing.assert_array_equal(ds.frame(3), self.stack[3])
        np.testing.assert_array_equal(ds.frame(-1), self.stack[-1])
        self.assertAlmostEqual(ds.pixel_size_um, 1.1)
        self.assertEqual(ds.reported_pixel_size_um, 0.102)
        with self.assertRaises(IndexError):
            ds.frame(6)

    def test_folder_name_beats_prefix_and_truncation_flagged(self):
        folder = make_fake_acquisition(self.tmp.name, "633-S-100cts-400ms_2", self.stack,
                                       prefix="561-S-100cts-400ms_2", intended=100)
        ds = MMDataset.open(folder)
        self.assertEqual(ds.wavelength_nm, 633)
        text = " ".join(ds.warnings)
        self.assertIn("differs from folder name", text)
        self.assertIn("6 of 100", text)

    def test_projections(self):
        ds = MMDataset.open(make_fake_acquisition(self.tmp.name, "488-S-100cts-400ms_1", self.stack))
        s = self.stack.astype(np.float64)
        np.testing.assert_allclose(project(ds, "mean"), s.mean(0), rtol=1e-6)
        np.testing.assert_array_equal(project(ds, "max"), self.stack.max(0))
        np.testing.assert_array_equal(project(ds, "min"), self.stack.min(0))
        np.testing.assert_allclose(project(ds, "sum", 1, 4), s[1:4].sum(0), rtol=1e-6)
        np.testing.assert_allclose(project(ds, "median"), np.median(s, 0), rtol=1e-6)
        np.testing.assert_array_equal(project(ds, "frame", frame=2), self.stack[2])
        # second call comes from the cache and must match
        np.testing.assert_allclose(project(ds, "mean"), s.mean(0), rtol=1e-6)

    def test_frame_indices_subsample(self):
        self.assertEqual(frame_indices(10, 2, 5), [2, 3, 4])
        idx = frame_indices(1000, max_frames=100)
        self.assertEqual((len(idx), idx[0], idx[-1]), (100, 0, 999))
        with self.assertRaises(ValueError):
            frame_indices(5, 5)

    def test_subtract_dark(self):
        img = np.array([[100, 150], [90, 300]], np.uint16)
        dark = np.full((2, 2), 100, np.float32)
        np.testing.assert_array_equal(subtract_dark(img, dark), [[0, 50], [0, 200]])
        np.testing.assert_array_equal(subtract_dark(img, dark, clip=False), [[0, 50], [-10, 200]])

    def test_grouping(self):
        t, st = self.tmp.name, self.stack
        make_fake_acquisition(t, "488-S-100cts-400ms_1", st, (0, 0, 100), start="2026-10-16 10:00:00")
        make_fake_acquisition(t, "561-S-100cts-400ms_1", st, (0.5, -4.0, 110), start="2026-10-16 10:01:00")
        make_fake_acquisition(t, "633-S-100cts-400ms_1", st, (0, 0, 100), start="2026-10-16 10:02:00")
        make_fake_acquisition(t, "488-S-100cts-400ms_2", st, (0, 0, 300), start="2026-10-16 09:00:00")
        make_fake_acquisition(t, "561-S-100cts-400ms_2", st, (127, 0, 100), start="2026-10-16 11:00:00")
        make_fake_acquisition(t, "633-S-100cts-400ms_2", st, (0, 0, 100), objective="6-UPLSAPO100XO",
                              start="2026-10-16 12:00:00")
        sets = group_by_position(scan_folder(t).samples)
        got = [sorted(d.label for d in s.members) for s in sets]
        self.assertEqual(got, [
            ["488-S-100cts-400ms_2"],  # same XY, Z 200 um away
            ["488-S-100cts-400ms_1", "561-S-100cts-400ms_1", "633-S-100cts-400ms_1"],
            ["561-S-100cts-400ms_2"],  # 127 um away in X
            ["633-S-100cts-400ms_2"],  # different objective
        ])
        self.assertTrue(sets[1].is_complete)
        self.assertEqual([s.label for s in sets], ["A", "B", "C", "D"])


@unittest.skipUnless(os.path.isdir(DATA_ROOT), f"real data not found at {DATA_ROOT}")
class RealDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scan = scan_folder(DATA_ROOT)
        cls.by_label = {d.label: d for d in cls.scan.datasets}

    def test_everything_opens(self):
        self.assertEqual(self.scan.errors, {})
        self.assertEqual((len(self.scan.samples), len(self.scan.calibrations)), (16, 2))

    def test_frame_counts(self):
        expected = {
            "488-Sample1-100cts-150ms_1": 84, "488-Sample1-3.0x-100cts-400ms_1": 12,
            "561-Sample1-100cts-400ms_1": 24, "488-Sample1-34.2x-100cts-400ms_1": 2,
            "488-Sample1-4.2x-100cts-400ms_1": 50, "561-Sample1-100cts-400ms_2": 100,
            "DarkCount_1": 1000,
        }
        for label, n in expected.items():
            self.assertEqual(self.by_label[label].n_frames, n, label)

    def test_mislabelled_633_folder(self):
        ds = self.by_label["633-Sample1-3.0x-100cts-400ms_2"]
        self.assertEqual(ds.wavelength_nm, 633)
        self.assertTrue(any("differs from folder name" in w for w in ds.warnings))

    def test_per_frame_position_used(self):
        # Summary.StagePositions says Y=-1763.52; frames say -2233.3.
        self.assertAlmostEqual(self.by_label["488-Sample1-3.0x-100cts-400ms_1"].stage_xyz_um[1], -2233.3, 1)

    def test_fov_sets(self):
        sets = group_by_position(self.scan.samples)
        self.assertEqual(len(sets), 6)
        self.assertEqual(sum(s.is_complete for s in sets), 3)
        members = {frozenset(d.label for d in s.members) for s in sets}
        self.assertIn(frozenset({"488-Sample1-3.0x-100cts-400ms_2", "561-Sample1-3.0x-100cts-400ms_1",
                                 "633-Sample1-3.0x-100cts-400ms_2"}), members)
        self.assertIn(frozenset({"488-Sample1-4.2x-100cts-400ms_1", "561-Sample1-4.2x-100cts-500ms_1",
                                 "633-Sample1-4.2x-100cts-500ms_1"}), members)

    def test_projection_small_stack(self):
        ds = self.by_label["488-Sample1-34.2x-100cts-400ms_1"]
        mean = project(ds, "mean")
        expected = (ds.frame(0).astype(np.float64) + ds.frame(1)) / 2
        np.testing.assert_allclose(mean, expected, rtol=1e-6)

    def test_pixel_size(self):
        self.assertAlmostEqual(self.by_label["561-Sample1-100cts-400ms_2"].pixel_size_um, 1.1)
        self.assertAlmostEqual(self.scan.dark().pixel_size_um, 0.11)


if __name__ == "__main__":
    unittest.main()
