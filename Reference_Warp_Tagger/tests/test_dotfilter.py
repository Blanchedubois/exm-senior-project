"""
Headless tests for the Stage-3 filters (no Qt).
"""
from __future__ import annotations
import os
import sys
import glob
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rwtag import io
from rwtag.glyph import dotfilter as gdf, detect as D

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODEL = os.path.join(_ROOT, "reference", "glyph_knn.yml")
_STITCHED = os.path.join(_ROOT, "Stitched Images")


def _lattice_dots(pitch=40.0, n=12, origin=(200.0, 200.0)):
    o = np.array(origin, float)
    pts = [o + [i * pitch, j * pitch] for i in range(n) for j in range(n)]
    return np.array(pts, float)


def _basis(pitch=40.0, origin=(200.0, 200.0)):
    return {"v1": np.array([pitch, 0.0]), "v2": np.array([0.0, pitch]),
            "origin": np.array(origin, float), "pitch": float(pitch)}


def test_filter_dots_reasons():
    dots = _lattice_dots()
    basis = _basis()
    # inject probes in clear space so each trips exactly one rule (priority is
    # too_close -> on_glyph -> off_lattice):
    dup = dots[0] + [2.0, 0.0]                          # duplicate -> too_close (pair)
    off = np.array([220.0, 220.0])                      # box centre: 28px off every node
    ong = np.array([900.0, 900.0])                      # far from lattice, on a glyph
    test = np.vstack([dots, dup, off, ong])
    glyph_pos = np.array([[900.0, 900.0]])
    recs, counts = gdf.filter_dots(test, basis, glyph_pos, glyph_h=30.0,
                                   params=gdf.DotFilterParams())
    by = {(round(r["x"], 1), round(r["y"], 1)): r["reason"] for r in recs}
    assert by[(220.0, 220.0)] == "off_lattice", by[(220.0, 220.0)]
    assert by[(900.0, 900.0)] == "on_glyph", by[(900.0, 900.0)]
    assert counts["too_close"] >= 2          # the duplicate pair both flagged
    assert counts["kept"] > 100              # the clean lattice mostly survives


def test_filter_dots_toggles_off():
    dots = _lattice_dots()
    p = gdf.DotFilterParams(min_sep_enable=False, glyph_enable=False, dev_enable=False)
    recs, counts = gdf.filter_dots(dots, _basis(), None, 30.0, p)
    assert counts["kept"] == len(dots)       # everything kept when all filters off


def test_filter_dashes_reasons():
    P = 750.0
    grid = {"u": np.array([1.0, 0.0]), "v": np.array([0.0, 1.0]),
            "box_pitch": P, "phase_u": 0.0, "phase_v": 0.0,
            "u_vec": np.array([P, 0.0]), "v_vec": np.array([0.0, P])}
    on_line = [[0.0, 0.5 * P], [0.0, 1.5 * P], [P, 0.5 * P]]   # on vertical box lines
    corner = [[0.0, 0.0]]                                      # line intersection
    offgrid = [[0.5 * P, 0.5 * P]]                             # box centre
    dashes = np.array(on_line + corner + offgrid, float)
    recs, counts = gdf.filter_dashes(dashes, grid, gdf.DashFilterParams())
    by = {(round(r["x"], 1), round(r["y"], 1)): r["reason"] for r in recs}
    assert by[(0.0, 0.0)] == "intersection"
    assert by[(round(0.5 * P, 1), round(0.5 * P, 1))] == "off_grid"
    assert counts["kept"] >= 3


def test_real_frame_filtering():
    files = sorted(glob.glob(os.path.join(_STITCHED, "2.0X*.tif")))
    if not files or not os.path.exists(_MODEL):
        print("  SKIP  test_real_frame_filtering (no data/model)"); return
    clf = D.load_classifier(_MODEL)
    det = D.detect(io.load_tiff(files[0]), clf)
    drecs, dc = gdf.filter_dots(det.dots, det.basis, det.glyphs, det.glyph_h, gdf.DotFilterParams())
    hrecs, hc = gdf.filter_dashes(det.dashes_all, det.grid, gdf.DashFilterParams())
    assert dc["kept"] / max(len(drecs), 1) > 0.85, f"too many dots dropped: {dc}"
    assert hc["kept"] >= 1
    print(f"  info  2.0x: dots kept {dc['kept']}/{len(drecs)} {dict(dc)}; "
          f"dashes kept {hc['kept']}/{len(hrecs)}")


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
