#!/usr/bin/env python3
"""
Analyse the simulated pre (1x) and post (4x) fiducial images from exm_sim.py.

  1. ACF of pre and ACF of post
       - dot-lattice basis in each image -> expansion tensor F (pre px -> post px)
       - peak heights post/pre vs lag order -> how much nonuniformity
  2. CCF of pre vs post corrected with the ACF transform
       - global CCF: residual shift, and how unambiguous the match is
       - windowed CCF: residual displacement field and local expansion map,
         naive (largest peak in the search box) vs lattice-aware (wrapped to one
         lattice cell, then quality-guided unwrapping)
  3. Cross-check against decoded ArUco tag centres and the ground truth

Run after exm_sim.py:  python exm_analysis.py
Figures go to ./sim_out/fig_*.png, numbers to ./sim_out/results.json
"""

import heapq
import json
import os

import numpy as np
from PIL import Image
from scipy import fft as sfft
from scipy import ndimage

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from check_tags import detect

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "sim_out")
UM_PX = 0.51


# ===================================================================== ACF
def acf(img, L):
    """Unbiased, normalised ACF for lags |dx|,|dy| <= L (zero-padded by L)."""
    f = img.astype(np.float32)
    f -= f.mean()
    h, w = f.shape
    shape = (h + L, w + L)
    F = sfft.rfft2(f, s=shape, workers=-1)
    ac = sfft.irfft2(F * np.conj(F), s=shape, workers=-1)
    del F
    O = sfft.rfft2(np.ones_like(f), s=shape, workers=-1)
    ov = sfft.irfft2(O * np.conj(O), s=shape, workers=-1)
    del O
    ac = np.roll(ac, (L, L), axis=(0, 1))[:2 * L + 1, :2 * L + 1]
    ov = np.roll(ov, (L, L), axis=(0, 1))[:2 * L + 1, :2 * L + 1]
    ac = ac / np.maximum(ov, 1)
    return (ac / ac[L, L]).astype(np.float64)


def radial_profile(a, L):
    Y, X = np.mgrid[-L:L + 1, -L:L + 1]
    r = np.hypot(X, Y).round().astype(int).ravel()
    return (np.bincount(r, a.ravel()) / np.bincount(r))[:L + 1]


def first_peak(prof):
    """First local max after the first local min of a radial profile."""
    k = 1
    while k < len(prof) - 1 and not (prof[k] < prof[k + 1]):
        k += 1
    while k < len(prof) - 1 and not (prof[k] > prof[k + 1]):
        k += 1
    return k


def subpixel_max(a, cx, cy, rad):
    """Highest pixel within rad of (cx, cy) (array coords), parabolic refine."""
    y0, x0 = int(round(cy)), int(round(cx))
    r = int(np.ceil(rad))
    ys, xs = slice(max(y0 - r, 1), y0 + r + 1), slice(max(x0 - r, 1), x0 + r + 1)
    sub = a[ys, xs]
    Y, X = np.mgrid[ys, xs]
    m = (X - cx) ** 2 + (Y - cy) ** 2 <= rad ** 2
    k = np.argmax(np.where(m, sub, -np.inf))
    y, x = Y.ravel()[k], X.ravel()[k]
    if not (0 < y < a.shape[0] - 1 and 0 < x < a.shape[1] - 1):
        return float(x), float(y), a[y, x]
    def par(m1, c0, p1):
        d = m1 - 2 * c0 + p1
        return 0.0 if d >= 0 else 0.5 * (m1 - p1) / d
    return (x + par(a[y, x - 1], a[y, x], a[y, x + 1]),
            y + par(a[y - 1, x], a[y, x], a[y + 1, x]), a[y, x])


def lattice_basis(a, L, K=8):
    """Dot-lattice basis (columns, px) from an ACF, refined on all peaks out to
    K lattice steps. Returns basis, peak table (i, j, x, y, height), pitch guess."""
    p = first_peak(radial_profile(a, L))
    Y, X = np.mgrid[-L:L + 1, -L:L + 1]
    r = np.hypot(X, Y)
    size = max(3, int(p / 3) | 1)
    peaks = (a == ndimage.maximum_filter(a, size=size)) & (r > 0.6 * p) & (r < 1.3 * p)
    cand = np.c_[X[peaks], Y[peaks], a[peaks]]
    a1 = cand[np.argmax(cand[:, 2]), :2]
    ang = np.arctan2(cand[:, 1], cand[:, 0]) - np.arctan2(a1[1], a1[0])
    perp = np.abs(np.cos(ang)) < 0.35
    a2 = cand[perp][np.argmax(cand[perp][:, 2]), :2]
    B = np.c_[a1, a2].astype(float)
    if np.linalg.det(B) < 0:
        B[:, 1] *= -1
    for kmax in (2, 4, K):                      # grow outward, refit each time
        rows = []
        for i in range(-kmax, kmax + 1):
            for j in range(-kmax, kmax + 1):
                if (i, j) == (0, 0) or i * i + j * j > kmax * kmax:
                    continue
                q = B @ [i, j]
                if np.abs(q).max() > L - p:
                    continue
                x, y, h = subpixel_max(a, q[0] + L, q[1] + L, 0.3 * p)
                rows.append((i, j, x - L, y - L, h))
        rows = np.array(rows)
        sol, *_ = np.linalg.lstsq(rows[:, :2], rows[:, 2:4], rcond=None)
        B = sol.T
    return B, rows, p


