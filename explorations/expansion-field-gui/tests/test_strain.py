"""
Validate Phase-6 strain: for a uniform expansion by lambda, the areal expansion
J = det F should recover ~lambda^2 (4 for lambda=2, 9 for lambda=3), roughly
uniform across the field, with small principal strains after removing it.
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
from fieldkit import strain
from gridtrack.types import CorrectionParams

SIM = os.path.normpath(os.path.join(ROOT, "..", "expansion-camera-sim", "tiffs"))
OPTICS = dict(vig_strength=0.88, vig_power=1.8, k1=-0.05, k2=-0.01)


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    init = os.path.join(SIM, "expansion_l1p00x.tif")
    e2 = os.path.join(SIM, "expansion_l2p00x.tif")
    e3 = os.path.join(SIM, "expansion_l3p00x.tif")
    if not (os.path.exists(init) and os.path.exists(DEFAULT_META)):
        pytest.skip("sim frames or grid_metadata.json missing")
    pr = ExpansionProject(initial_path=init, expansion_paths=[e2, e3],
                          out_dir=str(tmp_path_factory.mktemp("o")),
                          correction=CorrectionParams(**OPTICS))
    pr.process_all(); pr.pair_all()
    return pr


def _strain(project, name):
    key = next(k for k, v in project.pairings.items() if v.expansion_name == name)
    return project.strains[key]


def test_J_recovers_lambda_squared(project):
    s2 = strain.summary(_strain(project, "expansion_l2p00x"))
    s3 = strain.summary(_strain(project, "expansion_l3p00x"))
    assert abs(s2["J_median"] - 4.0) < 0.4          # lambda=2 -> J~4
    assert abs(s3["J_median"] - 9.0) < 1.0          # lambda=3 -> J~9


def test_principal_strain_small_relative_to_expansion(project):
    s = strain.summary(_strain(project, "expansion_l2p00x"))
    # after the (large) uniform expansion, residual anisotropy is comparatively small
    assert abs(s["max_shear_median"]) < 0.3


def test_strain_csv_written(project):
    d = os.path.join(project.out_dir, "pairing")
    assert os.path.exists(os.path.join(d, "strain_expansion_l2p00x_vs_initial.csv"))


def test_J_roughly_uniform(project):
    df = _strain(project, "expansion_l2p00x")
    J = df["J"].to_numpy(float)
    assert np.nanpercentile(J, 90) - np.nanpercentile(J, 10) < 1.5   # fairly uniform
