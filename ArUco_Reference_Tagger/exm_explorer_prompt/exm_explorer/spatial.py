"""Spatial structure of a distortion field (Qt-free).

  correlation_length      ACF of a scalar map (e.g. local expansion) with a
                          validity mask; the lag where it falls to 1/e
  axial_stats             are directions of maximum stretch random or aligned?
                          (axial data: angles mod 180, doubled-angle statistics)
  rms_error_vs_length     the ExM metric: RMS error of the distance between two
                          features against their separation
  reference_residual      how much distortion is left after correcting from
                          reference points on a square grid of spacing d
"""

import numpy as np
from scipy import fft as sfft
from scipy.interpolate import RBFInterpolator


# ===================================================================== correlation length
def masked_acf(f, mask, maxlag):
    """Normalised autocorrelation of f where mask is True (mean removed over
    the mask), lags |dx|, |dy| <= maxlag in grid steps. Unbiased: each lag is
    divided by its number of valid pairs."""
    m = mask & np.isfinite(f)
    g = np.where(m, f - np.nanmean(f[m]), 0.0)
    w = m.astype(float)
    h, wd = f.shape
    shape = (h + maxlag, wd + maxlag)
    G = sfft.rfft2(g, s=shape)
    W = sfft.rfft2(w, s=shape)
    num = sfft.irfft2(G * np.conj(G), s=shape)
    cnt = sfft.irfft2(W * np.conj(W), s=shape)
    num = np.roll(num, (maxlag, maxlag), (0, 1))[:2 * maxlag + 1, :2 * maxlag + 1]
    cnt = np.roll(cnt, (maxlag, maxlag), (0, 1))[:2 * maxlag + 1, :2 * maxlag + 1]
    a = np.where(cnt > 0.5, num / np.maximum(cnt, 1), np.nan)
    return a / a[maxlag, maxlag]


def radial_mean(a, step):
    L = a.shape[0] // 2
    Y, X = np.mgrid[-L:L + 1, -L:L + 1]
    r = np.hypot(X, Y)
    rb = np.round(r).astype(int).ravel()
    ok = np.isfinite(a).ravel()
    s = np.bincount(rb[ok], a.ravel()[ok], minlength=L + 1)
    n = np.bincount(rb[ok], minlength=L + 1)
    prof = np.where(n > 0, s / np.maximum(n, 1), np.nan)[:L + 1]
    return np.arange(L + 1) * step, prof


def correlation_length(f, mask, step, maxlag=None, level=np.exp(-1)):
    """Lag (in the units of step) where the radial ACF first drops below
    `level` (1/e by default), linearly interpolated. Returns (xi, lags, prof)."""
    maxlag = maxlag or min(f.shape) // 2
    lags, prof = radial_mean(masked_acf(f, mask, maxlag), step)
    below = np.nonzero(prof < level)[0]
    if len(below) == 0:
        return np.inf, lags, prof
    k = below[0]
    x0, x1, y0, y1 = lags[k - 1], lags[k], prof[k - 1], prof[k]
    return float(x0 + (level - y0) * (x1 - x0) / (y1 - y0)), lags, prof


# ===================================================================== directions
def axial_stats(theta_deg, area=None, xi=None):
    """Doubled-angle statistics for axial data (directions mod 180).

    R      mean resultant length of 2 theta: 0 = random, 1 = all aligned
    mean   mean direction (deg, 0..180)
    n_eff  independent samples: area / xi^2 when given (neighbouring windows
           of a correlated field are not independent), else len(theta)
    p      Rayleigh test p-value for 'no preferred direction' with n_eff"""
    t = np.deg2rad(np.asarray(theta_deg, float)) * 2
    C, S = np.cos(t).mean(), np.sin(t).mean()
    R = float(np.hypot(C, S))
    n = len(t) if (area is None or xi is None) else max(area / xi ** 2, 1.0)
    n = min(n, len(t))
    z = n * R * R
    p = float(np.exp(np.sqrt(1 + 4 * n + 4 * (n * n - z * n)) - (1 + 2 * n)))   # Zar's approximation
    return dict(R=R, mean_deg=float(np.degrees(np.arctan2(S, C) / 2) % 180), n=len(t),
                n_eff=float(n), p=min(max(p, 0.0), 1.0))


# ===================================================================== RMS error vs length
def rms_error_vs_length(xy, r, bins, n_pairs=400_000, seed=0):
    """xy (N, 2) positions and r (N, 2) residual displacements (same units).
    For random pairs i, j with separation L = |xy_i - xy_j| the length error
    is |r_i - r_j| (the error of the vector between them). Returns bin
    centres, RMS error per bin and pair counts."""
    rng = np.random.default_rng(seed)
    ok = np.all(np.isfinite(r), 1)
    xy, r = xy[ok], r[ok]
    i = rng.integers(0, len(xy), n_pairs)
    j = rng.integers(0, len(xy), n_pairs)
    keep = i != j
    i, j = i[keep], j[keep]
    L = np.hypot(*(xy[i] - xy[j]).T)
    e2 = ((r[i] - r[j]) ** 2).sum(1)
    k = np.digitize(L, bins) - 1
    nb = len(bins) - 1
    good = (k >= 0) & (k < nb)
    s = np.bincount(k[good], e2[good], minlength=nb)
    n = np.bincount(k[good], minlength=nb)
    rms = np.where(n > 0, np.sqrt(s / np.maximum(n, 1)), np.nan)
    return 0.5 * (bins[1:] + bins[:-1]), rms, n


