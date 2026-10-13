"""
Headless tests for the Stage-2 glyph pipeline (no Qt).

Covers the geometry recovery, the numbering-rule registration, digit clubbing,
a classifier smoke test, and a real-frame integration run.
"""
from __future__ import annotations
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rwtag import io
from rwtag.glyph import lattice as lt, gridmodel as gm, detect as D

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODEL = os.path.join(_ROOT, "reference", "glyph_knn.yml")
_STITCHED = os.path.join(_ROOT, "Stitched Images")


def _dot_lattice(pitch=40.0, angle_deg=20.0, n=18):
    th = np.radians(angle_deg)
    v1 = np.array([np.cos(th), np.sin(th)]) * pitch
    v2 = np.array([-np.sin(th), np.cos(th)]) * pitch
    pts = [i * v1 + j * v2 + (500, 500) for i in range(n) for j in range(n)]
    return np.array(pts, float)


def test_estimate_basis_recovers_pitch_angle():
    pts = _dot_lattice(pitch=40.0, angle_deg=20.0)
    b = lt.estimate_basis(pts)
    assert abs(b["pitch"] - 40.0) < 1.0, f"pitch off: {b['pitch']}"
    assert abs((b["angle_deg"] % 90) - 20.0) < 2.0, f"angle off: {b['angle_deg']}"


def test_refine_basis_stays_consistent():
    pts = _dot_lattice(pitch=40.0, angle_deg=12.0)
    b = lt.refine_basis(pts, lt.estimate_basis(pts))
    assert abs(np.hypot(*b["v1"]) - 40.0) < 0.5
    assert b["n_inliers"] > 250


def test_fit_box_grid_keeps_on_line_dashes_drops_strays():
    pts = _dot_lattice(pitch=40.0, angle_deg=0.0, n=40)
    basis = lt.refine_basis(pts, lt.estimate_basis(pts))
    box_pitch = 40.0 * lt.BOX_PER_DOT
    # dashes on vertical box lines x = 500 + k*box_pitch (many, so the phase locks to them)
    on = [[500 + k * box_pitch, 500 + t * box_pitch] for k in range(4) for t in range(4)]
    stray = [[500 + 0.5 * box_pitch, 500 + 0.5 * box_pitch]]    # box centre: off both u & v lines
    grid = lt.fit_box_grid(basis, np.array(on, float))
    kept, ndrop = lt.dashes_on_grid(np.array(on + stray, float), grid)
    assert len(kept) >= len(on) - 2, f"on-line dashes dropped ({len(kept)}/{len(on)})"
    assert ndrop >= 1, "the mid-box stray should be dropped"


def test_register_obeys_numbering_rule():
    """Three boxes consistent with one orientation must lock the grid, and every
    box number must satisfy N = col*5 + row + 1."""
    fit = {"O": np.array([0.0, 0.0]), "U": np.array([100.0, 0.0]), "V": np.array([0.0, 100.0])}
    boxes = {(0, 0): {"number": 1, "agree": 1.0, "n": 2},
             (1, 0): {"number": 6, "agree": 1.0, "n": 2},
             (0, 1): {"number": 2, "agree": 1.0, "n": 2}}
    reg = gm.register(boxes, letters=[], fit=fit, min_anchors=2)
    assert reg["registered"], reg
    assert gm.box_number((0, 0), reg) == 1
    assert gm.box_number((1, 0), reg) == 6
    assert gm.box_number((0, 1), reg) == 2
    assert gm.box_number((2, 3), reg) == 2 * 5 + 3 + 1     # 14


def test_fit_box_corner_and_grid_from_fit():
    fit = {"O": np.array([100.0, 50.0]), "U": np.array([760.0, 20.0]),
           "V": np.array([-15.0, 770.0])}
    # fit_box_corner is affine in (i,j)
    assert np.allclose(lt.fit_box_corner(fit, 1, 0) - lt.fit_box_corner(fit, 0, 0), fit["U"])
    assert np.allclose(lt.fit_box_corner(fit, 0, 1) - lt.fit_box_corner(fit, 0, 0), fit["V"])
    # grid_from_fit yields a box_grid dict whose lines pass through the fit origin
    g = lt.grid_from_fit(fit)
    P = g["box_pitch"]
    du = abs((fit["O"] @ g["u"] - g["phase_u"] + P / 2) % P - P / 2)
    dv = abs((fit["O"] @ g["v"] - g["phase_v"] + P / 2) % P - P / 2)
    assert du < 1e-6 and dv < 1e-6, "fit origin should lie on a box grid line"
    assert abs(P - 0.5 * (np.hypot(*fit["U"]) + np.hypot(*fit["V"]))) < 1e-6


def test_register_needs_evidence():
    fit = {"O": np.array([0.0, 0.0]), "U": np.array([100.0, 0.0]), "V": np.array([0.0, 100.0])}
    reg = gm.register({(0, 0): {"number": 1, "agree": 1.0, "n": 1}}, [], fit, min_anchors=2)
    assert not reg["registered"], "one box with no letters must not lock orientation"


def _digit(ch, x, y, box=(0, 0), slot="corner00", conf=0.9):
    return {"char": ch, "x": float(x), "y": float(y), "box": box, "slot": slot, "conf": conf}


def test_club_digits_joins_and_splits():
    digs = [_digit("1", 0, 0), _digit("3", 8, 0)]
    tok = gm.club_digits(digs, box_pitch=100.0, thresh_frac=0.35, dots=None)
    assert len(tok) == 1 and tok[0]["value"] == 13, tok
    # a fill dot between the two digits means they belong to different numbers
    tok2 = gm.club_digits(digs, box_pitch=100.0, thresh_frac=0.35, dots=np.array([[4.0, 0.0]]))
    assert len(tok2) == 2, tok2


def test_classifier_smoke():
    if not os.path.exists(_MODEL):
        print("  SKIP  test_classifier_smoke (no model)"); return
    clf = D.load_classifier(_MODEL)
    crop = (np.random.default_rng(0).random((28, 28)) * 255).astype(np.uint8)
    ch, conf = clf.predict_restricted(crop, list("0123456789"))
    assert ch in list("0123456789") and 0.0 <= conf <= 1.0


def test_real_frame_integration():
    import glob
    files = sorted(glob.glob(os.path.join(_STITCHED, "2.0X*.tif")))
    if not files or not os.path.exists(_MODEL):
        print("  SKIP  test_real_frame_integration (no data/model)"); return
    clf = D.load_classifier(_MODEL)
    det = D.detect(io.load_tiff(files[0]), clf)
    assert len(det.dots) > 800, f"too few dots: {len(det.dots)}"
    assert det.grid["box_pitch"] > 0 and det.fit is not None
    reg = "registered" if (det.model and det.model.get("registered")) else "NOT auto-registered"
    print(f"  info  2.0x: {len(det.dots)} dots, {len(det.reads)} reads, {reg}")


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
