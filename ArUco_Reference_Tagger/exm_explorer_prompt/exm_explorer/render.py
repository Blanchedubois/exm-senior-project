"""Image rendering.

Exact path (ported from exm_sim.render): every rectangle blurred by an
isotropic Gaussian, evaluated as erf products in the rectangle's own frame.
The fast splat path for live mode is added in milestone 2.
"""

import numpy as np
from scipy.special import erf

FWHM_TO_SIGMA = 1 / 2.3548


def psf_sigma_px(fwhm_um, um_px):
    return fwhm_um * FWHM_TO_SIGMA / um_px


def render_exact(size_px, cx, cy, hx, hy, theta_deg, sigma, chunk=3000, region=None):
    """Sum of rectangles (centres cx, cy and half sizes hx, hy in px, all
    rotated by theta_deg) blurred by a Gaussian of sigma px.

    region = (x0, y0, w, h) renders only that window of the image (same pixel
    grid); size_px is then ignored except for clarity."""
    if region is None:
        x0, y0, w, h = 0, 0, size_px, size_px
    else:
        x0, y0, w, h = region
    acc = np.zeros(w * h)
    t = np.deg2rad(theta_deg)
    c, s = np.cos(t), np.sin(t)
    k2 = np.sqrt(2) * sigma

    def f(u, half):
        return 0.5 * (erf((u + half) / k2) - erf((u - half) / k2))

    for half in np.unique(np.c_[hx, hy], axis=0):
        r = int(np.ceil(np.hypot(*half) + 4 * sigma))
        sel = np.nonzero((hx == half[0]) & (hy == half[1]) &
                         (cx > x0 - r - 1) & (cx < x0 + w + r) &
                         (cy > y0 - r - 1) & (cy < y0 + h + r))[0]
        d = np.arange(-r, r + 1)
        DX, DY = np.meshgrid(d, d)
        for k in range(0, len(sel), chunk):
            idx = sel[k:k + chunk]
            ix = np.round(cx[idx]).astype(int)[:, None, None] + DX
            iy = np.round(cy[idx]).astype(int)[:, None, None] + DY
            px = ix - cx[idx][:, None, None]
            py = iy - cy[idx][:, None, None]
            u = c * px + s * py
            v = -s * px + c * py
            val = f(u, half[0]) * f(v, half[1])
            ix = ix - x0
            iy = iy - y0
            ok = (ix >= 0) & (ix < w) & (iy >= 0) & (iy < h)
            acc += np.bincount(iy[ok] * w + ix[ok], val[ok], minlength=acc.size)
    return acc.reshape(h, w)


def expose(clean, peak, bg, read_e, rng):
    """Shot noise + read noise, 16-bit (exm_sim.expose)."""
    e = rng.poisson(clean * peak + bg).astype(np.float64)
    e += rng.normal(0, read_e, e.shape)
    return np.clip(np.round(e), 0, 65535).astype(np.uint16)


def expose_clean(clean, peak, bg):
    """Noise-free counterpart of expose()."""
    return np.clip(np.round(clean * peak + bg), 0, 65535).astype(np.uint16)
