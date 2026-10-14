"""
rwtag.errors
============
The error model (docs/05_PHASE5_ERROR_MODEL.md). Every detected dot and dash gets
a 2x2 position covariance; every ArUco tag a centre covariance, corner
covariances, and rotation / side sigmas; all in the RAW frame (where the photons
were counted) and propagated to the CORRECTED frame through the exact Jacobian
of the Stage-1 geometry. NO Qt.

DOTS -- the least-squares localisation variance (Mortensen et al. 2010, eq. 6),
per axis, in raw px^2:

    var = sa^2 / N * (16/9 + 8 pi sa^2 b2 / N)

  N   photons in the spot     = integrated signal (raw ADU) x gain (e-/ADU)
  b2  background variance     = (pixel noise sigma, raw ADU)^2 x gain^2, per pixel
  sa  spot width (px)         = measured second-moment sigma (includes pixelation)

Simulated against our Gaussian-mask centroid at four signal / background levels it
predicts the scatter to within 15 %. Without the camera gain the formula is
evaluated with gain = 1: the background term is unchanged (gain cancels), the
shot term is off by the unknown gain, and the export marks the rows
`relative_err = true`.

DASHES -- the same formula per axis with the dash's own width along it
(sqrt(L^2/12 + sigma_psf^2) along the dash, the spot width across).

TAGS -- Forstner corner covariance sigma_n^2 (sum grad I grad I^T)^-1 over a
module-sized window at each raw corner; centre = mean of the four corners; the
rotation and side sigmas by linear propagation through the same four-edge
formula the decoder uses.

CALIBRATION -- two numbers per project, stored with it and in every export:
  kappa   multiplies every predicted sigma; fitted so the model matches the scatter
          of the same features across repeat exposures of a static sample
          (`calibrate_from_repeats`); separate kappas for dots and tag centres;
  floor   a systematic per-axis sigma added in quadrature (pixel-phase bias,
          resampling): invisible to repeat frames (it is the same in each), so it
          is set from the dummy truth, or estimated per frame from the
          cross-validated warp residual (`floor_from_cv`, an upper bound: real
          local warping counts as floor).
Defaults kappa = 1, floor = 0, each with its source recorded.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import math
import numpy as np

from . import correct as C

MORT = 16.0 / 9.0


# Shipped defaults, measured on the dummy series (docs/05 "As built"):
#   kappa_tag / kappa_rot  -- repeat frames (opt_noise, 10 seeds x 3 states): the corner-gradient
#                             estimate is 2.35x / 3.3x optimistic for contour refinement, which
#                             fits whole edges; a property of the estimator, not of the sample.
#   floor_px               -- truth (opt_clean, opt_warp): 0.03 px in the densest frame, ~0 above.
#   tag_floor_px / rot_floor_deg -- truth: per-tag systematic of contour refinement on rounded tags.
#   kappa_dot stays 1: with the true camera gain the formula needs 0.9, without it 1.25, so the
#   repeat-frame calibration (or the gain) should set it for real data.
DEFAULTS = dict(kappa_dot=1.0, kappa_tag=2.35, kappa_rot=3.3, floor_px=0.03, tag_floor_px=0.073,
                rot_floor_deg=0.10, kappa_source="defaults (dummy repeat frames)",
                floor_source="defaults (dummy truth)")


@dataclass
class NoiseModel:
    gain_e_per_adu: float | None = None     # None -> relative errors (gain 1)
    kappa_dot: float = DEFAULTS["kappa_dot"]
    kappa_tag: float = DEFAULTS["kappa_tag"]
    kappa_rot: float = DEFAULTS["kappa_rot"]
    floor_px: float = DEFAULTS["floor_px"]              # dots and dashes, per axis
    tag_floor_px: float = DEFAULTS["tag_floor_px"]      # tag centres, per axis
    rot_floor_deg: float = DEFAULTS["rot_floor_deg"]    # tag rotation
    kappa_source: str = DEFAULTS["kappa_source"]        # | repeat images: <n> frames
    floor_source: str = DEFAULTS["floor_source"]        # | user | cv residual

    @property
    def relative(self):
        return not (self.gain_e_per_adu and self.gain_e_per_adu > 0)

    @property
    def gain(self):
        return float(self.gain_e_per_adu) if not self.relative else 1.0

    def to_dict(self):
        d = asdict(self); d["relative"] = self.relative
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__})


# ------------------------------------------------------------------ formulas
def mortensen_var(N, b2, sa):
    """Per-axis localisation variance (px^2) of a spot of N photons, width sa (px),
    on a background of variance b2 photons^2 per pixel. NaN where N <= 0."""
    N = np.asarray(N, float); sa = np.asarray(sa, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        v = sa ** 2 / N * (MORT + 8.0 * math.pi * sa ** 2 * b2 / N)
    return np.where(N > 0, v, np.nan)


def _iso(var):
    var = np.asarray(var, float)
    out = np.zeros((len(var), 2, 2))
    out[:, 0, 0] = var; out[:, 1, 1] = var
    return out


def cov_to_sxx(cov):
    """(N,2,2) -> (N,3) as sxx, syy, sxy."""
    cov = np.asarray(cov, float)
    return np.column_stack([cov[:, 0, 0], cov[:, 1, 1], cov[:, 0, 1]])


def sigma_major(cov):
    """Largest 1-sigma axis of each covariance (px)."""
    cov = np.asarray(cov, float)
    tr = cov[:, 0, 0] + cov[:, 1, 1]
    det = cov[:, 0, 0] * cov[:, 1, 1] - cov[:, 0, 1] ** 2
    return np.sqrt(np.maximum(tr / 2 + np.sqrt(np.maximum(tr ** 2 / 4 - det, 0)), 0))


# ------------------------------------------------------------------ dots
def dot_cov_raw(signal_adu, noise_adu, sigma_px, model: NoiseModel):
    """(N,2,2) raw-frame covariance of each dot, kappa and floor applied."""
    g = model.gain
    N = np.asarray(signal_adu, float) * g
    b2 = (float(noise_adu) * g) ** 2
    var = mortensen_var(N, b2, sigma_px) * model.kappa_dot ** 2 + model.floor_px ** 2
    return _iso(var)


# ------------------------------------------------------------------ dashes
def dash_cov_raw(raw, pts_raw, axis_raw, sigma_psf_px, len_px, noise_adu, model: NoiseModel):
    """(M,2,2) raw-frame covariance per dash. `axis_raw` (M,2) unit vectors along
    each dash. Photometry with a window that covers the whole dash."""
    from .aruco.detect import spot_photometry
    pts_raw = np.asarray(pts_raw, float).reshape(-1, 2)
    if not len(pts_raw):
        return np.zeros((0, 2, 2))
    s_along = math.sqrt(len_px ** 2 / 12.0 + sigma_psf_px ** 2)
    sig, _bg, _w = spot_photometry(raw, pts_raw, s_along, noise_adu)
    g = model.gain
    N = sig * g; b2 = (noise_adu * g) ** 2
    v_along = mortensen_var(N, b2, s_along)
    v_across = mortensen_var(N, b2, sigma_psf_px)
    a = np.asarray(axis_raw, float)
    p = np.column_stack([-a[:, 1], a[:, 0]])
    cov = (v_along[:, None, None] * np.einsum("ni,nj->nij", a, a)
           + v_across[:, None, None] * np.einsum("ni,nj->nij", p, p))
    return cov * model.kappa_dot ** 2 + model.floor_px ** 2 * np.eye(2)[None]


# ------------------------------------------------------------------ tags
def corner_cov(img, corners, half_win, noise_sigma):
    """Forstner covariance (2,2) per corner: sigma_n^2 (sum grad grad^T)^-1 over a
    (2 half_win + 1)^2 window. Returns (k,2,2); NaN where the window leaves the
    image or the tensor is singular."""
    img = np.asarray(img, np.float64)
    gy, gx = np.gradient(img)
    H, W = img.shape
    out = np.full((len(corners), 2, 2), np.nan)
    r = int(max(2, round(half_win)))
    for k, (x, y) in enumerate(np.asarray(corners, float)):
        if not (np.isfinite(x) and np.isfinite(y)):
            continue
        xi, yi = int(round(x)), int(round(y))
        if xi - r < 1 or yi - r < 1 or xi + r >= W - 1 or yi + r >= H - 1:
            continue
        sx = gx[yi - r:yi + r + 1, xi - r:xi + r + 1]; sy = gy[yi - r:yi + r + 1, xi - r:xi + r + 1]
        M = np.array([[(sx * sx).sum(), (sx * sy).sum()], [(sx * sy).sum(), (sy * sy).sum()]])
        if np.linalg.cond(M) < 1e8:
            out[k] = noise_sigma ** 2 * np.linalg.inv(M)
    return out


def _rot_side(c):
    """(rotation deg ccw-on-screen, mean side) of 4 corners -- the decoder's formula."""
    e = [c[1] - c[0], c[2] - c[1], c[3] - c[2], c[0] - c[3]]
    ang = [np.arctan2(v[1], v[0]) - k * np.pi / 2 for k, v in enumerate(e)]
    rot = -np.degrees(np.arctan2(np.mean(np.sin(ang)), np.mean(np.cos(ang))))
    return rot, float(np.mean([np.hypot(*v) for v in e]))


