#!/usr/bin/env python3
"""
Autocorrelation explorer: how the 2D autocorrelation function (ACF) reveals
spatial structure in an image, and how distortion changes it.

    python autocorr_demo.py                  # synthetic patterns
    python autocorr_demo.py --image my.png   # also analyse your own image

Requires: numpy, matplotlib  (pip install numpy matplotlib)

The ACF answers one question for every shift (dx, dy):
    "If I slide the image by (dx, dy), how similar is it to itself?"
It is computed with the Wiener-Khinchin theorem (ACF = inverse FFT of the
power spectrum), zero-padded so there is no wrap-around, and divided by the
pixel overlap at each lag (unbiased estimate).

Panels
  1. Image (distorted, + noise). Yellow arrows show how the distortion moves
     points (x3).
  2. ACF of the distorted image.
  3. ACF(distorted) - ACF(ideal). Green = gained, pink = lost.
     For the dot lattice, '+' marks the ideal peaks, blue arrows show how far
     each measured peak moved (x5) and red rings show how much it widened.
  4. Radial and directional ACF profiles (dashed gray = ideal).

Reading the difference panel
  * Arrows, no rings   -> uniform distortion (same everywhere)
  * Rings, no arrows   -> nonuniform distortion with no net trend
  * Both               -> average distortion plus variation around it
  * Arrow pattern      -> radial = expansion, along one axis = stretch,
                          circling = rotation

Sliders (each pattern uses the ones that make sense for it)
  feature size     blob / dot radius (px)
  period           grating period or lattice spacing (px)
  angle            orientation of the pattern (degrees, counter-clockwise)
  aspect           built-in stretch of the pattern itself (part of "ideal")
  jitter           random displacement of lattice dots (fraction of spacing)
  noise            added white noise (relative to the signal std)
  distortion       strength of the selected distortion:
                     stretch / shear : fractional (0.05 = 5 %)
                     rotation        : strength x 30 degrees
                     barrel          : extra scale at the image edge
                     smooth warp     : rms displacement = strength x 64 px
"""

import argparse

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse
from matplotlib.widgets import Button, RadioButtons, Slider

N = 256        # synthetic image size (px)
PAD = 48       # extra margin generated around synthetic images before warping
MAX_LAG = 96   # largest lag shown in the ACF panels (px)
K_PEAKS = 4    # lattice peaks analysed out to this many spacings


# --------------------------------------------------------------------------
# Image synthesis (on an n x n canvas)
# --------------------------------------------------------------------------
def gaussian_blur_fft(img, sigma, aspect=1.0, theta=0.0):
    """Anisotropic Gaussian blur done in Fourier space.
    sigma*aspect along direction theta, sigma perpendicular to it."""
    h, w = img.shape
    kx, ky = np.meshgrid(np.fft.fftfreq(w), np.fft.fftfreq(h))
    c, s = np.cos(theta), np.sin(theta)
    u = c * kx + s * ky
    v = -s * kx + c * ky
    H = np.exp(-2 * np.pi**2 * ((sigma * aspect * u) ** 2 + (sigma * v) ** 2))
    return np.real(np.fft.ifft2(np.fft.fft2(img) * H))


def make_blobs(p, rng, n):
    """Random texture with a characteristic grain size, no periodicity."""
    white = rng.standard_normal((n, n))
    return gaussian_blur_fft(white, p["size"], p["aspect"], np.deg2rad(p["angle"]))


def make_grating(p, rng, n):
    """Stripes: periodic in one direction, constant in the other."""
    y, x = np.mgrid[0:n, 0:n].astype(float)
    t = np.deg2rad(p["angle"])
    u = x * np.cos(t) + y * np.sin(t)
    return np.cos(2 * np.pi * u / p["period"])


def lattice_vectors(p):
    """The two ideal lattice vectors (columns) for the current settings."""
    a, t = p["period"], np.deg2rad(p["angle"])
    rot = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
    return rot @ np.diag([a * p["aspect"], a])


