"""
gridtrack.correct  (Stage 1)
============================
Correct microscope optics BEFORE any detection:

  1. Vignetting  -> flat-field: divide by the radial illumination model.
  2. Lens distortion -> exact radial un-distortion (inverse Brown-Conrady).

These are the inverse of the effects `expansion_camera_sim` applies, so a
corrected synthetic frame becomes flat and geometrically true -- which is also
how the correctness of this module is tested (see tests/).

Headless: every function takes arrays + a CorrectionParams and returns arrays.
"""
from __future__ import annotations
import numpy as np
import cv2

from .types import CorrectionParams, LevelsParams


# ----------------------------------------------------------------- vignetting
def _radius_norm(shape, cx_frac, cy_frac):
    """Normalized radius map in [0,~1], 0 at the chosen centre, ~1 at the
    farthest corner from it."""
    h, w = shape
    cx, cy = cx_frac * (w - 1), cy_frac * (h - 1)
    yy, xx = np.ogrid[0:h, 0:w]
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    rmax = max(np.hypot(cx, cy), np.hypot(w - 1 - cx, cy),
               np.hypot(cx, h - 1 - cy), np.hypot(w - 1 - cx, h - 1 - cy))
    return (r / max(rmax, 1e-6)).astype(np.float32)


def vignette_mask(shape, p: CorrectionParams) -> np.ndarray:
    """Illumination model V(r) = 1 - strength * r^power, in [floor, 1]."""
    r = _radius_norm(shape, p.vig_cx, p.vig_cy)
    return np.clip(1.0 - p.vig_strength * r ** p.vig_power, p.vig_floor, 1.0)


def correct_vignette(img: np.ndarray, p: CorrectionParams) -> np.ndarray:
    """Flat-field: divide the image by the illumination model."""
    if p.vig_strength <= 0:
        return img.astype(np.float32, copy=False)
    return (img.astype(np.float32) / vignette_mask(img.shape, p)).astype(np.float32)


# -------------------------------------------------------------- lens distortion
def _inverse_scale_map(shape, k1, k2, cx_frac, cy_frac):
    """Per-pixel radial scale s(rho) so that sampling the distorted image at
    rho*s recovers the undistorted image. Exact numeric inverse of
    h(r) = r*(1 + k1 r^2 + k2 r^4)."""
    h, w = shape
    fnorm = w / 2.0                                   # k1,k2 are half-width-relative
    cx, cy = cx_frac * (w - 1), cy_frac * (h - 1)
    r_s = np.linspace(0.0, 3.0, 4000)
    g = r_s * (1.0 + k1 * r_s ** 2 + k2 * r_s ** 4)
    mono = int(np.argmin(np.diff(g) > 0)) if not np.all(np.diff(g) > 0) else len(g)
    r_s, g = r_s[:mono], g[:mono]                     # keep the monotonic branch
    yy, xx = np.ogrid[0:h, 0:w]
    nx = (xx - cx) / fnorm
    ny = (yy - cy) / fnorm
    rho = np.sqrt(nx * nx + ny * ny)
    r_d = np.interp(rho, g, r_s)
    scale = np.where(rho > 1e-6, r_d / np.maximum(rho, 1e-6), 1.0).astype(np.float32)
    mapx = (cx + nx * scale * fnorm).astype(np.float32)
    mapy = (cy + ny * scale * fnorm).astype(np.float32)
    return mapx, mapy


def correct_distortion(img: np.ndarray, p: CorrectionParams) -> np.ndarray:
    """Remove radial lens distortion (barrel for k1<0)."""
    if p.k1 == 0 and p.k2 == 0:
        return img.astype(np.float32, copy=False)
    mapx, mapy = _inverse_scale_map(img.shape, p.k1, p.k2, p.dist_cx, p.dist_cy)
    return cv2.remap(img.astype(np.float32), mapx, mapy, cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_REPLICATE)


# ---------------------------------------------------------------- FFT low-pass
def _lowpass_mask(shape, p: CorrectionParams) -> np.ndarray:
    """Radial transfer function H(D) in [0,1] on the *unshifted* FFT grid, where
    D is the frequency radius as a fraction of the axis Nyquist (D=1 at Nyquist
    along an axis; ~1.41 at the diagonal corner). Passes DC (H=1 at D=0)."""
    h, w = shape
    fy = np.fft.fftfreq(h)[:, None]          # cycles/px in [-0.5, 0.5)
    fx = np.fft.fftfreq(w)[None, :]
    D = np.sqrt(fx * fx + fy * fy) / 0.5     # fraction of Nyquist
    Dc = max(float(p.lp_cutoff), 1e-3)
    shape_name = (p.lp_shape or "gaussian").lower()
    if shape_name == "ideal":
        H = (D <= Dc).astype(np.float32)
    elif shape_name == "butterworth":
        n = max(1, int(p.lp_order))
        H = 1.0 / (1.0 + (D / Dc) ** (2 * n))
    else:                                    # gaussian (default)
        H = np.exp(-(D * D) / (2.0 * Dc * Dc))
    return H.astype(np.float32)


