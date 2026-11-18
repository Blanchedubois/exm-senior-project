"""Reference-bead measurement (synthetic beads with known light) and an offscreen run of the window."""

import json
import os
import tempfile
import unittest

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ix83viewer.beads.refbeads import (  # noqa: E402
    BeadPick, RefStore, measure, snap_to_peak, suggest_radius, summarise,
)


def gaussian_bead(shape=(200, 200), x=100.0, y=100.0, light=50_000.0, sigma=3.0, bg=40.0):
    yy, xx = np.indices(shape)
    g = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma ** 2))
    return (bg + light * g / g.sum()).astype(np.float32)


class MeasureTests(unittest.TestCase):
    def test_recovers_known_light_over_background(self):
        img = gaussian_bead()
        r = suggest_radius(img, 100, 100)
        m = measure(img, BeadPick(100, 100, r))
        self.assertAlmostEqual(m.light, 50_000, delta=500)
        self.assertAlmostEqual(m.background, 40, delta=0.5)
        self.assertEqual(m.flags, ())

    def test_radius_covers_the_wings(self):
        r = suggest_radius(gaussian_bead(sigma=5.0), 100, 100)
        self.assertGreaterEqual(r, 12)  # a 5 px sigma bead still has light at 2.5 sigma

    def test_snap_finds_peak(self):
        self.assertEqual(snap_to_peak(gaussian_bead(x=103, y=97), 100, 100), (103.0, 97.0))

    def test_neighbour_in_ring_is_flagged(self):
        img = gaussian_bead() + gaussian_bead(x=116, y=100, bg=0)
        self.assertIn("crowded", measure(img, BeadPick(100, 100, 8)).flags)

    def test_edge_saturation_and_offcentre_flags(self):
        img = gaussian_bead(x=5, y=5)
        sat = np.zeros_like(img, bool)
        sat[5, 5] = True
        flags = measure(img, BeadPick(5, 5, 8), sat).flags
        for f in ("edge", "saturated", "off-centre"):
            self.assertIn(f, flags)

    def test_summary_leaves_out_flagged(self):
        good = measure(gaussian_bead(light=1000), BeadPick(100, 100, 12))
        other = measure(gaussian_bead(light=3000), BeadPick(100, 100, 12))
        bad = measure(gaussian_bead(x=5, y=5), BeadPick(5, 5, 8))
        s = summarise({"a": [good, bad], "b": [other]}, {"a": "H_1x", "b": "H_1x"})
        self.assertEqual(s["H_1x"].n_beads, 2)
        self.assertEqual(s["H_1x"].n_areas, 2)
        self.assertAlmostEqual(s["all"].mean_light, (good.light + other.light) / 2)

    def test_store_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "refs.json")
            store = RefStore(path, "exp")
            store.add("A_1", BeadPick(10, 20, 8))
            store.save()
            self.assertEqual(RefStore.load(path).picks["A_1"], [BeadPick(10, 20, 8)])


class WindowTests(unittest.TestCase):
    def test_add_move_remove_and_autosave(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication

        from ix83viewer.beads.experiment import Condition, Experiment
        from ix83viewer.beads.panels import AreaImage
        from ix83viewer.beads.refbeads_window import RefBeadWindow

        class FakeName:
            rep = 1

        class FakeDs:
            label, n_frames, exposure_ms, name = "H1x_1", 50, 20.0, FakeName()

        app = QApplication.instance() or QApplication([])
        cond = Condition("H_1x", "Homogenized, 1×", "Homogenized", 1, ("H1x_1",))
        exp = Experiment("t", "/nowhere", "Dark", 561, 3.03, "2 um", 11, (cond,), {})
        img = gaussian_bead(shape=(300, 300), x=150, y=150) + gaussian_bead(shape=(300, 300), x=60, y=200, bg=0)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "refs.json")
            win = RefBeadWindow(exp, {"H_1x": [AreaImage(cond, FakeDs(), img, 0)]}, RefStore(path, "t"))
            m = win.add_bead_at(152, 148)  # click near, not on, the peak
            self.assertEqual((m.pick.x, m.pick.y), (150.0, 150.0))
            win.add_bead_at(60, 200)
            win.move_bead(1, 60, 200, 10)
            self.assertEqual(win.store.picks["H1x_1"][1].r, 10)
            win.remove_bead(0)
            with open(path) as f:
                saved = json.load(f)
            self.assertEqual(len(saved["areas"]["H1x_1"]), 1)
            self.assertIn("light", saved["areas"]["H1x_1"][0])
            self.assertEqual(saved["summary"]["H_1x"]["n_beads"], 1)
            self.assertEqual(win.table.rowCount(), 1)
            # a real mouse click on the image adds a bead once the event has finished
            from PySide6.QtCore import QPointF
            from PySide6.QtTest import QTest

            win.resize(1200, 800)
            win.show()
            QTest.qWait(100)
            spot = win.glw.mapFromScene(win.vb.mapViewToScene(QPointF(150, 150)))
            QTest.mouseClick(win.glw.viewport(), Qt.LeftButton, Qt.NoModifier, spot)
            QTest.qWait(100)
            self.assertEqual(len(win.store.picks["H1x_1"]), 2)
            QTest.mouseClick(win.glw.viewport(), Qt.LeftButton, Qt.NoModifier, spot)  # on a circle: selects
            QTest.qWait(100)
            self.assertEqual(len(win.store.picks["H1x_1"]), 2)
            win.close()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
