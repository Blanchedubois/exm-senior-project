#!/usr/bin/env python3
"""
Simulate pre-expansion (1x) and post-expansion (4x) fluorescence images of the
'optimistic' ArUco + dot fiducial grid (reference_tags.json / spec_sheet.json).

Physics and imaging taken from the spec sheet
  * 0.51 um/px, Gaussian PSF with FWHM 1.91 um
  * every printed feature is a rigid island: it keeps its printed size and
    shape at any expansion; only the spacing between islands scales
  * printed material is BRIGHT in fluorescence (tag black modules = bright)
  * design frame is y-UP, images are y-DOWN (design -> image is a reflection)

Distortions
  pre  (1x): print jitter of every island (PRINT_JITTER_UM), a small stage
             rotation, shot + read noise.
  post (4x): expansion LAMBDA about the grid centre, stage rotation and offset,
             independent gel jitter of every island (GEL_JITTER_UM, in
             post-expansion um), shot + read noise, and LAGGING PATCHES:
             Gaussian regions whose local linear expansion is lower by
             'deficit' (0.12 -> that region expands 12 % less). The displacement
             field is the compatible (irrotational) field whose dilatation
             equals the requested deficit: u = grad(phi), lap(phi) = 2 e.
             Rigid islands translate with u and rotate with the stage only.

Outputs (in ./sim_out)
  pre.png, post.png      16-bit images
  truth.npz              true pixel positions of every feature in both images,
                         categories, ids, lag field, parameters
  features_truth.csv     the same positions as a table

Run:  python exm_sim.py  (needs numpy, scipy, opencv-contrib-python, pillow)
"""

import csv
import json
import os

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.special import erf

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.environ.get("REF_TAGS", os.path.join(HERE, "reference_tags.json"))
OUT = os.path.join(HERE, "sim_out")

# ----------------------------------------------------------------- parameters
UM_PX = 0.51
PSF_FWHM_UM = 1.91
FIELD_UM = 750.0
LAMBDA = 4.0

PRINT_JITTER_UM = 0.08          # rms, pre and post (it is the same print)
GEL_JITTER_UM = 0.40            # rms, post only, in post-expansion um
THETA_PRE_DEG = 0.6             # stage rotation in the pre image
THETA_POST_DEG = 4.0            # stage rotation in the post image
OFFSET_PRE_UM = (6.0, -4.0)
OFFSET_POST_UM = (30.0, -20.0)

# lagging patches in DESIGN coordinates (um, y-up): x, y, sigma, deficit
PATCHES = [(230.0, 530.0, 35.0, 0.15),
           (520.0, 260.0, 40.0, 0.12),
           (560.0, 590.0, 28.0, 0.15)]

PEAK_E_PRE = 600.0              # photo-electrons at a fully covered pixel
BG_E_PRE = 100.0
READ_E = 4.0
# spec: signal ~ lambda^-1.84, exposure raised ~ lambda^2 -> net lambda^0.16
POST_GAIN = LAMBDA ** 0.16

MARGIN_PRE_UM = 25.0
MARGIN_POST_UM = 50.0
SEED = 7

SIGMA_PX = PSF_FWHM_UM / 2.3548 / UM_PX


# ----------------------------------------------------------------- features
def load_features():
    """Rigid islands as rectangles in design um. Returns per-island centres and
    per-rectangle (island index, offset from island centre, half sizes)."""
    ref = json.load(open(REF))
    recs = ref["records"]
    dside = ref["dot_side_um"] / 2
    cfg = ref["config"]
    dash_l, dash_w = cfg["dash_len_um"] / 2, cfg["dash_width_um"] / 2
    aruco = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)

    isl_xy, isl_cat, isl_tag, isl_id = [], [], [], []
    rect_isl, rect_off, rect_half = [], [], []
    for r in recs:
        k = len(isl_xy)
        isl_xy.append((r["x_um"], r["y_um"]))
        isl_cat.append(r["category"])
        isl_tag.append(r["tag"])
        cat = r["category"]
        if cat == "dot":
            isl_id.append(-1)
            rect_isl.append(k); rect_off.append((0.0, 0.0)); rect_half.append((dside, dside))
        elif cat == "dash":
            isl_id.append(-1)
            horiz = r["meta"]["line"].startswith("H")
            rect_isl.append(k); rect_off.append((0.0, 0.0))
            rect_half.append((dash_l, dash_w) if horiz else (dash_w, dash_l))
        else:  # aruco: 6x6 modules incl. border; black module = printed
            m = r["meta"]
            isl_id.append(m["aruco_id"])
            size = m["size_um"]
            nmod = 6
            mod = size / nmod
            bits = cv2.aruco.generateImageMarker(aruco, m["aruco_id"], nmod)
            for row in range(nmod):          # row 0 = top of the marker
                for col in range(nmod):
                    if bits[row, col] == 0:  # black = printed
                        dx = -size / 2 + (col + 0.5) * mod
                        dy = size / 2 - (row + 0.5) * mod   # design y-up
                        rect_isl.append(k); rect_off.append((dx, dy))
                        rect_half.append((mod / 2, mod / 2))
    return dict(xy=np.array(isl_xy), cat=np.array(isl_cat), tag=np.array(isl_tag),
                id=np.array(isl_id), rect_isl=np.array(rect_isl),
                rect_off=np.array(rect_off), rect_half=np.array(rect_half))


