"""
Headless tests for the Stage-4 reference-warp tagging (no Qt).
"""
from __future__ import annotations
import os
import sys
import glob
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rwtag import io
from rwtag.refwarp import warp as W, tagmatch, strain as ST, series as S, tagframe as TF

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODEL = os.path.join(_ROOT, "reference", "glyph_knn.yml")
_STITCHED = os.path.join(_ROOT, "Stitched Images")
_REF = os.path.join(_ROOT, "reference", "reference_tags.json")


def _identity_reg():
    return {"orient": (0, 1, 1, 1), "offset": (0, 0)}


def _fit(scale=2.0):
    """Design box (150um) -> ~300px boxes with a slight shear."""
    return {"O": np.array([120.0, 90.0]), "U": np.array([150 * scale, 6.0]),
            "V": np.array([-4.0, 150 * scale])}


def test_reference_map_loads():
    data = TF.load_records(_REF)
    from collections import Counter
    cats = Counter(r["category"] for r in data)
    assert cats["dot"] > 5000 and cats["dash"] > 400, cats
    tags = [r["tag"] for r in data]
    assert len(tags) == len(set(tags)), "duplicate tags in reference map"


def test_synthetic_warp_roundtrip():
    """Known smooth warp of the reference dots -> fit_warp + tag_image must recover
    the tags of >95% of the points with residual ~ the injected noise."""
    records = TF.load_records(_REF)
    ref = TF.ref_dots_um(records)
    fit, reg = _fit(), _identity_reg()
    rng = np.random.default_rng(0)
    true = W.coarse_map(ref, fit, reg)
    true = true + 8.0 * np.sin(true / 900.0)          # gentle non-uniform bulge
    keep = rng.random(len(true)) < 0.7                # simulate partial FOV/detection
    det_px = true[keep] + rng.normal(0, 0.6, (int(keep.sum()), 2))
    pitch = float(np.hypot(*fit["U"]) / 18.75)        # px dot pitch

    model = W.fit_warp(ref, det_px, fit, reg, pitch)
    assert model["H"] is not None and model["kind"] == "tps"
    assert model["per_det_median"] < 2.5, model["per_det_median"]
    assert model["matched_frac"] > 0.9

    # tag recovery: each synthetic detection should get the tag of its own ref dot
    dot_rows = [r for r in records if r["category"] == "dot"]
    d = {"basis": {"pitch": pitch}, "dots": det_px, "dashes": None, "glyphs": None}
    res = tagmatch.tag_image(d, model, records)
    truth = np.array([r["tag"] for r in dot_rows] +
                     [""] * (len(ref) - len(dot_rows)))[: len(ref)][keep]
    got = res["dot"]
    correct = sum(1 for i, (tag, _r) in got.items() if truth[i] == tag)
    frac = correct / max(len(det_px), 1)
    assert frac > 0.95, f"only {frac:.2%} of tags recovered"


def test_design_to_fit_box_semantics_all_orients():
    """Regression (off-by-one box on negative-sign axes): a point INSIDE design box
    (col,row) must land inside the fit box whose registration box-number maps back
    to the same (col,row) — for every one of the 8 orientations."""
    from rwtag.glyph import gridmodel as gm
    orients = [(ca, cs, ra, rs) for ca in (0, 1) for ra in (0, 1) if ca != ra
               for cs in (-1, 1) for rs in (-1, 1)]
    for orient in orients:
        reg = {"orient": orient, "offset": (2, 1)}
        for (col, row) in ((0, 0), (2, 3), (4, 1)):
            u, v = col + 0.3, row + 0.6            # inside design box (col,row)
            f0, f1 = W.design_to_fit(u, v, reg)
            node = (int(np.floor(f0)), int(np.floor(f1)))
            c2, r2, _N = gm.box_colrow(node, reg)
            assert (c2, r2) == (col, row), \
                f"orient {orient}: design box {(col, row)} -> fit box {node} -> {(c2, r2)}"
            # inverse (coreg.design_coords formula) must recover the same box
            ca, cs, ra, rs = orient
            bc = [0.0, 0.0]; bc[0], bc[1] = f0, f1
            uu = cs * bc[ca] + reg["offset"][0] + (1.0 if cs < 0 else 0.0)
            vv = rs * bc[ra] + reg["offset"][1] + (1.0 if rs < 0 else 0.0)
            assert (int(np.floor(uu)), int(np.floor(vv))) == (col, row), \
                f"orient {orient}: inverse gave {(uu, vv)}"


def test_parse_label():
    assert S.parse_label("1.5XMISTstitchedimg-stitched-0.ome.tif") == 1.5
    assert S.parse_label("4.2Xfoo.tif") == 4.2
    assert S.parse_label("10Xbar.png") == 10.0
    assert S.parse_label("nolabel.tif") is None


def test_strain_synthetic():
    rng = np.random.default_rng(1)
    P0 = rng.random((300, 2)) * 1000
    P1 = 1.5 * P0 + rng.normal(0, 0.3, (300, 2))
    t0 = {f"dot|B1|{i}_0": tuple(P0[i]) for i in range(300)}
    t1 = {f"dot|B1|{i}_0": tuple(P1[i]) for i in range(300)}
    r = ST.strain(t0, t1, 1.0, 1.5)
    assert abs(r["mean"] - 1.5) < 0.02, r["mean"]
    assert r["n"] > 250


def test_warped_grid_segments():
    fit, reg = _fit(), _identity_reg()
    ref = TF.ref_dots_um(TF.load_records(_REF))
    det = W.coarse_map(ref, fit, reg)
    model = W.fit_warp(ref, det, fit, reg, float(np.hypot(*fit["U"]) / 18.75))
    segs = TF.warped_grid_segments(model)
    assert len(segs) == 12
    # the design origin grid line should pass near the mapped design origin
    o = W.warp_points(np.array([[0.0, 0.0]]), model)[0]
    d0 = min(np.hypot(*(s - o).T).min() for s in segs)
    assert d0 < 5.0


def test_real_frame_tagging():
    files = sorted(glob.glob(os.path.join(_STITCHED, "2.0X*.tif")))
    if not files or not os.path.exists(_MODEL):
        print("  SKIP  test_real_frame_tagging (no data/model)"); return
    from dataclasses import replace
    from rwtag import correct as C
    from rwtag.types import CorrectionParams
    from rwtag.glyph import detect as D, reader as gr
    clf = D.load_classifier(_MODEL)
    raw = io.load_tiff(files[0])
    corr = CorrectionParams()
    base = C.apply(raw, replace(corr, rotate_deg=0.0))
    corr.rotate_deg = float(gr.estimate_deskew(io.to_uint8(base), clf))
    det = D.detect(io.to_uint8(C.apply(raw, corr)), clf)
    tr = TF.tag_frame(det, None)
    assert tr is not None and tr.warp["per_det_median"] < 5.0
    assert tr.warp["matched_frac"] > 0.7
    ndot = sum(1 for t in tr.tags if t.startswith("dot|"))
    assert ndot > 1000, f"only {ndot} dot tags"
    print(f"  info  2.0x: {len(tr.tags)} tags, resid {tr.warp['per_det_median']:.1f}px, "
          f"matched {tr.warp['matched_frac']:.0%}")


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
