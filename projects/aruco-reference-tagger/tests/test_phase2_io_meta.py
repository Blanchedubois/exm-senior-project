"""
Phase 2 tests for rwtag.io + rwtag.meta (no Qt). V1 io suite ported verbatim,
plus the OME metadata reader and the metadata record.
"""
from __future__ import annotations
import os
import sys
import glob
import tempfile
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rwtag import io
from rwtag.types import CorrectionParams, LevelsParams

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STITCHED = os.path.normpath(os.path.join(_ROOT, "..", "reference-warp-tagger", "Stitched Images"))
_DUMMY = os.path.normpath(os.path.join(_ROOT, "..", "aruco-marker-design", "dummy"))


def test_session_roundtrip():
    corr = CorrectionParams(vig_strength=0.4, k1=-0.08, lp_enable=True,
                            lp_shape="butterworth", lp_order=3, rotate_deg=-12.5)
    lv = LevelsParams(lv_enable=True, lv_black_mode="percentile", lv_black_pct=35.0,
                      lv_white=0.9, lv_gamma=0.7)
    flags = {"vignette": True, "lens": True, "lowpass": True, "rotate": False, "levels": False}
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "s.json")
        io.save_session(p, "/some/image.ome.tif", corr, lv, flags)
        src, c2, lv2, f2 = io.load_session(p)
    assert src == "/some/image.ome.tif"
    assert c2.to_dict() == corr.to_dict(), "correction round-trip mismatch"
    assert lv2.to_dict() == lv.to_dict(), "levels round-trip mismatch"
    assert f2 == flags, "shared_flags round-trip mismatch"


def test_load_session_tolerates_old_format():
    """Old sessions stored only source_path + correction; loader must still work."""
    import json
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "old.json")
        with open(p, "w") as f:
            json.dump({"source_path": "x.tif",
                       "correction": CorrectionParams(k1=-0.05).to_dict()}, f)
        src, c, lv, flags = io.load_session(p)
    assert src == "x.tif" and abs(c.k1 + 0.05) < 1e-9
    assert isinstance(lv, LevelsParams) and flags == {}


def test_sidecar_path():
    assert io.sidecar_path("a/b/img.ome.tif") == "a/b/img.ome.tif.rwsession.json"


def test_preview_downsample():
    big = np.zeros((3000, 2000), np.float32)
    small = io.preview_downsample(big, max_side=1200)
    assert max(small.shape) == 1200
    tiny = np.zeros((500, 400), np.float32)
    assert io.preview_downsample(tiny, max_side=1200).shape == tiny.shape   # unchanged


def test_load_real_ome_tiff():
    files = sorted(glob.glob(os.path.join(_STITCHED, "*.ome.tif")))
    if not files:
        print("  SKIP  test_load_real_ome_tiff (no Stitched Images found)"); return
    img = io.load_tiff(files[0])
    assert img.ndim == 2 and img.dtype == np.float32
    assert min(img.shape) > 1000, "expected a large stitched frame"
    lo, hi = io.display_levels(img)
    assert hi > lo


# ------------------------------------------------------------ metadata (Phase 2)
from rwtag import meta as M          # noqa: E402


def test_ome_metadata_from_dummy():
    import json
    d = os.path.join(_DUMMY, "optimistic", "opt_warp")
    if not os.path.exists(os.path.join(d, "truth_meta.json")):
        print("  skip: dummy run not generated"); return
    truth = json.load(open(os.path.join(d, "truth_meta.json")))
    for name, tm in truth.items():
        got = io.read_ome_metadata(os.path.join(d, name + ".ome.tif"))
        for k in ("um_per_px", "magnification", "numerical_aperture", "immersion",
                  "laser_wavelength_nm", "laser_power_mw", "emission_wavelength_nm",
                  "exposure_ms", "detector_gain_setting", "date", "time"):
            assert k in got, (name, k)
            if isinstance(tm[k], float) or isinstance(tm[k], int):
                assert abs(float(got[k]) - float(tm[k])) < 1e-6, (name, k, got[k], tm[k])
            else:
                assert str(got[k]) == str(tm[k]), (name, k, got[k], tm[k])
        assert "gain_e_per_adu" not in got           # a header gain setting is not e-/ADU


def test_ome_metadata_real_frame():
    files = sorted(glob.glob(os.path.join(_STITCHED, "*.ome.tif")))
    if not files:
        print("  skip: no real frames"); return
    got = io.read_ome_metadata(files[0])
    assert abs(got["um_per_px"] - 0.51) < 1e-9 and "Bio-Formats" in got.get("file_creator", "")
    assert "magnification" not in got                # absent elements are not guessed


def test_auto_meta_filename_label():
    vals = io.auto_meta("/no/such/2.5X_sample.tif")
    assert vals["expansion_expected"] == (2.5, "filename") and vals["state_label"] == ("2.5X", "filename")


def test_meta_sidecar_roundtrip():
    m = M.ImageMeta()
    m.set("magnification", "100", "user"); m.set("um_per_px", 0.51, "header")
    m.set("cells_present", True, "user"); m.set("cells_description", "HeLa", "user")
    m.set("gel_type", "TExM", "user"); m.set("notes", "  ", "user")
    m.set_derived(expansion_derived=4.1234, handedness=-1.0)
    assert m.magnification == 100.0 and m.notes is None and "notes" not in m.sources
    with tempfile.TemporaryDirectory() as d:
        img = os.path.join(d, "x.ome.tif")
        M.save_meta(img, m)
        m2 = M.load_meta(img)
    assert m2.to_dict() == m.to_dict()
    assert m2.source("um_per_px") == "header" and m2.source("expansion_derived") == "pipeline"
    try:
        m.set_derived(magnification=3); raise AssertionError("non-derived field accepted")
    except KeyError:
        pass


def test_user_edit_survives_autofill():
    m = M.ImageMeta()
    m.set("um_per_px", 0.40, "user")
    n = m.apply_auto({"um_per_px": 0.51, "magnification": 20.0}, "header")
    assert n == 1 and m.um_per_px == 0.40 and m.source("um_per_px") == "user"
    assert m.magnification == 20.0 and m.source("magnification") == "header"


def test_coerce_rejects_garbage():
    assert M.coerce("um_per_px", "abc") is None and M.coerce("n_tiles", "4.0") == 4
    assert M.coerce("cells_present", "yes") is True and M.coerce("cells_present", "no") is False
    assert {f[1] for f in M.FIELDS} == {f.name for f in __import__("dataclasses").fields(M.ImageMeta)} - {"sources"}