def lowpass(img: np.ndarray, p: CorrectionParams) -> np.ndarray:
    """2-D Fourier low-pass with a settable cut-off. Reflect-pads first so the
    non-periodic frame borders don't ring. No-op unless p.lp_enable."""
    if not getattr(p, "lp_enable", False):
        return img.astype(np.float32, copy=False)
    pad = 32
    a = np.pad(img.astype(np.float32), pad, mode="reflect")
    H = _lowpass_mask(a.shape, p)            # matches np.fft.fft2's unshifted layout
    out = np.fft.ifft2(np.fft.fft2(a) * H).real
    return out[pad:pad + img.shape[0], pad:pad + img.shape[1]].astype(np.float32)


# --------------------------------------------------------- contrast / levels
def _value_scale(img: np.ndarray) -> float:
    """Reference full-scale value: 255 for 8-bit-range data, else the image max."""
    m = float(np.nanmax(img)) if img.size else 1.0
    return 255.0 if m <= 255.0 else max(m, 1e-6)


def resolve_black_norm(imgn: np.ndarray, p: LevelsParams) -> float:
    """Black point in NORMALISED [0,1] units for the chosen mode.
    auto: background + k·σ (σ via MAD of the dark half); percentile: p-th pctile;
    value: the manual normalised value."""
    mode = (p.lv_black_mode or "auto").lower()
    if mode == "value":
        return float(np.clip(p.lv_black, 0.0, 1.0))
    if mode == "percentile":
        return float(np.percentile(imgn, float(np.clip(p.lv_black_pct, 0.0, 100.0))))
    # auto: robust background = median, spread = MAD-derived σ (both resistant to the
    # sparse bright features), threshold at background + k·σ
    bg = float(np.median(imgn))
    sigma = float(1.4826 * np.median(np.abs(imgn - bg)))
    return bg + float(p.lv_black_k) * max(sigma, 1e-6)


def resolve_black_level(img: np.ndarray, p: LevelsParams) -> float:
    """The resolved black point back in the image's own value scale (for read-out)."""
    scale = _value_scale(img)
    return resolve_black_norm(img.astype(np.float32) / scale, p) * scale


def levels(img: np.ndarray, p: LevelsParams) -> np.ndarray:
    """Levels remap: floor (black point) -> 0, white point -> full scale, gamma
    on the mid-tones. No-op unless p.lv_enable. Preserves the value scale."""
    if not getattr(p, "lv_enable", False):
        return img.astype(np.float32, copy=False)
    scale = _value_scale(img)
    imgn = img.astype(np.float32) / scale
    black = resolve_black_norm(imgn, p)
    white = max(float(p.lv_white), black + 1e-3)
    t = np.clip((imgn - black) / (white - black), 0.0, 1.0) ** max(float(p.lv_gamma), 1e-3)
    return (t * scale).astype(np.float32)


# ---------------------------------------------------------------- full Stage 1
def apply(img: np.ndarray, p: CorrectionParams) -> np.ndarray:
    """Undo vignette (photometric) then distortion (geometric), then FFT low-pass
    (denoise, last). Returns a float32 image in the original value scale."""
    out = correct_vignette(img, p)
    out = correct_distortion(out, p)
    out = lowpass(out, p)
    return out


# ---------------------------------------------------------------- auto-estimate
def estimate_vignette(img: np.ndarray) -> tuple[float, float]:
    """Rough initial guess of (strength, power) from the bright-feature envelope.
    Best-effort: gives a starting point the sliders then refine. Returns (0,2) on
    failure so nothing breaks."""
    try:
        from scipy.optimize import curve_fit
        small = cv2.resize(img.astype(np.float32), (128, 128), interpolation=cv2.INTER_AREA)
        env = cv2.dilate(small, np.ones((9, 9), np.float32))     # bright-feature envelope
        r = _radius_norm(env.shape, 0.5, 0.5)
        nb = 24
        edges = np.linspace(0, r.max(), nb + 1)
        prof = np.array([env[(r >= edges[i]) & (r < edges[i + 1])].mean() if
                         np.any((r >= edges[i]) & (r < edges[i + 1])) else np.nan
                         for i in range(nb)])
        cx = 0.5 * (edges[:-1] + edges[1:])
        ok = np.isfinite(prof)
        cx, prof = cx[ok], prof[ok]
        if len(prof) < 5 or prof[0] <= 0:
            return 0.0, 2.0
        y = np.clip(prof / prof[0], 0.0, 1.5)
        f = lambda rr, s, pw: 1.0 - s * np.clip(rr, 0, 1) ** pw
        (s, pw), _ = curve_fit(f, cx, y, p0=[0.5, 2.0],
                               bounds=([0.0, 0.5], [1.0, 5.0]), maxfev=5000)
        return float(np.clip(s, 0, 1)), float(np.clip(pw, 0.5, 5))
    except Exception:
        return 0.0, 2.0
