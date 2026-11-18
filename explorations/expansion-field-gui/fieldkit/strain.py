"""
fieldkit.strain  (Phase 6)
=========================
Local strain / areal expansion from a pairing's displacement field.

For each paired marker, fit the deformation gradient F from its k nearest
neighbours (least squares  dx = F·dX, where dX are initial-frame neighbour
offsets and dx are the rigid-aligned deformed offsets X_init + u_full), then:

    J   = det F                      areal expansion   (~ lambda^2 for uniform)
    E   = 0.5 (F^T F - I)            Green-Lagrange strain
    E1,E2 = eigenvalues of E         principal strains
    max_shear = (E1 - E2) / 2

Using u_full (rigid motion already removed) means F carries the true local
deformation, so J is the physical areal expansion. Headless.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

STRAIN_COLS = ["tag_key", "type", "F00", "F01", "F10", "F11",
               "J", "E1", "E2", "max_shear", "status"]


def compute(field, k=8) -> pd.DataFrame:
    from scipy.spatial import cKDTree
    p = field[field["status"] == "paired"].reset_index(drop=True)
    if len(p) < 4:
        return pd.DataFrame(columns=STRAIN_COLS)
    Xi = p[["x_init_px", "y_init_px"]].to_numpy(float)
    Xd = Xi + p[["u_full_x_px", "u_full_y_px"]].to_numpy(float)   # rigid-aligned deformed
    kk = min(k, len(Xi) - 1)
    _, nn = cKDTree(Xi).query(Xi, k=kk + 1)

    rows = []
    for i in range(len(Xi)):
        idx = nn[i, 1:]
        dX = Xi[idx] - Xi[i]
        dx = Xd[idx] - Xd[i]
        F = np.linalg.lstsq(dX, dx, rcond=None)[0].T             # 2x2 (dx = F dX)
        J = float(np.linalg.det(F))
        E = 0.5 * (F.T @ F - np.eye(2))
        ev = np.sort(np.linalg.eigvalsh(E))                      # ascending
        rows.append({"tag_key": p["tag_key"].iloc[i], "type": p["type"].iloc[i],
                     "F00": F[0, 0], "F01": F[0, 1], "F10": F[1, 0], "F11": F[1, 1],
                     "J": J, "E1": float(ev[1]), "E2": float(ev[0]),
                     "max_shear": float((ev[1] - ev[0]) / 2), "status": "ok"})
    return pd.DataFrame(rows, columns=STRAIN_COLS)


def summary(strain_df) -> dict:
    if len(strain_df) == 0:
        return {"n": 0}
    J = strain_df["J"].to_numpy(float)
    return {"n": int(len(strain_df)),
            "J_median": float(np.nanmedian(J)), "J_mean": float(np.nanmean(J)),
            "J_min": float(np.nanmin(J)), "J_max": float(np.nanmax(J)),
            "E1_median": float(np.nanmedian(strain_df["E1"])),
            "max_shear_median": float(np.nanmedian(strain_df["max_shear"]))}


def merge_into_field(field, strain_df):
    """Attach J / E1 / E2 columns to the pairing field (on tag_key) for display."""
    out = field.drop(columns=[c for c in ("J", "E1", "E2", "max_shear") if c in field.columns])
    return out.merge(strain_df[["tag_key", "J", "E1", "E2", "max_shear"]],
                     on="tag_key", how="left")
