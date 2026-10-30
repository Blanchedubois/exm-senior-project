"""ACF, lattice fit, global and windowed CCF, unwrapping, local expansion.

Ported from exm_analysis.py. Changes from the reference are speed only:
  * the ACF overlap normalisation is computed analytically, (h-|dy|)(w-|dx|),
    instead of with a second FFT (same numbers)
  * FFTs use scipy.fft with all cores
  * the windowed CCF can be restricted to a subset of the window grid
  * peak picking and the local plane fit are vectorised (same maths)
No Qt here: the CLI, tests and worker all import this module.
"""

import heapq

import numpy as np
from scipy import fft as sfft
from scipy import ndimage

from .frames import describe


# ===================================================================== ACF
def acf(img, L):
    """Unbiased, normalised ACF for lags |dx|,|dy| <= L (zero-padded by L).
    Returns a (2L+1, 2L+1) array with lag (dx, dy) at [L + dy, L + dx]."""
    f = np.asarray(img, np.float32)
    f = f - f.mean()
    h, w = f.shape
    shape = (h + L, w + L)
    F = sfft.rfft2(f, s=shape, workers=-1)
    ac = sfft.irfft2(F * np.conj(F), s=shape, workers=-1)
    del F
    ac = np.roll(ac, (L, L), axis=(0, 1))[:2 * L + 1, :2 * L + 1]
    d = np.arange(-L, L + 1)
    ov = np.outer(h - np.abs(d), w - np.abs(d)).astype(np.float64)
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


