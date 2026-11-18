"""Validate Phase-5 polish: headless CLI batch runner + project session round-trip."""
import os
import warnings
import pytest

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
import sys
sys.path.insert(0, ROOT)

from fieldkit import cli
from fieldkit.project import ExpansionProject, DEFAULT_META

SIM = os.path.normpath(os.path.join(ROOT, "..", "expansion_camera_sim", "tiffs"))


def _skip_if_missing():
    if not (os.path.exists(os.path.join(SIM, "expansion_l1p00x.tif")) and os.path.exists(DEFAULT_META)):
        pytest.skip("sim frames or grid_metadata.json missing")


def test_cli_runs_stages_and_pairing(tmp_path):
    _skip_if_missing()
    out = str(tmp_path / "out")
    args = cli.build_parser().parse_args([
        "--initial", os.path.join(SIM, "expansion_l1p00x.tif"),
        "--expansions", os.path.join(SIM, "expansion_l2p00x.tif"),
        "--out", out, "--vig-strength", "0.88", "--vig-power", "1.8",
        "--k1", "-0.05", "--k2", "-0.01"])
    pr = cli.run(args)
    assert len(pr.results) == 2 and len(pr.pairings) == 1
    assert os.path.exists(os.path.join(out, "pairing",
                                       "pairing_expansion_l2p00x_vs_initial.csv"))
    assert os.path.exists(os.path.join(out, "pairing",
                                       "strain_expansion_l2p00x_vs_initial.csv"))
    assert abs(list(pr.pairings.values())[0].lambda_rel - 2.0) < 0.1


def test_project_session_round_trip(tmp_path):
    _skip_if_missing()
    out = str(tmp_path / "out2")
    args = cli.build_parser().parse_args([
        "--initial", os.path.join(SIM, "expansion_l1p00x.tif"),
        "--expansions", os.path.join(SIM, "expansion_l2p00x.tif"),
        "--out", out, "--vig-strength", "0.88", "--k1", "-0.05", "--no-pair"])
    cli.run(args)
    pr2 = ExpansionProject.load_project_json(out)
    assert os.path.basename(pr2.initial_path) == "expansion_l1p00x.tif"
    assert len(pr2.expansion_paths) == 1
    assert abs(pr2.correction.vig_strength - 0.88) < 1e-6
    assert abs(pr2.correction.k1 - (-0.05)) < 1e-6
