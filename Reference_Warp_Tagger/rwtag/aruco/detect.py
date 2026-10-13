"""
rwtag.aruco.detect
==================
Stage-2 for the V2 print: decode the ArUco tags, fit the design -> image affine
from their corners, detect + refine the fill dots, and hand back a DetectResult
that refwarp.tagframe / warp / tagmatch consume unchanged.

    detect(u8, design, params) -> DetectResult
        model = {registered, kind:"aruco", reg (identity), affine, sign, tags,
                 aruco_xy, ...}     fit = {O, U, V, box_um}    grid, basis, dots, dashes

WHY THE FIT IS EXACT. refwarp.warp.coarse_map(um) = O + (x/box) U + (y/box) V under
the identity registration. Setting O = A(0,0), U = A_lin (box,0), V = A_lin (0,box)
and fit["box_um"] = box makes that map equal to the fitted affine A everywhere, so
the ICP/TPS refinement starts from the tag solution and no box-numbering step is
needed. `grid` (for the dash filter) is anchored at the NODE lattice instead --
V2 insets node (0,0) by half a tag, so the two differ by that offset.

HANDEDNESS. The design frame is y-up (STL), the image y-down, so A must be a
reflection: sign(det A_lin) = -1. That sign is computed, stored on the model and
checked by the series driver on every frame -- the 0d / Phase-B / W8 bug class
(fitting a proper rotation to a reflected frame gives a confident, wrong answer).

DETECTOR SETTINGS (R16). Plain inversion, NO CLAHE (W1: CLAHE over a dense dot
field collapses decode in the pattern centre). errorCorrectionRate = 1.0 (W3: the
0.6 default rounds DICT_4X4_50's single correctable bit to zero). Tags whose
corners fall in the un-distortion edge band are ignored (W3). Dot centres are
refined with a Gaussian-mask centroid (W7: +25-35% over the plain centroid);
`refine="fit"` runs the full per-dot Gaussian least-squares fit W7 measured with,
for validation. Top-hat element >= 2 x the imaged dot FWHM (W5/W9).
"""
from __future__ import annotations
from dataclasses import dataclass, field
import json
import math
import numpy as np
import cv2
from cv2 import aruco

from rwtag.glyph import lattice as lt
from rwtag.glyph.types import DetectResult

IDENTITY_REG = {"orient": (0, 1, 1, 1), "offset": (0, 0)}


# ----------------------------------------------------------------- design map
@dataclass
class Design:
    """The V2 reference map (`cad/aruco_grid_<variant>.reference_tags.json`)."""
    records: list
    box_um: float                     # node pitch, (750 - tag) / 5
    origin_um: float                  # design coordinate of node (0,0) (= tag/2, fit "inside")
    dot_pitch_um: float
    dot_side_um: float
    tag_um: float
    dict_name: str
    grid_n: int

    @classmethod
    def from_dict(cls, data):
        cfg = data.get("config", {})
        tag = float(cfg.get("tag_um", 0.0))
        origin = tag / 2.0 if cfg.get("fit", "inside") == "inside" else 0.0
        return cls(records=data["records"], box_um=float(data["box_um"]),
                   origin_um=origin, dot_pitch_um=float(data["dot_pitch"]),
                   dot_side_um=float(data.get("dot_side_um", cfg.get("dot_side_um", 2.125))),
                   tag_um=tag, dict_name=cfg.get("dict_name", "DICT_4X4_50"),
                   grid_n=int(data.get("grid_n", 5)))

    @classmethod
    def load(cls, path):
        with open(path) as f:
            return cls.from_dict(json.load(f))

    def tag_records(self):
        return [r for r in self.records if r["category"] == "aruco"]

    def design_corners(self, rec):
        """Design-frame (y-UP) corners of a tag record in ArUco's canonical order
        TL, TR, BR, BL. The generator draws the marker with its canonical top row at
        the HIGHEST design y, and the image flips y, so the canonical marker is what
        the camera sees -- corner k of the detection is corner k here."""
        s = float(rec["meta"].get("size_um", self.tag_um)) / 2.0
        x, y = float(rec["x_um"]), float(rec["y_um"])
        return np.array([[x - s, y + s], [x + s, y + s], [x + s, y - s], [x - s, y - s]])


