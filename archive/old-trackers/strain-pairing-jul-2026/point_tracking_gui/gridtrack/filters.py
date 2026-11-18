"""
gridtrack.filters  (Stage 5)
============================
Quality filters for the tracked points. Each filter MARKS offending dots
(status -> "filtered", with a `filter_reason`) rather than deleting rows, so the
record stays complete and auditable. Filters operate on matched dots.

The headline filter is minimum-separation: because the ArUco tags fix the image
scale (px/um) and the reference fixes the dot pitch (um), the EXPECTED dot
spacing in pixels is known; any two detected dots much closer than that are
spurious (merged blobs, a stray detection, a double-tag) and are discarded.

Headless: a FeatureTable + GridModel + Reference in, a FeatureTable out.
"""
from __future__ import annotations
from collections import Counter
import numpy as np

from .types import FilterParams
from .reference import transform_points


def _mad(v):
    med = np.nanmedian(v)
    return med, 1.4826 * np.nanmedian(np.abs(v - med)) + 1e-9


def _predicted_xy(feats, dot_idx, grid):
    """Box-homography prediction for each matched dot (aligned with dot_idx)."""
    pred = np.full((len(dot_idx), 2), np.nan)
    sub = feats.loc[dot_idx]
    for (bi, bj), Hb in grid.box_homographies.items():
        m = (sub["box_i"] == bi) & (sub["box_j"] == bj)
        if not m.any():
            continue
        ref = sub.loc[m, ["ref_x_um", "ref_y_um"]].to_numpy(float)
        pred[m.to_numpy()] = transform_points(Hb, ref)
    return pred


def apply_filters(feats, grid, reference, params: FilterParams = None, image_shape=None):
    """Return a copy of `feats` with failing matched-dots marked status='filtered'
    and a `filter_reason`. `feats.attrs['filter_counts']` summarises what was cut."""
    params = params or FilterParams()
    feats = feats.copy()
    if "filter_reason" not in feats.columns:
        feats["filter_reason"] = ""

    is_dot = (feats["type"] == "dot") & (feats["status"] == "matched")
    idx = feats.index[is_dot]
    if len(idx) == 0:
        feats.attrs["filter_counts"] = {}
        return feats
    xy = feats.loc[idx, ["img_x_px", "img_y_px"]].to_numpy(float)
    reason = {}                                          # DataFrame index -> first reason

    # 1. minimum separation (expected pitch from ArUco scale x reference dot pitch)
    if params.enable_proximity:
        from scipy.spatial import cKDTree
        pitch_px = reference.config["dot_pitch_um"] * grid.px_per_um
        min_sep = params.min_sep_frac * pitch_px
        for a, b in cKDTree(xy).query_pairs(min_sep):
            reason.setdefault(idx[a], "proximity")
            reason.setdefault(idx[b], "proximity")

    # 2. blob quality: robust gate on mass and size
    if params.enable_quality:
        for col in ("mass", "size"):
            if col in feats.columns:
                v = feats.loc[idx, col].to_numpy(float)
                med, mad = _mad(v)
                z = np.abs(v - med) / mad
                for k, i in enumerate(idx):
                    if np.isfinite(z[k]) and z[k] > params.quality_mad:
                        reason.setdefault(i, "quality")

    # 3. prediction residual (distance from the box homography)
    if params.enable_residual and grid.box_homographies:
        pred = _predicted_xy(feats, idx, grid)
        res = np.linalg.norm(xy - pred, axis=1)
        med, mad = _mad(res)
        thr = params.residual_max_px if params.residual_max_px > 0 else med + params.residual_mad * mad
        for k, i in enumerate(idx):
            if np.isfinite(res[k]) and res[k] > thr:
                reason.setdefault(i, "residual")

    # 4. neighbourhood smoothness (displacement vs local neighbours)
    if params.enable_smoothness and grid.box_homographies and len(idx) > params.neighbor_k:
        from scipy.spatial import cKDTree
        pred = _predicted_xy(feats, idx, grid)
        disp = xy - pred                                 # displacement field
        tree = cKDTree(xy)
        _, nn = tree.query(xy, k=params.neighbor_k + 1)  # includes self
        local_med = np.array([np.nanmedian(disp[nn[r, 1:]], axis=0) for r in range(len(xy))])
        dev = np.linalg.norm(disp - local_med, axis=1)
        med, mad = _mad(dev)
        thr = med + params.neighbor_mad * mad
        for k, i in enumerate(idx):
            if np.isfinite(dev[k]) and dev[k] > thr:
                reason.setdefault(i, "smoothness")

    # 5. border proximity
    if params.enable_border and image_shape is not None:
        h, w = image_shape[:2]
        b = params.border_px
        for k, i in enumerate(idx):
            x, y = xy[k]
            if x < b or y < b or x > w - b or y > h - b:
                reason.setdefault(i, "border")

    for i, r in reason.items():
        feats.at[i, "status"] = "filtered"
        feats.at[i, "filter_reason"] = r
    feats.attrs["filter_counts"] = dict(Counter(reason.values()))
    feats.attrs["n_filtered"] = len(reason)
    feats.attrs["n_survivors"] = int(len(idx) - len(reason))
    return feats