def make_lattice(p, rng, n):
    """Square lattice of dots, optionally stretched, rotated and jittered."""
    B = lattice_vectors(p)
    m = int(1.6 * n / p["period"]) + 2
    i, j = np.mgrid[-m:m + 1, -m:m + 1]
    x = n / 2 + B[0, 0] * i + B[0, 1] * j
    y = n / 2 + B[1, 0] * i + B[1, 1] * j
    x = x + rng.normal(0, p["jitter"] * p["period"], x.shape)
    y = y + rng.normal(0, p["jitter"] * p["period"], y.shape)
    xi, yi = np.round(x).astype(int), np.round(y).astype(int)
    keep = (xi >= 0) & (xi < n) & (yi >= 0) & (yi < n)
    img = np.zeros((n, n))
    np.add.at(img, (yi[keep], xi[keep]), 1.0)
    return gaussian_blur_fft(img, p["size"])


def load_user_image(path, max_side=384):
    img = plt.imread(path).astype(float)
    if img.ndim == 3:
        img = img[..., :3].mean(axis=2)
    step = int(np.ceil(max(img.shape) / max_side))
    return img[::step, ::step]


# --------------------------------------------------------------------------
# Distortions
# --------------------------------------------------------------------------
DISTORTIONS = ["None", "Uniform stretch (x)", "Shear", "Rotation",
               "Barrel", "Smooth random warp"]


def affine_matrix(kind, s):
    if kind == "Uniform stretch (x)":
        return np.array([[1 + s, 0], [0, 1]])
    if kind == "Shear":
        return np.array([[1, s], [0, 1]])
    if kind == "Rotation":
        t = np.deg2rad(30 * s)
        return np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
    return None


def warp_field(shape, s, seed, R):
    """Smooth random displacement field, rms = s * 64 px."""
    rng = np.random.default_rng(seed + 9999)
    f = rng.standard_normal((2,) + shape)
    ux, uy = (gaussian_blur_fft(f[k], 0.12 * R) for k in range(2))
    amp = s * 64
    return ux * amp / (ux.std() + 1e-12), uy * amp / (uy.std() + 1e-12)


def forward_displacement(kind, s, X, Y, R, field=None):
    """Where a point at (X, Y) (centred coords) moves to, minus where it was."""
    M = affine_matrix(kind, s)
    if M is not None:
        return (M[0, 0] - 1) * X + M[0, 1] * Y, M[1, 0] * X + (M[1, 1] - 1) * Y
    if kind == "Barrel":
        k = s * (X**2 + Y**2) / R**2
        return k * X, k * Y
    if kind == "Smooth random warp" and field is not None:
        return field
    return np.zeros_like(X), np.zeros_like(Y)


def apply_distortion(img, kind, s, seed, R):
    """Warp img by backward mapping (exact inverse for affine and barrel)."""
    if kind == "None" or s == 0:
        return img.copy()
    h, w = img.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    X, Y = xx - w / 2, yy - h / 2
    M = affine_matrix(kind, s)
    if M is not None:
        Mi = np.linalg.inv(M)
        SX, SY = Mi[0, 0] * X + Mi[0, 1] * Y, Mi[1, 0] * X + Mi[1, 1] * Y
    elif kind == "Barrel":
        SX, SY = X.copy(), Y.copy()
        for _ in range(10):                      # solve X = S (1 + s|S|^2/R^2)
            f = 1 + s * (SX**2 + SY**2) / R**2
            SX, SY = X / f, Y / f
    else:
        ux, uy = warp_field(img.shape, s, seed, R)
        SX, SY = X - ux, Y - uy
    return bilinear(img, SX + w / 2, SY + h / 2)


def bilinear(img, sx, sy):
    h, w = img.shape
    x0 = np.clip(np.floor(sx).astype(int), 0, w - 2)
    y0 = np.clip(np.floor(sy).astype(int), 0, h - 2)
    fx = np.clip(sx - x0, 0, 1)
    fy = np.clip(sy - y0, 0, 1)
    return (img[y0, x0] * (1 - fx) * (1 - fy) + img[y0, x0 + 1] * fx * (1 - fy)
            + img[y0 + 1, x0] * (1 - fx) * fy + img[y0 + 1, x0 + 1] * fx * fy)


