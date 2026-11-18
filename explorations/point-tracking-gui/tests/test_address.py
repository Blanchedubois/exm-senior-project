"""
Validate Stage-2 detection + orientation against the simulator.

The simulator rotates stage k by  2 + 3k  degrees (accumulating). After Stage-1
correction, Stage 2 should decode all in-frame tags, recover that rotation, and
leave the image with ~0 residual tilt (tags upright).
"""
import os
import numpy as np
import pytest

from gridtrack import io, correct, address
from gridtrack.types import CorrectionParams

OPTICS = dict(vig_strength=0.88, vig_power=1.8, k1=-0.05, k2=-0.01)
SIM = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "expansion-camera-sim"))


def _load_corrected(name):
    p = os.path.join(SIM, "tiffs", name)
    if not os.path.exists(p):
        pytest.skip("expansion-camera-sim frames not generated")
    raw = io.load_tiff(p)
    return correct.apply(raw, CorrectionParams(**OPTICS))


def test_detects_all_tags_lambda1():
    img = _load_corrected("expansion_l1p00x.tif")
    det = address.detect_and_orient(img, "DICT_6X6_1000", CorrectionParams(**OPTICS))
    assert len(det.ids) >= 24                     # ~all 25 in-frame tags
    assert len(set(det.ids.tolist())) == len(det.ids)   # no duplicate ids


@pytest.mark.parametrize("name,applied", [
    ("expansion_l1p00x.tif", 2.0),
    ("expansion_l2p00x.tif", 8.0),
    ("expansion_l3p00x.tif", 14.0),
])
def test_recovers_rotation_and_orients_upright(name, applied):
    img = _load_corrected(name)
    det = address.detect_and_orient(img, "DICT_6X6_1000", CorrectionParams(**OPTICS))
    # recovered global rotation magnitude matches the simulator's applied angle
    assert abs(abs(det.theta_deg) - applied) < 1.5, (name, det.theta_deg)
    # after orienting, the tags are upright (near-zero residual tilt)
    assert abs(det.residual_deg) < 0.6, (name, det.residual_deg)


def test_orientation_makes_tags_upright_directly():
    img = _load_corrected("expansion_l3p00x.tif")
    det = address.detect_and_orient(img, "DICT_6X6_1000", CorrectionParams(**OPTICS))
    # measure tilt directly on the returned (oriented) corners
    tilt = address.global_rotation(det.corners)
    assert abs(tilt) < 0.6


def test_single_tag_sim_frame_detects_and_orients():
    # high-expansion frames have ~1 tag in view -> must still detect + orient
    img = _load_corrected("expansion_l5p00x.tif")
    det = address.detect_and_orient(img, "DICT_6X6_1000", CorrectionParams(**OPTICS))
    assert len(det.ids) >= 1
    assert abs(det.residual_deg) < 0.6                # upright


def test_single_plain_tag_both_polarities():
    # a lone black-on-white tag must decode even with the default invert=True
    import cv2, cv2.aruco as aruco
    d = aruco.getPredefinedDictionary(aruco.DICT_6X6_1000)
    canvas = np.full((600, 600), 255, np.uint8)
    canvas[180:420, 180:420] = aruco.generateImageMarker(d, 7, 240)
    canvas = cv2.warpAffine(canvas, cv2.getRotationMatrix2D((300, 300), 12, 1.0),
                            (600, 600), borderValue=255)          # tilt 12 deg
    for inv in (True, False):
        det = address.detect_and_orient(canvas.astype(np.float32), "DICT_6X6_1000",
                                        CorrectionParams(invert=inv))
        assert list(det.ids) == [7], f"invert={inv}"
        assert abs(address.global_rotation(det.corners)) < 0.5   # oriented upright
