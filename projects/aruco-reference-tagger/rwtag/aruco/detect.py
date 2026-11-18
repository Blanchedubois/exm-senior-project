"""
rwtag.aruco.detect
==================
Stage 2 for the V2 print (docs/03_PHASE3_DETECT_STAGE.md). Replaces V1's three
OCR steps (detect grid / read glyphs / solve) with one:

  1. decode the tags on the Stage-1 CORRECTED frame (Phase 1), flagging any tag
     whose corners have no real raw-frame source (the un-distortion edge band);
  2. fit the design -> image affine through the tag centres: registration,
     expansion factor and rotation are READ, not inferred;
  3. detect dots once per printed dot size (one size for designs 1-3, five for
     the spectrum print) with a top-hat and area band sized to THAT dot, and give
     each dot to the box its design position falls in -- keeping it only if that
     box prints that size; refine every centre with a Gaussian-mask centroid on
     the float corrected image using its box's imaged spot width;
  4. fit a lattice per box (pitch, angle, phase) -> lambda from the dots as a
     cross-check of lambda from the tags;
  5. dashes (aspect-gated) on the node lattice;
  6. photometry of every dot on the RAW frame at its raw position (integrated
     signal and background in raw ADU) for the Phase-5 error model;
  7. the SECOND PASS: the same detector on the raw frame, joined to the
     corrected-frame features by id (tags) and nearest neighbour (dots, dashes)
     -- an independent raw position for every feature, beside the corrected
     position mapped back through the exact inverse correction.

Returns a DetectResult that the ported tagging code consumes (its V1 fields are
kept). Ported pieces: refine_gauss / refine_fit / detect_dashes / _tag_mask /
the fit dict construction, from reference-warp-tagger/rwtag/aruco/detect.py.
"""
from __future__ import annotations
import math
import numpy as np
import cv2

from rwtag import io, correct as C, lattice as lt
from rwtag.types import DetectResult
from .design import Design
from .tags import ArucoParams, decode_tags
from .pose import frame_pose
from .fit import fit_affine

IDENTITY_REG = {"orient": (0, 1, 1, 1), "offset": (0, 0)}


# ------------------------------------------------------------------ refinement
def _patches(img, pts, R):
    H, W = img.shape
    xi = np.round(pts[:, 0]).astype(int); yi = np.round(pts[:, 1]).astype(int)
    ok = (xi >= R) & (yi >= R) & (xi < W - R) & (yi < H - R)
    d = np.arange(-R, R + 1)
    P = img[(yi[ok, None, None] + d[None, :, None]), (xi[ok, None, None] + d[None, None, :])]
    return P.astype(np.float64), xi, yi, ok, d


def refine_gauss(img, pts, sigma_px, iters=4):
    """Gaussian-mask centroid (Anderson & King): iteratively re-centre a Gaussian
    window of the spot's own width on the background-subtracted patch. Vectorised;
    converges to the least-squares Gaussian centre for a Gaussian spot (W7: within
    4 % of a full fit at 1/15 the cost)."""
    pts = np.asarray(pts, float)
    if not len(pts):
        return pts
    R = max(4, int(math.ceil(2.5 * sigma_px)))
    P, xi, yi, ok, d = _patches(np.asarray(img, np.float64), pts, R)
    if not ok.any():
        return pts
    bg = np.percentile(P.reshape(len(P), -1), 20, axis=1)[:, None, None]
    P = np.clip(P - bg, 0, None)
    cx = pts[ok, 0] - xi[ok]; cy = pts[ok, 1] - yi[ok]
    dx = d[None, None, :]; dy = d[None, :, None]
    for _ in range(iters):
        w = P * np.exp(-((dx - cx[:, None, None]) ** 2 + (dy - cy[:, None, None]) ** 2) / (2.0 * sigma_px ** 2))
        s = w.sum(axis=(1, 2)); good = s > 1e-9
        ncx = np.where(good, (w * dx).sum(axis=(1, 2)) / np.where(good, s, 1), cx)
        ncy = np.where(good, (w * dy).sum(axis=(1, 2)) / np.where(good, s, 1), cy)
        cx, cy = np.clip(ncx, -R + 1, R - 1), np.clip(ncy, -R + 1, R - 1)
    out = pts.copy()
    out[ok, 0] = xi[ok] + cx; out[ok, 1] = yi[ok] + cy
    return out


