"""Phase 2 colour merge."""

import unittest

import numpy as np

from ix83viewer.core.composite import Layer, composite, normalize


class CompositeTests(unittest.TestCase):
    def test_normalize(self):
        img = np.array([[0, 100, 200, 300]], np.uint16)
        np.testing.assert_allclose(normalize(img, (100, 200)), [[0, 0, 1, 1]])
        np.testing.assert_allclose(normalize(img, (5, 5)), [[0, 1, 1, 1]])  # degenerate levels

    def test_rgb_channels_add(self):
        a = np.array([[0, 50, 100]], np.float32)
        b = np.array([[100, 50, 0]], np.float32)
        rgb = composite([Layer(a, (0, 100), (1, 0, 0)), Layer(b, (0, 100), (0, 0, 1))])
        self.assertEqual(rgb.shape, (1, 3, 3))
        np.testing.assert_allclose(rgb[0], [[0, 0, 1], [0.5, 0, 0.5], [1, 0, 0]])

    def test_overlapping_colors_clip(self):
        a = np.ones((2, 2))
        rgb = composite([Layer(a, (0, 1), (1, 0, 1)), Layer(a, (0, 1), (1, 1, 0))])
        self.assertEqual(rgb.max(), 1.0)
        np.testing.assert_allclose(rgb[0, 0], [1, 1, 1])

    def test_shape_mismatch(self):
        with self.assertRaises(ValueError):
            composite([Layer(np.ones((2, 2)), (0, 1), (1, 0, 0)), Layer(np.ones((3, 2)), (0, 1), (0, 1, 0))])
        with self.assertRaises(ValueError):
            composite([])


if __name__ == "__main__":
    unittest.main()
