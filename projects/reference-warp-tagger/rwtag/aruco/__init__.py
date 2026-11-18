"""
rwtag.aruco — Stage-2 for the V2 (ArUco) print. NO Qt.

Replaces glyph reading with `cv2.aruco` decode: every decoded tag IS its node, so
the registration (orientation + offset) that Stage 2 used to vote for from digit
reads is read directly, and the design -> image affine is fitted from tag corners.
Everything downstream (refwarp.warp / tagmatch / tagframe, dotfilter, pairing,
strain) is unchanged: `detect()` returns the same DetectResult the glyph path does.

Detector requirements R16 (aruco-marker-design/workshop/docs/WORKSHOP_PLAN.md):
  no CLAHE · errorCorrectionRate = 1.0 · un-distortion edge band excluded ·
  Gaussian-refined dot centres · top-hat sized to the imaged FWHM.
"""
from __future__ import annotations

from .detect import ArucoParams, Design, detect, decode_tags, fit_affine
from . import series

__all__ = ["ArucoParams", "Design", "detect", "decode_tags", "fit_affine", "series"]
