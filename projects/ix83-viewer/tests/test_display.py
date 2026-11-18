"""Phase 1 display helpers (no GUI needed)."""

import unittest

import numpy as np

from ix83viewer.core.display import (
    COLOR_PRESETS, DEFAULT_PRESET, auto_levels, format_um, nice_scale_length, ramp_lut, wavelength_color,
)


class DisplayTests(unittest.TestCase):
    def test_default_mapping_is_spectral_rgb(self):
        self.assertEqual([wavelength_color(w) for w in (633, 561, 488)], [(1, 0, 0), (0, 1, 0), (0, 0, 1)])

    def test_unknown_and_nearby_wavelengths(self):
        self.assertEqual(wavelength_color(None), (1.0, 1.0, 1.0))
        self.assertEqual(wavelength_color(640), wavelength_color(633))
        self.assertEqual(wavelength_color(405), (1.0, 1.0, 1.0))
        for preset in COLOR_PRESETS:
            self.assertEqual(len(COLOR_PRESETS[preset]), 3)

    def test_ramp_lut(self):
        lut = ramp_lut((1, 0.5, 0))
        self.assertEqual(lut.shape, (256, 3))
        np.testing.assert_array_equal(lut[0], [0, 0, 0])
        np.testing.assert_array_equal(lut[-1], [255, 128, 0])

    def test_auto_levels_ignores_hot_pixels(self):
        img = np.full((100, 100), 100, np.uint16)
        img[:50] = 200
        img[0, 0] = 60000
        lo, hi = auto_levels(img)
        self.assertEqual((lo, hi), (100.0, 200.0))
        self.assertEqual(auto_levels(np.zeros((4, 4))), (0.0, 1.0))

    def test_scale_length(self):
        self.assertEqual([nice_scale_length(v) for v in (310, 99, 2.4, 0.7)], [200, 50, 2, 0.5])
        self.assertEqual((format_um(200), format_um(2000)), ("200 µm", "2 mm"))


if __name__ == "__main__":
    unittest.main()