# ------------------------------------------------------------------ params
@dataclass
class ArucoParams:
    um_per_px: float = 0.510
    psf_fwhm_um: float = 2.5          # the microscope's PSF (Phase 1b); sizes the top-hat
    error_correction_rate: float = 1.0
    edge_band_um: float = 25.0        # un-distortion band excluded at the frame edge (W3)
    dot_area: tuple = (12, 220)       # px^2, W5: the V1 floor of 30 loses nothing, 12 is safe
    tophat: int = 0                   # 0 -> derived, >= 2 x imaged FWHM (odd, >= 11)
    refine: str = "gauss"             # "gauss" (Gaussian-mask centroid) | "fit" (W7 LSQ) | "none"
    refine_iters: int = 4
    noise_k: float = 5.0              # threshold floor: median + k * robust sigma of the top-hat
                                      # (0 -> plain Otsu, the V1 behaviour). See detect_dots.
    dash_area: tuple = (0, 1400)      # 0 -> derived from the dot size
    dash_min_aspect: float = 2.0
    ransac_px: float = 4.0
    mask_tags: bool = True            # drop dot detections inside decoded tags (module blobs)
    detector_params: dict = field(default_factory=dict)   # extra cv2 DetectorParameters

    def imaged_fwhm_px(self, dot_side_um):
        return math.hypot(dot_side_um, self.psf_fwhm_um) / self.um_per_px

    def tophat_px(self, dot_side_um):
        if self.tophat:
            return int(self.tophat) | 1
        return max(11, int(math.ceil(2.0 * self.imaged_fwhm_px(dot_side_um))) | 1)

    @property
    def edge_band_px(self):
        return self.edge_band_um / self.um_per_px


def detector(params: ArucoParams, dict_name="DICT_4X4_50"):
    p = aruco.DetectorParameters()
    p.errorCorrectionRate = float(params.error_correction_rate)
    for k, v in params.detector_params.items():
        setattr(p, k, v)
    return aruco.ArucoDetector(aruco.getPredefinedDictionary(getattr(aruco, dict_name)), p)


# ------------------------------------------------------------------ tags
def decode_tags(u8, params: ArucoParams, dict_name="DICT_4X4_50"):
    """Decode on the plain-inverted frame. Returns ({id: {centre, corners}}, info).
    Duplicated ids (two detections claiming one id) are dropped -- a misdecode is
    worse than a missing tag -- and tags touching the edge band are ignored."""
    inv = 255 - np.asarray(u8, np.uint8)
    corners, ids, _rej = detector(params, dict_name).detectMarkers(inv)
    H, W = inv.shape[:2]
    b = params.edge_band_px
    tags, dupes, banded = {}, set(), 0
    if ids is not None:
        for c, i in zip(corners, ids.flatten()):
            c = np.asarray(c, float).reshape(4, 2)
            if (c[:, 0].min() < b or c[:, 1].min() < b
                    or c[:, 0].max() > W - 1 - b or c[:, 1].max() > H - 1 - b):
                banded += 1
                continue
            i = int(i)
            if i in tags or i in dupes:
                dupes.add(i); tags.pop(i, None)
                continue
            tags[i] = {"centre": c.mean(0), "corners": c}
    return tags, {"n_raw": 0 if ids is None else int(len(ids)), "n_banded": banded,
                  "dupes": sorted(dupes)}


def tag_handedness(design: Design, tags: dict):
    """Per-tag handedness from the corner ORDER: sign(cross(TR-TL, BL-TL)) in the
    image times the same in the design. A y-up design seen in a y-down image gives
    -1 on every tag; +1 means a mirrored frame (or a missing y flip). Returns
    (sign, n_agree, n_total) with sign the majority value."""
    votes = []
    for r in design.tag_records():
        aid = int(r["meta"]["aruco_id"])
        if aid in tags:
            for c in (design.design_corners(r), tags[aid]["corners"]):
                a, b = c[1] - c[0], c[3] - c[0]
                votes.append(np.sign(a[0] * b[1] - a[1] * b[0]))
    v = np.asarray(votes).reshape(-1, 2)
    if not len(v):
        return 0.0, 0, 0
    per = v[:, 0] * v[:, 1]
    sign = float(np.sign(per.sum())) or -1.0
    return sign, int((per == sign).sum()), int(len(per))


