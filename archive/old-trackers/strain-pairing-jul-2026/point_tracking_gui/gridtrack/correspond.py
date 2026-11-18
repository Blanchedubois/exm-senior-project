"""
gridtrack.correspond
=====================
Assignment helpers shared by Stages 3-4. Headless.
"""
from __future__ import annotations
import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.spatial.distance import cdist


def assign_hungarian(det_xy, pred_xy, max_dist):
    """Optimal 1-to-1 assignment of detected -> predicted points, gated by
    max_dist. Returns list of (det_index, pred_index) pairs within the gate."""
    det_xy = np.asarray(det_xy, float).reshape(-1, 2)
    pred_xy = np.asarray(pred_xy, float).reshape(-1, 2)
    if len(det_xy) == 0 or len(pred_xy) == 0:
        return []
    C = cdist(det_xy, pred_xy)
    big = C.max() + max_dist + 1.0
    Cg = np.where(C <= max_dist, C, big)
    ri, ci = linear_sum_assignment(Cg)
    return [(int(r), int(c)) for r, c in zip(ri, ci) if C[r, c] <= max_dist]