def refine_fit(img, pts, sigma_px, R=6):
    """Per-dot Gaussian least-squares fit (scipy curve_fit). Slow (~1 ms/dot);
    the reference refine_gauss is validated against."""
    from scipy.optimize import curve_fit
    xg, yg = np.meshgrid(np.arange(-R, R + 1), np.arange(-R, R + 1))
    f = lambda xy, a, x0, y0, s, b: (a * np.exp(-((xy[0] - x0) ** 2 + (xy[1] - y0) ** 2) / (2 * s * s)) + b).ravel()
    out = np.asarray(pts, float).copy()
    for i, (x, y) in enumerate(out):
        xi, yi = int(round(x)), int(round(y))
        if xi - R < 0 or yi - R < 0 or xi + R + 1 > img.shape[1] or yi + R + 1 > img.shape[0]:
            continue
        pa = img[yi - R:yi + R + 1, xi - R:xi + R + 1].astype(float)
        try:
            p, _ = curve_fit(f, (xg, yg), pa.ravel(), p0=[pa.max() - pa.min(), x - xi, y - yi, sigma_px, pa.min()], maxfev=2000)
            if abs(p[1]) < 3 and abs(p[2]) < 3:
                out[i] = (xi + p[1], yi + p[2])
        except Exception:
            pass
    return out


_DISC_K = 2.5                                   # integration disc radius, in sigma
_DISC_FRAC = 1.0 - math.exp(-_DISC_K ** 2 / 2)  # fraction of a 2-D Gaussian inside it
# second moment of a 2-D Gaussian truncated at k sigma, relative to sigma^2 (per axis)
_TRUNC_M2 = 1.0 - (_DISC_K ** 2 * math.exp(-_DISC_K ** 2 / 2)) / (2.0 * _DISC_FRAC)


def background_noise(img, low_pct=40.0):
    """Robust per-pixel noise sigma of the dark background (image units): the MAD
    of horizontal neighbour differences, / sqrt(2), over background REGIONS --
    chosen on a 7x7 box-filtered copy below its low_pct percentile. Choosing by
    the pixels' own values would keep only the low half of the noise and halve
    the estimate."""
    a = np.asarray(img, np.float64)
    sm = cv2.blur(a.astype(np.float32), (7, 7))
    sm = cv2.dilate(sm, np.ones((5, 5), np.uint8))          # keep away from feature flanks
    thr = np.percentile(sm, low_pct)
    d = a[:, 1:] - a[:, :-1]
    m = (sm[:, 1:] < thr) & (sm[:, :-1] < thr)
    if m.sum() < 1000:
        m = np.ones_like(d, bool)
    v = d[m]
    return float(1.4826 * np.median(np.abs(v - np.median(v))) / math.sqrt(2.0))


