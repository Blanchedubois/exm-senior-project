"""Measurements: line profiles, region statistics, photobleaching, colocalisation.

Coordinates passed in are image pixel coordinates (x = column, y = row);
the GUI converts from view coordinates by removing each channel's display
offset.  All functions are pure numpy/scipy so they can be tested and
scripted without the GUI.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import ndimage
from scipy.optimize import curve_fit
from skimage.filters import threshold_otsu

SATURATION_ADU = 65535
MIN_BLEACH_FRACTION = 0.02  # below a 2% drop there is nothing meaningful to fit


# ---- line profile --------------------------------------------------------
def line_profile(img: np.ndarray, p0: tuple[float, float], p1: tuple[float, float],
                 step: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Values along p0 -> p1 (x, y), sampled every `step` px with bilinear
    interpolation. Returns (distance_px, values); outside the image is NaN."""
    (x0, y0), (x1, y1) = p0, p1
    length = math.hypot(x1 - x0, y1 - y0)
    n = max(2, int(round(length / step)) + 1)
    t = np.linspace(0.0, 1.0, n)
    xs, ys = x0 + t * (x1 - x0), y0 + t * (y1 - y0)
    # pixel (i, j) covers [j, j+1) x [i, i+1); its centre is (j + 0.5, i + 0.5)
    vals = ndimage.map_coordinates(img.astype(np.float32), [ys - 0.5, xs - 0.5], order=1,
                                   mode="constant", cval=np.nan)
    return t * length, vals


# ---- region statistics ---------------------------------------------------
def clip_rect(rect: tuple[float, float, float, float], shape) -> tuple[int, int, int, int] | None:
    """(x, y, w, h) -> integer rect inside the image, or None if it misses.
    Edges round to the nearest pixel boundary, so a box keeps its pixel count
    when an alignment offset moves it by a fraction of a pixel."""
    x, y, w, h = rect
    rnd = lambda v: int(math.floor(v + 0.5))  # noqa: E731
    x0, y0 = max(0, rnd(x)), max(0, rnd(y))
    x1, y1 = min(shape[1], rnd(x) + rnd(w)), min(shape[0], rnd(y) + rnd(h))
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1 - x0, y1 - y0


def region_stats(img: np.ndarray, rect=None, raw: np.ndarray | None = None,
                 pixel_size_um: float | None = None) -> dict:
    """Stats inside rect (x, y, w, h) or the whole image. `raw` (unprocessed
    values) is used to count camera-saturated pixels."""
    r = clip_rect(rect, img.shape) if rect is not None else (0, 0, img.shape[1], img.shape[0])
    if r is None:
        return {}
    x, y, w, h = r
    patch = img[y:y + h, x:x + w].astype(np.float64)
    src = raw[y:y + h, x:x + w] if raw is not None else patch
    mean, std = float(patch.mean()), float(patch.std())
    out = {"pixels": int(patch.size), "mean": mean, "median": float(np.median(patch)), "std": std,
           "min": float(patch.min()), "max": float(patch.max()), "sum": float(patch.sum()),
           "snr": mean / std if std > 0 else float("inf"),
           "saturated": int(np.count_nonzero(src >= SATURATION_ADU)), "rect": r}
    if pixel_size_um:
        out["area_um2"] = patch.size * pixel_size_um ** 2
    return out


# ---- photobleaching ------------------------------------------------------
@dataclass(frozen=True)
class BleachFit:
    amplitude: float
    tau_s: float
    offset: float
    half_life_s: float
    r2: float


def bleach_curve(frames, rect=None) -> np.ndarray:
    """Mean intensity per frame inside rect (or whole frame)."""
    out = []
    r = None
    for f in frames:
        if r is None:
            r = clip_rect(rect, f.shape) if rect is not None else (0, 0, f.shape[1], f.shape[0])
            if r is None:
                return np.array([])
        x, y, w, h = r
        out.append(float(f[y:y + h, x:x + w].mean()))
    return np.asarray(out)


