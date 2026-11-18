"""
fieldkit.markers
================
Unify one image's detected ArUco tags + surviving dots into a single tagged
"markers" table. This is the table both sides of a pairing are joined on
(Phase 3). Each row has a canonical `tag_key` that means the same physical point
in every image.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

MARKER_COLS = ["type", "tag_key", "aruco_id", "box_i", "box_j", "local_i", "local_j",
               "img_x_px", "img_y_px", "px_per_um"]


def build(det, grid, feats) -> pd.DataFrame:
    """tags (from grid.nodes, detected) + dots (from feats, survived Stage 5)."""
    rows = []
    for n in grid.nodes:
        if n.status == "detected":
            rows.append({"type": "tag", "tag_key": f"T{n.aruco_id}", "aruco_id": n.aruco_id,
                         "box_i": np.nan, "box_j": np.nan, "local_i": np.nan, "local_j": np.nan,
                         "img_x_px": n.img_xy_px[0], "img_y_px": n.img_xy_px[1],
                         "px_per_um": grid.px_per_um})
    dots = feats[(feats["type"] == "dot") & (feats["status"] == "matched")]
    for _, r in dots.iterrows():
        bi, bj, li, lj = int(r["box_i"]), int(r["box_j"]), int(r["local_i"]), int(r["local_j"])
        rows.append({"type": "dot", "tag_key": f"D{bi}.{bj}.{li}.{lj}", "aruco_id": np.nan,
                     "box_i": bi, "box_j": bj, "local_i": li, "local_j": lj,
                     "img_x_px": r["img_x_px"], "img_y_px": r["img_y_px"],
                     "px_per_um": grid.px_per_um})
    return pd.DataFrame(rows, columns=MARKER_COLS)