# ----------------------------------------------------------------- lag field
def lag_field(step=2.0):
    """Displacement (design um, y-up) from the lagging patches, on a padded
    grid. Returns interpolators for ux, uy and the local linear scale."""
    xs = np.arange(-400.0, 1150.0, step)
    X, Y = np.meshgrid(xs, xs)
    e = np.zeros_like(X)
    for x, y, s, d in PATCHES:
        e -= d * np.exp(-((X - x) ** 2 + (Y - y) ** 2) / (2 * s * s))
    src = 2 * e - (2 * e).mean()
    k = np.fft.fftfreq(len(xs), step)
    KX, KY = np.meshgrid(k, k)
    k2 = (2 * np.pi) ** 2 * (KX ** 2 + KY ** 2)
    k2[0, 0] = 1
    ph = -np.fft.fft2(src) / k2
    ph[0, 0] = 0
    ux = np.real(np.fft.ifft2(1j * 2 * np.pi * KX * ph))
    uy = np.real(np.fft.ifft2(1j * 2 * np.pi * KY * ph))
    duy_dy, duy_dx = np.gradient(uy, step)
    dux_dy, dux_dx = np.gradient(ux, step)
    scale = np.sqrt((1 + dux_dx) * (1 + duy_dy) - dux_dy * duy_dx)

    def interp(field, x, y):
        return ndimage.map_coordinates(field, [(y - xs[0]) / step, (x - xs[0]) / step],
                                       order=1, mode="nearest")
    return dict(xs=xs, ux=ux, uy=uy, scale=scale, e=e, interp=interp)


# ----------------------------------------------------------------- geometry
def rot(deg):
    t = np.deg2rad(deg)
    return np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])


def to_image_plane(xy_design):
    """design (y-up) -> sample plane as seen by the camera (y-down), in um."""
    return np.c_[xy_design[:, 0], FIELD_UM - xy_design[:, 1]]


def place(xy_img_um, scale, theta_deg, offset_um, margin_um, size_px, jitter_um, rng):
    """Positions in image pixels: rotate+scale about the grid centre, offset,
    jitter, then into the image whose centre holds the grid centre."""
    c = np.array([FIELD_UM / 2, FIELD_UM / 2])
    p = (xy_img_um - c) @ (scale * rot(theta_deg)).T
    p += np.array(offset_um) + rng.normal(0, jitter_um, p.shape)
    return p / UM_PX + size_px / 2.0


# ----------------------------------------------------------------- rendering
def render(size_px, cx, cy, hx, hy, theta_deg, sigma=SIGMA_PX, chunk=3000):
    """Sum of rotated rectangles blurred by an isotropic Gaussian (exact:
    erf products in each rectangle's own frame)."""
    acc = np.zeros(size_px * size_px)
    t = np.deg2rad(theta_deg)
    c, s = np.cos(t), np.sin(t)
    k2 = np.sqrt(2) * sigma

    def f(u, h):
        return 0.5 * (erf((u + h) / k2) - erf((u - h) / k2))

    for half in np.unique(np.c_[hx, hy], axis=0):
        sel = np.nonzero((hx == half[0]) & (hy == half[1]))[0]
        r = int(np.ceil(np.hypot(*half) + 4 * sigma))
        d = np.arange(-r, r + 1)
        DX, DY = np.meshgrid(d, d)
        for k in range(0, len(sel), chunk):
            idx = sel[k:k + chunk]
            x0 = np.round(cx[idx]).astype(int)[:, None, None]
            y0 = np.round(cy[idx]).astype(int)[:, None, None]
            ix, iy = x0 + DX, y0 + DY
            px = ix - cx[idx][:, None, None]
            py = iy - cy[idx][:, None, None]
            u = c * px + s * py
            v = -s * px + c * py
            val = f(u, half[0]) * f(v, half[1])
            ok = (ix >= 0) & (ix < size_px) & (iy >= 0) & (iy < size_px)
            acc += np.bincount((iy[ok] * size_px + ix[ok]), val[ok], minlength=acc.size)
    return acc.reshape(size_px, size_px)