def _rot_scale(design: Design, tags: dict, sign):
    """Rotation + PRINT scale (px per printed um) from the tags' own corners, which
    are rigid -- the tag keeps its printed size at every expansion -- via a
    Kabsch fit of design corner vectors (y flipped if sign < 0) to image corner
    vectors. Returns (R 2x2 proper rotation, print_scale)."""
    S, D = [], []
    F = np.diag([1.0, sign])
    for r in design.tag_records():
        aid = int(r["meta"]["aruco_id"])
        if aid in tags:
            dc = design.design_corners(r); ic = tags[aid]["corners"]
            S.append((dc - dc.mean(0)) @ F.T); D.append(ic - ic.mean(0))
    S = np.concatenate(S); D = np.concatenate(D)
    U, sv, Vt = np.linalg.svd(S.T @ D)
    d = np.sign(np.linalg.det(U @ Vt)) or 1.0
    R = (U @ np.diag([1.0, d]) @ Vt).T
    scale = float(sv.sum() / (S ** 2).sum())
    return R, scale


def fit_affine(design: Design, tags: dict, params: ArucoParams, dots=None):
    """Design um (y-up) -> image px affine.

    RIGID ISLANDS: a tag keeps its printed size while the pattern expands, so its
    CORNERS are not affine images of the design corners for lambda != 1 (the first
    version of this fit used them and was three dot pitches off at 2x). The
    expansion is carried by the tag CENTRES:
      >= 3 tags  full affine through the centres (RANSAC), handedness checked
                 against the corner order;
      2 tags     similarity with the corner-order handedness through the centres;
      1 tag      rotation + handedness from the tag's corners, translation from its
                 centre, and the expansion scale from the DOT LATTICE pitch (the
                 dots' spacing grows with lambda, the tag does not); falls back to
                 the print scale (lambda = 1) with a warning flag if too few dots.
    Returns (A 2x3, info) or (None, info)."""
    sign, n_agree, n_tot = tag_handedness(design, tags)
    src, dst, used = [], [], []
    for r in design.tag_records():
        aid = int(r["meta"]["aruco_id"])
        if aid in tags:
            src.append([float(r["x_um"]), float(r["y_um"])]); dst.append(tags[aid]["centre"]); used.append(aid)
    info = {"n_matched": len(used), "ids": used, "n_unknown": len(set(tags) - set(used)),
            "sign": sign, "handedness_agree": f"{n_agree}/{n_tot}", "method": None,
            "scale_from_dots": False}
    if not used:
        return None, info
    src = np.asarray(src, float); dst = np.asarray(dst, float)
    A = None
    if len(used) >= 3:
        Af, inl = cv2.estimateAffine2D(src, dst, method=cv2.RANSAC,
                                       ransacReprojThreshold=params.ransac_px * 3,
                                       maxIters=2000, confidence=0.999, refineIters=20)
        # three nearly collinear tags (one grid line) make the affine ill-conditioned:
        # fall through to the similarity in that case
        if Af is not None and np.sign(np.linalg.det(Af[:, :2])) == sign:
            sv = np.linalg.svd(Af[:, :2], compute_uv=False)
            if sv[1] / sv[0] > 0.5:
                A = Af; info["method"] = "affine(centres)"; info["n_inliers"] = int(inl.sum())
    if A is None:
        R, print_scale = _rot_scale(design, tags, sign)
        F = np.diag([1.0, sign])
        if len(used) >= 2:
            # similarity: scale from centre spacing, rotation from the corners
            S = (src - src.mean(0)) @ F.T @ R.T; D = dst - dst.mean(0)
            scale = float((S * D).sum() / (S ** 2).sum())
            info["method"] = "similarity(centres)"
        else:
            scale = print_scale
            if dots is not None and len(dots) >= 30:
                try:
                    b = lt.estimate_basis(np.asarray(dots, float))
                    scale = float(b["pitch"]) / design.dot_pitch_um
                    info["scale_from_dots"] = True
                except Exception:
                    pass
            info["method"] = "single tag" + (" (scale from dot lattice)" if info["scale_from_dots"]
                                             else " (PRINT scale — expansion unknown)")
        Al = scale * R @ F
        t = dst.mean(0) - src.mean(0) @ Al.T
        A = np.column_stack([Al, t])
    res = np.hypot(*((src @ A[:, :2].T + A[:, 2]) - dst).T)
    info.update(centre_rms_px=float(np.sqrt(np.mean(res ** 2))),
                scale_px_per_um=float(np.sqrt(abs(np.linalg.det(A[:, :2])))))
    return A, info


