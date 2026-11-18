"""
Validate Phase-3 pairing against the simulator's expansion series.

The sim's fixed-zoom frames spread features by the absolute expansion factor, so
pairing the initial (l1, lambda=1) to l2 / l3 should recover a RELATIVE expansion
of ~2.0 / ~3.0, and the residual field (mean expansion removed) should be small.
"""
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
from gridtrack.types import CorrectionParams

SIM = os.path.normpath(os.path.join(ROOT, "..", "expansion_camera_sim", "tiffs"))
OPTICS = dict(vig_strength=0.88, vig_power=1.8, k1=-0.05, k2=-0.01)


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    init = os.path.join(SIM, "expansion_l1p00x.tif")
    e2 = os.path.join(SIM, "expansion_l2p00x.tif")
    e3 = os.path.join(SIM, "expansion_l3p00x.tif")
    if not (os.path.exists(init) and os.path.exists(DEFAULT_META)):
        pytest.skip("sim frames or grid_metadata.json missing")
    out = str(tmp_path_factory.mktemp("out"))
    pr = ExpansionProject(initial_path=init, expansion_paths=[e2, e3], out_dir=out,
                          correction=CorrectionParams(**OPTICS))
    pr.process_all()
    pr.pair_all()
    return pr


def _pairing(project, name):
    return next(p for k, p in project.pairings.items() if p.expansion_name == name)


def test_recovers_relative_expansion_factor(project):
    assert abs(_pairing(project, "expansion_l2p00x").lambda_rel - 2.0) < 0.1
    assert abs(_pairing(project, "expansion_l3p00x").lambda_rel - 3.0) < 0.15


def test_full_field_shows_expansion_residual_is_small(project):
    pr = _pairing(project, "expansion_l2p00x")
    f = pr.field[pr.field["status"] == "paired"]
    # full displacement (keeps expansion) >> residual warpage (expansion removed)
    assert f["u_full_mag_um"].median() > 5 * f["u_resid_mag_um"].median()
    assert f["u_resid_mag_um"].median() < 2.0            # residual ~ the minimal warp (um)


def test_pairing_csvs_written_with_columns(project):
    import pandas as pd
    from fieldkit.pairing import PAIRING_COLS
    d = os.path.join(project.out_dir, "pairing")
    assert os.path.exists(os.path.join(d, "pairing_summary.csv"))
    fp = os.path.join(d, "pairing_expansion_l2p00x_vs_initial.csv")
    df = pd.read_csv(fp)
    assert list(df.columns) == PAIRING_COLS
    assert (df["status"] == "paired").sum() > 100


def test_shared_markers_are_tags_and_dots(project):
    pr = _pairing(project, "expansion_l2p00x")
    assert pr.n_tags >= 4 and pr.n_dots > 100
