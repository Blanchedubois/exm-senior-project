"""
Validate Stage-4 dot/dash detection + tagging against the simulator.

At lambda=1 the whole grid is in view, so essentially every reference dot should
be found, uniquely tagged (box,i,j), and localised close to its box-homography
prediction (residual ~ the small warp).
"""
import os
import warnings
import numpy as np
import pytest

warnings.filterwarnings("ignore")

from gridtrack import io, correct, address, reference, measure
from gridtrack.reference import transform_points
from gridtrack.types import CorrectionParams, MeasureParams

OPTICS = dict(vig_strength=0.88, vig_power=1.8, k1=-0.05, k2=-0.01)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM = os.path.normpath(os.path.join(ROOT, "..", "expansion-camera-sim"))
META = os.path.normpath(os.path.join(ROOT, "..", "hydrogel_marker_analysis",
                                     "toolkit", "grid_metadata.json"))


@pytest.fixture(scope="module")
def stage4_l1():
    fp = os.path.join(SIM, "tiffs", "expansion_l1p00x.tif")
    if not (os.path.exists(fp) and os.path.exists(META)):
        pytest.skip("sim frames or grid_metadata.json missing")
    p = CorrectionParams(**OPTICS)
    img = correct.apply(io.load_tiff(fp), p)
    det = address.detect_and_orient(img, "DICT_6X6_1000", p)
    ref = reference.load(META)
    grid = reference.map_grid(det, ref)
    feats = measure.detect_features(det.image, grid, ref, MeasureParams())
    return ref, grid, feats


def test_almost_all_dots_matched(stage4_l1):
    ref, grid, feats = stage4_l1
    dots = feats[feats.type == "dot"]
    matched = dots[dots.status == "matched"]
    expected = sum(b["n_dots"] for b in ref.boxes)      # all boxes in view at lambda=1
    assert len(matched) / expected > 0.98               # ~ every dot found


def test_tags_are_unique_and_complete(stage4_l1):
    ref, grid, feats = stage4_l1
    dots = feats[feats.type == "dot"]
    # every reference dot appears exactly once (matched or recorded missing)
    assert len(dots) == sum(b["n_dots"] for b in ref.boxes)
    keys = list(zip(dots.box_i, dots.box_j, dots.local_i, dots.local_j))
    assert len(keys) == len(set(keys))                  # no duplicate tags


def test_localisation_close_to_prediction(stage4_l1):
    ref, grid, feats = stage4_l1
    m = feats[(feats.type == "dot") & (feats.status == "matched")]
    resid = []
    for (bi, bj), Hb in grid.box_homographies.items():
        sub = m[(m.box_i == bi) & (m.box_j == bj)]
        if len(sub) == 0:
            continue
        pred = transform_points(Hb, sub[["ref_x_um", "ref_y_um"]].to_numpy())
        resid.append(np.linalg.norm(pred - sub[["img_x_px", "img_y_px"]].to_numpy(), axis=1))
    resid = np.concatenate(resid)
    assert np.median(resid) < 3.0                       # sub-few-px (warp-limited)


def test_dashes_detected(stage4_l1):
    ref, grid, feats = stage4_l1
    assert (feats.type == "dash").sum() > 0


def test_dashes_tagged_single_tag_frame():
    # lambda=5 shows ~1 tag: dashes on region-grown edges must still get tagged,
    # with a unique, monotonic index per edge (node-anchored 1-D indexing)
    import os, warnings, numpy as np
    warnings.filterwarnings("ignore")
    from gridtrack import io as gio, correct as corr, address, reference as refm, measure as meas
    from gridtrack.types import CorrectionParams as CP, MeasureParams as MP
    fp = os.path.join(SIM, "tiffs", "expansion_l5p00x.tif")
    if not (os.path.exists(fp) and os.path.exists(META)):
        pytest.skip("sim frames missing")
    p = CP(**OPTICS)
    det = address.detect_and_orient(corr.apply(gio.load_tiff(fp), p), "DICT_6X6_1000", p)
    ref = refm.load(META)
    dots_xy = meas.detect_dots(det.image, MP())[["x", "y"]].to_numpy()
    grid = refm.map_grid(det, ref, dots_xy=dots_xy)
    feats = meas.detect_features(det.image, grid, ref, MP())
    d = feats[feats["type"] == "dash"]
    assert len(d) > 0                                     # tagged despite one tag
    for _, g in d.groupby(["box_i", "box_j", "edge"]):
        ks = g["local_i"].to_numpy()
        assert len(set(ks)) == len(ks)                   # unique index per edge
        assert (np.diff(np.sort(ks)) >= 1).all()         # strictly increasing
