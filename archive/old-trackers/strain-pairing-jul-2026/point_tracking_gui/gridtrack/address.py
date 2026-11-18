"""
gridtrack.address  (Stage 2)
============================
Find every ArUco tag, read its number, and rotate the image so all tags are
vertically upright.

Runs on the Stage-1-corrected image. Headless: arrays in, `MarkerDetection` out.
"""
from __future__ import annotations
import numpy as np
import cv2
import cv2.aruco as aruco

from .types import CorrectionParams, MarkerDetection
from .io import to_uint8

_SUBPIX = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.01)


def get_dictionary(name: str):
    return aruco.getPredefinedDictionary(getattr(aruco, name))


def preprocess_for_aruco(img: np.ndarray, p: CorrectionParams, invert: bool | None = None):
    """Float image -> uint8 tuned for ArUco: (optionally) invert fluorescence so
    tags are dark-bordered on light, then CLAHE for local contrast."""
    u8 = to_uint8(img)
    if (p.invert if invert is None else invert):
        u8 = 255 - u8
    if p.clahe_clip and p.clahe_clip > 0:
        u8 = cv2.createCLAHE(p.clahe_clip, (8, 8)).apply(u8)
    return u8


def detect_markers(u8: np.ndarray, dict_name: str, refine: bool = True):
    """Detect + decode tags on a uint8 image. Returns (ids, corners, centers)."""
    det = aruco.ArucoDetector(get_dictionary(dict_name), aruco.DetectorParameters())
    corners, ids, _ = det.detectMarkers(u8)
    out_ids, out_corners, out_centers = [], {}, {}
    if ids is None:
        return np.array([], int), out_corners, out_centers
    for k, idv in enumerate(ids.flatten()):
        c = corners[k].reshape(4, 2).astype(np.float32)
        if refine:
            cc = c.reshape(-1, 1, 2).copy()
            cv2.cornerSubPix(u8, cc, (5, 5), (-1, -1), _SUBPIX)
            c = cc.reshape(4, 2)
        out_ids.append(int(idv))
        out_corners[int(idv)] = c
        out_centers[int(idv)] = c.mean(0)
    order = np.argsort(out_ids)
    ids_sorted = np.array(out_ids, int)[order]
    return ids_sorted, out_corners, out_centers


def marker_angle(corner: np.ndarray) -> float:
    """Angle (rad) of a tag's top edge (top-left -> top-right). ArUco returns
    corners in canonical order, so this equals the image rotation of that tag."""
    v = corner[1] - corner[0]
    return float(np.arctan2(v[1], v[0]))


def global_rotation(corners: dict) -> float:
    """Circular-mean tag tilt across all tags (degrees). Robust because the grid
    is rigid, so every tag shares the same rotation."""
    if not corners:
        return 0.0
    angs = np.array([marker_angle(c) for c in corners.values()])
    mean = np.arctan2(np.sin(angs).mean(), np.cos(angs).mean())
    return float(np.degrees(mean))


def rotate_expand(img: np.ndarray, theta_deg: float, border: float = 0.0, return_M=False):
    """Rotate about the centre, growing the canvas so nothing is clipped.
    With return_M=True also returns the 2x3 affine used (identity if no rotation)."""
    if abs(theta_deg) < 1e-6:
        M = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        return (img, M) if return_M else img
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), theta_deg, 1.0)
    cos, sin = abs(M[0, 0]), abs(M[0, 1])
    nW, nH = int(h * sin + w * cos), int(h * cos + w * sin)
    M[0, 2] += (nW - w) / 2.0
    M[1, 2] += (nH - h) / 2.0
    out = cv2.warpAffine(img, M, (nW, nH), flags=cv2.INTER_LINEAR, borderValue=border)
    return (out, M) if return_M else out


def _apply_affine(M, pts):
    """Apply a 2x3 affine to (N,2) points."""
    pts = np.asarray(pts, float).reshape(-1, 2)
    return pts @ M[:, :2].T + M[:, 2]


def detect_and_orient(img: np.ndarray, dict_name: str,
                      p: CorrectionParams) -> MarkerDetection:
    """The one Stage-2 entry point: detect tags (either polarity), estimate the
    global tilt, and rotate the image upright. Works with a SINGLE tag.

    The upright corners are obtained by transforming the detected corners through
    the rotation (exact) rather than re-detecting -- re-detection could drop a
    lone tag (rotation blur / wrong polarity) and lose the only anchor."""
    ids, corners, centers = detect_markers(preprocess_for_aruco(img, p), dict_name)

    # polarity fallback: if few decoded, try the other contrast and keep the best
    if len(ids) < 2:
        idsb, cornersb, centersb = detect_markers(
            preprocess_for_aruco(img, p, invert=not p.invert), dict_name)
        if len(idsb) > len(ids):
            ids, corners, centers = idsb, cornersb, centersb

    if len(ids) == 0:                              # no anchor at all -> flag (Stage 3 handles)
        return MarkerDetection(img.astype(np.float32), ids, corners, centers,
                               0.0, dict_name, 0.0)

    theta = global_rotation(corners)               # measured tag tilt (y-down atan2)
    oriented, M = rotate_expand(img.astype(np.float32), theta,
                                border=float(np.median(img)), return_M=True)
    # carry the corners into the upright frame analytically (never loses the tag)
    corners_o = {i: _apply_affine(M, corners[i]) for i in corners}
    centers_o = {i: _apply_affine(M, centers[i]).ravel() for i in centers}
    residual = global_rotation(corners_o)
    return MarkerDetection(oriented, ids, corners_o, centers_o, theta, dict_name, residual)