def tag_pose_cov(corners, ccov):
    """From (4,2) corners and (4,2,2) corner covariances: (centre cov (2,2),
    rotation sigma deg, side sigma px) by linear propagation (finite differences)."""
    corners = np.asarray(corners, float)
    centre = np.sum(ccov, axis=0) / 16.0                          # mean of 4 independent corners
    full = np.zeros((8, 8))
    for k in range(4):
        full[2 * k:2 * k + 2, 2 * k:2 * k + 2] = ccov[k]
    g_rot = np.zeros(8); g_side = np.zeros(8)
    r0, s0 = _rot_side(corners)
    h = 1e-4
    for j in range(8):
        c = corners.copy().reshape(-1); c[j] += h
        r1, s1 = _rot_side(c.reshape(4, 2))
        g_rot[j] = ((r1 - r0 + 180) % 360 - 180) / h; g_side[j] = (s1 - s0) / h
    return centre, float(math.sqrt(max(g_rot @ full @ g_rot, 0))), float(math.sqrt(max(g_side @ full @ g_side, 0)))


# ------------------------------------------------------------------ the whole frame
def apply(det, raw, correction, model: NoiseModel, design=None):
    """Fill det.dot_cov_corr / dot_cov_raw / dash_cov_* / tag_cov and det.noise.
    `raw` is the raw frame (or None: everything is evaluated in the corrected
    frame, flagged). Safe on an unregistered detection."""
    shape = det.u8.shape[:2]
    geo_id = correction is None or C.geometric_is_identity(correction)
    noise = float(det.params.get("noise_sigma", 0.0)) or 1.0
    on_raw = raw is not None
    img = np.asarray(raw if on_raw else det.u8, np.float64)
    um = float(det.params.get("um_per_px", 0.51)); psf = float(det.params.get("psf_fwhm_um", 2.5))
    # ---- dots
    n = len(det.dots)
    flag = np.array([""] * n, dtype=object)
    if n and det.dot_signal is not None:
        sa = np.where(np.isfinite(det.dot_sigma_px), det.dot_sigma_px, np.nanmedian(det.dot_sigma_px))
        Craw = dot_cov_raw(det.dot_signal, noise, sa, model)
        # dots whose photometry window leaves the frame (or failed): a conservative
        # 4x the frame's median variance, flagged -- every feature carries an error
        bad = ~np.isfinite(Craw).all((1, 2)) | (Craw[:, 0, 0] <= 0)
        if bad.any() and (~bad).any():
            Craw[bad] = 4.0 * np.median(Craw[~bad], axis=0)
            flag[bad] = "border_estimate"
        raw_xy = C.inverse_geometric(det.dots, correction, shape) if not geo_id else det.dots
        Ccorr = C.propagate_cov(Craw, C.forward_jacobian(raw_xy, correction, shape)) if not geo_id else Craw
        badc = ~np.isfinite(Ccorr).all((1, 2))
        if badc.any() and (~badc).any():
            Ccorr[badc] = 4.0 * np.median(Ccorr[~badc], axis=0); flag[badc] = "border_estimate"
    else:
        Craw = Ccorr = np.full((n, 2, 2), np.nan)
    det.dot_cov_raw, det.dot_cov_corr, det.dot_cov_flag = Craw, Ccorr, flag
    # ---- dashes
    m = len(det.dashes_all)
    if m and det.grid is not None and on_raw:
        g = det.grid
        P = g["box_pitch"]
        pu = det.dashes_all @ g["u"] - g["phase_u"]; pv = det.dashes_all @ g["v"] - g["phase_v"]
        du = np.abs((pu + P / 2) % P - P / 2); dv = np.abs((pv + P / 2) % P - P / 2)
        axis_corr = np.where((du < dv)[:, None], g["v"][None], g["u"][None])
        raw_xy = C.inverse_geometric(det.dashes_all, correction, shape) if not geo_id else det.dashes_all
        if not geo_id:
            Ji = C.inverse_jacobian(det.dashes_all, correction, shape)
            axis_raw = np.einsum("nij,nj->ni", Ji, axis_corr)
            axis_raw /= np.linalg.norm(axis_raw, axis=1, keepdims=True)
        else:
            axis_raw = axis_corr
        sp = psf / 2.35482 / um
        Hraw = dash_cov_raw(img, raw_xy, axis_raw, sp, 8.125 / um, noise, model)
        Hcorr = C.propagate_cov(Hraw, C.forward_jacobian(raw_xy, correction, shape)) if not geo_id else Hraw
        for H_ in (Hraw, Hcorr):
            b_ = ~np.isfinite(H_).all((1, 2))
            if b_.any() and (~b_).any():
                H_[b_] = 4.0 * np.median(H_[~b_], axis=0)
    else:
        Hraw = Hcorr = np.full((m, 2, 2), np.nan)
    det.dash_cov_raw, det.dash_cov_corr = Hraw, Hcorr
    # ---- tags
    tag_cov = {}
    module_raw = (design.tag_um / 6.0 / um) if design is not None else 7.5
    for i, t in det.tags.items():
        cr = C.inverse_geometric(t.corners_px, correction, shape) if not geo_id else t.corners_px
        cc = corner_cov(img, cr, 0.5 * module_raw, noise) * model.kappa_tag ** 2
        if not np.isfinite(cc).all():
            tag_cov[i] = None; continue
        if not geo_id:
            J = C.forward_jacobian(cr, correction, shape)
            cc_corr = C.propagate_cov(cc, J)
        else:
            cc_corr = cc
        centre_corr, rot_s, side_s = tag_pose_cov(t.corners_px, cc_corr)
        rot_s = math.hypot(rot_s * model.kappa_rot / max(model.kappa_tag, 1e-9), model.rot_floor_deg)
        centre_raw, _r, _s = tag_pose_cov(cr, cc)
        fl = model.tag_floor_px ** 2 * np.eye(2)
        centre_raw = centre_raw + fl
        centre_corr = centre_corr + (C.propagate_cov(fl[None], C.forward_jacobian(t.centre_px[None] if geo_id else
                                     C.inverse_geometric(t.centre_px[None], correction, shape), correction, shape))[0]
                                     if not geo_id else fl)
        tag_cov[i] = {"centre_corr": centre_corr, "centre_raw": centre_raw, "corners_corr": cc_corr,
                      "corners_raw": cc, "rot_sigma_deg": rot_s, "side_sigma_px": side_s,
                      "decode_class": t.decode_class}
    det.tag_cov = tag_cov
    det.noise = dict(model.to_dict(), noise_sigma_adu=noise, evaluated_on="raw" if on_raw else "corrected")
    return det


