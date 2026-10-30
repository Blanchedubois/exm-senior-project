"""Acceptance test 1: frames and tag decoding."""

import numpy as np
import pytest

from exm_explorer import frames, sim, tags
from exm_explorer.scenario import Imaging


def test_design_sample_roundtrip():
    rng = np.random.default_rng(0)
    xy = rng.uniform(0, 750, (100, 2))
    assert np.allclose(frames.sample_to_design(frames.design_to_sample(xy)), xy)
    # y flips: the bottom-left design corner is the bottom-left image corner
    assert np.allclose(frames.design_to_sample([[0.0, 0.0]]), [[0.0, 750.0]])


@pytest.mark.parametrize("scale,theta", [(1.0, 0.6), (4.0, 4.0), (10.0, -31.0)])
def test_design_image_roundtrip_and_handedness(scale, theta):
    p = frames.Placement(scale, theta, (30.0, -20.0), 4000)
    rng = np.random.default_rng(1)
    xy = rng.uniform(0, 750, (200, 2))
    px = p.design_to_px(xy)
    assert np.allclose(p.px_to_design(px), xy, atol=1e-9)
    A, b = p.design_affine()
    assert np.allclose(xy @ A.T + b, px)
    assert frames.handedness(p) == -1
    # a fitted affine design -> px must find the reflection too
    A2, _ = frames.fit_affine(xy, px)
    assert np.sign(np.linalg.det(A2)) == -1


def test_placements_match_exm_sim_sizes():
    pre, post = sim.placements(Imaging())
    assert (pre.size_px, post.size_px) == (1569, 6593)
    assert abs(sim.placements(Imaging(lam=10.0))[1].size_px - 16000) < 20   # brief: ~16,000 px


def _check_tags(img, isl_px, grid, min_perim):
    found = tags.detect(img, min_perim)
    truth = {int(grid.aruco_id[k]): isl_px[k] for k in grid.tags}
    assert set(found) == set(truth), f"decoded {sorted(found)}"
    err = [np.hypot(*(found[i][0] - truth[i])) for i in truth]
    return max(err)


@pytest.mark.slow
def test_all_tags_decode_pre_and_post(legacy_sim, grid):
    pos = legacy_sim.positions
    assert _check_tags(legacy_sim.pre, pos.pre_px, grid, 0.01) < 1.0
    assert _check_tags(legacy_sim.post, pos.post_px, grid, 0.003) < 1.5