def expose(clean, peak, bg, rng):
    e = rng.poisson(clean * peak + bg).astype(np.float64)
    e += rng.normal(0, READ_E, e.shape)
    return np.clip(np.round(e), 0, 65535).astype(np.uint16)


# ----------------------------------------------------------------- main
def simulate():
    os.makedirs(OUT, exist_ok=True)
    rng = np.random.default_rng(SEED)
    F = load_features()
    lag = lag_field()

    # design -> displaced design (lag acts only after expansion)
    xy = F["xy"] + rng.normal(0, PRINT_JITTER_UM, F["xy"].shape)   # print jitter
    ux = lag["interp"](lag["ux"], F["xy"][:, 0], F["xy"][:, 1])
    uy = lag["interp"](lag["uy"], F["xy"][:, 0], F["xy"][:, 1])
    xy_lag = xy + np.c_[ux, uy]

    n_pre = int(np.ceil((FIELD_UM + 2 * MARGIN_PRE_UM) / UM_PX))
    ext = LAMBDA * FIELD_UM / 2 * (np.cos(np.deg2rad(THETA_POST_DEG)) + np.sin(np.deg2rad(THETA_POST_DEG)))
    n_post = int(np.ceil(2 * (ext + MARGIN_POST_UM + max(map(abs, OFFSET_POST_UM))) / UM_PX))

    isl_pre = place(to_image_plane(xy), 1.0, THETA_PRE_DEG, OFFSET_PRE_UM,
                    MARGIN_PRE_UM, n_pre, 0.0, rng)
    isl_post = place(to_image_plane(xy_lag), LAMBDA, THETA_POST_DEG, OFFSET_POST_UM,
                     MARGIN_POST_UM, n_post, GEL_JITTER_UM, rng)

    def rects(isl_px, theta):
        R = rot(theta)
        off = to_image_plane(F["rect_off"] + FIELD_UM / 2)  # flip y of offsets
        off = (off - FIELD_UM / 2) @ R.T / UM_PX
        p = isl_px[F["rect_isl"]] + off
        h = F["rect_half"] / UM_PX
        return p[:, 0], p[:, 1], h[:, 0], h[:, 1]

    pre_clean = render(n_pre, *rects(isl_pre, THETA_PRE_DEG), THETA_PRE_DEG)
    post_clean = render(n_post, *rects(isl_post, THETA_POST_DEG), THETA_POST_DEG)
    pre = expose(pre_clean, PEAK_E_PRE, BG_E_PRE, rng)
    post = expose(post_clean, PEAK_E_PRE * POST_GAIN, BG_E_PRE * POST_GAIN, rng)

    Image.fromarray(pre).save(os.path.join(OUT, "pre.png"))
    Image.fromarray(post).save(os.path.join(OUT, "post.png"))

    # true global affine pre px -> post px over all islands
    M = np.c_[isl_pre, np.ones(len(isl_pre))]
    T, *_ = np.linalg.lstsq(M, isl_post, rcond=None)
    np.savez_compressed(os.path.join(OUT, "truth.npz"),
                        pre_px=isl_pre, post_px=isl_post, cat=F["cat"], tag=F["tag"],
                        aruco_id=F["id"], design_um=F["xy"], affine_pre_to_post=T,
                        lag_xs=lag["xs"], lag_scale=lag["scale"], lag_ux=lag["ux"],
                        lag_uy=lag["uy"], patches=np.array(PATCHES),
                        params=json.dumps(dict(
                            UM_PX=UM_PX, PSF_FWHM_UM=PSF_FWHM_UM, LAMBDA=LAMBDA,
                            PRINT_JITTER_UM=PRINT_JITTER_UM, GEL_JITTER_UM=GEL_JITTER_UM,
                            THETA_PRE_DEG=THETA_PRE_DEG, THETA_POST_DEG=THETA_POST_DEG,
                            OFFSET_PRE_UM=OFFSET_PRE_UM, OFFSET_POST_UM=OFFSET_POST_UM,
                            PATCHES=PATCHES, SEED=SEED)))
    with open(os.path.join(OUT, "features_truth.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["tag", "category", "aruco_id", "x_design_um", "y_design_um",
                    "x_pre_px", "y_pre_px", "x_post_px", "y_post_px"])
        for k in range(len(isl_pre)):
            w.writerow([F["tag"][k], F["cat"][k], F["id"][k], *np.round(F["xy"][k], 4),
                        *np.round(isl_pre[k], 3), *np.round(isl_post[k], 3)])
    print(f"pre {pre.shape}, post {post.shape}; true affine (pre->post px):\n{T[:2].T}")
    return pre, post


if __name__ == "__main__":
    simulate()
