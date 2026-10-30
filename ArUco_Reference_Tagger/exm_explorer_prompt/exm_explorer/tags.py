"""ArUco detection on fluorescence images (ported from check_tags.detect).

Printed material is bright, so the image is inverted before cv2.aruco. Post
images need a small minimum perimeter because the tags keep their printed
size while the image grows by lambda.
"""

import cv2
import numpy as np


TILE_ABOVE_PX = 8192        # larger images are searched in overlapping tiles


def _detector(min_perim):
    p = cv2.aruco.DetectorParameters()
    p.minMarkerPerimeterRate = min_perim
    return cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), p)


def _to_u8(im, lo, hi):
    g = np.clip((np.asarray(im, np.float32) - lo) / max(hi - lo, 1e-9) * 255, 0, 255).astype(np.uint8)
    return 255 - g                                # printed bright -> black modules


def detect(img, min_perim=0.01, tile=2048, overlap=256):
    """Returns {aruco_id: (centre_xy_px, corners_4x2_px)}; corners in cv2
    order TL, TR, BR, BL. Use centres only for registration: tags are rigid.

    Images larger than TILE_ABOVE_PX (lambda ~10 post images) are searched in
    overlapping tiles, which keeps the memory down, with a white point suited
    to a frame that is almost all background. min_perim keeps
    its meaning (a fraction of the whole image's larger side)."""
    if max(img.shape) <= TILE_ABOVE_PX:
        im = np.asarray(img, np.float32)
        lo, hi = np.percentile(im, [1, 99.9])
        corners, ids, _ = _detector(min_perim).detectMarkers(_to_u8(im, lo, hi))
        if ids is None:
            return {}
        return {int(i): (c.reshape(4, 2).mean(0), c.reshape(4, 2)) for i, c in zip(ids.ravel(), corners)}
    h, w = img.shape
    # at high expansion the dots cover < 0.1 % of the frame, so the 99.9th
    # percentile is still background noise and stretching to it breaks the
    # tags' borders apart; the 99.99th sits on printed material
    lo, hi = np.percentile(np.asarray(img[::4, ::4], np.float32), [1, 99.99])
    min_abs = min_perim * max(h, w)              # minimum perimeter in px
    det = _detector(min(0.5, min_abs / tile))
    best = {}
    stride = tile - overlap
    for y0 in range(0, max(h - overlap, 1), stride):
        for x0 in range(0, max(w - overlap, 1), stride):
            sub = img[y0:y0 + tile, x0:x0 + tile]
            corners, ids, _ = det.detectMarkers(_to_u8(sub, lo, hi))
            if ids is None:
                continue
            for i, c in zip(ids.ravel(), corners):
                c = c.reshape(4, 2) + [x0, y0]
                ctr = c.mean(0)
                # keep the sighting farthest from its tile's edge
                margin = min(ctr[0] - x0, ctr[1] - y0, x0 + sub.shape[1] - ctr[0], y0 + sub.shape[0] - ctr[1])
                if int(i) not in best or margin > best[int(i)][2]:
                    best[int(i)] = (ctr, c, margin)
    return {i: (v[0], v[1]) for i, v in best.items()}


def centres(found):
    return {i: v[0] for i, v in found.items()}


def min_perimeter_for(shape_px, tag_side_px):
    """minMarkerPerimeterRate that still admits a tag of tag_side_px in an
    image of shape_px (OpenCV normalises by the larger image side)."""
    return 0.6 * 4 * tag_side_px / max(shape_px)