def fit_bleaching(t_s: np.ndarray, values: np.ndarray) -> BleachFit | None:
    """Fit I(t) = A·exp(-t/τ) + C. Returns None if it does not converge or the
    signal is not decaying."""
    t_s, values = np.asarray(t_s, float), np.asarray(values, float)
    if len(values) < 4 or values[0] <= 0 or 1 - values[-1] / values[0] < MIN_BLEACH_FRACTION:
        return None
    span = t_s[-1] - t_s[0] or 1.0
    p0 = (values[0] - values[-1], span / 2, values[-1])
    try:
        (a, tau, c), _ = curve_fit(lambda t, a, tau, c: a * np.exp(-(t - t_s[0]) / tau) + c, t_s, values,
                                   p0=p0, bounds=([0, span / 1000, -np.inf], [np.inf, span * 1000, np.inf]),
                                   maxfev=5000)
    except (RuntimeError, ValueError):
        return None
    pred = a * np.exp(-(t_s - t_s[0]) / tau) + c
    ss_res, ss_tot = float(((values - pred) ** 2).sum()), float(((values - values.mean()) ** 2).sum())
    return BleachFit(float(a), float(tau), float(c), float(tau * math.log(2)),
                     1 - ss_res / ss_tot if ss_tot > 0 else 0.0)


# ---- colocalisation ------------------------------------------------------
@dataclass(frozen=True)
class Coloc:
    pearson: float
    manders_m1: float  # fraction of A's signal (above threshold) where B is above its threshold
    manders_m2: float  # fraction of B's signal where A is above its threshold
    threshold_a: float
    threshold_b: float
    pixels: int


def colocalization(a: np.ndarray, b: np.ndarray, mask: np.ndarray | None = None,
                   threshold_a: float | None = None, threshold_b: float | None = None) -> Coloc:
    """Pearson's r over the region, and thresholded Manders M1/M2.
    Thresholds default to Otsu's method on each channel."""
    if a.shape != b.shape:
        raise ValueError(f"Shape mismatch: {a.shape} vs {b.shape}")
    va, vb = a.astype(np.float64), b.astype(np.float64)
    if mask is not None:
        va, vb = va[mask], vb[mask]
    else:
        va, vb = va.ravel(), vb.ravel()
    finite = np.isfinite(va) & np.isfinite(vb)
    va, vb = va[finite], vb[finite]
    ta = float(threshold_otsu(va)) if threshold_a is None else float(threshold_a)
    tb = float(threshold_otsu(vb)) if threshold_b is None else float(threshold_b)
    da, db = va - va.mean(), vb - vb.mean()
    denom = math.sqrt(float((da * da).sum()) * float((db * db).sum()))
    pearson = float((da * db).sum() / denom) if denom > 0 else 0.0
    above_a, above_b = va > ta, vb > tb
    sa, sb = float(va[above_a].sum()), float(vb[above_b].sum())
    m1 = float(va[above_a & above_b].sum() / sa) if sa > 0 else 0.0
    m2 = float(vb[above_a & above_b].sum() / sb) if sb > 0 else 0.0
    return Coloc(pearson, m1, m2, ta, tb, int(va.size))


def rect_mask(shape, rect) -> np.ndarray | None:
    r = clip_rect(rect, shape) if rect is not None else None
    if r is None:
        return None
    m = np.zeros(shape, bool)
    x, y, w, h = r
    m[y:y + h, x:x + w] = True
    return m


def joint_histogram(a: np.ndarray, b: np.ndarray, levels_a, levels_b, bins: int = 128, mask=None) -> np.ndarray:
    """log(1 + counts) 2D histogram of (a, b) within the display levels (for the scatter plot)."""
    va, vb = (a[mask], b[mask]) if mask is not None else (a.ravel(), b.ravel())
    h, _, _ = np.histogram2d(va, vb, bins=bins, range=[levels_a, levels_b])
    return np.log1p(h)


# ---- saturation / clipping overlay ---------------------------------------
def clipping_overlay(shown: np.ndarray, raw: np.ndarray | None, levels: tuple[float, float]) -> np.ndarray:
    """RGBA uint8: magenta where the camera saturated, yellow where the display
    clips (value above the white level), transparent elsewhere."""
    rgba = np.zeros((*shown.shape, 4), np.uint8)
    rgba[shown > levels[1]] = (255, 220, 0, 110)
    src = raw if raw is not None else shown
    rgba[src >= SATURATION_ADU] = (255, 0, 255, 230)
    return rgba
