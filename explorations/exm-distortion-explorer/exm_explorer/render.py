"""Image rendering.

Exact path (ported from exm_sim.render): every rectangle blurred by an
isotropic Gaussian, evaluated as erf products in the rectangle's own frame.

Fast path (live mode): the corrected post is rendered directly in the pre
frame. Rectangles of one kind (dot, H dash, V dash, tag module) share one
kernel, so their centres are splatted bilinearly onto the grid and the sum is
multiplied in Fourier space by the analytic kernel spectrum: the rigid
rectangle (printed size, i.e. 1/lambda of its pre size in this frame) times
the effective Gaussian of the faithful path (PSF, the 0.45 lambda anti-alias
blur and linear interpolation), pushed through the inverse registration
affine. The bilinear splat's own blur is divided out.
"""

from functools import lru_cache

import numpy as np
from scipy import fft as sfft
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
        sel = sel[np.argsort(cy[sel], kind="stable")]     # chunks cover a few rows only
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
            flat = iy[ok] * w + ix[ok]
            if flat.size == 0:
                continue
            # accumulate over the touched span only: at lambda = 10 the image
            # has 256 M pixels and a full-size bincount per chunk would not fit
            lo, hi = int(flat.min()), int(flat.max()) + 1
            acc[lo:hi] += np.bincount(flat - lo, val[ok], minlength=hi - lo)
    return acc.reshape(h, w)


def expose(clean, peak, bg, read_e, rng, rows=1024):
    """Shot noise + read noise, 16-bit (exm_sim.expose).

    Works in blocks of rows so a 16 000 px image does not need several 2 GB
    temporaries. All Poisson draws come before all read-noise draws, in C
    order, exactly as the one-shot version: the random stream and the result
    are unchanged."""
    h = clean.shape[0]
    e = np.empty(clean.shape, np.float32)          # counts < 2^24 are exact
    for r in range(0, h, rows):
        e[r:r + rows] = rng.poisson(clean[r:r + rows] * peak + bg)
    out = np.empty(clean.shape, np.uint16)
    for r in range(0, h, rows):
        blk = e[r:r + rows].astype(np.float64) + rng.normal(0, read_e, e[r:r + rows].shape)
        out[r:r + rows] = np.clip(np.round(blk), 0, 65535)
    return out


def expose_clean(clean, peak, bg):
    """Noise-free counterpart of expose()."""
    return np.clip(np.round(clean * peak + bg), 0, 65535).astype(np.uint16)


# ===================================================================== fast path
def splat_bilinear(x, y, shape, w=None):
    """Bilinear splat of unit (or w) weights at (x, y) px onto shape."""
    h, wd = shape
    x0 = np.floor(x).astype(int)
    y0 = np.floor(y).astype(int)
    fx, fy = x - x0, y - y0
    w = np.ones_like(x) if w is None else w
    idx, val = [], []
    for dy, wy in ((0, 1 - fy), (1, fy)):
        for dx, wx in ((0, 1 - fx), (1, fx)):
            xi, yi = x0 + dx, y0 + dy
            ok = (xi >= 0) & (xi < wd) & (yi >= 0) & (yi < h)
            idx.append(yi[ok] * wd + xi[ok])
            val.append((w * wx * wy)[ok])
    return np.bincount(np.concatenate(idx), np.concatenate(val), minlength=h * wd).reshape(h, wd)


@lru_cache(maxsize=4)
def _freqs(ny, nx):
    fx = sfft.rfftfreq(nx)[None, :]
    fy = sfft.fftfreq(ny)[:, None]
    deconv = 1.0 / np.maximum((np.sinc(fx) * np.sinc(fy)) ** 2, 1e-3)
    return fx, fy, deconv


def rect_kernel_spectrum(fx, fy, Ainv, theta_deg, hx, hy, sigma):
    """Spectrum (cycles/px of the pre frame) of k(x) = g(A x), g a rectangle
    with half sizes hx, hy (post px) rotated by theta_deg and blurred by a
    Gaussian of sigma post px: K(f) = g^(A^-T f) / |det A|."""
    nux = Ainv[0, 0] * fx + Ainv[1, 0] * fy
    nuy = Ainv[0, 1] * fx + Ainv[1, 1] * fy
    t = np.deg2rad(theta_deg)
    c, s = np.cos(t), np.sin(t)
    nu_u = c * nux + s * nuy
    nu_v = -s * nux + c * nuy
    g = (2 * hx * np.sinc(2 * hx * nu_u)) * (2 * hy * np.sinc(2 * hy * nu_v)) * \
        np.exp(-2 * np.pi ** 2 * sigma ** 2 * (nux ** 2 + nuy ** 2))
    return g * abs(np.linalg.det(Ainv))


def faithful_sigma_post_px(psf_fwhm_um, um_px, lam_A):
    """Effective Gaussian (post px) of the faithful corrected post: PSF, the
    anti-alias blur 0.45 lambda and linear interpolation (variance ~1/6)."""
    return np.sqrt(psf_sigma_px(psf_fwhm_um, um_px) ** 2 + round(0.45 * lam_A, 2) ** 2 + 1 / 6)


_KERNEL_CACHE = {}


def _kernel(ny, nx, Ainv, theta_deg, hx, hy, sigma):
    """Kernel spectra are cached: they change only with the registration, and
    by far less than the rendering accuracy for changes below 1e-5."""
    key = (ny, nx, tuple(np.round(Ainv.ravel(), 5)), round(theta_deg, 4), round(hx, 4),
           round(hy, 4), round(sigma, 4))
    K = _KERNEL_CACHE.get(key)
    if K is None:
        fx, fy, _ = _freqs(ny, nx)
        K = rect_kernel_spectrum(fx, fy, Ainv, theta_deg, hx, hy, sigma).astype(np.complex64)
        if len(_KERNEL_CACHE) > 32:
            _KERNEL_CACHE.clear()
        _KERNEL_CACHE[key] = K
    return K


def render_corrected_fast(rect_xy_pre, rect_kind, kind_half_post, A, theta_post_deg, sigma_post,
                          shape):
    """Clean corrected post in the pre frame (same units as render_exact).

    rect_xy_pre     (M, 2) rectangle centres already mapped into the pre frame
    rect_kind       (M,) kind index
    kind_half_post  {kind: (hx, hy)} half sizes in post px"""
    h, w = shape
    ny, nx = sfft.next_fast_len(h + 8, real=True), sfft.next_fast_len(w + 8, real=True)
    fx, fy, deconv = _freqs(ny, nx)
    Ainv = np.linalg.inv(A)
    acc = None
    for k, (hx, hy) in kind_half_post.items():
        m = rect_kind == k
        if not m.any():
            continue
        sp = splat_bilinear(rect_xy_pre[m, 0], rect_xy_pre[m, 1], (ny, nx))
        F = sfft.rfft2(sp.astype(np.float32), workers=-1) * _kernel(ny, nx, Ainv, theta_post_deg, hx, hy,
                                                                     sigma_post)
        acc = F if acc is None else acc + F
    if acc is None:
        return np.zeros(shape)
    return sfft.irfft2(acc * deconv, s=(ny, nx), workers=-1)[:h, :w]
