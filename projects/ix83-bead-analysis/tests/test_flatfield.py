"""Illumination map and bead check on synthetic fields with a known fall-off."""

import os
import tempfile
import unittest

import numpy as np
from scipy import ndimage as ndi

from ix83viewer.beads.flatfield import MIN_ILLUMINATION, bead_check, estimate, fit_gamma, save
from ix83viewer.beads.refbeads import BeadPick, measure, summarise

SIZE = 400


def illumination(size=SIZE, sigma=0.3):  # corners ~7%, like the real field
    yy, xx = np.indices((size, size))
    r = np.hypot(xx - size * 0.48, yy - size * 0.52) / size
    return np.exp(-r ** 2 / (2 * sigma ** 2))


def field(seed, light=20_000.0, n=40):
    rng = np.random.default_rng(seed)
    illum = illumination()
    beads = np.zeros((SIZE, SIZE))
    ys, xs = rng.integers(10, SIZE - 10, n), rng.integers(10, SIZE - 10, n)
    beads[ys, xs] = light
    beads = ndi.gaussian_filter(beads, 2.0)
    glow = 30 * (1 + 0.1 * rng.standard_normal())  # areas differ a little in gel glow
    img = illum * (glow + beads) + rng.normal(0, 1, (SIZE, SIZE))
    return img.astype(np.float32), list(zip(xs, ys))


class FlatFieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fields = [field(s) for s in range(8)]
        cls.ff = estimate({f"a{i}": f[0] for i, f in enumerate(cls.fields)})

    def test_recovers_known_falloff(self):
        truth = illumination() / illumination().max()
        lit = truth > 0.3
        err = np.abs(self.ff.flat[lit] - truth[lit])
        self.assertLess(float(np.median(err)), 0.05)
        self.assertLess(abs(self.ff.centre_xy[0] - SIZE * 0.48), 15)

    def test_peak_is_one_and_dim_region_marked(self):
        self.assertAlmostEqual(float(self.ff.flat.max()), 1.0, places=5)
        self.assertTrue((~self.ff.usable()).any())
        self.assertTrue((self.ff.flat[~self.ff.usable()] < MIN_ILLUMINATION).all())

    def _beads(self, power=1.0):
        """Beads whose light follows the true illumination ** power, measured against the true map."""
        rng = np.random.default_rng(5)
        truth = illumination() / illumination().max()
        out = []
        for i in range(60):
            x, y = rng.integers(20, SIZE - 20, 2)
            light = 1e5 * truth[y, x] ** power * np.exp(0.15 * rng.standard_normal())
            out.append({"condition": "H_1x" if i % 2 else "NH_1x", "light": light * (3 if i % 2 else 1),
                        "base_illumination": float(truth[y, x])})  # tests the fit itself, not the map
        return out

    def test_fit_gamma_recovers_power(self):
        for power in (1.0, 1.6):
            g, ci, n = fit_gamma(self._beads(power))
            self.assertEqual(n, 60)
            self.assertAlmostEqual(g, power, delta=0.15)
            self.assertLess(ci[0], g)
            self.assertGreater(ci[1], g)

    def test_bead_check_trend_gone_after_calibration(self):
        beads = self._beads(1.6)
        g, _, _ = fit_gamma(beads)
        with tempfile.TemporaryDirectory() as d:
            res = bead_check(beads, g, os.path.join(d, "check.png"))
            self.assertTrue(os.path.exists(res["plot"]))
        v = list(res["versions"].values())
        self.assertGreater(v[0]["spearman"], 0.8)  # raw: dim beads look dim
        self.assertGreater(v[1]["spearman"], 0.3)  # glow map alone under-corrects a steeper fall-off
        self.assertLess(abs(v[2]["spearman"]), 0.3)
        self.assertLess(v[2]["cv"], v[0]["cv"])

    def test_gamma_applies_to_map(self):
        ff2 = self.ff.with_gamma(2.0)
        self.assertAlmostEqual(ff2.at(100, 120), self.ff.base_at(100, 120) ** 2, places=5)
        self.assertGreater(float((~ff2.usable()).mean()), float((~self.ff.usable()).mean()))

    def test_measure_flags_dim_light_and_summary_uses_corrected(self):
        img, _ = self.fields[0]
        m = measure(img, BeadPick(200, 200, 9), illumination=0.1)
        self.assertIn("dim-light", m.flags)
        ok = measure(img, BeadPick(200, 200, 9), illumination=0.5)
        self.assertAlmostEqual(ok.light_corrected, ok.light / 0.5)
        s = summarise({"a": [ok, m]}, {"a": "H_1x"}, exclude_flags=("dim-light",))
        self.assertAlmostEqual(s["H_1x"].mean_light, ok.light_corrected)

    def test_save_writes_map_json_and_plot(self):
        with tempfile.TemporaryDirectory() as d:
            names = {os.path.basename(p) for p in save(self.ff, d, "test")}
            self.assertEqual(names, {"flat.tif", "glow_map.tif", "flat.json", "flat.png"})


if __name__ == "__main__":
    unittest.main()