def match_bases(Bpre, Bpost):
    """Pick the post basis orientation (one of 4 lattice rotations) that gives
    the smallest rotation between images. A square lattice alone cannot tell
    4 deg from 94 deg; tags or the CCF settle that."""
    best = None
    for k in range(4):
        Rk = np.array([[0, -1], [1, 0]]) ** 0
        Rk = np.linalg.matrix_power(np.array([[0, -1], [1, 0]]), k)
        Bp = Bpost @ Rk
        F = Bp @ np.linalg.inv(Bpre)
        rot = np.degrees(np.arctan2(F[1, 0] - F[0, 1], F[0, 0] + F[1, 1]))
        if best is None or abs(rot) < abs(best[2]):
            best = (Bp, F, rot)
    return best[0], best[1]


def describe(F):
    U, S, Vt = np.linalg.svd(F)
    R = U @ Vt
    return dict(scale=float(np.sqrt(S[0] * S[1])), s_max=float(S[0]), s_min=float(S[1]),
                anisotropy=float(S[0] / S[1]),
                stretch_dir_deg=float(np.degrees(np.arctan2(Vt[0, 1], Vt[0, 0])) % 180),
                rotation_deg=float(np.degrees(np.arctan2(R[1, 0], R[0, 0]))))


# ===================================================================== CCF
_BLUR_CACHE = {}


def correct_post(post, A, b, shape):
    """Resample post into the pre frame: corrected(x) = post(A x + b)."""
    lam = np.sqrt(abs(np.linalg.det(A)))
    key = round(0.45 * lam, 2)
    if key not in _BLUR_CACHE:                      # anti-alias before shrinking
        _BLUR_CACHE[key] = ndimage.gaussian_filter(post.astype(np.float32), key)
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]].astype(np.float32)
    sx = A[0, 0] * xx + A[0, 1] * yy + b[0]
    sy = A[1, 0] * xx + A[1, 1] * yy + b[1]
    return ndimage.map_coordinates(_BLUR_CACHE[key], [sy, sx], order=1, mode="constant",
                                   cval=float(np.median(post)))


def ccf_global(a, b, L):
    """c(s) = sum a(x) b(x+s), normalised, |s| <= L."""
    a = a.astype(np.float64) - a.mean()
    b = b.astype(np.float64) - b.mean()
    h, w = a.shape
    shape = (h + L, w + L)
    c = sfft.irfft2(np.conj(sfft.rfft2(a, s=shape)) * sfft.rfft2(b, s=shape), s=shape)
    c = np.roll(c, (L, L), axis=(0, 1))[:2 * L + 1, :2 * L + 1]
    return c / np.sqrt((a ** 2).sum() * (b ** 2).sum())