# ------------------------------------------------------------------ calibration
def _emp_cov(stack):
    """(seeds, n, 2) positions -> (n,2,2) sample covariance (NaN-safe: features
    missing in any seed are dropped by the caller)."""
    d = stack - stack.mean(0)
    return np.einsum("snj,snk->njk", d, d) / (stack.shape[0] - 1)


def raw_model(gain=None):
    """kappa = 1 and every floor 0: the model the repeat-frame calibration fits."""
    return NoiseModel(gain_e_per_adu=gain, kappa_dot=1.0, kappa_tag=1.0, kappa_rot=1.0, floor_px=0.0,
                      tag_floor_px=0.0, rot_floor_deg=0.0, kappa_source="uncalibrated", floor_source="none")


def calibrate_from_repeats(results):
    """`results` = [(DetectResult, TagResult)] for repeat exposures of ONE static
    state, computed with `raw_model()` (kappa 1, no floors). Matched by tag.
    Returns dict(kappa_dot, kappa_tag, kappa_rot, n_dots, n_tags, ratio spreads).
    kappa^2 = median over features of (empirical / model) variance, per axis
    pooled, so the model reproduces the median scatter."""
    common = set.intersection(*[set(tr.tags) for _d, tr in results])
    dots = sorted(t for t in common if t.startswith("dot|"))
    tags = sorted(t for t in common if t.startswith("aruco|"))
    out = {"n_frames": len(results), "n_dots": len(dots), "n_tags": len(tags)}
    if len(dots) >= 20:
        P = np.stack([[tr.tags[t] for t in dots] for _d, tr in results])
        emp = _emp_cov(P)
        mod = np.mean([[d.dot_cov_corr[tr.src[t][1]] for t in dots] for d, tr in results], axis=0)
        r = (emp[:, 0, 0] + emp[:, 1, 1]) / (mod[:, 0, 0] + mod[:, 1, 1])
        r = r[np.isfinite(r)]
        out.update(kappa_dot=float(math.sqrt(np.median(r))), dot_ratio_p10=float(np.percentile(r, 10)),
                   dot_ratio_p90=float(np.percentile(r, 90)))
    if len(tags) >= 3:
        P = np.stack([[tr.tags[t] for t in tags] for _d, tr in results])
        emp = _emp_cov(P)
        ids = [int(t.split("|")[2]) for t in tags]
        mod = np.mean([[d.tag_cov[i]["centre_corr"] for i in ids] for d, _tr in results], axis=0)
        r = (emp[:, 0, 0] + emp[:, 1, 1]) / (mod[:, 0, 0] + mod[:, 1, 1])
        rot = np.stack([[d.tags[i].rot_deg for i in ids] for d, _tr in results])
        rs = np.mean([[d.tag_cov[i]["rot_sigma_deg"] for i in ids] for d, _tr in results], axis=0)
        rr = rot.var(0, ddof=1) / rs ** 2
        out.update(kappa_tag=float(math.sqrt(np.median(r))), kappa_rot=float(math.sqrt(np.median(rr))),
                   tag_ratio_p10=float(np.percentile(r, 10)), tag_ratio_p90=float(np.percentile(r, 90)))
    return out


