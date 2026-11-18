"""Phase 5: exports write the right pixels, metadata and sidecars."""

import json
import os
import tempfile
import unittest

import numpy as np
import tifffile
from PIL import Image

from ix83viewer.core.adjust import ChannelSettings
from ix83viewer.core.export import (
    ChannelData, burn_scale_bar, ffmpeg_path, quantitative, render_channel, render_merge, write_channel_tiff,
    write_hyperstack,
)
from ix83viewer.core.export_jobs import ExportOptions, build_set_channels, export_channels
from ix83viewer.core.offsets import Offset, OffsetStore
from ix83viewer.core.processing import Processing
from ix83viewer.core.settings_store import SettingsStore
from ix83viewer.io.mm_dataset import MMDataset
from ix83viewer.io.scan import group_by_position, scan_folder

from test_data_layer import make_fake_acquisition


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["IX83_CACHE_DIR"] = os.path.join(self.tmp.name, "cache")
        rng = np.random.default_rng(3)
        src = os.path.join(self.tmp.name, "data")
        os.makedirs(src)
        self.chs = []
        for wl, color in ((633, (1, 0, 0)), (561, (0, 1, 0)), (488, (0, 0, 1))):
            stack = rng.integers(100, 1000, (4, 64, 80)).astype(np.uint16)
            ds = MMDataset.open(make_fake_acquisition(src, f"{wl}-S-4cts-400ms_1", stack, (0, 0, 0)))
            self.chs.append(ChannelData(ds, stack.mean(0).astype(np.float32), (100.0, 1000.0),
                                        ChannelSettings(), color))
        self.chs[2].offset = Offset(2.0, -3.0, "manual")
        self.out = os.path.join(self.tmp.name, "out")

    def tearDown(self):
        self.tmp.cleanup()

    def test_quantitative_keeps_values(self):
        img = np.array([[0.4, 1.6, 70000.0, -5]], np.float32)
        np.testing.assert_array_equal(quantitative(img), [[0, 2, 65535, 0]])
        self.assertEqual(quantitative(img, "float32").dtype, np.float32)

    def test_channel_tiff_values_and_metadata(self):
        os.makedirs(self.out)
        ch = self.chs[0]
        p = write_channel_tiff(ch, os.path.join(self.out, "c.tif"))
        with tifffile.TiffFile(p) as tf:
            data = tf.asarray()
            ij = tf.imagej_metadata
            xres = tf.pages[0].tags["XResolution"].value
        np.testing.assert_array_equal(data, np.round(ch.image).astype(np.uint16))
        self.assertEqual(ij["unit"], "um")
        self.assertAlmostEqual(xres[1] / xres[0], 1.1, places=3)  # um per pixel
        self.assertIn("LUTs", ij)

    def test_hyperstack_aligned(self):
        os.makedirs(self.out)
        p = write_hyperstack(self.chs, os.path.join(self.out, "s.tif"), aligned=True)
        with tifffile.TiffFile(p) as tf:
            data = tf.asarray()
            ij = tf.imagej_metadata
        self.assertEqual(data.shape, (3, 64, 80))
        self.assertEqual(ij["mode"], "composite")
        self.assertEqual(ij["Labels"], ["633 nm", "561 nm", "488 nm"])
        # 488 shifted down 2, left 3: pixel (10, 10) came from (8, 13)
        self.assertEqual(data[2, 10, 10], np.round(self.chs[2].image[8, 13]))
        np.testing.assert_array_equal(data[0], np.round(self.chs[0].image))
        p2 = write_hyperstack(self.chs, os.path.join(self.out, "s.ome.tif"), ome=True)
        with tifffile.TiffFile(p2) as tf:
            self.assertTrue(tf.is_ome)
            self.assertEqual(tf.asarray().shape, (3, 64, 80))

    def test_render_and_scale_bar(self):
        rgb = render_channel(self.chs[1])
        self.assertEqual((rgb.shape, rgb.dtype), ((64, 80, 3), np.uint8))
        self.assertEqual(rgb[..., 0].max(), 0)  # green only
        merged = render_merge(self.chs, aligned=True)
        self.assertGreater(merged[..., 2][20:40, 20:40].mean(), 0)
        bar = burn_scale_bar(np.zeros((200, 300, 3), np.uint8), 1.1)
        self.assertEqual(bar[-15:-5, -100:, :].max(), 255)  # white bar in the bottom-right corner
        self.assertEqual(bar[:50].max(), 0)

    def test_export_channels_writes_everything(self):
        opts = ExportOptions(channel_images=True, merged_format="jpg", figure_format="pdf", movie=True,
                             movie_format="gif", fps=5)
        files = export_channels(self.chs, self.out, "Set B/Mean", opts, title="Test")
        names = sorted(os.path.basename(f) for f in files)
        self.assertEqual(names, sorted([
            "Set_B_Mean_633.tif", "Set_B_Mean_561.tif", "Set_B_Mean_488.tif", "Set_B_Mean_stack.tif",
            "Set_B_Mean_633.jpg", "Set_B_Mean_561.jpg", "Set_B_Mean_488.jpg", "Set_B_Mean_merged.jpg",
            "Set_B_Mean_figure.pdf", "Set_B_Mean_movie.gif", "Set_B_Mean.json"]))
        with Image.open(os.path.join(self.out, "Set_B_Mean_movie.gif")) as gif:
            self.assertEqual(gif.n_frames, 4)
        with open(os.path.join(self.out, "Set_B_Mean.json")) as f:
            side = json.load(f)
        self.assertEqual(len(side["channels"]), 3)
        self.assertEqual(side["channels"][2]["offset_px"], {"dy": 2.0, "dx": -3.0, "source": "manual", "confidence": None})
        self.assertEqual(side["options"]["merged_format"], "jpg")
        self.assertIn("Set_B_Mean_merged.jpg", side["files"])

    @unittest.skipUnless(ffmpeg_path(), "ffmpeg not installed")
    def test_mp4(self):
        files = export_channels(self.chs, self.out, "m", ExportOptions(
            raw_tiffs=False, hyperstack=False, merged=False, figure=False, movie=True, movie_format="mp4"))
        mp4 = [f for f in files if f.endswith(".mp4")][0]
        self.assertGreater(os.path.getsize(mp4), 1000)

    def test_processing_applied_to_quantitative_export(self):
        ch = self.chs[0]
        ch.settings = ChannelSettings(Processing(background="percentile", bg_param=50))
        from ix83viewer.core.processing import apply_processing
        ch.image = apply_processing(ch.image, ch.settings.processing)
        p = write_channel_tiff(ch, os.path.join(self.tmp.name, "p.tif"))
        self.assertAlmostEqual(float(np.median(tifffile.imread(p))), 0, delta=1)


HERE = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.environ.get("IX83_DATA_ROOT",
                           os.path.join(HERE, "..", "..", "..", "Experimentation", "IX83 Data", "16Oct26"))


@unittest.skipUnless(os.path.isdir(DATA_ROOT), "real data not found")
class RealBatchTests(unittest.TestCase):
    def test_build_set_b(self):
        with tempfile.TemporaryDirectory() as d:
            sets = group_by_position(scan_folder(DATA_ROOT).samples)
            set_b = next(s for s in sets if 633 in s.wavelengths and any("400ms_3" in m.label for m in s.members))
            chs = build_set_channels(set_b, "Mean", SettingsStore(d), OffsetStore(os.path.join(d, "o.json")))
            self.assertEqual([c.name for c in chs], ["633", "561", "488"])
            self.assertEqual(chs[1].ds.label, "561-Sample1-100cts-400ms_2")  # most frames, first by name
            self.assertTrue(all(c.image.shape == (1412, 1412) for c in chs))


if __name__ == "__main__":
    unittest.main()
