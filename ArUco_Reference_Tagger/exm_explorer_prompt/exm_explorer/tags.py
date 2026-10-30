"""ArUco detection on fluorescence images (ported from check_tags.detect).

Printed material is bright, so the image is inverted before cv2.aruco. Post
images need a small minimum perimeter because the tags keep their printed
size while the image grows by lambda.
"""

import cv2
import numpy as np


def detect(img, min_perim=0.01):
    """Returns {aruco_id: (centre_xy_px, corners_4x2_px)}; corners in cv2
    order TL, TR, BR, BL. Use centres only for registration: tags are rigid."""
    im = np.asarray(img, np.float32)
    lo, hi = np.percentile(im, [1, 99.9])
    g = np.clip((im - lo) / max(hi - lo, 1e-9) * 255, 0, 255).astype(np.uint8)
    g = 255 - g                                   # printed bright -> black modules
    p = cv2.aruco.DetectorParameters()
    p.minMarkerPerimeterRate = min_perim
    det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), p)
    corners, ids, _ = det.detectMarkers(g)
    if ids is None:
        return {}
    return {int(i): (c.reshape(4, 2).mean(0), c.reshape(4, 2)) for i, c in zip(ids.ravel(), corners)}


def centres(found):
    return {i: v[0] for i, v in found.items()}


def min_perimeter_for(shape_px, tag_side_px):
    """minMarkerPerimeterRate that still admits a tag of tag_side_px in an
    image of shape_px (OpenCV normalises by the larger image side)."""
    return 0.6 * 4 * tag_side_px / max(shape_px)
