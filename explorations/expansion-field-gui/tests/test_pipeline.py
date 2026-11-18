"""
Validate Phase-1: per-image batch processing + per-stage CSV output.
Runs the initial + one expansion image through all 5 stages and checks the CSVs.
"""
import os
import warnings
import pytest

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
import sys
sys.path.insert(0, ROOT)

from fieldkit.project import ExpansionProject, DEFAULT_META
from gridtrack.types import CorrectionParams

SIM = os.path.normpath(os.path.join(ROOT, "..", "expansion-camera-sim", "tiffs"))
OPTICS = dict(vig_strength=0.88, vig_power=1.8, k1=-0.05, k2=-0.01)


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    init = os.path.join(SIM, "expansion_l1p00x.tif")
    exp = os.path.join(SIM, "expansion_l2p00x.tif")
    if not (os.path.exists(init) and os.path.exists(DEFAULT_META)):
        pytest.skip("sim frames or grid_metadata.json missing")
    out = str(tmp_path_factory.mktemp("out"))
    pr = ExpansionProject(initial_path=init, expansion_paths=[exp], out_dir=out,
                          correction=CorrectionParams(**OPTICS))
    pr.process_all()
    return pr


def test_all_images_processed(project):
    assert len(project.results) == 2
    for res in project.results.values():
        assert len(res.markers) > 100          # tags + dots


def test_per_stage_csvs_written(project):
    import pandas as pd
    for path in project.all_paths():
        name = os.path.splitext(os.path.basename(path))[0]
        d = os.path.join(project.out_dir, name)
        for fn in ["stage1_correction.csv", "stage2_tags.csv", "stage3_nodes.csv",
                   "stage4_features.csv", "stage5_features_filtered.csv", "markers.csv"]:
            fp = os.path.join(d, fn)
            assert os.path.exists(fp), fn
            assert len(pd.read_csv(fp)) >= 1


def test_markers_table_has_tags_and_dots(project):
    res = project.results[project.initial_path]
    mk = res.markers
    assert (mk["type"] == "tag").sum() >= 20
    assert (mk["type"] == "dot").sum() > 1000
    assert mk["tag_key"].is_unique               # every physical point once


def test_project_json_written(project):
    assert os.path.exists(os.path.join(project.out_dir, "project.json"))
