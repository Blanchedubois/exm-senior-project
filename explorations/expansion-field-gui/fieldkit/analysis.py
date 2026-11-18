"""
fieldkit.analysis
=================
Headless helpers that support the field view: summary statistics of a pairing
field and an interpolated magnitude map (for the heatmap background). Pure
compute -- no GUI. (Strain/J is a separate future module, per the scope.)
"""
from __future__ import annotations
import numpy as np


def _paired(field):
    return field[field["status"] == "paired"]


def field_summary(field) -> dict:
    p = _paired(field)
    def stat(col):
        v = p[col].to_numpy(float)
        return (float(np.nanmedian(v)), float(np.nanmax(v))) if len(v) else (float("nan"),) * 2
    fm, fx = stat("u_full_mag_um")
    rm, rx = stat("u_resid_mag_um")
    s = {"n_paired": int(len(p)),
         "n_unpaired_initial": int((field["status"] == "unpaired_initial").sum()),
         "n_unpaired_expansion": int((field["status"] == "unpaired_expansion").sum()),
         "full_median_um": fm, "full_max_um": fx,
         "resid_median_um": rm, "resid_max_um": rx}
    if "J" in p.columns:
        jm, jx = stat("J")
        s["J_median"], s["J_max"] = jm, jx
    return s


def interpolate_scalar(field, col, image_shape, step=6):
    """Interpolate a per-marker scalar column onto a regular grid over the image.
    Returns (Z, step); outside the marker hull -> NaN."""
    from scipy.interpolate import griddata
    p = _paired(field)
    xy = p[["x_init_px", "y_init_px"]].to_numpy(float)
    val = p[col].to_numpy(float)
    ok = np.isfinite(val)
    xy, val = xy[ok], val[ok]
    H, W = image_shape[:2]
    GX, GY = np.meshgrid(np.arange(0, W, step), np.arange(0, H, step))
    if len(xy) < 3:
        return np.full(GX.shape, np.nan), step
    return griddata(xy, val, (GX, GY), method="linear"), step


def interpolate_magnitude(field, mode, image_shape, step=6):
    """|u| (µm) heatmap grid. `mode` = "full" | "residual"."""
    return interpolate_scalar(field, f"u_{mode}_mag_um", image_shape, step)
