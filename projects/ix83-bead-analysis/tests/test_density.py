"""Density from total light on synthetic gels with a known bead count, illumination and blur."""

import os
import tempfile
import unittest

import numpy as np

from ix83viewer.beads.density import analyse, area_light, write_outputs
from ix83viewer.beads.refbeads import BeadPick, measure

SIZE, PX = 500, 1.1
LIGHT = 40_000.0


def illumination():
    yy, xx = np.indices((SIZE, SIZE))
    r = np.hypot(xx - SIZE / 2, yy - SIZE / 2) / SIZE
    return np.exp(-r ** 2 / (2 * 0.35 ** 2))


def gel(n_beads, seed, glow=20.0):
    """Beads uniformly over the field, half in focus, half blurred (same light); returns image and in-focus spots."""
    rng = np.random.default_rng(seed)
    yy, xx = np.indices((SIZE, SIZE))
    img = np.full((SIZE, SIZE), glow)
    spots = []
    for k in range(n_beads):
        x, y = rng.uniform(0, SIZE, 2)
        sigma = 2.0 if k % 2 else rng.uniform(6, 15)
        g = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma ** 2))
        img += LIGHT * g / (2 * np.pi * sigma ** 2)
        if sigma == 2.0:
            spots.append((x, y))
    return (img * illumination() + rng.normal(0, 0.5, img.shape)).astype(np.float32), spots


class DensityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = illumination() / illumination().max()
        images, refs = {}, {"areas": {}}
        for ci, (cond, n) in enumerate((("A_1x", 180), ("A_3x", 20))):  # 9x fewer beads: 3x linear expansion
            for i in range(3):
                img, spots = gel(n, seed=100 * ci + i)  # fixed seeds: the test must not change between runs
                folder = f"{cond}_{i}"
                images[folder] = (cond, img, PX)
                picks = []
                for x, y in spots:
                    il = base[int(y), int(x)]
                    m = measure(img, BeadPick(round(x), round(y), 10), illumination=il)
                    if not m.flags and il > 0.5:
                        picks.append({"x": m.pick.x, "y": m.pick.y, "light": m.light, "flags": []})
                refs["areas"][folder] = picks[:6]
        cls.images, cls.refs, cls.base = images, refs, base
        cls.res = analyse(images, refs, base, 1.0, [("A", "A_1x", "A_3x", 3.0)], 3.0)

    def test_bead_light_recovered(self):
        for c in ("A_1x", "A_3x"):
            # blurred neighbours inflate reference beads in a dense field by up to ~15%
            self.assertAlmostEqual(self.res.bead_light[c]["mean"] / LIGHT, 1.0, delta=0.2)

    def test_density_matches_truth(self):
        field_mm2 = SIZE * SIZE * (PX / 1000) ** 2
        g = self.res.groups[0]
        self.assertAlmostEqual(g["base_density"]["mean"] / (180 / field_mm2), 1.0, delta=0.25)
        self.assertAlmostEqual(g["measured_density"]["mean"] / (20 / field_mm2), 1.0, delta=0.15)

    def test_implied_expansion(self):
        g = self.res.groups[0]
        self.assertAlmostEqual(g["implied_linear_expansion"], 3.0, delta=0.5)
        lo, hi = g["implied_linear_expansion_95ci"]
        self.assertLessEqual(lo, g["implied_linear_expansion"])
        self.assertGreaterEqual(hi, g["implied_linear_expansion"])
        self.assertAlmostEqual(g["ideal_density"]["mean"], g["base_density"]["mean"] / 9)

    def test_area_per_bead_is_inverse_density(self):
        g = self.res.groups[0]
        inv = [1 / v for v in g["base_density"]["values"]]
        self.assertEqual(g["base_area_per_bead"]["values"], inv)
        self.assertAlmostEqual(g["ideal_area_per_bead"]["mean"], g["base_area_per_bead"]["mean"] * 9)

    def test_expansion_basis(self):
        lin = self.res.groups[0]
        self.assertEqual(lin["ideal_drop"], 9)  # 3x linear = 9x area
        area = analyse(self.images, self.refs, self.base, 1.0, [("A", "A_1x", "A_3x", 3.0)], 3.0,
                       expansion_basis="area").groups[0]
        self.assertEqual(area["ideal_drop"], 3)
        self.assertAlmostEqual(area["ideal_density"]["mean"], lin["base_density"]["mean"] / 3)
        self.assertEqual(area["implied_linear_expansion"], lin["implied_linear_expansion"])

    def test_floor_removes_uniform_glow(self):
        img, _ = gel(0, seed=1, glow=50.0)
        a = area_light(img, self.base, PX)
        self.assertLess(abs(a["total"]) / a["total_no_floor"], 0.02)

    def test_writes_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            paths = write_outputs(self.res, d, {}, "synthetic", {"A": {"main": 3.0, "no floor": 2.5}})
            self.assertEqual({os.path.basename(p) for p in paths},
                             {"density_areas.csv", "density_summary.json", "density_candles.png",
                              "density_comparison.png", "expansion_vs_ideal.png", "area_per_bead_candles.png",
                              "implied_expansion.png"})


if __name__ == "__main__":
    unittest.main()
