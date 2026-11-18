"""
Headless tests for rwtag.io: session round-trip and OME-TIFF load (no Qt).
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

_STITCHED = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "Stitched Images")


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


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fails = 0
    for fn in fns:
        try:
            fn(); print(f"  PASS  {fn.__name__}")
        except AssertionError as e:
            fails += 1; print(f"  FAIL  {fn.__name__}: {e}")
        except Exception as e:
            fails += 1; print(f"  ERR   {fn.__name__}: {e!r}")
    print(f"\n{len(fns) - fails}/{len(fns)} passed")
    sys.exit(1 if fails else 0)
