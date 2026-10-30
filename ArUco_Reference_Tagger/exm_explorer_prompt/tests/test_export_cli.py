"""Export bundle and the headless command-line runner."""

import csv
import json
import os

import numpy as np
import pytest
from PIL import Image

from exm_explorer import cli, export
from exm_explorer.scenario import PRESETS, Scenario


def test_image_roundtrip_16bit(tmp_path):
    img = (np.arange(64 * 80) * 13 % 65536).astype(np.uint16).reshape(64, 80)
    for ext in (".png", ".tif"):
        p = export.write_image(str(tmp_path / f"a{ext}"), img)
        if ext == ".png":
            back = np.array(Image.open(p))
        else:
            import tifffile
            back = tifffile.imread(p)
        assert back.dtype == np.uint16 and np.array_equal(back, img)


def test_apply_setting():
    sc = PRESETS["example"]()
    cli.apply_setting(sc, "imaging.lam", "10")
    cli.apply_setting(sc, "solver.nu", "0.45")
    cli.apply_setting(sc, "sites.1.eps1", "0.08")
    cli.apply_setting(sc, "imaging.noise", "false")
    cli.apply_setting(sc, "imaging.seed", "3")
    assert sc.imaging.lam == 10.0 and sc.solver.nu == 0.45 and sc.sites[1].eps1 == 0.08
    assert sc.imaging.noise is False and sc.imaging.seed == 3
    with pytest.raises(SystemExit):
        cli.apply_setting(sc, "imaging.nope", "1")


def test_scenario_json_roundtrip(tmp_path):
    sc = PRESETS["workshop: random"]()
    p = str(tmp_path / "s.json")
    sc.save(p)
    back = Scenario.load(p)
    assert back.to_dict() == sc.to_dict()


@pytest.mark.slow
def test_cli_writes_bundle_and_summary(tmp_path):
    out = str(tmp_path / "out")
    assert cli.main(["--preset", "exm_sim batch run", "--out", out]) == 0
    run = os.path.join(out, "exm_sim_batch_run")
    for f in ("scenario.json", "pre.png", "post.png", "features_truth.csv", "metrics.json"):
        assert os.path.isfile(os.path.join(run, f)), f
    with open(os.path.join(run, "features_truth.csv")) as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == export.TRUTH_COLUMNS and len(rows) == 1 + 18341
    m = json.load(open(os.path.join(run, "metrics.json")))
    ref = json.load(open(os.path.join(os.path.dirname(__file__), "..", "reference", "results.json")))
    assert set(ref) - {"ccf_after_acf_correction", "ccf_after_tag_correction"} <= set(m)
    assert abs(m["acf_global"]["scale"] - ref["acf_global"]["scale"]) < 1e-6
    post = np.array(Image.open(os.path.join(run, "post.png")))
    assert post.dtype == np.uint16 and post.shape == (6593, 6593)
    with open(os.path.join(out, "summary.csv")) as fh:
        s = list(csv.DictReader(fh))
    assert len(s) == 1 and abs(float(s[0]["tag_scale"]) - 3.979) < 0.002