# ------------------------------------------------------------------ dots
def detect_dots(u8, tophat=15, dot_area=(12, 220), max_aspect=1.7, min_extent=0.55,
                noise_k=5.0):
    """Production dot detector (rwtag.glyph.lattice.detect_dots: top-hat, Otsu,
    size / roundness) with ONE addition: the threshold is floored at the top-hat
    image's noise level, median + noise_k * 1.4826 * MAD.

    WHY. Stage 1 flat-fields the frame, which amplifies the read noise in the
    vignetted corners by up to 10x. In a SPARSE frame (a 34 um-tag print at 6x:
    ~650 dots in 7 Mpx) Otsu no longer sees a bimodal histogram and drops INTO the
    noise -- on the Phase-C truth frames it chose 12 with the noise at
    median 10, sigma 6, so 59% of the detections were noise and the real dots
    merged with it (31% efficiency). The same frame without flat-fielding, or
    with the floor, detects 96-97% with 3% false. Dense frames are unaffected:
    their Otsu threshold is far above the floor and max() keeps it. This is the
    "sparse-frame-robust threshold" R16 anticipated for PSF >= 3.5 um; it is
    needed at 3.18 um as soon as the frame is flat-fielded."""
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(tophat) | 1, int(tophat) | 1))
    th = cv2.morphologyEx(np.asarray(u8, np.uint8), cv2.MORPH_TOPHAT, se)
    otsu, _ = cv2.threshold(th, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    thr = float(otsu)
    if noise_k > 0:
        med = float(np.median(th)); mad = float(np.median(np.abs(th.astype(np.int16) - med))) * 1.4826
        thr = max(thr, med + noise_k * mad)
    b = (th > thr).astype(np.uint8) * 255
    n, _lab, st, cen = cv2.connectedComponentsWithStats(b, 8)
    pts = []
    for i in range(1, n):
        a, w, h = st[i, cv2.CC_STAT_AREA], st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT]
        if not (dot_area[0] <= a <= dot_area[1]):
            continue
        if max(w, h) / max(min(w, h), 1) > max_aspect or a / max(w * h, 1) < min_extent:
            continue
        pts.append(cen[i])
    return np.asarray(pts, float).reshape(-1, 2)


def _patches(img, pts, R):
    """(N, 2R+1, 2R+1) float patches around integer-rounded pts; valid mask."""
    H, W = img.shape
    xi = np.round(pts[:, 0]).astype(int); yi = np.round(pts[:, 1]).astype(int)
    ok = (xi >= R) & (yi >= R) & (xi < W - R) & (yi < H - R)
    d = np.arange(-R, R + 1)
    P = img[(yi[ok, None, None] + d[None, :, None]), (xi[ok, None, None] + d[None, None, :])]
    return P.astype(np.float64), xi, yi, ok, d


def refine_gauss(img, pts, sigma_px, iters=4):
    """Gaussian-mask centroid (Anderson & King): iteratively re-centre a Gaussian
    window of the spot's own width on the background-subtracted patch. Vectorised
    over all dots; converges to the least-squares Gaussian centre for a Gaussian
    spot, at a few percent of curve_fit's cost."""
    pts = np.asarray(pts, float)
    if not len(pts):
        return pts
    R = max(4, int(math.ceil(2.5 * sigma_px)))
    P, xi, yi, ok, d = _patches(img, pts, R)
    if not ok.any():
        return pts
    bg = np.percentile(P.reshape(len(P), -1), 20, axis=1)[:, None, None]
    P = np.clip(P - bg, 0, None)
    cx = pts[ok, 0] - xi[ok]; cy = pts[ok, 1] - yi[ok]
    dx = d[None, None, :]; dy = d[None, :, None]
    for _ in range(iters):
        w = P * np.exp(-((dx - cx[:, None, None]) ** 2 + (dy - cy[:, None, None]) ** 2)
                       / (2.0 * sigma_px ** 2))
        s = w.sum(axis=(1, 2)); good = s > 1e-9
        ncx = np.where(good, (w * dx).sum(axis=(1, 2)) / np.where(good, s, 1), cx)
        ncy = np.where(good, (w * dy).sum(axis=(1, 2)) / np.where(good, s, 1), cy)
        cx, cy = np.clip(ncx, -R + 1, R - 1), np.clip(ncy, -R + 1, R - 1)
    out = pts.copy()
    out[ok, 0] = xi[ok] + cx; out[ok, 1] = yi[ok] + cy
    return out


