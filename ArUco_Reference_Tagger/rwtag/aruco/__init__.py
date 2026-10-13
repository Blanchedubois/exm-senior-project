"""
rwtag.aruco — ArUco recognition for the V2 print. NO Qt.

Phase 1 (docs/01_PHASE1_ARUCO_RECOGNITION.md): decode every tag in a frame with
its id, sub-pixel corners, centre, rotation, corner-order sign and a decode
confidence record; summarise the frame's pose; fit the design -> image affine
from the tag centres. Dot and dash detection arrive with Phase 3.
"""
from __future__ import annotations

from .design import Design, BoxSpec
from .tags import ArucoParams, TagObservation, decode_tags, detector
from .pose import FramePose, frame_pose, tag_handedness
from .fit import fit_affine

__all__ = ["Design", "BoxSpec", "ArucoParams", "TagObservation", "decode_tags", "detector",
           "FramePose", "frame_pose", "tag_handedness", "fit_affine"]