def spot_photometry(img, pts, sigma_px, noise_sigma=None):
    """Per point: (signal, background, sigma_meas), in the image's own units.

    Background = the 10th percentile of a (3.5 sigma)-radius patch. In a dense
    lattice (pitch ~4 sigma at lambda = 1) any ring around a dot lands on its
    neighbours, so a ring median reads high; the low percentile finds the floor
    between dots. Signal = sum of (pixel - background) inside a 2.5-sigma disc,
    divided by the Gaussian fraction inside it (0.956), i.e. the spot's total.
    sigma_meas = second-moment width inside the disc, corrected for the
    truncation. NaN where a point is NaN or too close to the border. `sigma_px`
    (scalar or per point) sets the window sizes. `noise_sigma` (image units) removes
    the 10th-percentile's own bias: for Gaussian pixel noise it sits 1.2816 sigma
    below the true background, which over a ~100-pixel disc doubles a faint
    spot's signal (simulated: 1531 read for 800 true photons)."""
    pts = np.asarray(pts, float).reshape(-1, 2)
    n = len(pts)
    sig = np.broadcast_to(np.asarray(sigma_px, float), (n,)).copy()
    out_s = np.full(n, np.nan); out_b = np.full(n, np.nan); out_w = np.full(n, np.nan)
    img = np.asarray(img, np.float64)
    finite = np.isfinite(pts).all(1)
    for sv in np.unique(np.round(sig[finite], 2)):
        idx = np.nonzero(finite & (np.round(sig, 2) == sv))[0]
        R = max(4, int(math.ceil(3.5 * sv)))
        P, xi, yi, ok, d = _patches(img, pts[idx], R)
        if not ok.any():
            continue
        dy, dx = np.meshgrid(d, d, indexing="ij")
        ox = pts[idx[ok], 0] - xi[ok]; oy = pts[idx[ok], 1] - yi[ok]
        r2 = (dx[None] - ox[:, None, None]) ** 2 + (dy[None] - oy[:, None, None]) ** 2
        disc = r2 <= (_DISC_K * sv) ** 2
        bg = np.percentile(P.reshape(len(P), -1), 10, axis=1)
        if noise_sigma:
            bg = bg + 1.2816 * float(noise_sigma)
        Q = P - bg[:, None, None]
        s = (Q * disc).sum(axis=(1, 2)) / _DISC_FRAC
        w = np.clip(Q, 0, None) * disc
        ws = w.sum(axis=(1, 2))
        m2 = (w * r2).sum(axis=(1, 2))
        width = np.sqrt(np.where(ws > 0, m2 / np.where(ws > 0, ws, 1) / 2.0 / _TRUNC_M2, np.nan))
        j = idx[ok]
        out_s[j] = s; out_b[j] = bg; out_w[j] = width
    return out_s, out_b, out_w


# ------------------------------------------------------------------ dashes, mask
DASH_LEN_UM, DASH_W_UM = 8.125, 2.125        # V2 boundary dashes (V1 dimensions)