def floor_from_errors(err_xy, cov):
    """Per-axis systematic floor (px) that, added in quadrature, makes the median
    squared error match: err (n,2) vs truth, cov (n,2,2) the model WITHOUT floor."""
    e2 = (np.asarray(err_xy) ** 2).sum(1)
    v = np.asarray(cov)[:, 0, 0] + np.asarray(cov)[:, 1, 1]
    ok = np.isfinite(e2) & np.isfinite(v)
    # median of chi2(2) is 2 ln 2: per-axis variance ~ median(e2) / (2 ln 2)
    tot = np.median(e2[ok]) / (2 * math.log(2))
    return float(math.sqrt(max(tot - np.median(v[ok]) / 2.0, 0.0)))


def floor_from_cv(tr, det):
    """Upper-bound floor from the cross-validated warp residual of one frame (px):
    the residual variance per axis beyond the model's own. Real local warping
    finer than the spline counts as floor here."""
    tags = [t for t in tr.tags if t.startswith("dot|") and tr.src[t][0] == "dot"]
    if len(tags) < 50:
        return float("nan")
    r2 = np.array([tr.residuals[t] ** 2 for t in tags])
    v = np.array([np.trace(det.dot_cov_corr[tr.src[t][1]]) for t in tags])
    tot = np.median(r2) / (2 * math.log(2))
    return float(math.sqrt(max(tot / 2.0 - np.nanmedian(v) / 2.0, 0.0)))