def windowed_ccf(pre, cor, win, step, S):
    """Normalised CCF in Hann windows; returns centres, ccf stack (2S+1)^2, contrast."""
    h, w = pre.shape
    cs_y = np.arange(win // 2, h - win // 2 + 1, step)
    cs_x = np.arange(win // 2, w - win // 2 + 1, step)
    hann = np.outer(np.hanning(win), np.hanning(win)).astype(np.float32)
    n = 2 * win
    out = np.zeros((len(cs_y), len(cs_x), 2 * S + 1, 2 * S + 1), np.float32)
    contrast = np.zeros((len(cs_y), len(cs_x)), np.float32)
    for a, cy in enumerate(cs_y):
        A = np.stack([pre[cy - win // 2:cy + win // 2, cx - win // 2:cx + win // 2] for cx in cs_x])
        Bw = np.stack([cor[cy - win // 2:cy + win // 2, cx - win // 2:cx + win // 2] for cx in cs_x])
        A = (A - A.mean((1, 2), keepdims=True)) * hann
        Bw = (Bw - Bw.mean((1, 2), keepdims=True)) * hann
        na = np.sqrt((A ** 2).sum((1, 2)))
        nb = np.sqrt((Bw ** 2).sum((1, 2)))
        C = np.fft.irfft2(np.conj(np.fft.rfft2(A, s=(n, n))) * np.fft.rfft2(Bw, s=(n, n)), s=(n, n))
        C = np.roll(C, (S, S), axis=(1, 2))[:, :2 * S + 1, :2 * S + 1]
        out[a] = C / np.maximum(na * nb, 1e-9)[:, None, None]
        contrast[a] = na
    return cs_x, cs_y, out, contrast


def peak_in_region(c, S, mask):
    """Subpixel max of one window's CCF restricted to mask."""
    k = np.argmax(np.where(mask, c, -np.inf))
    y, x = divmod(k, c.shape[1])
    if 0 < y < c.shape[0] - 1 and 0 < x < c.shape[1] - 1:
        def par(m1, c0, p1):
            d = m1 - 2 * c0 + p1
            return 0.0 if d >= 0 else 0.5 * (m1 - p1) / d
        return x - S + par(c[y, x - 1], c[y, x], c[y, x + 1]), \
               y - S + par(c[y - 1, x], c[y, x], c[y + 1, x]), c[y, x]
    return x - S, y - S, c[y, x]


def unwrap(wrapped, quality, valid, B):
    """Quality-guided unwrapping of a displacement field known only modulo the
    lattice B. Neighbouring windows are assumed to differ by < half a cell."""
    Binv = np.linalg.inv(B)
    ny, nx = quality.shape
    lat = np.einsum("ij,yxj->yxi", Binv, wrapped)       # lattice coords
    out = np.full_like(lat, np.nan)
    q = np.where(valid, quality, -np.inf)
    cy, cx = ny // 2, nx // 2
    win = q[max(cy - 3, 0):cy + 4, max(cx - 3, 0):cx + 4]
    sy, sx = np.unravel_index(np.argmax(win), win.shape)
    seed = (sy + max(cy - 3, 0), sx + max(cx - 3, 0))
    out[seed] = lat[seed]
    heap = [(-q[seed], seed)]
    done = np.zeros(quality.shape, bool)
    done[seed] = True
    while heap:
        _, (y, x) = heapq.heappop(heap)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            yy, xx = y + dy, x + dx
            if 0 <= yy < ny and 0 <= xx < nx and valid[yy, xx] and not done[yy, xx]:
                ref = out[y, x]
                out[yy, xx] = lat[yy, xx] + np.round(ref - lat[yy, xx])
                done[yy, xx] = True
                heapq.heappush(heap, (-q[yy, xx], (yy, xx)))
    disp = np.einsum("ij,yxj->yxi", B, out)
    return disp


def local_scale_fit(disp, step, base_scale, rad=2):
    """Local linear expansion from a least-squares plane fit of the residual
    displacement over (2 rad + 1)^2 neighbouring windows."""
    ny, nx, _ = disp.shape
    out = np.full((ny, nx), np.nan)
    oy, ox = np.mgrid[-rad:rad + 1, -rad:rad + 1]
    for a in range(ny):
        for c in range(nx):
            if not np.isfinite(disp[a, c, 0]):
                continue
            ys, xs = a + oy.ravel(), c + ox.ravel()
            m = (ys >= 0) & (ys < ny) & (xs >= 0) & (xs < nx)
            ys, xs = ys[m], xs[m]
            d = disp[ys, xs]
            g = np.isfinite(d[:, 0])
            if g.sum() < 9:
                continue
            M = np.c_[(xs[g] - c) * step, (ys[g] - a) * step, np.ones(g.sum())]
            cf, *_ = np.linalg.lstsq(M, d[g], rcond=None)
            J = np.eye(2) + cf[:2].T
            out[a, c] = base_scale * np.sqrt(abs(np.linalg.det(J)))
    return out


def local_scale(disp, step, base_scale):
    """Local linear expansion from the gradient of the residual displacement."""
    dux_dy, dux_dx = np.gradient(disp[..., 0], step)
    duy_dy, duy_dx = np.gradient(disp[..., 1], step)
    det = (1 + dux_dx) * (1 + duy_dy) - dux_dy * duy_dx
    return base_scale * np.sqrt(np.abs(det))


# ===================================================================== main
def main():
    pre = np.array(Image.open(os.path.join(OUT, "pre.png"))).astype(np.float32)
    post = np.array(Image.open(os.path.join(OUT, "post.png"))).astype(np.float32)
    T = np.load(os.path.join(OUT, "truth.npz"))
    pre_px, post_px, cat = T["pre_px"], T["post_px"], T["cat"]
    Ftrue = T["affine_pre_to_post"][:2].T
    res = {"truth_global": describe(Ftrue)}

    # ------------------------------------------------------------ 1. ACFs
    Lpre, Lpost = 330, 1250
    A_pre = acf(pre, Lpre)
    A_post = acf(post, Lpost)
    Bpre, rows_pre, p_pre = lattice_basis(A_pre, Lpre)
    Bpost, rows_post, p_post = lattice_basis(A_post, Lpost)
    Bpost, F_acf = match_bases(Bpre, Bpost)
    res["acf_pre_basis_px"] = Bpre.tolist()
    res["acf_post_basis_px"] = Bpost.tolist()
    res["acf_pitch_pre_um"] = float(np.sqrt(abs(np.linalg.det(Bpre))) * UM_PX)
    res["acf_pitch_post_um"] = float(np.sqrt(abs(np.linalg.det(Bpost))) * UM_PX)
    res["acf_global"] = describe(F_acf)

    # peak heights post/pre at the same lattice index
    def heights(A, L, B, K=8):
        out = {}
        p = np.sqrt(abs(np.linalg.det(B)))
        for i in range(-K, K + 1):
            for j in range(-K, K + 1):
                if (i, j) == (0, 0) or i * i + j * j > K * K:
                    continue
                q = B @ [i, j]
                if np.abs(q).max() > L - p:
                    continue
                out[(i, j)] = subpixel_max(A, q[0] + L, q[1] + L, 0.3 * p)[2]
        return out
    H_pre = heights(A_pre, Lpre, Bpre)
    H_post = heights(A_post, Lpost, Bpost)
    keys = sorted(set(H_pre) & set(H_post), key=lambda k: np.hypot(*k))
    order = np.array([np.hypot(*k) for k in keys])
    ratio = np.array([H_post[k] / H_pre[k] for k in keys])

    # ------------------------------------------------------------ 2. tags
    d_pre = detect(os.path.join(OUT, "pre.png"), 0.01)
    d_post = detect(os.path.join(OUT, "post.png"), 0.003)
    common = sorted(set(d_pre) & set(d_post))
    P0 = np.array([d_pre[i] for i in common])
    P1 = np.array([d_post[i] for i in common])
    Tt, *_ = np.linalg.lstsq(np.c_[P0, np.ones(len(P0))], P1, rcond=None)
    res["aruco_tags"] = dict(n_tags=len(common), global_=describe(Tt[:2].T))

    # ------------------------------------------------------------ 3. CCF
    c_pre = np.array(pre.shape[::-1]) / 2.0
    c_post = np.array(post.shape[::-1]) / 2.0
    Lg, win, step, S = 300, 64, 24, 12
    pitch_pre = np.sqrt(abs(np.linalg.det(Bpre)))
    dots = cat == "dot"
    hann1 = np.hanning(win)

    def pipeline(A, b):
        """Correct post with x_post = A x_pre + b, then global + windowed CCF."""
        cor0 = correct_post(post, A, b, pre.shape)
        G0 = ccf_global(pre, cor0, Lg)
        sx, sy, _ = subpixel_max(G0, Lg, Lg, Lg - 1)
        s = np.array([sx - Lg, sy - Lg])          # pre(x) ~ cor0(x + s)
        b = b + A @ s                              # so that cor(x) = cor0(x + s)
        cor = correct_post(post, A, b, pre.shape)
        G = ccf_global(pre, cor, Lg)
        Yg, Xg = np.mgrid[-Lg:Lg + 1, -Lg:Lg + 1]
        side = np.where(np.hypot(Xg, Yg) > 3, G, -np.inf)
        k2 = np.unravel_index(np.argmax(side), G.shape)
        out = dict(G=G, k2=k2, shift=s, A=A, b=b)
        stats = dict(global_shift_applied_px=s.tolist(), ccf_peak=float(G[Lg, Lg]),
                     next_best_peak=float(G[k2]), next_best_at_px=[int(Xg[k2]), int(Yg[k2])])

        Ainv = np.linalg.inv(A)
        true_disp = (post_px - b) @ Ainv.T - pre_px      # where pre content lands in cor
        cs_x, cs_y, C, contrast = windowed_ccf(pre, cor, win, step, S)
        ny, nx = len(cs_y), len(cs_x)
        valid = contrast > 0.5 * np.median(contrast[contrast > np.percentile(contrast, 60)])
        Yc, Xc = np.mgrid[-S:S + 1, -S:S + 1]
        lat = np.einsum("ij,jyx->iyx", np.linalg.inv(Bpre), np.stack([Xc, Yc]).astype(float))
        cell = (np.abs(lat[0]) <= 0.5) & (np.abs(lat[1]) <= 0.5)
        box = np.ones_like(cell)
        naive = np.full((ny, nx, 2), np.nan)
        wrapped = np.full((ny, nx, 2), np.nan)
        qual = np.zeros((ny, nx))
        for a in range(ny):
            for c in range(nx):
                if valid[a, c]:
                    naive[a, c] = peak_in_region(C[a, c], S, box)[:2]
                    x2, y2, h2 = peak_in_region(C[a, c], S, cell)
                    wrapped[a, c] = x2, y2
                    qual[a, c] = h2
        unw = unwrap(np.nan_to_num(wrapped), qual, valid, Bpre)
        lat_med = np.nanmedian(np.einsum("ij,yxj->yxi", np.linalg.inv(Bpre), unw)[valid], axis=0)
        unw -= Bpre @ np.round(lat_med)
        unw[~valid] = np.nan

        true_win = np.full((ny, nx, 2), np.nan)
        true_scale = np.full((ny, nx), np.nan)
        for a, cy in enumerate(cs_y):
            for c, cx in enumerate(cs_x):
                if not valid[a, c]:
                    continue
                m = dots & (np.abs(pre_px[:, 0] - cx) < win / 2) & (np.abs(pre_px[:, 1] - cy) < win / 2)
                if m.sum() < 6:
                    continue
                wgt = np.interp(pre_px[m, 0] - cx + win / 2, np.arange(win), hann1) * \
                      np.interp(pre_px[m, 1] - cy + win / 2, np.arange(win), hann1)
                true_win[a, c] = (true_disp[m] * wgt[:, None]).sum(0) / wgt.sum()
                M = np.c_[pre_px[m], np.ones(m.sum())]
                # truth over the same footprint as the plane fit (+/- 2 steps)
                mm = dots & (np.abs(pre_px[:, 0] - cx) < 2 * step + win / 4) & \
                     (np.abs(pre_px[:, 1] - cy) < 2 * step + win / 4)
                M = np.c_[pre_px[mm], np.ones(mm.sum())]
                Tl, *_ = np.linalg.lstsq(M, post_px[mm], rcond=None)
                true_scale[a, c] = np.sqrt(abs(np.linalg.det(Tl[:2].T)))
        lam = np.sqrt(abs(np.linalg.det(A)))
        meas_scale = local_scale_fit(unw, step, lam)
        naive_scale = local_scale_fit(naive, step, lam)
        ok = np.isfinite(true_win[..., 0]) & np.isfinite(unw[..., 0])
        err_naive = np.hypot(*(naive - true_win)[ok].T)
        err_unw = np.hypot(*(unw - true_win)[ok].T)
        sok = ok & np.isfinite(meas_scale) & np.isfinite(true_scale)
        stats.update(
            window_px=win, step_px=step, windows=int(ok.sum()),
            true_residual_max_px=float(np.nanmax(np.hypot(*true_win[ok].T))),
            naive_rms_err_px=float(np.sqrt(np.mean(err_naive ** 2))),
            naive_frac_off_by_a_cell=float(np.mean(err_naive > 0.5 * pitch_pre)),
            unwrapped_rms_err_px=float(np.sqrt(np.mean(err_unw ** 2))),
            unwrapped_frac_off_by_a_cell=float(np.mean(err_unw > 0.5 * pitch_pre)),
            local_scale_corr=float(np.corrcoef(meas_scale[sok], true_scale[sok])[0, 1]),
            local_scale_rms_err=float(np.sqrt(np.mean((meas_scale[sok] - true_scale[sok]) ** 2))),
            true_bulk_scale_median=float(np.nanmedian(true_scale[ok])))
        out.update(cs_x=cs_x, cs_y=cs_y, naive=naive, unwrapped=unw, true_win=true_win,
                   true_scale=true_scale, meas_scale=meas_scale, naive_scale=naive_scale,
                   ok=ok, sok=sok, err_naive=err_naive, err_unw=err_unw, stats=stats)
        return out

    P_acf = pipeline(F_acf, c_post - F_acf @ c_pre)
    P_tag = pipeline(Tt[:2].T, Tt[2])
    res["ccf_after_acf_correction"] = P_acf["stats"]
    res["ccf_after_tag_correction"] = P_tag["stats"]

    json.dump(res, open(os.path.join(OUT, "results.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))

    # main CCF figure uses the tag-corrected run
    G, k2 = P_tag["G"], P_tag["k2"]
    cs_x, cs_y = P_tag["cs_x"], P_tag["cs_y"]
    naive, unwrapped, true_win = P_tag["naive"], P_tag["unwrapped"], P_tag["true_win"]
    true_scale, meas_scale, naive_scale = P_tag["true_scale"], P_tag["meas_scale"], P_tag["naive_scale"]
    ok, sok, err_naive, err_unw = P_tag["ok"], P_tag["sok"], P_tag["err_naive"], P_tag["err_unw"]
    res["windowed_ccf"] = P_tag["stats"]

    # ============================================================ figures
    patches = T["patches"]
    params = json.loads(str(T["params"]))
    n_pre = pre.shape[0]

    def design_to_pre_px(x, y):
        th = np.deg2rad(params["THETA_PRE_DEG"])
        R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
        v = np.array([x - 375.0, (750.0 - y) - 375.0]) @ R.T + params["OFFSET_PRE_UM"]
        return v / UM_PX + n_pre / 2.0

    def outline(ax, scale_px=1.0, centre_fn=design_to_pre_px, color="w"):
        for x, y, s, d in patches:
            cx, cy = centre_fn(x, y)
            ax.add_patch(plt.Circle((cx, cy), 1.5 * s / UM_PX * scale_px, fill=False,
                                    ls="--", color=color, lw=1))

    # ---------- figure 1: images and truth
    fig, axs = plt.subplots(2, 3, figsize=(20, 13.5))
    lo, hi = np.percentile(pre, [1, 99.7])
    axs[0, 0].imshow(pre, cmap="gray", vmin=lo, vmax=hi)
    outline(axs[0, 0], color="orange")
    axs[0, 0].set_title(f"Pre (1x): {pre.shape[1]}×{pre.shape[0]} px\n(orange = where lagging patches will be)")
    lo2, hi2 = np.percentile(post, [1, 99.97])
    axs[0, 1].imshow(post[::4, ::4], cmap="gray", vmin=lo2, vmax=hi2)
    axs[0, 1].set_title(f"Post (4x): {post.shape[1]}×{post.shape[0]} px (shown 1:4)\n"
                        f"true scale {res['truth_global']['scale']:.4f}, rotation "
                        f"{res['truth_global']['rotation_deg']:+.2f}° vs pre")
    # zoom on one patch edge, same sample region in both
    zx, zy = design_to_pre_px(patches[0][0] + 45, patches[0][1])
    hw = 70
    axs[0, 2].imshow(pre[int(zy) - hw:int(zy) + hw, int(zx) - hw:int(zx) + hw], cmap="gray",
                     vmin=lo, vmax=hi)
    axs[0, 2].set_title("Pre zoom (patch 1 edge, 71×71 µm)")
    zp = np.array([zx, zy, 1.0]) @ T["affine_pre_to_post"]
    hw4 = int(hw * res["truth_global"]["scale"])
    axs[1, 0].imshow(post[int(zp[1]) - hw4:int(zp[1]) + hw4, int(zp[0]) - hw4:int(zp[0]) + hw4],
                     cmap="gray", vmin=lo2, vmax=hi2)
    axs[1, 0].set_title("Post zoom, same sample region\n(rigid dots stay small, spacing ×4)")
    xs = T["lag_xs"]
    im = axs[1, 1].imshow(params["LAMBDA"] * T["lag_scale"], origin="lower", cmap="viridis",
                          extent=[xs[0], xs[-1], xs[0], xs[-1]], vmin=3.35, vmax=4.05)
    axs[1, 1].set_xlim(0, 750); axs[1, 1].set_ylim(0, 750)
    for x, y, s, dd in patches:
        axs[1, 1].add_patch(plt.Circle((x, y), 1.5 * s, fill=False, ls="--", color="w"))
        axs[1, 1].text(x, y + 1.6 * s, f"−{dd * 100:.0f}%", color="w", ha="center")
    fig.colorbar(im, ax=axs[1, 1], shrink=0.8, label="local linear expansion")
    axs[1, 1].set_title("Ground truth: local expansion (design µm, y up)")
    axs[1, 1].set_xlabel("x (µm)"); axs[1, 1].set_ylabel("y (µm)")
    tw = true_win.copy()
    q = axs[1, 2].quiver(*np.meshgrid(cs_x, cs_y), tw[..., 0], tw[..., 1], np.hypot(tw[..., 0], tw[..., 1]),
                         angles="xy", scale_units="xy", scale=0.25, cmap="plasma", width=0.003)
    axs[1, 2].set_xlim(0, n_pre); axs[1, 2].set_ylim(n_pre, 0); axs[1, 2].set_aspect("equal")
    outline(axs[1, 2], color="k")
    fig.colorbar(q, ax=axs[1, 2], shrink=0.8, label="px (pre frame)")
    axs[1, 2].set_title("Ground truth: residual displacement after the\nglobal fit (arrows ×4, pre px; pitch = 9.8 px)")
    for ax in axs.ravel()[[0, 1, 2, 3]]:
        ax.set_xticks([]); ax.set_yticks([])
    plt.tight_layout(); plt.savefig(os.path.join(OUT, "fig_1_images.png"), dpi=55, bbox_inches="tight"); plt.close()

    # ---------- figure 2: ACFs
    fig, axs = plt.subplots(2, 3, figsize=(20, 13))
    def show_acf(ax, A, L, zoom, B, title, v=1.0):
        ax.imshow(A, cmap="RdBu_r", vmin=-v, vmax=v, extent=[-L - .5, L + .5, L + .5, -L - .5])
        ax.set_xlim(-zoom, zoom); ax.set_ylim(zoom, -zoom)
        if B is not None:
            ax.annotate("", xy=B[:, 0], xytext=(0, 0), arrowprops=dict(color="lime", width=2))
            ax.annotate("", xy=B[:, 1], xytext=(0, 0), arrowprops=dict(color="gold", width=2))
        ax.set_title(title); ax.set_xlabel("lag dx (px)"); ax.set_ylabel("lag dy (px)")
    g = res["acf_global"]
    show_acf(axs[0, 0], A_pre, Lpre, 5.5 * p_pre, Bpre,
             f"ACF pre, small lags: dot lattice\npitch {res['acf_pitch_pre_um']:.3f} µm (design 5.000)")
    show_acf(axs[0, 1], A_pre, Lpre, Lpre, None,
             "ACF pre, large lags: node lattice\n(tags + dash lines, 285 px)")
    show_acf(axs[1, 0], A_post, Lpost, 5.5 * p_post, Bpost,
             f"ACF post, small lags: dot lattice\npitch {res['acf_pitch_post_um']:.2f} µm")
    show_acf(axs[1, 1], A_post, Lpost, Lpost, None,
             "ACF post, large lags: node lattice (×4)\n(colour range ±0.15)", v=0.15)
    ax = axs[0, 2]
    ax.axis("off")
    tg, tt = res["truth_global"], res["aruco_tags"]["global_"]
    rows = [("", "ACF (dots)", "ArUco tags", "truth"),
            ("scale", f"{g['scale']:.4f}", f"{tt['scale']:.4f}", f"{tg['scale']:.4f}"),
            ("anisotropy", f"{g['anisotropy']:.4f}", f"{tt['anisotropy']:.4f}", f"{tg['anisotropy']:.4f}"),
            ("rotation (°)", f"{g['rotation_deg']:+.3f}", f"{tt['rotation_deg']:+.3f}", f"{tg['rotation_deg']:+.3f}")]
    tbl = ax.table(cellText=rows, loc="center", cellLoc="center")
    tbl.scale(1, 2.4); tbl.set_fontsize(13)
    ax.set_title("Global pre → post transform\n(ACF needs no alignment or correspondence)", fontsize=12)
    ax = axs[1, 2]
    ax.plot(order, ratio, "o", ms=4, color="tab:red")
    bins = np.arange(0.5, 9, 1)
    idx = np.digitize(order, bins)
    ax.plot([order[idx == k].mean() for k in np.unique(idx)],
            [ratio[idx == k].mean() for k in np.unique(idx)], "k-", lw=2, label="mean per shell")
    ax.axhline(1, color="gray", ls="--")
    ax.set_xlabel("lag (dot-lattice spacings)"); ax.set_ylabel("ACF peak height, post / pre")
    ax.set_title("Peak height post/pre vs lag\nflat drop = jitter; falling trend = nonuniform expansion")
    ax.legend(); ax.grid(alpha=0.3)
    plt.tight_layout(); plt.savefig(os.path.join(OUT, "fig_2_acf.png"), dpi=55, bbox_inches="tight"); plt.close()

    # ---------- figure 3: CCF
    fig, axs = plt.subplots(2, 4, figsize=(24, 12.5))
    ax = axs[0, 0]
    ax.imshow(G, cmap="magma", extent=[-Lg - .5, Lg + .5, Lg + .5, -Lg - .5])
    ax.set_title(f"Global CCF(pre, corrected post), ±{Lg} px\npeak {G[Lg, Lg]:.3f}; next best {G[k2]:.3f}")
    ax.set_xlabel("shift (px)")
    ax = axs[0, 1]
    z = 30
    ax.imshow(G, cmap="magma", extent=[-Lg - .5, Lg + .5, Lg + .5, -Lg - .5])
    ax.set_xlim(-z, z); ax.set_ylim(z, -z)
    ax.set_title("Global CCF, zoom ±30 px\nside peaks = dot lattice (9.8 px)")
    vmax = 1.2 * np.nanmax(np.hypot(*true_win[ok].T))
    for ax, field, title in [(axs[0, 2], naive, "Windowed CCF, naive\n(largest peak within ±12 px)"),
                             (axs[0, 3], unwrapped, "Windowed CCF, lattice-aware\n(wrapped to one cell, then unwrapped)")]:
        mag = np.hypot(field[..., 0], field[..., 1])
        im = ax.imshow(mag, cmap="plasma", vmin=0, vmax=vmax,
                       extent=[cs_x[0] - step / 2, cs_x[-1] + step / 2, cs_y[-1] + step / 2, cs_y[0] - step / 2])
        ax.set_xlim(0, n_pre); ax.set_ylim(n_pre, 0); outline(ax)
        e = err_naive if field is naive else err_unw
        ax.set_title(f"{title}\n|displacement|; rms error {np.sqrt(np.mean(e ** 2)):.2f} px, "
                     f"{100 * np.mean(e > 4.9):.1f}% off by a cell", fontsize=11)
        fig.colorbar(im, ax=ax, shrink=0.75, label="px")
    ax = axs[1, 0]
    im = ax.imshow(np.hypot(true_win[..., 0], true_win[..., 1]), cmap="plasma", vmin=0, vmax=vmax,
                   extent=[cs_x[0] - step / 2, cs_x[-1] + step / 2, cs_y[-1] + step / 2, cs_y[0] - step / 2])
    ax.set_xlim(0, n_pre); ax.set_ylim(n_pre, 0); outline(ax)
    ax.set_title("Ground truth |displacement| per window")
    fig.colorbar(im, ax=ax, shrink=0.75, label="px")
    ext = [cs_x[0] - step / 2, cs_x[-1] + step / 2, cs_y[-1] + step / 2, cs_y[0] - step / 2]
    for ax, fld, title in [(axs[1, 1], np.where(ok, true_scale, np.nan), "Ground truth local expansion"),
                           (axs[1, 2], np.where(ok, meas_scale, np.nan),
                            f"Measured local expansion (lattice-aware CCF)\nr = {res['windowed_ccf']['local_scale_corr']:.3f}")]:
        im = ax.imshow(fld, cmap="viridis", vmin=3.35, vmax=4.05, extent=ext)
        ax.set_xlim(0, n_pre); ax.set_ylim(n_pre, 0); outline(ax)
        ax.set_title(title)
        fig.colorbar(im, ax=ax, shrink=0.75)
    ax = axs[1, 3]
    ax.plot(true_scale[sok], meas_scale[sok], ".", ms=3, alpha=0.4, color="k", label="lattice-aware")
    nok = sok & np.isfinite(naive_scale)
    ax.plot(true_scale[nok], np.clip(naive_scale[nok], 3.0, 4.4), ".", ms=3, alpha=0.25,
            color="tab:red", label="naive")
    ax.plot([3.35, 4.1], [3.35, 4.1], "b--", lw=1)
    ax.set_xlim(3.35, 4.1); ax.set_ylim(3.0, 4.4)
    ax.set_xlabel("true local expansion"); ax.set_ylabel("measured")
    ax.set_title(f"Local expansion per window\nrms error {res['windowed_ccf']['local_scale_rms_err']:.3f}")
    ax.legend()
    for ax in axs.ravel()[[2, 3, 4, 5, 6]]:
        ax.set_xticks([]); ax.set_yticks([])
    plt.tight_layout(); plt.savefig(os.path.join(OUT, "fig_3_ccf.png"), dpi=55, bbox_inches="tight"); plt.close()

    # ---------- figure 4: CCF when only the ACF transform is used for correction
    fig, axs = plt.subplots(1, 3, figsize=(19, 6.3))
    st = P_acf["stats"]
    Ga = P_acf["G"]
    axs[0].imshow(Ga, cmap="magma", extent=[-Lg - .5, Lg + .5, Lg + .5, -Lg - .5])
    axs[0].set_xlim(-30, 30); axs[0].set_ylim(30, -30)
    axs[0].set_title(f"Global CCF after ACF-only correction, ±30 px\npeak {st['ccf_peak']:.3f} vs next "
                     f"{st['next_best_peak']:.3f} at {st['next_best_at_px']}: ambiguous")
    ext_a = [P_acf["cs_x"][0] - step / 2, P_acf["cs_x"][-1] + step / 2,
             P_acf["cs_y"][-1] + step / 2, P_acf["cs_y"][0] - step / 2]
    im = axs[1].imshow(np.hypot(*np.moveaxis(P_acf["true_win"], -1, 0)), cmap="plasma", extent=ext_a)
    axs[1].set_xlim(0, n_pre); axs[1].set_ylim(n_pre, 0); outline(axs[1])
    fig.colorbar(im, ax=axs[1], shrink=0.8, label="px")
    axs[1].set_title(f"True residual after ACF-only correction\nmax {st['true_residual_max_px']:.1f} px "
                     f"(dot pitch 9.8 px)")
    e = np.hypot(*np.moveaxis(P_acf["unwrapped"] - P_acf["true_win"], -1, 0))
    im = axs[2].imshow(e, cmap="Reds", vmin=0, vmax=20, extent=ext_a)
    axs[2].set_xlim(0, n_pre); axs[2].set_ylim(n_pre, 0); outline(axs[2], color="k")
    fig.colorbar(im, ax=axs[2], shrink=0.8, label="px")
    axs[2].set_title(f"Windowed CCF error (lattice-aware)\n{100 * st['unwrapped_frac_off_by_a_cell']:.0f}% "
                     f"of windows off by ≥ half a cell")
    for ax in axs[1:]:
        ax.set_xticks([]); ax.set_yticks([])
    plt.tight_layout(); plt.savefig(os.path.join(OUT, "fig_4_ccf_acf_only.png"), dpi=55, bbox_inches="tight"); plt.close()


if __name__ == "__main__":
    main()