def detect_dashes(u8, params: ArucoParams, dot_side_um, mask=None):
    """Boundary dashes (8.125 x 2.125 um): elongated mid-size blobs.

    Area-only rules cannot separate V2's dashes from its dots (both small), so an
    aspect is required -- but blur rounds a dash's ends, so the gate is set from
    the IMAGED aspect sqrt(L^2 + PSF^2) / sqrt(W^2 + PSF^2) (2.2 at PSF 3.4 against
    3.4 printed), not a fixed 2. The threshold carries the same sparse-frame noise
    floor as the dots (lattice.detect_blobs): plain Otsu on a high-expansion frame
    holding a handful of dashes drops into the noise. The ARUCO tags' modules are
    masked out; dots are rejected by area (a dash covers ~4 dot areas)."""
    tophat = max(41, int(math.ceil(1.5 * math.hypot(DASH_LEN_UM, params.psf_fwhm_um) / params.um_per_px)) | 1)
    th = cv2.morphologyEx(u8, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (tophat, tophat)))
    otsu, _ = cv2.threshold(th, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    thr = float(otsu)
    if params.noise_k > 0:
        med = float(np.median(th)); mad = float(np.median(np.abs(th.astype(np.int16) - med))) * 1.4826
        thr = max(thr, med + params.noise_k * mad)
    b = (th > thr).astype(np.uint8) * 255
    if mask is not None:
        b[np.asarray(mask) == 0] = 0
    n, _lab, st, cen = cv2.connectedComponentsWithStats(b, 8)
    imaged_aspect = math.hypot(DASH_LEN_UM, params.psf_fwhm_um) / math.hypot(DASH_W_UM, params.psf_fwhm_um)
    min_aspect = min(params.dash_min_aspect, max(1.35, 1.0 + 0.6 * (imaged_aspect - 1.0)))
    side = dot_side_um / params.um_per_px
    a0 = 2.0 * side * side
    a1 = 6.0 * math.hypot(DASH_LEN_UM, params.psf_fwhm_um) * math.hypot(DASH_W_UM, params.psf_fwhm_um) / params.um_per_px ** 2
    a = st[1:, cv2.CC_STAT_AREA]; w = st[1:, cv2.CC_STAT_WIDTH]; h = st[1:, cv2.CC_STAT_HEIGHT]
    ok = ((a >= a0) & (a <= a1) & (np.maximum(w, h) / np.maximum(np.minimum(w, h), 1) >= min_aspect)
          & (a / np.maximum(w * h, 1) >= 0.45))
    return cen[1:][ok].astype(float).reshape(-1, 2)


def _allowed_mask(shape, tags, grow_px):
    """uint8 mask, 0 inside every decoded tag (grown by grow_px), 1 elsewhere."""
    m = np.ones(shape[:2], np.uint8)
    for t in tags.values():
        c = t.corners_px; ctr = c.mean(0)
        poly = ctr + (c - ctr) * (1.0 + grow_px / max(np.linalg.norm(c[0] - ctr), 1.0))
        cv2.fillConvexPoly(m, np.round(poly).astype(np.int32), 0)
    return m


# ------------------------------------------------------------------ helpers
def _design_box_of(design: Design, A, pts):
    """Box number of each image point through the inverse affine (0 = outside)."""
    if not len(pts):
        return np.zeros(0, int)
    Al, t = A[:, :2], A[:, 2]
    X = (np.asarray(pts, float) - t) @ np.linalg.inv(Al).T
    col = np.floor((X[:, 0] - design.origin_um) / design.box_um).astype(int)
    row = np.floor((X[:, 1] - design.origin_um) / design.box_um).astype(int)
    inside = (col >= 0) & (col < design.grid_n) & (row >= 0) & (row < design.grid_n)
    return np.where(inside, col * design.grid_n + row + 1, 0)


def _dots_by_size(u8, refine_img, design, params, A, allowed, map_to_corr=None):
    """Detect dots once per printed dot size; keep each where its box prints that
    size. `map_to_corr` maps detections into the corrected frame for the box test
    (the raw pass). Returns (pts in u8's frame, box per dot, sigma per dot)."""
    sizes = sorted({b.dot_um for b in design.boxes})
    by_size = {s: {b.N for b in design.boxes if b.dot_um == s} for s in sizes}
    P, Bx, S = [], [], []
    for s in sizes:
        pts, _area = lt.detect_blobs(u8, tophat=params.tophat_px(s), area=params.dot_area_px(s),
                                     noise_k=params.noise_k, mask=allowed)
        if not len(pts):
            continue
        q = map_to_corr(pts) if map_to_corr is not None else pts
        good = np.isfinite(q).all(1)
        N = np.zeros(len(pts), int)
        N[good] = _design_box_of(design, A, q[good])
        keep = np.isin(N, list(by_size[s]))
        pts, N = pts[keep], N[keep]
        sigma = params.imaged_fwhm_px(s) / 2.35482
        if len(pts) and params.refine == "gauss":
            pts = refine_gauss(refine_img, pts, sigma, params.refine_iters)
        elif len(pts) and params.refine == "fit":
            pts = refine_fit(refine_img, pts, sigma)
        P.append(pts); Bx.append(N); S.append(np.full(len(pts), sigma))
    if not P:
        return np.zeros((0, 2)), np.zeros(0, int), np.zeros(0)
    return np.concatenate(P), np.concatenate(Bx), np.concatenate(S)


def _jackknife_lam(design, tags, um_per_px):
    """Leave-one-tag-out spread of the expansion factor (>= 4 usable tags)."""
    src, dst = [], []
    for r in design.tag_records():
        t = tags.get(int(r["meta"]["aruco_id"]))
        if t is not None and t.usable:
            src.append([r["x_um"], r["y_um"]]); dst.append(t.centre_px)
    n = len(src)
    if n < 4:
        return float("nan")
    src = np.asarray(src, float); dst = np.asarray(dst, float)
    lams = []
    for k in range(n):
        m = np.arange(n) != k
        X = np.column_stack([src[m], np.ones(m.sum())])
        sol, *_ = np.linalg.lstsq(X, dst[m], rcond=None)
        lams.append(math.sqrt(abs(np.linalg.det(sol[:2].T))) * um_per_px)
    lams = np.asarray(lams)
    return float(math.sqrt((n - 1) / n * ((lams - lams.mean()) ** 2).sum()))


def _match_nearest(src, dst, gate):
    """One-to-one greedy nearest match src -> dst within gate (scalar or per src).
    Returns index into dst per src (-1 if none)."""
    out = np.full(len(src), -1, int)
    if not len(src) or not len(dst):
        return out
    from scipy.spatial import cKDTree
    gate = np.broadcast_to(np.asarray(gate, float), (len(src),))
    ok = np.isfinite(src).all(1)
    d, j = cKDTree(dst).query(np.where(ok[:, None], src, 0.0))
    cand = sorted((d[i], i, j[i]) for i in np.nonzero(ok)[0] if d[i] < gate[i])
    used = set()
    for _d, i, jj in cand:
        if jj not in used:
            used.add(jj); out[i] = jj
    return out


# ------------------------------------------------------------------ detect
def detect(corr_img, design: Design, params: ArucoParams = None, raw_img=None, correction=None,
           dict_name=None, noise_model=None) -> DetectResult:
    """Full Stage 2 on a Stage-1 corrected frame. `raw_img` + `correction` enable
    the exact edge test, raw-frame photometry and the raw second pass.
    `noise_model` (rwtag.errors.NoiseModel) sets the gain, kappa and floor of the
    per-feature covariances (default: relative errors, kappa 1, floor 0)."""
    det = _detect(corr_img, design, params, raw_img, correction, dict_name)
    from rwtag import errors as ER
    return ER.apply(det, raw_img, correction, noise_model or ER.NoiseModel(), design)


def _detect(corr_img, design, params=None, raw_img=None, correction=None, dict_name=None):
    params = params or ArucoParams()
    dict_name = dict_name or design.dict_name
    corr = np.asarray(corr_img, np.float32)
    u8 = io.to_uint8_robust(corr)
    H, W = u8.shape[:2]
    shape = (H, W)
    geo_id = correction is None or C.geometric_is_identity(correction)
    module_px = design.tag_um / 6.0 / params.um_per_px

    # ---- 1. tags --------------------------------------------------------------
    tags, tinfo = decode_tags(u8, params, dict_name, tag_um=design.tag_um)
    if correction is not None and not geo_id:
        for t in tags.values():
            if not C.raw_source_valid(t.corners_px, correction, shape, module_px).all():
                t.in_edge_band = True
    # ---- 2. registration --------------------------------------------------------
    A, ainfo = fit_affine(design, tags)
    pose = frame_pose(tags, design, affine_sign=(ainfo["sign"] if A is not None and
                                                 ainfo.get("sign_source") == "affine" else None))
    known = {v for _i, _j, v in design.node_ids}
    aruco_xy = {i: tuple(map(float, t.centre_px)) for i, t in tags.items() if t.usable and i in known}
    allowed = _allowed_mask(shape, tags, grow_px=module_px) if params.mask_tags else None
    params_d = params.to_dict()

    if A is None:
        dots, _a = lt.detect_blobs(u8, tophat=params.tophat_px(min(b.dot_um for b in design.boxes)),
                                   area=params.dot_area_px(design.dot_side_um), noise_k=params.noise_k, mask=allowed)
        model = {"kind": "aruco", "registered": False, "reg": IDENTITY_REG, "tags": tags, "aruco_xy": aruco_xy,
                 "decode": tinfo, "affine_info": ainfo,
                 "reason": ("no ArUco tag decoded" if not tags else
                            "no usable tag in the design (edge band / ambiguous / unknown ids)"),
                 "summary": "not registered (no usable tag)"}
        return DetectResult(u8=u8, dots=dots, basis=_basis_any(dots), dashes_all=np.zeros((0, 2)),
                            dashes_on_grid=np.zeros((0, 2)), glyphs=np.zeros((0, 2)), model=model,
                            stage="grid", tags=tags, frame_pose=pose, dot_box=np.zeros(len(dots), int),
                            dot_flag=np.array([""] * len(dots), dtype=object), design_name=design.name,
                            design_sha=dict(design.file_sha256), params=params_d)

    Al, t0 = A[:, :2], A[:, 2]
    box = design.box_um
    fit = {"O": t0.copy(), "U": Al @ np.array([box, 0.0]), "V": Al @ np.array([0.0, box]), "box_um": box}
    o = design.origin_um
    O_node = Al @ np.array([o, o]) + t0
    U, V = fit["U"], fit["V"]
    Pu, Pv = float(np.hypot(*U)), float(np.hypot(*V))
    grid = {"u": U / Pu, "v": V / Pv, "box_pitch": 0.5 * (Pu + Pv), "phase_u": float((O_node @ (U / Pu)) % (0.5 * (Pu + Pv))),
            "phase_v": float((O_node @ (V / Pv)) % (0.5 * (Pu + Pv))), "u_vec": U, "v_vec": V, "origin": O_node}

    # ---- 3. dots, per printed size ----------------------------------------------
    dots, dot_box, dot_sig = _dots_by_size(u8, corr, design, params, A, allowed)

    # ---- 4. per-box lattices ------------------------------------------------------
    basis_by_box, per_box = {}, {}
    for b in design.boxes:
        m = dot_box == b.N
        n = int(m.sum())
        rec = {"design": b.count, "detected": n, "dot_um": b.dot_um, "pitch_um": b.pitch_um,
               "pitch_px": float("nan"), "lam": float("nan")}
        if n >= 12:
            p = b.pitch_um
            init = {"v1": Al @ np.array([p, 0.0]), "v2": Al @ np.array([0.0, p])}
            origin = Al @ np.array([b.x0_um + b.phase_um, b.y0_um + b.phase_um]) + t0
            try:
                bb = lt.refine_basis(dots[m], init, origin=origin)
                basis_by_box[b.N] = bb
                rec["pitch_px"] = bb["pitch"]
                rec["lam"] = bb["pitch"] * params.um_per_px / p
            except np.linalg.LinAlgError:
                pass
        per_box[b.N] = rec
    lams = [r["lam"] for r in per_box.values() if r["detected"] >= 30 and np.isfinite(r["lam"])]
    lam_dots = float(np.median(lams)) if lams else float("nan")
    if basis_by_box:
        best = max(basis_by_box, key=lambda N: per_box[N]["detected"])
        basis = dict(basis_by_box[best]); basis["box"] = best
    else:
        p = design.dot_pitch_um
        basis = {"v1": Al @ np.array([p, 0.0]), "v2": Al @ np.array([0.0, p]),
                 "pitch": float(np.hypot(*(Al @ np.array([p, 0.0])))), "origin": O_node.copy(), "angle_deg": 0.0}

    # ---- 5. dashes -------------------------------------------------------------
    dashes = detect_dashes(u8, params, design.dot_side_um, mask=allowed)
    on_grid, ndrop = lt.dashes_on_grid(dashes, grid) if len(dashes) else (dashes, 0)

    # ---- edge flags (exact: no real raw source within one spot width) -----------
    fwhm = dot_sig * 2.35482
    if correction is not None and not geo_id:
        valid = np.ones(len(dots), bool)
        for f in np.unique(np.round(fwhm, 3)):
            mm = np.round(fwhm, 3) == f
            valid[mm] = C.raw_source_valid(dots[mm], correction, shape, params.edge_margin_fwhm * f)
    else:
        mg = params.edge_margin_fwhm * fwhm
        valid = ((dots[:, 0] >= mg) & (dots[:, 0] <= W - 1 - mg) & (dots[:, 1] >= mg) & (dots[:, 1] <= H - 1 - mg)) \
            if len(dots) else np.zeros(0, bool)
    dot_flag = np.where(valid, "", "edge").astype(object)
    if len(dashes) and correction is not None and not geo_id:
        dvalid = C.raw_source_valid(dashes, correction, shape, params.edge_margin_fwhm * float(np.median(fwhm)) if len(fwhm) else 3.0)
    else:
        dvalid = np.ones(len(dashes), bool)
    dash_flag = np.where(dvalid, "", "edge").astype(object)

    # ---- 6. photometry on the raw frame -----------------------------------------
    if raw_img is not None:
        raw = np.asarray(raw_img, np.float32)
        noise_raw = background_noise(raw)
        dots_raw_map = C.inverse_geometric(dots, correction, shape) if not geo_id else dots.copy()
        sig_raw, bg_raw, width = spot_photometry(raw, dots_raw_map, dot_sig, noise_raw)
        photometry_on = "raw"
    else:
        raw = None
        dots_raw_map = None
        noise_raw = background_noise(corr)
        sig_raw, bg_raw, width = spot_photometry(corr, dots, dot_sig, noise_raw)
        photometry_on = "corrected"
    params_d["photometry_on"] = photometry_on
    params_d["noise_sigma"] = noise_raw

    # ---- 7. the raw second pass ---------------------------------------------------
    raw_pass = None
    # Stage 1 rotates content by +rotate_deg (ccw on screen), so raw = corrected - rotate_deg
    rot_raw = float(pose.frame_rot_deg) - (float(correction.rotate_deg) if correction is not None else 0.0)
    if raw is not None and params.raw_pass:
        raw_pass = _raw_pass(raw, design, params, dict_name, A, tags, dots, dot_box, dot_sig,
                             dots_raw_map, dashes, correction, shape, geo_id, module_px)   # ALL dashes: indices match dashes_all
        if np.isfinite(raw_pass["rot_deg"]):
            rot_raw = raw_pass["rot_deg"]

    lam = ainfo["scale_px_per_um"] * params.um_per_px
    lam_sig = _jackknife_lam(design, tags, params.um_per_px)
    n_edge = int((dot_flag == "edge").sum())
    model = {"kind": "aruco", "registered": True, "reg": IDENTITY_REG, "affine": A, "sign": ainfo["sign"],
             "tags": tags, "aruco_xy": aruco_xy, "decode": tinfo, "affine_info": ainfo,
             "scale_px_per_um": ainfo["scale_px_per_um"], "node_num": {}, "labels": [],
             "summary": (f"{ainfo['n_matched']} tags · λ {lam:.4f}"
                         + (f" ± {lam_sig:.4f}" if np.isfinite(lam_sig) else "")
                         + (f" (dots {lam_dots:.4f})" if np.isfinite(lam_dots) else "")
                         + f" · rot {rot_raw:+.2f}° raw · {ainfo['method']} · centre rms {ainfo['centre_rms_px']:.2f} px · "
                         f"handedness {'-1 (expected)' if ainfo['sign'] < 0 else '+1 MIRRORED'} · "
                         f"{len(dots)} dots ({n_edge} edge) · {len(on_grid)} dashes")}
    return DetectResult(
        u8=u8, dots=dots, basis=basis, dashes_all=dashes, dashes_on_grid=np.asarray(on_grid, float).reshape(-1, 2),
        glyphs=np.zeros((0, 2)), grid=grid, fit=fit, reads=[], model=model, glyph_h=0.0,
        n_dashes_dropped=int(ndrop), stage="solved", tags=tags, frame_pose=pose, dot_box=dot_box,
        dot_flag=dot_flag, dash_flag=dash_flag, dot_signal=sig_raw, dot_bg=bg_raw, dot_sigma_px=width,
        basis_by_box=basis_by_box, per_box=per_box, lam_tags=lam, lam_tags_sigma=lam_sig, lam_dots=lam_dots,
        rot_raw_deg=rot_raw, design_name=design.name, design_sha=dict(design.file_sha256), params=params_d,
        raw_pass=raw_pass)


def _raw_pass(raw, design, params, dict_name, A, tags, dots, dot_box, dot_sig, dots_raw_map,
              dashes_corr, correction, shape, geo_id, module_px):
    """Detect again on the RAW frame and join to the corrected-frame features.
    Per feature: the independent raw detection (`*_det`, NaN if none matched) and
    the corrected position mapped to raw through the exact inverse (`*_map`)."""
    raw_u8 = io.to_uint8_robust(raw)
    rtags, _ = decode_tags(raw_u8, params, dict_name, tag_um=design.tag_um)
    to_corr = (lambda P: C.forward_geometric(P, correction, shape)) if not geo_id else None
    allowed = _allowed_mask(shape, rtags, grow_px=module_px) if params.mask_tags else None
    rdots, _rbox, _rs = _dots_by_size(raw_u8, raw, design, params, A, allowed, map_to_corr=to_corr)
    # dots: nearest raw detection to each mapped corrected dot, gate 0.45 x its box pitch
    pitch_px = np.array([0.45 * (design.box(int(N)).pitch_um / params.um_per_px) *
                         (A_scale(A) * params.um_per_px) if N else 0.0 for N in dot_box])
    j = _match_nearest(dots_raw_map, rdots, pitch_px)
    det = np.full((len(dots), 2), np.nan)
    det[j >= 0] = rdots[j[j >= 0]]
    # tags by id
    tags_det, tags_map, corners_det = {}, {}, {}
    for i, t in tags.items():
        m = C.inverse_geometric(t.centre_px[None], correction, shape)[0] if not geo_id else t.centre_px
        tags_map[i] = (float(m[0]), float(m[1]))
        rt = rtags.get(i)
        if rt is not None and not rt.duplicate:
            tags_det[i] = (float(rt.centre_px[0]), float(rt.centre_px[1]))
            corners_det[i] = rt.corners_px.copy()
    # dashes
    rdash = detect_dashes(raw_u8, params, design.dot_side_um, mask=allowed)
    dmap = C.inverse_geometric(dashes_corr, correction, shape) if (not geo_id and len(dashes_corr)) else np.asarray(dashes_corr, float).reshape(-1, 2)
    jd = _match_nearest(dmap, rdash, 0.45 * design.dot_pitch_um / params.um_per_px * A_scale(A) * params.um_per_px)
    ddet = np.full((len(dmap), 2), np.nan)
    ddet[jd >= 0] = rdash[jd[jd >= 0]]
    found = np.isfinite(det).all(1)
    dd = np.hypot(*(det[found] - dots_raw_map[found]).T) if found.any() else np.zeros(0)
    rpose = frame_pose(rtags, design)
    return {"dots_det": det, "dots_map": dots_raw_map, "dots_found": found,
            "tags_det": tags_det, "tags_map": tags_map, "tag_corners_det": corners_det,
            "tags_rot_det": {i: rtags[i].rot_deg for i in tags_det},
            "dashes_det": ddet, "dashes_map": dmap,
            "n_raw_dots": int(len(rdots)), "n_raw_dots_unmatched": int(len(rdots) - (j >= 0).sum()),
            "dot_match_frac": float(found.mean()) if len(found) else float("nan"),
            "median_det_minus_map_px": float(np.median(dd)) if len(dd) else float("nan"),
            "rot_deg": float(rpose.frame_rot_deg) if rpose.n_tags else float("nan"),
            "geometric_identity": bool(geo_id)}


def A_scale(A):
    """px per design um of an affine."""
    return float(math.sqrt(abs(np.linalg.det(A[:, :2]))))


def _basis_any(dots):
    dots = np.asarray(dots, float).reshape(-1, 2)
    if len(dots) >= 50:
        try:
            return lt.refine_basis(dots, lt.estimate_basis(dots))
        except Exception:
            pass
    return {"v1": np.array([1.0, 0.0]), "v2": np.array([0.0, 1.0]), "pitch": 1.0, "origin": np.zeros(2), "angle_deg": 0.0}


# ------------------------------------------------------------------ helpers for callers
def params_for_meta(meta, base: ArucoParams = None) -> ArucoParams:
    """Detector params with the pixel size taken from the image's metadata."""
    from dataclasses import replace
    base = base or ArucoParams()
    return replace(base, um_per_px=float(meta.um_per_px)) if getattr(meta, "um_per_px", None) else base


def apply_to_meta(det: DetectResult, meta):
    """Write the derived expansion, rotation and handedness into the record."""
    if det is None or not (det.model and det.model.get("registered")):
        return
    meta.set_derived(expansion_derived=round(det.lam_tags, 6),
                     expansion_derived_sigma=(round(det.lam_tags_sigma, 6) if np.isfinite(det.lam_tags_sigma) else None),
                     rotation_derived_deg=(round(det.rot_raw_deg, 4) if np.isfinite(det.rot_raw_deg) else None),
                     handedness=float(det.model["sign"]))


def predicted_px(design_um, det: DetectResult):
    """Design um -> corrected-frame px through the tag affine (no warp)."""
    A = det.model["affine"]
    P = np.asarray(design_um, float).reshape(-1, 2)
    return P @ A[:, :2].T + A[:, 2]