def refine_fit(img, pts, sigma_px, R=6):
    """W7/W8's per-dot Gaussian least-squares fit (scipy curve_fit). Slow (~1 ms
    per dot); the reference the fast refinement is validated against."""
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
            p, _ = curve_fit(f, (xg, yg), pa.ravel(),
                             p0=[pa.max() - pa.min(), x - xi, y - yi, sigma_px, pa.min()], maxfev=2000)
            if abs(p[1]) < 3 and abs(p[2]) < 3:
                out[i] = (xi + p[1], yi + p[2])
        except Exception:
            pass
    return out


def detect_dashes(u8, params: ArucoParams, dot_side_um):
    """Boundary dashes (8.125 x 2.125 um): elongated mid-size blobs. V1's area-only
    rule cannot separate V2's dashes from its dots (both are small), so require an
    aspect ratio too."""
    th = cv2.morphologyEx(u8, cv2.MORPH_TOPHAT,
                          cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (41, 41)))
    _, b = cv2.threshold(th, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    n, _lab, st, cen = cv2.connectedComponentsWithStats(b, 8)
    a0 = params.dash_area[0] or 2.0 * (dot_side_um / params.um_per_px) ** 2
    pts = []
    for i in range(1, n):
        a, w, h = st[i, cv2.CC_STAT_AREA], st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT]
        if a0 <= a <= params.dash_area[1] and max(w, h) / max(min(w, h), 1) >= params.dash_min_aspect \
                and a / max(w * h, 1) >= 0.5:
            pts.append(cen[i])
    return np.asarray(pts, float).reshape(-1, 2)


def _tag_mask(shape, tags, grow_px):
    m = np.zeros(shape[:2], np.uint8)
    for t in tags.values():
        c = t["corners"]; ctr = c.mean(0)
        poly = ctr + (c - ctr) * (1.0 + grow_px / max(np.linalg.norm(c[0] - ctr), 1.0))
        cv2.fillConvexPoly(m, np.round(poly).astype(np.int32), 1)
    return m


