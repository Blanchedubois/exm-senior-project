"""
fieldkit.pairing  (Phase 3 -- the core deliverable)
==================================================
Pair the markers of the INITIAL image to the markers of one EXPANSION image by
their tags, and produce the expansion displacement vector field.

Correspondence is a table join on `tag_key` (ArUco tags and dots both carry an
absolute address). The registration is fit on the shared TAGS (robust), and each
shared marker gets TWO displacement vectors, in BOTH px and µm:

  * full displacement  u_full  = R_rigid(X_exp) - X_init   (rigid-aligned: keeps
        the expansion; shows the gel spreading)
  * residual warpage   u_resid = G_sim(X_exp)  - X_init    (similarity-aligned:
        mean expansion+rotation removed; local non-uniform part)

Headless: two markers tables in, a PairingResult (field DataFrame + summary) out.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
import cv2

PAIRING_COLS = [
    "tag_key", "type", "aruco_id", "box_i", "box_j", "local_i", "local_j",
    "x_init_px", "y_init_px", "x_exp_px", "y_exp_px",
    "u_full_x_px", "u_full_y_px", "u_full_x_um", "u_full_y_um", "u_full_mag_um",
    "u_resid_x_px", "u_resid_y_px", "u_resid_x_um", "u_resid_y_um", "u_resid_mag_um",
    "status"]


@dataclass
class PairingResult:
    expansion_name: str
    field: pd.DataFrame            # one row per marker (paired + unpaired)
    lambda_rel: float             # relative expansion factor (expanded / initial)
    rotation_deg: float           # inter-frame rotation
    rms_px: float                 # registration residual on the fit points
    px_per_um: float
    n_tags: int                   # shared tags
    n_dots: int                   # shared dots
    n_inliers: int

    def summary_row(self):
        return {"expansion_name": self.expansion_name, "lambda_rel": self.lambda_rel,
                "rotation_deg": self.rotation_deg, "rms_px": self.rms_px,
                "px_per_um": self.px_per_um, "n_tags": self.n_tags,
                "n_dots": self.n_dots, "n_inliers": self.n_inliers}


def _apply(M, pts):
    pts = np.asarray(pts, float).reshape(-1, 2)
    return pts @ M[:2, :2].T + M[:2, 2]


def _fit_similarity(src, dst, thresh):
    """Fit similarity src->dst (RANSAC). Returns (2x3 M, inlier mask)."""
    src = np.asarray(src, np.float32); dst = np.asarray(dst, np.float32)
    M, mask = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
                                          ransacReprojThreshold=thresh)
    if M is None:                                     # RANSAC failed -> least squares
        M, mask = cv2.estimateAffinePartial2D(src, dst, method=cv2.LMEDS)
    inl = mask.ravel().astype(bool) if mask is not None else np.ones(len(src), bool)
    return np.asarray(M, float), inl


def pair(initial_markers, expansion_markers, expansion_name, ransac_thresh=4.0) -> PairingResult:
    m = initial_markers.merge(expansion_markers, on="tag_key", how="outer",
                              suffixes=("_I", "_E"), indicator=True)
    for col in ("type", "aruco_id", "box_i", "box_j", "local_i", "local_j"):
        m[col] = m[f"{col}_I"].where(m[f"{col}_I"].notna(), m[f"{col}_E"])

    both = (m["_merge"] == "both").to_numpy()
    if both.sum() < 2:
        raise ValueError(f"only {both.sum()} shared markers with {expansion_name}")
    XI = m.loc[both, ["img_x_px_I", "img_y_px_I"]].to_numpy(float)
    XE = m.loc[both, ["img_x_px_E", "img_y_px_E"]].to_numpy(float)
    is_tag = (m.loc[both, "type"] == "tag").to_numpy()

    # fit the registration on shared TAGS if enough, else on all shared markers
    if is_tag.sum() >= 4:
        src, dst = XE[is_tag], XI[is_tag]
    else:
        src, dst = XE, XI
    G, inl = _fit_similarity(src, dst, ransac_thresh)      # G: expanded -> initial (similarity)

    a, b = G[0, 0], G[1, 0]
    c = float(np.hypot(a, b))                              # scale
    rotation = float(np.degrees(np.arctan2(b, a)))
    lam = float(1.0 / c) if c > 1e-9 else float("nan")    # expanded is larger by ~1/c
    Rr = G[:2, :2] / c                                     # pure rotation
    muE, muI = src.mean(0), dst.mean(0)
    R = np.zeros((2, 3)); R[:2, :2] = Rr; R[:2, 2] = muI - Rr @ muE   # rigid (no scale)

    u_full = _apply(R, XE) - XI
    u_resid = _apply(G, XE) - XI
    s = float(np.nanmedian(m["px_per_um_I"]))
    fit_pred = _apply(G, src)
    rms = float(np.sqrt(((fit_pred - dst)[inl] ** 2).sum(1).mean())) if inl.any() else float("nan")

    # assemble the field table (paired rows carry vectors; unpaired recorded w/ NaN)
    n = len(m)
    out = pd.DataFrame(index=m.index)
    out["tag_key"] = m["tag_key"]; out["type"] = m["type"]
    out["aruco_id"] = m["aruco_id"]
    out["box_i"] = m["box_i"]; out["box_j"] = m["box_j"]
    out["local_i"] = m["local_i"]; out["local_j"] = m["local_j"]
    out["x_init_px"] = m["img_x_px_I"]; out["y_init_px"] = m["img_y_px_I"]
    out["x_exp_px"] = m["img_x_px_E"]; out["y_exp_px"] = m["img_y_px_E"]
    for col in PAIRING_COLS:
        if col not in out:
            out[col] = np.nan
    bi = np.where(both)[0]
    out.iloc[bi, out.columns.get_indexer(["u_full_x_px", "u_full_y_px"])] = u_full
    out.iloc[bi, out.columns.get_indexer(["u_resid_x_px", "u_resid_y_px"])] = u_resid
    out.iloc[bi, out.columns.get_indexer(["u_full_x_um", "u_full_y_um"])] = u_full / s
    out.iloc[bi, out.columns.get_indexer(["u_resid_x_um", "u_resid_y_um"])] = u_resid / s
    out.iloc[bi, out.columns.get_indexer(["u_full_mag_um"])] = np.hypot(u_full[:, 0], u_full[:, 1])[:, None] / s
    out.iloc[bi, out.columns.get_indexer(["u_resid_mag_um"])] = np.hypot(u_resid[:, 0], u_resid[:, 1])[:, None] / s
    status = np.where(both, "paired",
                      np.where(m["_merge"].to_numpy() == "left_only",
                               "unpaired_initial", "unpaired_expansion"))
    out["status"] = status
    out = out[PAIRING_COLS].reset_index(drop=True)

    return PairingResult(expansion_name, out, lam, rotation, rms, s,
                         int(is_tag.sum()), int((~is_tag).sum()), int(inl.sum()))
