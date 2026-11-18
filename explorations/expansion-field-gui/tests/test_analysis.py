"""Validate Phase-4 field analysis helpers (summary + magnitude interpolation)."""
import os
import warnings
import numpy as np
import pytest

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
import sys
sys.path.insert(0, ROOT)

from fieldkit.project import ExpansionProject, DEFAULT_META
from fieldkit import analysis
from gridtrack.types import CorrectionParams

SIM = os.path.normpath(os.path.join(ROOT, "..", "expansion_camera_sim", "tiffs"))
OPTICS = dict(vig_strength=0.88, vig_power=1.8, k1=-0.05, k2=-0.01)


@pytest.fixture(scope="module")
def field(tmp_path_factory):
    init = os.path.join(SIM, "expansion_l1p00x.tif")
    exp = os.path.join(SIM, "expansion_l2p00x.tif")
    if not (os.path.exists(init) and os.path.exists(DEFAULT_META)):
        pytest.skip("sim frames or grid_metadata.json missing")
    pr = ExpansionProject(initial_path=init, expansion_paths=[exp],
                          out_dir=str(tmp_path_factory.mktemp("o")),
                          correction=CorrectionParams(**OPTICS))
    pr.process_all(); pr.pair_all()
    return list(pr.pairings.values())[0].field, pr.results[init].detection.image.shape


def test_field_summary(field):
    f, _ = field
    s = analysis.field_summary(f)
    assert s["n_paired"] > 100
    assert s["full_median_um"] > s["resid_median_um"]      # expansion >> residual warp


def test_interpolated_magnitude_grid(field):
    f, shape = field
    Z, step = analysis.interpolate_magnitude(f, "full", shape, step=8)
    assert Z.shape == (int(np.ceil(shape[0] / 8)), int(np.ceil(shape[1] / 8)))
    assert np.isfinite(Z).any()                            # interior interpolated
    assert np.isnan(Z).any()                               # outside-hull -> NaN