def mahalanobis2(d, cov):
    """Squared Mahalanobis distance of vectors d (n,2) under covariances (n,2,2)."""
    d = np.asarray(d, float); cov = np.asarray(cov, float)
    det = cov[:, 0, 0] * cov[:, 1, 1] - cov[:, 0, 1] ** 2
    with np.errstate(divide="ignore", invalid="ignore"):
        return (d[:, 0] ** 2 * cov[:, 1, 1] - 2 * d[:, 0] * d[:, 1] * cov[:, 0, 1] + d[:, 1] ** 2 * cov[:, 0, 0]) / det


# ------------------------------------------------------------------ alignment
def bootstrap_alignment(P_move, P_target, kind="rigid", n_boot=200, seed=0, about=None):
    """Fit P_target ~ T(P_move) (rigid: R, t; similarity: s, R, t; reflection not
    allowed) and its parameter covariance by bootstrap over the pairs.
    Returns dict(params [theta_deg, tx, ty(, s)], cov, fit). `about` = the point
    the rotation is reported about (default the move centroid)."""
    from .refwarp.warp import similarity
    A = np.asarray(P_move, float); B = np.asarray(P_target, float)
    rng = np.random.default_rng(seed)

    def fit(a, b):
        ma, mb = a.mean(0), b.mean(0)
        H = (a - ma).T @ (b - mb)
        U, S, Vt = np.linalg.svd(H)
        d = np.sign(np.linalg.det(Vt.T @ U.T)) or 1.0
        R = Vt.T @ np.diag([1.0, d]) @ U.T
        s = float((S * [1.0, d]).sum() / ((a - ma) ** 2).sum()) if kind == "similarity" else 1.0
        t = mb - s * R @ ma
        th = math.degrees(math.atan2(R[1, 0], R[0, 0]))
        c = about if about is not None else A.mean(0)
        tc = s * R @ c + t                                   # where `about` lands
        return np.array([th, tc[0], tc[1]] + ([s] if kind == "similarity" else [])), (s, R, t)

    p0, (s, R, t) = fit(A, B)
    boots, fits = [], []
    for _ in range(n_boot):
        k = rng.integers(0, len(A), len(A))
        pb, fb = fit(A[k], B[k])
        boots.append(pb); fits.append(fb)
    cov = np.cov(np.asarray(boots).T)
    return {"params": p0, "cov": cov, "s": s, "R": R, "t": t, "kind": kind, "fits": fits,
            "names": ["theta_deg", "x_about", "y_about"] + (["s"] if kind == "similarity" else [])}
