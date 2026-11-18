"""
Validate Stage-3 grid mapping against the simulator + its grid_metadata.json.

Every decoded tag must map to the correct (node_i,node_j); the global fit must be
consistent (recovered scale ~ the camera px/um), and undetected reference nodes
must be predicted.
"""
import os
import numpy as np
import pytest

from gridtrack import io, correct, address, reference
from gridtrack.types import CorrectionParams

OPTICS = dict(vig_strength=0.88, vig_power=1.8, k1=-0.05, k2=-0.01)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM = os.path.normpath(os.path.join(ROOT, "..", "expansion-camera-sim"))
META = os.path.normpath(os.path.join(ROOT, "..", "hydrogel_marker_analysis",
                                     "toolkit", "grid_metadata.json"))


def _grid_for(name, model="similarity"):
    fp = os.path.join(SIM, "tiffs", name)
    if not (os.path.exists(fp) and os.path.exists(META)):
        pytest.skip("sim frames or grid_metadata.json missing")
    p = CorrectionParams(**OPTICS)
    img = correct.apply(io.load_tiff(fp), p)
    det = address.detect_and_orient(img, "DICT_6X6_1000", p)
    ref = reference.load(META)
    return det, ref, reference.map_grid(det, ref, model=model)


def test_all_detected_nodes_get_correct_ij():
    det, ref, grid = _grid_for("expansion_l1p00x.tif")
    assert grid.n_total == len(ref.nodes)
    assert grid.n_detected >= 24
    for nd in grid.nodes:
        if nd.status == "detected":
            r = ref.id_to_node[nd.aruco_id]
            assert (nd.node_i, nd.node_j) == (r["node_i"], r["node_j"])


def test_recovered_scale_and_low_residual():
    det, ref, grid = _grid_for("expansion_l1p00x.tif")
    # sim camera is 8 px/um; corrected frame preserves scale
    assert 6.0 < grid.px_per_um < 10.0
    # global similarity residual is the (minimal) warp -> a handful of px
    assert grid.rms_residual_px < 20.0


def test_missing_nodes_are_predicted_and_boxes_have_homographies():
    # at lambda=2 only ~9 tags are in-FOV; the rest must be predicted, not dropped
    det, ref, grid = _grid_for("expansion_l2p00x.tif")
    n_pred = sum(1 for nd in grid.nodes if nd.status == "predicted")
    assert grid.n_detected + n_pred == grid.n_total
    assert n_pred > 0
    assert len(grid.box_homographies) >= 1


def test_single_marker_tier_maps_grid():
    # lambda=5 frame shows ~1 tag -> single-marker tier must produce a usable grid
    import warnings; warnings.filterwarnings("ignore")
    from gridtrack import measure
    from gridtrack.types import MeasureParams
    det, ref, _ = _grid_for("expansion_l5p00x.tif")
    dots_xy = measure.detect_dots(det.image, MeasureParams())[["x", "y"]].to_numpy()
    grid = reference.map_grid(det, ref, dots_xy=dots_xy)
    assert grid.method == "single_marker"
    assert 4.0 < grid.lambda_local < 6.0                 # recovered local expansion ~5
    assert len(grid.box_homographies) >= 4               # region-grew to several boxes
    assert grid.box_confidence                            # confidences reported


def test_single_marker_tags_dots_accurately():
    import warnings; warnings.filterwarnings("ignore")
    import numpy as np
    from gridtrack import measure
    from gridtrack.reference import transform_points
    from gridtrack.types import MeasureParams
    det, ref, _ = _grid_for("expansion_l5p00x.tif")
    dots_xy = measure.detect_dots(det.image, MeasureParams())[["x", "y"]].to_numpy()
    grid = reference.map_grid(det, ref, dots_xy=dots_xy)
    feats = measure.detect_features(det.image, grid, ref, MeasureParams())
    m = feats[(feats["type"] == "dot") & (feats["status"] == "matched")]
    on = 0
    for (bi, bj), Hb in grid.box_homographies.items():
        s = m[(m["box_i"] == bi) & (m["box_j"] == bj)]
        if len(s) == 0:
            continue
        pr = transform_points(Hb, s[["ref_x_um", "ref_y_um"]].to_numpy())
        on += int((np.linalg.norm(pr - s[["img_x_px", "img_y_px"]].to_numpy(), axis=1) < 4).sum())
    assert on / max(len(m), 1) > 0.85                    # region-grow tags accurately


def test_zero_tags_is_unanchored():
    det, ref, _ = _grid_for("expansion_l1p00x.tif")
    det.ids = det.ids[:0]                                 # simulate no tags
    grid = reference.map_grid(det, ref, dots_xy=None)
    assert grid.method == "unanchored"
    assert len(grid.box_homographies) == 0
