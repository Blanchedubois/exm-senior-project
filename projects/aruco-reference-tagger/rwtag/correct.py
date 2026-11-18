"""
rwtag.correct  (Stage 1)
========================
Correct microscope optics BEFORE any detection, then apply a per-image contrast
remap:

  1. Vignetting     -> flat-field: divide by the radial illumination model.
  2. Lens distortion -> exact radial un-distortion (inverse Brown-Conrady).
  3. FFT low-pass   -> optional Fourier denoise.
  4. Deskew         -> rotate the whole frame upright.
  5. Levels         -> per-image black/white/gamma remap (applied separately).

Ported verbatim from the Point-Tracking GUI (`gridtrack/correct.py`); the optics
functions are the numeric inverse of the effects `expansion_camera_sim` applies,
so a corrected synthetic frame becomes flat and geometrically true -- which is
also how the correctness of this module is tested (see tests/).

Headless: every function takes arrays + a params dataclass and returns arrays.
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
    """Reference full-scale value: 255 for 8-bit-range data, else the image max.
    On this data (uint16 frames topping out ~1200 down to ~379) this keys off the
    ACTUAL image max, not an assumed 65535."""
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


# ---------------------------------------------------------------- deskew
def rotate(img: np.ndarray, deg: float) -> np.ndarray:
    """Rotate the frame about its centre by `deg` degrees (deskew), same size."""
    if not deg:
        return img.astype(np.float32, copy=False)
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), float(deg), 1.0)
    return cv2.warpAffine(img.astype(np.float32), M, (w, h), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REPLICATE)


# ---------------------------------------------------------------- full Stage 1
def apply(img: np.ndarray, p: CorrectionParams) -> np.ndarray:
    """Undo vignette (photometric) then distortion (geometric), then FFT low-pass
    (denoise), then deskew rotation (last). Returns float32 in the original scale.
    Levels are applied SEPARATELY (per-image) on this result -- see `levels`."""
    out = correct_vignette(img, p)
    out = correct_distortion(out, p)
    out = lowpass(out, p)
    out = rotate(out, getattr(p, "rotate_deg", 0.0))
    return out


def process(img: np.ndarray, c: CorrectionParams, lv: LevelsParams) -> np.ndarray:
    """The full Stage-1 result the rest of the app consumes: shared optics
    (`apply`) followed by the per-image contrast remap (`levels`)."""
    return levels(apply(img, c), lv)


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


# ================================================================ point geometry
# The geometric part of Stage 1 (lens un-distortion, then deskew rotation) maps
# every pixel of the raw frame to the corrected frame. Detection runs on images,
# but positions must also travel between the two frames exactly, with their
# covariances, so the export can report each feature in both. Photometric steps
# (vignette, low-pass, levels) do not move points.
#
# Convention (identical to `correct_distortion` / `_inverse_scale_map`): with
# u = (p - c) / f, c = (dist_cx (w-1), dist_cy (h-1)), f = w / 2, a raw point at
# normalised radius r appears in the un-distorted frame at radius
#     rho = h(r) = r (1 + k1 r^2 + k2 r^4)
# along the same direction. The rotation is cv2.getRotationMatrix2D about
# (w/2, h/2), applied after the lens step, exactly as `rotate` does.

def _h(r, k1, k2):
    return r * (1.0 + k1 * r * r + k2 * r ** 4)


def _hp(r, k1, k2):
    return 1.0 + 3.0 * k1 * r * r + 5.0 * k2 * r ** 4


def lens_range(k1, k2):
    """(r_max, rho_max): the end of the monotonic branch of h, searched over the
    same r in [0, 3] that `_inverse_scale_map` uses. Raw points beyond r_max fold
    back; corrected points beyond rho_max have NO raw source (the image correction
    fills them by clamping -- smeared, unusable). Both map to NaN."""
    r = np.linspace(0.0, 3.0, 4001)
    hp = _hp(r, k1, k2)
    bad = np.nonzero(hp <= 0)[0]
    r_max = float(r[bad[0] - 1]) if len(bad) else 3.0
    return r_max, float(_h(r_max, k1, k2))


def _h_inv(rho, k1, k2, iters=40):
    """Solve h(r) = rho on the monotonic branch by Newton (exact to ~1e-12)."""
    r = np.array(rho, float, copy=True)
    for _ in range(iters):
        d = (_h(r, k1, k2) - rho) / np.maximum(_hp(r, k1, k2), 1e-6)
        r -= d
        if np.max(np.abs(d), initial=0.0) < 1e-13:
            break
    return r


def _lens_frame(p: CorrectionParams, shape):
    h, w = shape[:2]
    return np.array([p.dist_cx * (w - 1), p.dist_cy * (h - 1)], float), w / 2.0


def _rot_affine(p: CorrectionParams, shape):
    h, w = shape[:2]
    M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), float(getattr(p, "rotate_deg", 0.0)), 1.0)
    return M[:, :2].astype(float), M[:, 2].astype(float)


def geometric_is_identity(p: CorrectionParams) -> bool:
    return not (p.k1 or p.k2 or getattr(p, "rotate_deg", 0.0))


def forward_geometric(points_raw, p: CorrectionParams, shape):
    """Raw-frame px -> corrected-frame px (lens un-distortion, then rotation)."""
    P = np.asarray(points_raw, float).reshape(-1, 2).copy()
    if p.k1 or p.k2:
        c, f = _lens_frame(p, shape)
        u = (P - c) / f
        r = np.hypot(u[:, 0], u[:, 1])
        P = c + u * (1.0 + p.k1 * r ** 2 + p.k2 * r ** 4)[:, None] * f
        r_max, _ = lens_range(p.k1, p.k2)
        P[r > r_max] = np.nan
    if getattr(p, "rotate_deg", 0.0):
        A, t = _rot_affine(p, shape)
        P = P @ A.T + t
    return P


def inverse_geometric(points_corr, p: CorrectionParams, shape):
    """Corrected-frame px -> raw-frame px: undo the rotation exactly, then the
    lens step by solving h(r) = rho (Newton). Round trip with forward_geometric
    is exact to floating point."""
    P = np.asarray(points_corr, float).reshape(-1, 2).copy()
    if getattr(p, "rotate_deg", 0.0):
        A, t = _rot_affine(p, shape)
        P = (P - t) @ np.linalg.inv(A).T
    if p.k1 or p.k2:
        c, f = _lens_frame(p, shape)
        u = (P - c) / f
        rho = np.hypot(u[:, 0], u[:, 1])
        _r_max, rho_max = lens_range(p.k1, p.k2)
        out = rho > rho_max
        r = _h_inv(np.minimum(rho, rho_max), p.k1, p.k2)
        g = np.where(rho > 1e-12, r / np.maximum(rho, 1e-12), 1.0)
        P = c + u * g[:, None] * f
        P[out] = np.nan
    return P


def forward_jacobian(points_raw, p: CorrectionParams, shape):
    """(N,2,2) Jacobian d(corr)/d(raw) at each raw point."""
    P = np.asarray(points_raw, float).reshape(-1, 2)
    J = np.repeat(np.eye(2)[None], len(P), axis=0)
    if p.k1 or p.k2:
        c, f = _lens_frame(p, shape)
        u = (P - c) / f
        r = np.hypot(u[:, 0], u[:, 1])
        s = 1.0 + p.k1 * r ** 2 + p.k2 * r ** 4
        dsdr_over_r = 2.0 * p.k1 + 4.0 * p.k2 * r ** 2          # (ds/dr) / r, finite at r = 0
        J = s[:, None, None] * np.eye(2)[None] + dsdr_over_r[:, None, None] * np.einsum("ni,nj->nij", u, u)
    if getattr(p, "rotate_deg", 0.0):
        A, _t = _rot_affine(p, shape)
        J = np.einsum("ij,njk->nik", A, J)
    return J


def inverse_jacobian(points_corr, p: CorrectionParams, shape):
    """(N,2,2) Jacobian d(raw)/d(corr) at each corrected point. Equals the
    matrix inverse of forward_jacobian at the matching raw point."""
    P = np.asarray(points_corr, float).reshape(-1, 2)
    Ainv = np.eye(2)
    if getattr(p, "rotate_deg", 0.0):
        A, t = _rot_affine(p, shape)
        Ainv = np.linalg.inv(A)
        P = (P - t) @ Ainv.T
    J = np.repeat(Ainv[None], len(P), axis=0)
    if p.k1 or p.k2:
        c, f = _lens_frame(p, shape)
        u = (P - c) / f
        rho = np.hypot(u[:, 0], u[:, 1])
        r = _h_inv(rho, p.k1, p.k2)
        safe = rho > 1e-9
        g = np.where(safe, r / np.where(safe, rho, 1.0), 1.0)
        drdrho = 1.0 / np.maximum(_hp(r, p.k1, p.k2), 1e-9)
        gp_over_rho = np.where(safe, (drdrho * rho - r) / np.where(safe, rho, 1.0) ** 3, 0.0)
        L = g[:, None, None] * np.eye(2)[None] + gp_over_rho[:, None, None] * np.einsum("ni,nj->nij", u, u)
        J = np.einsum("nij,jk->nik", L, Ainv)
    return J


def propagate_cov(cov, J):
    """Transform (N,2,2) covariances by (N,2,2) Jacobians: J C J^T."""
    return np.einsum("nij,njk,nlk->nil", J, np.asarray(cov, float), J)


def raw_source_valid(points_corr, p: CorrectionParams, shape, margin_px=0.0):
    """True where a corrected-frame point has a real raw-frame source: its raw
    position exists (inside the lens model's range) and lies at least
    `margin_px` inside the raw frame. Points failing this sit in the band the
    correction fills by clamping -- smeared, not data. This is the exact form of
    the V2 workshop's 'un-distortion edge band'."""
    h, w = shape[:2]
    q = inverse_geometric(points_corr, p, shape)
    ok = np.isfinite(q).all(1)
    m = float(margin_px)
    ok[ok] = ((q[ok, 0] >= m) & (q[ok, 0] <= w - 1 - m) & (q[ok, 1] >= m) & (q[ok, 1] <= h - 1 - m))
    return ok