# ------------------------------------------------------------------ detect
def detect(img, design: Design, params: ArucoParams = None, dict_name=None) -> DetectResult:
    """Full V2 Stage 2 on a Stage-1 corrected (bright-on-dark) image."""
    from rwtag.glyph.detect import to_u8
    params = params or ArucoParams()
    dict_name = dict_name or design.dict_name
    u8 = to_u8(img)
    H, W = u8.shape[:2]

    tags, tinfo = decode_tags(u8, params, dict_name)
    aruco_xy = {}
    for r in design.tag_records():
        aid = int(r["meta"]["aruco_id"])
        if aid in tags:
            aruco_xy[aid] = tuple(map(float, tags[aid]["centre"]))

    # --- dots: top-hat / Otsu (production) -> drop tag interiors -> refine -------
    tophat = params.tophat_px(design.dot_side_um)
    dots = detect_dots(u8, tophat=tophat, dot_area=params.dot_area, noise_k=params.noise_k)
    if params.mask_tags and len(dots) and tags:
        module_px = design.tag_um / 6.0 / params.um_per_px
        m = _tag_mask(u8.shape, tags, grow_px=module_px)
        keep = m[np.clip(np.round(dots[:, 1]).astype(int), 0, H - 1),
                 np.clip(np.round(dots[:, 0]).astype(int), 0, W - 1)] == 0
        dots = dots[keep]
    A, ainfo = fit_affine(design, tags, params, dots=dots)
    sigma_px = params.imaged_fwhm_px(design.dot_side_um) / 2.35482
    if len(dots) and params.refine == "gauss":
        dots = refine_gauss(u8, dots, sigma_px, params.refine_iters)
    elif len(dots) and params.refine == "fit":
        dots = refine_fit(u8, dots, sigma_px)
    dashes = detect_dashes(u8, params, design.dot_side_um)

    base_model = {"kind": "aruco", "tags": tags, "aruco_xy": aruco_xy, "decode": tinfo,
                  "affine_info": ainfo, "node_num": {}, "labels": {}, "reg": IDENTITY_REG}
    if A is None:
        model = dict(base_model, registered=False,
                     reason=("no ArUco tag decoded" if not tags else
                             "decoded ids not in the reference map"),
                     summary="not registered (no usable tag)")
        return DetectResult(u8=u8, dots=np.asarray(dots, float).reshape(-1, 2),
                            basis=_basis_fallback(dots), dashes_all=dashes, dashes_on_grid=dashes,
                            glyphs=np.zeros((0, 2)), grid=None, fit=None, reads=[], model=model,
                            glyph_h=0.0, n_dashes_dropped=0, stage="grid")

    Al, t = A[:, :2], A[:, 2]
    box = design.box_um
    fit = {"O": t.copy(), "U": Al @ np.array([box, 0.0]), "V": Al @ np.array([0.0, box]),
           "box_um": box}
    o = design.origin_um
    O_node = Al @ np.array([o, o]) + t
    U, V = fit["U"], fit["V"]
    Pu, Pv = float(np.hypot(*U)), float(np.hypot(*V))
    u, v = U / Pu, V / Pv
    P = 0.5 * (Pu + Pv)
    grid = {"u": u, "v": v, "box_pitch": P, "phase_u": float((O_node @ u) % P),
            "phase_v": float((O_node @ v) % P), "u_vec": U, "v_vec": V}
    on_grid, ndrop = lt.dashes_on_grid(dashes, grid) if len(dashes) else (dashes, 0)

    p = design.dot_pitch_um
    basis = {"v1": Al @ np.array([p, 0.0]), "v2": Al @ np.array([0.0, p]),
             "pitch": float(np.hypot(*(Al @ np.array([p, 0.0])))), "origin": O_node.copy()}
    basis["angle_deg"] = float(np.degrees(np.arctan2(basis["v1"][1], basis["v1"][0])) % 90)
    if len(dots) >= 50:
        try:
            basis = lt.refine_basis(np.asarray(dots, float), basis)
        except Exception:
            pass

    model = dict(base_model, registered=True, affine=A, sign=ainfo["sign"],
                 scale_px_per_um=ainfo["scale_px_per_um"],
                 summary=(f"{ainfo['n_matched']} tags · {ainfo['scale_px_per_um']:.3f} px/um · "
                          f"{ainfo['method']} · centre rms {ainfo['centre_rms_px']:.2f} px · "
                          f"handedness {'mirror (expected)' if ainfo['sign'] < 0 else 'PROPER — check y flip'}"))
    return DetectResult(u8=u8, dots=np.asarray(dots, float).reshape(-1, 2), basis=basis,
                        dashes_all=dashes, dashes_on_grid=np.asarray(on_grid, float).reshape(-1, 2),
                        glyphs=np.zeros((0, 2)), grid=grid, fit=fit, reads=[], model=model,
                        glyph_h=0.0, n_dashes_dropped=int(ndrop), stage="solved")


def _basis_fallback(dots):
    dots = np.asarray(dots, float).reshape(-1, 2)
    if len(dots) >= 50:
        try:
            return lt.refine_basis(dots, lt.estimate_basis(dots))
        except Exception:
            pass
    return {"v1": np.array([1.0, 0.0]), "v2": np.array([0.0, 1.0]), "pitch": 1.0,
            "origin": np.zeros(2), "angle_deg": 0.0}


def predicted_px(design_um, det: DetectResult):
    """Design um -> image px through the tag affine (no warp refinement)."""
    A = det.model["affine"]
    P = np.asarray(design_um, float).reshape(-1, 2)
    return P @ A[:, :2].T + A[:, 2]
