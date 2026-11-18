"""
Validate Stage-5 filters: clean data mostly survives, injected defects are caught.
"""
import os
import warnings
import numpy as np
import pandas as pd
import pytest

warnings.filterwarnings("ignore")

from gridtrack import io, correct, address, reference, measure, filters
from gridtrack.types import CorrectionParams, MeasureParams, FilterParams

OPTICS = dict(vig_strength=0.88, vig_power=1.8, k1=-0.05, k2=-0.01)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM = os.path.normpath(os.path.join(ROOT, "..", "expansion_camera_sim"))
META = os.path.normpath(os.path.join(ROOT, "..", "hydrogel_marker_analysis",
                                     "toolkit", "grid_metadata.json"))


@pytest.fixture(scope="module")
def tracked():
    fp = os.path.join(SIM, "tiffs", "expansion_l1p00x.tif")
    if not (os.path.exists(fp) and os.path.exists(META)):
        pytest.skip("sim frames or grid_metadata.json missing")
    p = CorrectionParams(**OPTICS)
    img = correct.apply(io.load_tiff(fp), p)
    det = address.detect_and_orient(img, "DICT_6X6_1000", p)
    ref = reference.load(META)
    grid = reference.map_grid(det, ref)
    feats = measure.detect_features(det.image, grid, ref, MeasureParams())
    return det, ref, grid, feats


def test_clean_data_mostly_survives(tracked):
    det, ref, grid, feats = tracked
    out = filters.apply_filters(feats, grid, ref, FilterParams(enable_border=False),
                                image_shape=det.image.shape)
    n_match = int(((feats["type"] == "dot") & (feats["status"] == "matched")).sum())
    assert out.attrs["n_survivors"] / n_match > 0.97      # good data isn't nuked


def test_proximity_filter_catches_a_close_duplicate(tracked):
    det, ref, grid, feats = tracked
    f2 = feats.copy()
    # duplicate a matched dot ~2 px away -> a too-close pair
    row = f2[(f2["type"] == "dot") & (f2["status"] == "matched")].iloc[0].copy()
    row["img_x_px"] += 2.0
    f2 = pd.concat([f2, pd.DataFrame([row])], ignore_index=True)
    out = filters.apply_filters(f2, grid, ref,
                                FilterParams(enable_quality=False, enable_residual=False,
                                             enable_border=False), image_shape=det.image.shape)
    assert out.attrs["filter_counts"].get("proximity", 0) >= 2   # both of the pair


def test_residual_filter_catches_a_misplaced_dot(tracked):
    det, ref, grid, feats = tracked
    f2 = feats.copy()
    m = f2.index[(f2["type"] == "dot") & (f2["status"] == "matched")]
    f2.at[m[100], "img_x_px"] += 25.0                     # jump one dot far from prediction
    out = filters.apply_filters(f2, grid, ref,
                                FilterParams(enable_proximity=False, enable_quality=False,
                                             enable_border=False), image_shape=det.image.shape)
    assert out.at[m[100], "status"] == "filtered"
    assert out.at[m[100], "filter_reason"] == "residual"


def test_border_filter_marks_edge_dots(tracked):
    det, ref, grid, feats = tracked
    out = filters.apply_filters(feats, grid, ref,
                                FilterParams(enable_proximity=False, enable_quality=False,
                                             enable_residual=False, enable_border=True,
                                             border_px=400.0), image_shape=det.image.shape)
    assert out.attrs["filter_counts"].get("border", 0) > 0