def _par(m1, c0, p1):
    d = m1 - 2 * c0 + p1
    return 0.0 if d >= 0 else 0.5 * (m1 - p1) / d


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
    return (x + _par(a[y, x - 1], a[y, x], a[y, x + 1]),
            y + _par(a[y - 1, x], a[y, x], a[y + 1, x]), a[y, x])


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
    the smallest rotation between images. Returns (Bpost', F = Bpost' Bpre^-1)."""
    best = None
    for k in range(4):
        Rk = np.linalg.matrix_power(np.array([[0, -1], [1, 0]]), k)
        Bp = Bpost @ Rk
        F = Bp @ np.linalg.inv(Bpre)
        rot = np.degrees(np.arctan2(F[1, 0] - F[0, 1], F[0, 0] + F[1, 1]))
        if best is None or abs(rot) < abs(best[2]):
            best = (Bp, F, rot)
    return best[0], best[1]


def peak_heights(A, L, B, K=8):
    """ACF peak height at every lattice index (i, j) with i^2 + j^2 <= K^2."""
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


def height_ratio(H_pre, H_post):
    """(lag order, post/pre peak height) over common lattice indices."""
    keys = sorted(set(H_pre) & set(H_post), key=lambda k: np.hypot(*k))
    order = np.array([np.hypot(*k) for k in keys])
    ratio = np.array([H_post[k] / H_pre[k] for k in keys])
    return order, ratio


def acf_peak_shifts(A_meas, A_ref, L, B, K=4):
    """Peak shift and widening of A_meas against A_ref at the lattice peaks of
    B (both ACFs in the same frame). Returns rows (i, j, x_ref, y_ref, dx, dy,
    width_ratio); width from the curvature of the peak."""
    p = np.sqrt(abs(np.linalg.det(B)))
    rows = []
    for i in range(-K, K + 1):
        for j in range(-K, K + 1):
            if (i, j) == (0, 0) or i * i + j * j > K * K:
                continue
            q = B @ [i, j]
            if np.abs(q).max() > L - p:
                continue
            x0, y0, h0 = subpixel_max(A_ref, q[0] + L, q[1] + L, 0.3 * p)
            x1, y1, h1 = subpixel_max(A_meas, q[0] + L, q[1] + L, 0.3 * p)
            rows.append((i, j, x0 - L, y0 - L, x1 - x0, y1 - y0,
                         _width(A_meas, x1, y1) / max(_width(A_ref, x0, y0), 1e-9)))
    return np.array(rows)


def _width(a, x, y):
    """RMS width of a peak from its discrete Laplacian (Gaussian model)."""
    yi, xi = int(round(y)), int(round(x))
    if not (0 < yi < a.shape[0] - 1 and 0 < xi < a.shape[1] - 1):
        return np.nan
    c = a[yi, xi]
    lap = a[yi, xi - 1] + a[yi, xi + 1] + a[yi - 1, xi] + a[yi + 1, xi] - 4 * c
    return np.sqrt(max(-2 * c / lap, 0)) if lap < 0 else np.nan


# ===================================================================== CCF
class Corrector:
    """Resample a post image into the pre frame: corrected(x) = post(A x + b),
    with an anti-alias blur of 0.45 lambda post px first (cached per lambda)."""

    def __init__(self, post):
        self.post = np.asarray(post, np.float32)
        self.cval = float(np.median(self.post))
        self._blur = {}

    def __call__(self, A, b, shape):
        lam = np.sqrt(abs(np.linalg.det(A)))
        key = round(0.45 * lam, 2)
        if key not in self._blur:
            self._blur[key] = ndimage.gaussian_filter(self.post, key)
        yy, xx = np.mgrid[0:shape[0], 0:shape[1]].astype(np.float32)
        sx = A[0, 0] * xx + A[0, 1] * yy + b[0]
        sy = A[1, 0] * xx + A[1, 1] * yy + b[1]
        return ndimage.map_coordinates(self._blur[key], [sy, sx], order=1, mode="constant",
                                       cval=self.cval)


def ccf_global(a, b, L, Fa=None):
    """c(s) = sum a(x) b(x+s), normalised, |s| <= L. Fa: cached
    (rfft of mean-free a at shape (h+L, w+L), sum a^2)."""
    h, w = a.shape
    shape = (h + L, w + L)
    if Fa is None:
        Fa = global_ccf_prep(a, L)
    Fa_, aa = Fa
    b = np.asarray(b, np.float64) - b.mean()
    c = sfft.irfft2(np.conj(Fa_) * sfft.rfft2(b, s=shape, workers=-1), s=shape, workers=-1)
    c = np.roll(c, (L, L), axis=(0, 1))[:2 * L + 1, :2 * L + 1]
    return c / np.sqrt(aa * (b ** 2).sum())


def global_ccf_prep(a, L):
    a = np.asarray(a, np.float64) - a.mean()
    h, w = a.shape
    return sfft.rfft2(a, s=(h + L, w + L), workers=-1), float((a ** 2).sum())


def ccf_side_peak(G, L, r_excl=3):
    """Best competing peak of a global CCF outside radius r_excl of zero lag."""
    Yg, Xg = np.mgrid[-L:L + 1, -L:L + 1]
    side = np.where(np.hypot(Xg, Yg) > r_excl, G, -np.inf)
    k2 = np.unravel_index(np.argmax(side), G.shape)
    return float(G[k2]), (int(Xg[k2]), int(Yg[k2]))


def window_centres(shape, win, step):
    h, w = shape
    return np.arange(win // 2, w - win // 2 + 1, step), np.arange(win // 2, h - win // 2 + 1, step)


def window_contrast(pre, win, step):
    """Norm of each Hann-weighted, mean-free pre window (pre only: cacheable)."""
    cs_x, cs_y = window_centres(pre.shape, win, step)
    hann = np.outer(np.hanning(win), np.hanning(win)).astype(np.float32)
    out = np.zeros((len(cs_y), len(cs_x)), np.float32)
    for a, cy in enumerate(cs_y):
        A = np.stack([pre[cy - win // 2:cy + win // 2, cx - win // 2:cx + win // 2] for cx in cs_x])
        A = (A - A.mean((1, 2), keepdims=True)) * hann
        out[a] = np.sqrt((A ** 2).sum((1, 2)))
    return out


def valid_windows(contrast):
    return contrast > 0.5 * np.median(contrast[contrast > np.percentile(contrast, 60)])


def windowed_ccf(pre, cor, win, step, S, which=None):
    """Normalised CCF in Hann windows. Returns cs_x, cs_y, ccf stack
    (ny, nx, 2S+1, 2S+1) and contrast. which: optional (ny, nx) bool mask of
    windows to compute (others stay zero)."""
    pre = np.asarray(pre, np.float32)
    cor = np.asarray(cor, np.float32)
    cs_x, cs_y = window_centres(pre.shape, win, step)
    hann = np.outer(np.hanning(win), np.hanning(win)).astype(np.float32)
    n = 2 * win
    out = np.zeros((len(cs_y), len(cs_x), 2 * S + 1, 2 * S + 1), np.float32)
    contrast = np.zeros((len(cs_y), len(cs_x)), np.float32)
    for a, cy in enumerate(cs_y):
        cols = np.arange(len(cs_x)) if which is None else np.nonzero(which[a])[0]
        if len(cols) == 0:
            continue
        sl = [slice(cs_x[c] - win // 2, cs_x[c] + win // 2) for c in cols]
        rows = slice(cy - win // 2, cy + win // 2)
        A = np.stack([pre[rows, s] for s in sl])
        Bw = np.stack([cor[rows, s] for s in sl])
        A = (A - A.mean((1, 2), keepdims=True)) * hann
        Bw = (Bw - Bw.mean((1, 2), keepdims=True)) * hann
        na = np.sqrt((A ** 2).sum((1, 2)))
        nb = np.sqrt((Bw ** 2).sum((1, 2)))
        C = sfft.irfft2(np.conj(sfft.rfft2(A, s=(n, n), workers=-1)) *
                        sfft.rfft2(Bw, s=(n, n), workers=-1), s=(n, n), workers=-1)
        C = np.roll(C, (S, S), axis=(1, 2))[:, :2 * S + 1, :2 * S + 1]
        out[a, cols] = C / np.maximum(na * nb, 1e-9)[:, None, None]
        contrast[a, cols] = na
    return cs_x, cs_y, out, contrast


def peaks_in_region(C, S, mask):
    """Vectorised peak_in_region over a stack C (..., 2S+1, 2S+1): subpixel
    (dx, dy) and height of the max inside mask."""
    sh = C.shape[:-2]
    m = C.shape[-1]
    flat = np.where(mask, C, -np.inf).reshape(-1, m * m)
    Cf = C.reshape(-1, m, m)
    k = np.argmax(flat, axis=1)
    y, x = np.divmod(k, m)
    idx = np.arange(len(k))
    h = Cf[idx, y, x]
    inner = (y > 0) & (y < m - 1) & (x > 0) & (x < m - 1)
    yc, xc = np.clip(y, 1, m - 2), np.clip(x, 1, m - 2)

    def par(m1, c0, p1):
        d = m1 - 2 * c0 + p1
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(d >= 0, 0.0, 0.5 * (m1 - p1) / np.where(d == 0, 1, d))
    c0 = Cf[idx, yc, xc]
    dx = np.where(inner, par(Cf[idx, yc, xc - 1], c0, Cf[idx, yc, xc + 1]), 0.0)
    dy = np.where(inner, par(Cf[idx, yc - 1, xc], c0, Cf[idx, yc + 1, xc]), 0.0)
    return ((x - S + dx).reshape(sh), (y - S + dy).reshape(sh), h.reshape(sh))


def cell_mask(B, S):
    """Lags within one lattice cell of B (|lattice coords| <= 0.5)."""
    Yc, Xc = np.mgrid[-S:S + 1, -S:S + 1]
    lat = np.einsum("ij,jyx->iyx", np.linalg.inv(B), np.stack([Xc, Yc]).astype(float))
    return (np.abs(lat[0]) <= 0.5) & (np.abs(lat[1]) <= 0.5)


def unwrap(wrapped, quality, valid, B):
    """Quality-guided unwrapping of a displacement field known only modulo the
    lattice B. Neighbouring windows are assumed to differ by < half a cell."""
    Binv = np.linalg.inv(B)
    ny, nx = quality.shape
    lat = np.einsum("ij,yxj->yxi", Binv, wrapped)       # lattice coords
    out = np.full_like(lat, np.nan)
    q = np.where(valid, quality, -np.inf)
    if not valid.any():
        return np.einsum("ij,yxj->yxi", B, out)
    # seed: best window near the grid centre (as the reference); for a
    # restricted set of windows, near the middle of those instead
    vy, vx = np.nonzero(valid)
    for cy, cx in ((ny // 2, nx // 2), (int(np.median(vy)), int(np.median(vx)))):
        win = q[max(cy - 3, 0):cy + 4, max(cx - 3, 0):cx + 4]
        sy, sx = np.unravel_index(np.argmax(win), win.shape)
        seed = (sy + max(cy - 3, 0), sx + max(cx - 3, 0))
        if valid[seed]:
            break
    else:
        k = np.argmax(q[vy, vx])
        seed = (vy[k], vx[k])
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
    return np.einsum("ij,yxj->yxi", B, out)


def local_scale_fit(disp, step, base_scale, rad=2, min_pts=9):
    """Local linear expansion from a least-squares plane fit of the residual
    displacement over (2 rad + 1)^2 neighbouring windows (vectorised
    exm_analysis.local_scale_fit). Returns (scale, J) with J the local
    Jacobian I + grad(disp) per window."""
    ny, nx, _ = disp.shape
    fin = np.isfinite(disp[..., 0]) & np.isfinite(disp[..., 1])
    d = np.where(fin[..., None], disp, 0.0)
    # sums of the normal equations, [dx, dy, 1] design, over the neighbourhood
    S = np.zeros((ny, nx, 3, 3))
    R = np.zeros((ny, nx, 3, 2))
    for oy in range(-rad, rad + 1):
        for ox in range(-rad, rad + 1):
            ys0, ys1 = max(0, -oy), min(ny, ny - oy)
            xs0, xs1 = max(0, -ox), min(nx, nx - ox)
            w = np.zeros((ny, nx))
            dd = np.zeros((ny, nx, 2))
            w[ys0:ys1, xs0:xs1] = fin[ys0 + oy:ys1 + oy, xs0 + ox:xs1 + ox]
            dd[ys0:ys1, xs0:xs1] = d[ys0 + oy:ys1 + oy, xs0 + ox:xs1 + ox]
            v = np.array([ox * step, oy * step, 1.0])
            S += w[..., None, None] * np.outer(v, v)
            R += (w[..., None] * dd)[..., None, :] * v[:, None]
    n = S[..., 2, 2]
    ok = fin & (n >= min_pts)
    scale = np.full((ny, nx), np.nan)
    J = np.full((ny, nx, 2, 2), np.nan)
    if ok.any():
        cf = np.linalg.solve(S[ok], R[ok])           # (k, 3, 2): rows d/dx, d/dy, const
        Jk = np.eye(2) + np.swapaxes(cf[:, :2, :], 1, 2)
        J[ok] = Jk
        scale[ok] = base_scale * np.sqrt(np.abs(np.linalg.det(Jk)))
    return scale, J


# ===================================================================== truth per window
def window_truth(pre_px, post_px, dots, cs_x, cs_y, mask, A, b, win, step):
    """Hann-weighted true displacement in each window (where pre content lands
    in the corrected post) and the true local scale over the plane-fit
    footprint. Same definitions as exm_analysis."""
    ny, nx = len(cs_y), len(cs_x)
    true_disp = (post_px - b) @ np.linalg.inv(A).T - pre_px
    hann1 = np.hanning(win)
    tw = np.full((ny, nx, 2), np.nan)
    ts = np.full((ny, nx), np.nan)
    P = pre_px[dots]
    D = true_disp[dots]
    Q = post_px[dots]
    reach = 2 * step + win / 4
    for a, cy in enumerate(cs_y):
        if not mask[a].any():
            continue
        band = np.abs(P[:, 1] - cy) < max(win / 2, reach)
        Pb, Db, Qb = P[band], D[band], Q[band]
        for c in np.nonzero(mask[a])[0]:
            cx = cs_x[c]
            m = (np.abs(Pb[:, 0] - cx) < win / 2) & (np.abs(Pb[:, 1] - cy) < win / 2)
            if m.sum() < 6:
                continue
            wgt = np.interp(Pb[m, 0] - cx + win / 2, np.arange(win), hann1) * \
                np.interp(Pb[m, 1] - cy + win / 2, np.arange(win), hann1)
            tw[a, c] = (Db[m] * wgt[:, None]).sum(0) / wgt.sum()
            mm = (np.abs(Pb[:, 0] - cx) < reach) & (np.abs(Pb[:, 1] - cy) < reach)
            M = np.c_[Pb[mm], np.ones(mm.sum())]
            Tl, *_ = np.linalg.lstsq(M, Qb[mm], rcond=None)
            ts[a, c] = np.sqrt(abs(np.linalg.det(Tl[:2].T)))
    return tw, ts


# ===================================================================== pipeline
def ccf_pipeline(pre, make_cor, A, b, Bpre, truth=None, win=64, step=24, S=12, Lg=300,
                 pre_cache=None, which=None, refine_shift=True):
    """Correct post with x_post = A x_pre + b, then global + windowed CCF
    (exm_analysis.main.pipeline).

    make_cor(A, b) -> corrected post in the pre frame.
    truth: optional dict(pre_px, post_px, dots) for error statistics.
    pre_cache: optional dict with 'Fa' (global_ccf_prep) and 'contrast'.
    which: optional (ny, nx) bool mask restricting the windowed CCF."""
    pre_cache = pre_cache if pre_cache is not None else {}
    if "Fa" not in pre_cache:
        pre_cache["Fa"] = global_ccf_prep(pre, Lg)
    if "contrast" not in pre_cache:
        pre_cache["contrast"] = window_contrast(pre, win, step)
    Fa = pre_cache["Fa"]
    s = np.zeros(2)
    if refine_shift:
        cor0 = make_cor(A, b)
        G0 = ccf_global(pre, cor0, Lg, Fa)
        sx, sy, _ = subpixel_max(G0, Lg, Lg, Lg - 1)
        s = np.array([sx - Lg, sy - Lg])          # pre(x) ~ cor0(x + s)
        b = b + A @ s
    cor = make_cor(A, b)
    G = ccf_global(pre, cor, Lg, Fa)
    nb_h, nb_at = ccf_side_peak(G, Lg)
    stats = dict(global_shift_applied_px=s.tolist(), ccf_peak=float(G[Lg, Lg]),
                 next_best_peak=nb_h, next_best_at_px=list(nb_at),
                 ambiguity_ratio=float(G[Lg, Lg] / nb_h) if nb_h > 0 else float("inf"))

    contrast = pre_cache["contrast"]
    valid = valid_windows(contrast)
    if which is not None:
        valid = valid & which
    cs_x, cs_y, C, _ = windowed_ccf(pre, cor, win, step, S, which=valid)
    ny, nx = len(cs_y), len(cs_x)
    box = np.ones((2 * S + 1, 2 * S + 1), bool)
    cell = cell_mask(Bpre, S)
    nx_, ny_, _ = peaks_in_region(C, S, box)
    naive = np.stack([nx_, ny_], -1).astype(float)
    wx, wy, qual = peaks_in_region(C, S, cell)
    wrapped = np.stack([wx, wy], -1).astype(float)
    naive[~valid] = np.nan
    wrapped[~valid] = 0.0
    qual = np.where(valid, qual, 0.0)
    unw = unwrap(wrapped, qual, valid, Bpre)
    if valid.any():
        lat_med = np.nanmedian(np.einsum("ij,yxj->yxi", np.linalg.inv(Bpre), unw)[valid], axis=0)
        unw -= Bpre @ np.round(lat_med)
    unw[~valid] = np.nan

    lam = np.sqrt(abs(np.linalg.det(A)))
    meas_scale, meas_J = local_scale_fit(unw, step, lam)
    naive_scale, _ = local_scale_fit(naive, step, lam)
    out = dict(G=G, Lg=Lg, shift=s, A=A, b=b, cor=cor, cs_x=cs_x, cs_y=cs_y, valid=valid,
               naive=naive, unwrapped=unw, quality=qual, meas_scale=meas_scale, meas_J=meas_J,
               naive_scale=naive_scale, stats=stats)
    stats.update(window_px=win, step_px=step, windows=int(valid.sum()))

    if truth is not None:
        pitch_pre = np.sqrt(abs(np.linalg.det(Bpre)))
        true_win, true_scale = window_truth(truth["pre_px"], truth["post_px"], truth["dots"],
                                            cs_x, cs_y, valid, A, b, win, step)
        ok = np.isfinite(true_win[..., 0]) & np.isfinite(unw[..., 0])
        err_naive = np.hypot(*(naive - true_win)[ok].T)
        err_unw = np.hypot(*(unw - true_win)[ok].T)
        sok = ok & np.isfinite(meas_scale) & np.isfinite(true_scale)
        nonempty = ok.any()
        stats.update(
            windows=int(ok.sum()),
            true_residual_max_px=float(np.nanmax(np.hypot(*true_win[ok].T))) if nonempty else np.nan,
            naive_rms_err_px=float(np.sqrt(np.mean(err_naive ** 2))) if nonempty else np.nan,
            naive_frac_off_by_a_cell=float(np.mean(err_naive > 0.5 * pitch_pre)) if nonempty else np.nan,
            unwrapped_rms_err_px=float(np.sqrt(np.mean(err_unw ** 2))) if nonempty else np.nan,
            unwrapped_frac_off_by_a_cell=float(np.mean(err_unw > 0.5 * pitch_pre)) if nonempty else np.nan,
            local_scale_corr=float(np.corrcoef(meas_scale[sok], true_scale[sok])[0, 1])
            if sok.sum() > 2 and np.std(true_scale[sok]) > 0 else np.nan,
            local_scale_rms_err=float(np.sqrt(np.mean((meas_scale[sok] - true_scale[sok]) ** 2)))
            if sok.any() else np.nan,
            true_bulk_scale_median=float(np.nanmedian(true_scale[ok])) if nonempty else np.nan)
        out.update(true_win=true_win, true_scale=true_scale, ok=ok, sok=sok,
                   err_naive=err_naive, err_unw=err_unw)
    return out


# ===================================================================== global from ACF
def acf_global(A_pre, Lpre, A_post, Lpost):
    """Lattice bases from both ACFs and the pre -> post linear map."""
    Bpre, rows_pre, p_pre = lattice_basis(A_pre, Lpre)
    Bpost, rows_post, p_post = lattice_basis(A_post, Lpost)
    Bpost, F = match_bases(Bpre, Bpost)
    return dict(Bpre=Bpre, Bpost=Bpost, F=F, p_pre=p_pre, p_post=p_post, describe=describe(F))