def remove_similarity(src, dst):
    """Residual dst - T(src) after the best similarity T (scale, rotation,
    translation), expressed in src units. Returns (residual, scale)."""
    mu_s, mu_d = src.mean(0), dst.mean(0)
    a, b = src - mu_s, dst - mu_d
    zs = a[:, 0] + 1j * a[:, 1]
    zd = b[:, 0] + 1j * b[:, 1]
    k = (np.conj(zs) @ zd) / (np.conj(zs) @ zs)          # scale * e^{i rot}
    fit = k * zs
    res = (zd - fit) / k                                 # back in src units
    return np.c_[res.real, res.imag], float(abs(k))


# ===================================================================== referencing density
def reference_residual(xs, ux, uy, spacing, field=(0.0, 750.0), eval_step=6.0):
    """Correct u from samples on a square grid of `spacing` (thin-plate
    spline through the reference points, plus an affine part) and return the
    RMS of what is left, and of u itself (after removing its affine part),
    over the field."""
    x = np.arange(field[0], field[1] + 1e-9, eval_step)
    X, Y = np.meshgrid(x, x)
    step = xs[1] - xs[0]

    def sample(f, px, py):
        from scipy import ndimage
        return ndimage.map_coordinates(f, [(py - xs[0]) / step, (px - xs[0]) / step], order=1)

    P = np.c_[X.ravel(), Y.ravel()]
    U = np.c_[sample(ux, P[:, 0], P[:, 1]), sample(uy, P[:, 0], P[:, 1])]
    # the affine part is removed by any registration, so it is not 'distortion'
    M = np.c_[P, np.ones(len(P))]
    U = U - M @ np.linalg.lstsq(M, U, rcond=None)[0]
    rx = np.arange(field[0], field[1] + 1e-9, spacing)
    RX, RY = np.meshgrid(rx, rx)
    Q = np.c_[RX.ravel(), RY.ravel()]
    UQ = np.c_[sample(ux, Q[:, 0], Q[:, 1]), sample(uy, Q[:, 0], Q[:, 1])]
    UQ = UQ - np.c_[Q, np.ones(len(Q))] @ np.linalg.lstsq(M, np.c_[sample(ux, P[:, 0], P[:, 1]),
                                                                    sample(uy, P[:, 0], P[:, 1])],
                                                          rcond=None)[0]
    fit = RBFInterpolator(Q, UQ, kernel="thin_plate_spline", degree=1)(P)
    left = U - fit
    return float(np.sqrt((left ** 2).sum(1).mean())), float(np.sqrt((U ** 2).sum(1).mean()))


# ===================================================================== extrema
def local_extrema(f, x=None, y=None, min_separation=3, min_deviation=0.0, reference=None,
                  max_points=50):
    """Local maxima and minima of a 2D map (NaN = no data).

    f              (ny, nx) map, rows along y
    x, y           1D coordinates of the columns / rows (default: indices)
    min_separation neighbourhood radius in grid steps; a point must be the
                   extreme value within it (non-maximum suppression)
    min_deviation  keep only extrema at least this far from `reference`
                   (default the median of f): set it from a control's noise
                   floor so noise bumps are not reported
    Returns a list of dicts kind ('max' | 'min'), x, y (parabolic sub-grid
    refinement), value, deviation (value - reference), sorted by |deviation|."""
    f = np.asarray(f, float)
    ny, nx = f.shape
    x = np.arange(nx, dtype=float) if x is None else np.asarray(x, float)
    y = np.arange(ny, dtype=float) if y is None else np.asarray(y, float)
    fin = np.isfinite(f)
    if not fin.any():
        return []
    ref = float(np.nanmedian(f)) if reference is None else float(reference)
    size = 2 * int(min_separation) + 1
    from scipy import ndimage
    out = []
    for kind, g in (("max", f), ("min", -f)):
        h = np.where(fin, g, -np.inf)
        peak = (h == ndimage.maximum_filter(h, size=size, mode="nearest")) & fin
        # a flat plateau gives many equal maxima: keep one per connected patch
        lab, nlab = ndimage.label(peak)
        if nlab == 0:
            continue
        idx = ndimage.maximum_position(h, lab, range(1, nlab + 1))
        for (j, i) in idx:
            dev = f[j, i] - ref
            if (kind == "max" and dev < min_deviation) or (kind == "min" and -dev < min_deviation):
                continue
            # an extreme on the edge of the data is not a resolved extremum
            if j == 0 or i == 0 or j == ny - 1 or i == nx - 1:
                continue
            if not (fin[j - 1:j + 2, i - 1:i + 2].all()):
                continue
            ox = _parabolic(g[j, i - 1], g[j, i], g[j, i + 1])
            oy = _parabolic(g[j - 1, i], g[j, i], g[j + 1, i])
            out.append(dict(kind=kind, x=float(np.interp(i + ox, np.arange(nx), x)),
                            y=float(np.interp(j + oy, np.arange(ny), y)), value=float(f[j, i]),
                            deviation=float(dev), row=int(j), col=int(i)))
    out.sort(key=lambda d: -abs(d["deviation"]))
    return out[:max_points]


def _parabolic(m1, c0, p1):
    d = m1 - 2 * c0 + p1
    return 0.0 if d >= 0 else float(np.clip(0.5 * (m1 - p1) / d, -0.5, 0.5))