# --------------------------------------------------------------------------
# Autocorrelation and the measurements derived from it
# --------------------------------------------------------------------------
def autocorr(img, max_lag=MAX_LAG):
    """Normalised, unbiased 2D ACF via FFT. Returns (acf, L): acf has shape
    (2L+1, 2L+1) with zero lag at the centre."""
    h, w = img.shape
    f = img - img.mean()
    shape = (2 * h, 2 * w)
    ac = np.fft.irfft2(np.abs(np.fft.rfft2(f, s=shape)) ** 2, s=shape)
    ones = np.fft.rfft2(np.ones_like(f), s=shape)
    overlap = np.fft.irfft2(np.abs(ones) ** 2, s=shape)
    ac = np.fft.fftshift(ac) / np.maximum(np.fft.fftshift(overlap), 1.0)
    ac /= ac[h, w]
    L = min(max_lag, h // 2, w // 2)
    return ac[h - L:h + L + 1, w - L:w + L + 1], L


def radial_profile(acf, L):
    y, x = np.mgrid[-L:L + 1, -L:L + 1]
    r = np.hypot(x, y).round().astype(int).ravel()
    prof = np.bincount(r, acf.ravel()) / np.bincount(r)
    return prof[:L + 1]


def crossing(prof, level):
    below = np.nonzero(prof < level)[0]
    if len(below) == 0:
        return np.nan
    k = below[0]
    if k == 0:
        return 0.0
    return k - 1 + (prof[k - 1] - level) / (prof[k - 1] - prof[k])


def central_lobe(acf, L):
    """Connected region of positive ACF containing the origin."""
    pos = acf > 0
    region = np.zeros_like(pos)
    region[L, L] = True
    while True:
        grown = region.copy()
        grown[1:, :] |= region[:-1, :]
        grown[:-1, :] |= region[1:, :]
        grown[:, 1:] |= region[:, :-1]
        grown[:, :-1] |= region[:, 1:]
        grown &= pos
        if (grown == region).all():
            return region
        region = grown


def lobe_shape(acf, L, lobe):
    """Second moments of the central peak (ACF > 0.5) -> ellipse."""
    y, x = np.mgrid[-L:L + 1, -L:L + 1]
    m = lobe & (acf > 0.5)
    wts = acf[m]
    xs, ys = x[m], y[m]
    cov = np.array([[np.sum(wts * xs * xs), np.sum(wts * xs * ys)],
                    [np.sum(wts * xs * ys), np.sum(wts * ys * ys)]]) / wts.sum()
    vals, vecs = np.linalg.eigh(cov)
    vals = np.maximum(vals, 1e-6)
    major = vecs[:, 1]
    angle = np.degrees(np.arctan2(major[1], major[0])) % 180
    return np.sqrt(vals[1]), np.sqrt(vals[0]), angle


def repeat_peak(acf, L, lobe, min_height=0.15):
    y, x = np.mgrid[-L:L + 1, -L:L + 1]
    r = np.hypot(x, y)
    cand = (~lobe) & (acf > min_height) & (r <= 0.8 * L)
    if not cand.any():
        return None
    score = np.where(cand, acf - 0.002 * r, -np.inf)
    k = np.unravel_index(np.argmax(score), acf.shape)
    return x[k], y[k], acf[k]


def directional_cut(acf, L, angle_deg):
    r = np.arange(L + 1)
    t = np.deg2rad(angle_deg)
    xi = np.clip(np.round(r * np.cos(t)).astype(int) + L, 0, 2 * L)
    yi = np.clip(np.round(r * np.sin(t)).astype(int) + L, 0, 2 * L)
    return acf[yi, xi]


def ideal_lattice_lags(p, L, rad, K=K_PEAKS):
    """Ideal lattice lag vectors out to K spacings that fit in the ACF window."""
    B = lattice_vectors(p)
    lags = []
    for i in range(-K, K + 1):
        for j in range(-K, K + 1):
            if (i, j) == (0, 0) or i * i + j * j > K * K:
                continue
            d = B @ [i, j]
            if abs(d[0]) < L - rad and abs(d[1]) < L - rad:
                lags.append(d)
    return np.array(lags).reshape(-1, 2)


def peak_stats(acf, L, lags, rad):
    """Centroid and rms width of the positive ACF near each expected lag."""
    Y, X = np.mgrid[-L:L + 1, -L:L + 1]
    out = np.full((len(lags), 3), np.nan)
    for k, (dx, dy) in enumerate(lags):
        w = (X - dx) ** 2 + (Y - dy) ** 2 < rad**2
        v = np.clip(acf, 0, None) * w
        s = v.sum()
        if s <= 1e-9:
            continue
        mx, my = (v * X).sum() / s, (v * Y).sum() / s
        out[k] = mx, my, np.sqrt((v * ((X - mx) ** 2 + (Y - my) ** 2)).sum() / s)
    return out


def affine_from_peaks(ideal_c, meas_c):
    """Fit meas = F @ ideal; return principal stretches, their direction and
    the rotation, via the polar decomposition of F."""
    ok = np.all(np.isfinite(ideal_c), axis=1) & np.all(np.isfinite(meas_c), axis=1)
    if ok.sum() < 3:
        return None
    T, *_ = np.linalg.lstsq(ideal_c[ok], meas_c[ok], rcond=None)
    F = T.T
    U, S, Vt = np.linalg.svd(F)
    Rm = U @ Vt
    rot = np.degrees(np.arctan2(Rm[1, 0], Rm[0, 0]))
    direction = np.degrees(np.arctan2(Vt[0, 1], Vt[0, 0])) % 180
    return S[0], S[1], direction, rot


# --------------------------------------------------------------------------
# Interactive figure
# --------------------------------------------------------------------------
HINTS = {
    "Random blobs": "Only a central peak; its width = grain size.",
    "Grating": "ACF is itself a grating.",
    "Dot lattice": "Side peaks sit on the lattice vectors.",
    "Your image": "Look for side peaks and an elongated centre.",
}
DIST_HINTS = {
    "None": "No distortion: the difference is just noise.",
    "Uniform stretch (x)": "Arrows along x, growing with lag;\nno rings (uniform).",
    "Shear": "Arrows parallel to x, sign flips\nabove/below the centre; no rings.",
    "Rotation": "Arrows circle the centre; no rings.",
    "Barrel": "Outward arrows (net expansion) AND\nrings (scale varies across image).",
    "Smooth random warp": "Rings but almost no arrows:\nspacing varies, no overall trend.",
}
GENERATORS = {"Random blobs": make_blobs, "Grating": make_grating,
              "Dot lattice": make_lattice}


def build_app(user_img=None):
    state = {"seed": 0, "pattern": "Dot lattice", "dist": "Barrel"}

    fig = plt.figure(figsize=(17, 9))
    fig.canvas.manager.set_window_title("Autocorrelation explorer")
    top, hgt = 0.43, 0.50
    ax_img = fig.add_axes([0.015, top, 0.19, hgt])
    ax_acf = fig.add_axes([0.26, top, 0.19, hgt])
    ax_cb = fig.add_axes([0.455, top, 0.007, hgt])
    ax_dif = fig.add_axes([0.50, top, 0.20, hgt])
    ax_prof = fig.add_axes([0.755, top, 0.23, hgt])

    sm = plt.cm.ScalarMappable(cmap="RdBu_r", norm=plt.Normalize(-1, 1))
    fig.colorbar(sm, cax=ax_cb)

    labels = list(GENERATORS) + (["Your image"] if user_img is not None else [])
    ax_radio = fig.add_axes([0.02, 0.10, 0.10, 0.04 + 0.04 * len(labels)])
    ax_radio.set_title("Pattern", fontsize=10)
    radio = RadioButtons(ax_radio, labels, active=labels.index(state["pattern"]))

    ax_dradio = fig.add_axes([0.13, 0.04, 0.12, 0.30])
    ax_dradio.set_title("Distortion", fontsize=10)
    dradio = RadioButtons(ax_dradio, DISTORTIONS,
                          active=DISTORTIONS.index(state["dist"]))

    def mk(y, label, lo, hi, init, step=None):
        return Slider(fig.add_axes([0.38, y, 0.20, 0.025]), label, lo, hi,
                      valinit=init, valstep=step)

    sliders = {
        "size":   mk(0.335, "feature size (px)", 1, 15, 3, 0.5),
        "period": mk(0.290, "period (px)", 6, 60, 20, 1),
        "angle":  mk(0.245, "angle (deg)", 0, 180, 0, 1),
        "aspect": mk(0.200, "aspect", 1, 4, 1, 0.1),
        "jitter": mk(0.155, "jitter (x period)", 0, 0.4, 0.0, 0.01),
        "noise":  mk(0.110, "noise", 0, 3, 0.3, 0.05),
        "dist":   mk(0.050, "distortion strength", 0, 0.15, 0.06, 0.005),
    }
    btn = Button(fig.add_axes([0.02, 0.02, 0.10, 0.045]), "New random seed")
    readout = fig.text(0.665, 0.355, "", va="top", family="monospace", fontsize=9)

    def update(_=None):
        p = {k: s.val for k, s in sliders.items()}
        kind, strength = state["dist"], p["dist"]
        rng = np.random.default_rng(state["seed"])

        # base pattern, generated with a margin so warping never pulls in blanks
        if state["pattern"] == "Your image":
            base, pad = user_img.copy(), 0
            R = min(base.shape) / 2
        else:
            base, pad = GENERATORS[state["pattern"]](p, rng, N + 2 * PAD), PAD
            R = N / 2
        warped = apply_distortion(base, kind, strength, state["seed"], R)
        crop = (slice(pad, base.shape[0] - pad), slice(pad, base.shape[1] - pad))
        ideal, dist = base[crop], warped[crop]

        # identical normalisation and noise for both, so only the warp differs
        mu, sd = ideal.mean(), ideal.std() + 1e-12
        noise = p["noise"] * rng.standard_normal(ideal.shape)
        ideal = (ideal - mu) / sd + noise
        dist = (dist - mu) / sd + noise

        acf, L = autocorr(dist)
        acf0, _ = autocorr(ideal)
        dacf = acf - acf0
        prof, prof0 = radial_profile(acf, L), radial_profile(acf0, L)
        corr_len = crossing(prof, 1 / np.e)
        lobe = central_lobe(acf, L)
        s_major, s_minor, lobe_angle = lobe_shape(acf, L, lobe)
        peak = repeat_peak(acf, L, lobe)

        # --- image + displacement arrows
        h, w = dist.shape
        ax_img.clear()
        ax_img.imshow(dist, cmap="gray", origin="lower")
        if kind != "None" and strength > 0:
            step = max(h, w) // 8
            gy, gx = np.mgrid[step // 2:h:step, step // 2:w:step].astype(float)
            field = None
            if kind == "Smooth random warp":
                fx, fy = warp_field(warped.shape, strength, state["seed"], R)
                field = (fx[crop][gy.astype(int), gx.astype(int)],
                         fy[crop][gy.astype(int), gx.astype(int)])
            ux, uy = forward_displacement(kind, strength, gx - w / 2, gy - h / 2,
                                          R, field)
            ax_img.quiver(gx, gy, ux, uy, angles="xy", scale_units="xy",
                          scale=1 / 3, color="gold", width=0.006)
        ax_img.set_xlim(-0.5, w - 0.5); ax_img.set_ylim(-0.5, h - 0.5)
        ax_img.set_title(f"Image: {kind.lower()}" if kind != "None" else "Image")
        ax_img.set_xticks([]); ax_img.set_yticks([])

        # --- ACF
        ext = [-L - 0.5, L + 0.5, -L - 0.5, L + 0.5]
        ax_acf.clear()
        ax_acf.imshow(acf, cmap="RdBu_r", vmin=-1, vmax=1, origin="lower", extent=ext)
        ax_acf.axhline(0, color="k", lw=0.3); ax_acf.axvline(0, color="k", lw=0.3)
        ax_acf.add_patch(Ellipse((0, 0), 4 * s_major, 4 * s_minor,
                                 angle=lobe_angle, fill=False, color="lime", lw=2))
        if peak is not None:
            ax_acf.plot([0, peak[0]], [0, peak[1]], color="gold", lw=1.5)
            ax_acf.plot(peak[0], peak[1], "x", color="gold", ms=12, mew=3)
        ax_acf.set_title("ACF (distorted)")
        ax_acf.set_xlabel("dx (px)"); ax_acf.set_ylabel("dy (px)")

        # --- difference
        ax_dif.clear()
        ax_dif.imshow(dacf, cmap="PiYG", vmin=-0.6, vmax=0.6, origin="lower",
                      extent=ext)
        ax_dif.set_title("ACF(distorted) − ACF(ideal)\ngreen = gained, pink = lost",
                         fontsize=10)
        ax_dif.set_xlabel("dx (px)")
        fit = None
        if state["pattern"] == "Dot lattice":
            rad = 0.45 * p["period"]
            lags = ideal_lattice_lags(p, L, rad)
            st0 = peak_stats(acf0, L, lags, rad)
            st1 = peak_stats(acf, L, lags, rad)
            shift = st1[:, :2] - st0[:, :2]
            widen = np.nan_to_num(st1[:, 2] - st0[:, 2])
            ax_dif.plot(lags[:, 0], lags[:, 1], "+", color="k", ms=5, mew=0.8)
            ax_dif.scatter(st0[:, 0], st0[:, 1], s=10 + 250 * np.clip(widen, 0, None),
                           facecolors="none", edgecolors="tab:red", lw=1.2)
            ax_dif.quiver(st0[:, 0], st0[:, 1], shift[:, 0], shift[:, 1],
                          angles="xy", scale_units="xy", scale=0.2,
                          color="tab:blue", width=0.006)
            zoom = min(L, (K_PEAKS + 0.6) * p["period"] * p["aspect"])
            ax_dif.set_xlim(-zoom, zoom); ax_dif.set_ylim(-zoom, zoom)
            fit = affine_from_peaks(st0[:, :2], st1[:, :2])
            mean_widen = np.nanmean(st1[:, 2] - st0[:, 2])

        # --- profiles
        ax_prof.clear()
        r = np.arange(L + 1)
        ax_prof.plot(r, prof0, color="gray", ls="--", lw=1.5, label="ideal radial")
        ax_prof.plot(r, prof, "k", lw=2, label="distorted radial")
        ax_prof.plot(r, directional_cut(acf, L, lobe_angle), color="tab:green",
                     lw=1, label="along lobe long axis")
        ax_prof.plot(r, directional_cut(acf, L, lobe_angle + 90), color="tab:purple",
                     lw=1, label="along lobe short axis")
        ax_prof.axhline(1 / np.e, color="gray", ls=":", lw=1)
        ax_prof.axhline(0, color="gray", lw=0.5)
        ax_prof.set_xlim(0, L); ax_prof.set_ylim(-1.05, 1.05)
        ax_prof.set_xlabel("lag distance (px)"); ax_prof.set_ylabel("ACF")
        ax_prof.set_title("ACF profiles")
        ax_prof.legend(loc="upper right", fontsize=8)

        # --- numbers
        lines = [
            f"correlation length (1/e) : {corr_len:6.1f} px",
            f"central lobe anisotropy  : {s_major / s_minor:6.2f}"
            f"  at {lobe_angle:5.1f} deg",
        ]
        if peak is not None:
            lines.append(f"nearest repeat           : {np.hypot(peak[0], peak[1]):6.1f} px"
                         f"  ({peak[0]:+d}, {peak[1]:+d})")
        else:
            lines.append("nearest repeat           : none found")
        lines.append(f"rms of ACF difference    : {np.sqrt(np.mean(dacf**2)):6.3f}")
        if fit is not None:
            s1, s2, d, rot = fit
            lines += ["",
                      "affine fit to ACF peaks (uniform part):",
                      f"  stretches  {s1:.3f} / {s2:.3f}  (max along {d:5.1f} deg)",
                      f"  rotation   {rot:+.2f} deg",
                      "nonuniform part:",
                      f"  mean peak widening {mean_widen:+.2f} px"]
        elif state["pattern"] != "Dot lattice":
            lines += ["", "(peak arrows/rings: dot lattice only)"]
        lines += ["", HINTS[state["pattern"]], DIST_HINTS[kind]]
        readout.set_text("\n".join(lines))
        fig.canvas.draw_idle()

    def on_radio(label):
        state["pattern"] = label
        update()

    def on_dradio(label):
        state["dist"] = label
        update()

    def on_seed(_):
        state["seed"] += 1
        update()

    radio.on_clicked(on_radio)
    dradio.on_clicked(on_dradio)
    btn.on_clicked(on_seed)
    for s in sliders.values():
        s.on_changed(update)

    update()
    fig._widgets = (radio, dradio, btn, sliders)
    return fig, update, state


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", help="optional image file to analyse")
    args = ap.parse_args()
    user_img = load_user_image(args.image) if args.image else None
    build_app(user_img)
    plt.show()


if __name__ == "__main__":
    main()
