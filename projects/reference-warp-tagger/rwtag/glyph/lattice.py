"""
glyphtrack.lattice
=================
Structure-first geometry for the glyph marker grid.

The markers are a rigid regular grid, so we recover the geometry from the
thousands of fine DOTS (which vote robustly) rather than trying to tell glyphs
from dashes blob-by-blob. From the dot lattice we get rotation + pitch; combined
with the box period that locates the fiducial slots where glyphs (and only
glyphs) live.

Headless: numpy + OpenCV (+ scipy KDTree).
"""
from __future__ import annotations
import numpy as np
import cv2


# ------------------------------------------------------------ dot detection
def detect_dots(gray: np.ndarray, tophat=15, dot_area=(30, 220),
                max_aspect=1.7, min_extent=0.55):
    """Centroids (N,2 float) of the fine fill dots: small, round, bright blobs.
    A small white top-hat flattens the background so a global Otsu isolates the
    dots; size + roundness keep dots and drop glyph/dash structure."""
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (tophat, tophat))
    th = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, se)
    _, b = cv2.threshold(th, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(b, 8)
    pts = []
    for i in range(1, n):
        a = stats[i, cv2.CC_STAT_AREA]; w = stats[i, cv2.CC_STAT_WIDTH]
        h = stats[i, cv2.CC_STAT_HEIGHT]
        if not (dot_area[0] <= a <= dot_area[1]):
            continue
        if max(w, h) / max(min(w, h), 1) > max_aspect:
            continue
        if a / max(w * h, 1) < min_extent:
            continue
        pts.append(cent[i])
    return np.asarray(pts, float)


# ------------------------------------------------------------ lattice basis
def estimate_basis(pts: np.ndarray, k=6):
    """Estimate the two shortest lattice basis vectors (v1, v2) and pitch from a
    point set, via a histogram of nearest-neighbour vectors. Returns
    dict(v1, v2, pitch, angle_deg)."""
    from scipy.spatial import cKDTree
    tree = cKDTree(pts)
    d, idx = tree.query(pts, k=k + 1)                    # self + k neighbours
    pitch = float(np.median(d[:, 1]))                    # 1st-NN distance = true pitch
    vecs = []
    for i in range(len(pts)):
        for j in range(1, k + 1):
            vecs.append(pts[idx[i, j]] - pts[i])
    vecs = np.asarray(vecs)
    lens = np.hypot(vecs[:, 0], vecs[:, 1])
    # keep only primitive-step vectors (the 4 nearest of a square lattice)
    keep = vecs[(lens > 0.8 * pitch) & (lens < 1.2 * pitch)]
    ang = (np.degrees(np.arctan2(keep[:, 1], keep[:, 0])) % 90.0)   # fold to [0,90)
    hist, edges = np.histogram(ang, bins=180, range=(0, 90))
    # refine the peak by a small local average (sub-bin)
    pk = int(np.argmax(hist))
    a0 = float(edges[pk] + (edges[1] - edges[0]) / 2)
    th = np.radians(a0)
    v1 = np.array([np.cos(th), np.sin(th)]) * pitch
    v2 = np.array([-np.sin(th), np.cos(th)]) * pitch
    return {"v1": v1, "v2": v2, "pitch": pitch, "angle_deg": a0}


# ------------------------------------------------------------ box geometry
# measured from the STL (expansion-invariant ratios)
DOT_UM = 8.0
BOX_UM = 150.0
BOX_PER_DOT = BOX_UM / DOT_UM                          # 18.75 dots per box
# fiducial slot centres, local micrometres within a 150um box (x=along-u, y=along-v)
FIDUCIALS = {
    "corner00": (23, 24), "corner02": (23, 127), "corner20": (127, 24),
    "corner22": (127, 127), "center": (75, 75),
    "A": (27, 74), "B": (74, 27), "C": (122, 75), "D": (74, 123),
}
NUMBER_SLOTS = ["corner00", "corner02", "corner20", "corner22", "center"]
LETTER_SLOTS = {"A": "A", "B": "B", "C": "C", "D": "D"}


def detect_dashes(gray, tophat=41, dash_area=(180, 1400), min_extent=0.55):
    """Centroids (N,2) of the solid boundary dashes — mid-size, fairly solid
    bright bars. They mark the box edges, so their phase locks the box grid."""
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (tophat, tophat))
    th = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, se)
    _, b = cv2.threshold(th, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(b, 8)
    pts = []
    for i in range(1, n):
        a = stats[i, cv2.CC_STAT_AREA]; w = stats[i, cv2.CC_STAT_WIDTH]
        h = stats[i, cv2.CC_STAT_HEIGHT]
        if dash_area[0] <= a <= dash_area[1] and a / max(w * h, 1) >= min_extent:
            pts.append(cent[i])
    return np.asarray(pts, float)


def _phase_mode(proj, period, bins=180):
    """Mode of (proj mod period): the common offset of a set of collinear
    features (the box-boundary phase along one axis)."""
    r = np.mod(proj, period)
    h, e = np.histogram(r, bins=bins, range=(0, period))
    # circular smoothing so a peak split across the wrap is captured
    hs = np.convolve(np.r_[h, h, h], np.ones(5) / 5, "same")[bins:2 * bins]
    return float(e[int(np.argmax(hs))] + period / (2 * bins))


def dashes_on_grid(dash_pts, grid, tol_frac=0.15):
    """Dash centres that lie ON / close to a box boundary line. Returns
    (kept_centres Nx2, n_dropped). Distance to the nearest grid line is the
    perpendicular offset to the nearest u-line or v-line (the dashes sit on the
    box edges, so true dashes are close; strays are dropped)."""
    dash_pts = np.asarray(dash_pts, float)
    if len(dash_pts) == 0:
        return dash_pts, 0
    P = grid["box_pitch"]
    pu = dash_pts @ grid["u"] - grid["phase_u"]
    pv = dash_pts @ grid["v"] - grid["phase_v"]
    du = np.abs((pu + P / 2) % P - P / 2)                # dist to nearest u-line
    dv = np.abs((pv + P / 2) % P - P / 2)                # dist to nearest v-line
    keep = np.minimum(du, dv) < tol_frac * P
    return dash_pts[keep], int((~keep).sum())


def fit_box_grid(basis, dash_pts):
    """Given the dot-lattice basis and the boundary dashes, return the box grid:
    unit axes, box period (px), and the corner-phase along each axis."""
    u = basis["v1"] / np.linalg.norm(basis["v1"])      # box axes == dot axes
    v = basis["v2"] / np.linalg.norm(basis["v2"])
    box_pitch = basis["pitch"] * BOX_PER_DOT
    pu = dash_pts @ u; pv = dash_pts @ v
    phase_u = _phase_mode(pu, box_pitch)
    phase_v = _phase_mode(pv, box_pitch)
    return {"u": u, "v": v, "box_pitch": box_pitch,
            "phase_u": phase_u, "phase_v": phase_v,
            "u_vec": u * box_pitch, "v_vec": v * box_pitch}


# fiducial slot positions as a FRACTION of the box (for lattice fitting)
SLOT_FRACS = {s: (lx / BOX_UM, ly / BOX_UM) for s, (lx, ly) in FIDUCIALS.items()}


def fit_fiducial_lattice(glyph_pts, grid, iters=10, tol=0.12):
    """Refine the box lattice by snapping detected GLYPHS to their nearest fiducial
    slot and re-fitting (origin O, axes U, V) by least squares. Each glyph lies at
    an integer box + a known fractional slot offset, so this locks the geometry
    precisely and, as a by-product, assigns every inlier glyph to a slot.
    Returns O, U, V, per-glyph box node + slot for inliers."""
    O = box_corner(grid, 0, 0).astype(float)
    U = grid["u_vec"].astype(float).copy()
    V = grid["v_vec"].astype(float).copy()
    slots = list(SLOT_FRACS.keys())
    fr = np.array([SLOT_FRACS[s] for s in slots])        # (9,2) fractional offsets
    inl = np.zeros(len(glyph_pts), bool); node = np.zeros((len(glyph_pts), 2))
    which = [None] * len(glyph_pts)
    for _ in range(iters):
        Minv = np.linalg.inv(np.column_stack([U, V]))
        bc = (glyph_pts - O) @ Minv.T                    # continuous box coords
        best_d = np.full(len(glyph_pts), 1e9)
        for si, (fx, fy) in enumerate(fr):
            cand = np.round(bc - [fx, fy]) + [fx, fy]     # nearest node for this slot
            d = np.hypot(*(bc - cand).T)
            upd = d < best_d
            best_d[upd] = d[upd]; node[upd] = cand[upd]
            for kk in np.nonzero(upd)[0]:
                which[kk] = slots[si]
        inl = best_d < tol
        if inl.sum() < 8:
            break
        A = np.column_stack([np.ones(int(inl.sum())), node[inl, 0], node[inl, 1]])
        sol, *_ = np.linalg.lstsq(A, glyph_pts[inl], rcond=None)
        O, U, V = sol[0], sol[1], sol[2]
    return {"O": O, "U": U, "V": V, "inliers": inl, "node": node,
            "slot": which, "n_inliers": int(inl.sum()),
            "box_pitch": float((np.hypot(*U) + np.hypot(*V)) / 2)}


def fslot_point(fit, i, j, local_um):
    """Image point of fiducial slot `local_um`=(x,y) inside box (i,j) for a fit."""
    lx, ly = local_um
    return fit["O"] + (i + lx / BOX_UM) * fit["U"] + (j + ly / BOX_UM) * fit["V"]


def fit_box_corner(fit, i, j):
    """Image point of box-corner node (i, j) from the GLYPH-fitted lattice. This is
    anchored to the read glyphs (validated by registration), so its box boundaries
    track the real dashes far better than the coarse dash-phase `box_corner` — use
    it for display whenever a `fit` is available."""
    return fit["O"] + i * fit["U"] + j * fit["V"]


def grid_from_fit(fit):
    """A box-grid dict (same shape as `fit_box_grid`) derived from the glyph fit, so
    dash filtering / geometry that expects a `grid` can use the accurate lattice.
    Box lines pass through the fit origin; pitch is the mean of the U,V lengths."""
    U, V = np.asarray(fit["U"], float), np.asarray(fit["V"], float)
    Pu, Pv = float(np.hypot(*U)), float(np.hypot(*V))
    u, v = U / max(Pu, 1e-9), V / max(Pv, 1e-9)
    P = 0.5 * (Pu + Pv)
    O = np.asarray(fit["O"], float)
    return {"u": u, "v": v, "box_pitch": P,
            "phase_u": float((O @ u) % P), "phase_v": float((O @ v) % P),
            "u_vec": U, "v_vec": V}


def box_corner(grid, i, j):
    """Image point of box-corner lattice node (i, j)."""
    return (grid["phase_u"] + i * grid["box_pitch"]) * grid["u"] + \
           (grid["phase_v"] + j * grid["box_pitch"]) * grid["v"]


def slot_point(grid, i, j, local_um):
    """Image point of a fiducial slot at `local_um`=(x,y) inside box (i,j)."""
    lx, ly = local_um
    return box_corner(grid, i, j) + (lx / BOX_UM) * grid["u_vec"] \
        + (ly / BOX_UM) * grid["v_vec"]


def draw_box_grid(gray, grid, i_range=(-1, 8), j_range=(-1, 8)):
    """Overlay box boundaries (cyan) + fiducial slots (numbers=amber, letters=green)."""
    vis = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    H, W = gray.shape

    def inb(p):
        return -50 <= p[0] <= W + 50 and -50 <= p[1] <= H + 50
    for i in range(*i_range):
        for j in range(*j_range):
            a = box_corner(grid, i, j); b = box_corner(grid, i + 1, j)
            c = box_corner(grid, i, j + 1)
            if inb(a) and inb(b):
                cv2.line(vis, tuple(a.astype(int)), tuple(b.astype(int)), (255, 210, 0), 1)
            if inb(a) and inb(c):
                cv2.line(vis, tuple(a.astype(int)), tuple(c.astype(int)), (255, 210, 0), 1)
    for i in range(*i_range):
        for j in range(*j_range):
            for slot in NUMBER_SLOTS:
                p = slot_point(grid, i, j, FIDUCIALS[slot])
                if inb(p):
                    cv2.drawMarker(vis, tuple(p.astype(int)), (0, 190, 255), cv2.MARKER_CROSS, 12, 2)
            for slot in LETTER_SLOTS:
                p = slot_point(grid, i, j, FIDUCIALS[slot])
                if inb(p):
                    cv2.drawMarker(vis, tuple(p.astype(int)), (60, 230, 90), cv2.MARKER_DIAMOND, 12, 2)
    return vis


def refine_basis(pts, basis, iters=6):
    """Globally refine the lattice basis by iterated closest-node least squares:
    assign each dot to its integer lattice node, re-fit (origin, v1, v2) to all
    inliers, repeat. Removes the small angle/pitch error that smears far boxes."""
    origin = pts[np.argmin(np.hypot(*(pts - pts.mean(0)).T))].astype(float)
    v1, v2 = basis["v1"].astype(float).copy(), basis["v2"].astype(float).copy()
    for _ in range(iters):
        Binv = np.linalg.inv(np.column_stack([v1, v2]))
        ij = np.round((pts - origin) @ Binv.T)
        A = np.column_stack([np.ones(len(pts)), ij[:, 0], ij[:, 1]])
        pred = A @ np.column_stack([origin, v1, v2]).T
        good = np.hypot(*(pts - pred).T) < 0.35 * np.hypot(*v1)
        if good.sum() < 12:
            break
        sol, *_ = np.linalg.lstsq(A[good], pts[good], rcond=None)   # rows: origin,v1,v2
        origin, v1, v2 = sol[0], sol[1], sol[2]
    return {"v1": v1, "v2": v2, "origin": origin, "pitch": float(np.hypot(*v1)),
            "angle_deg": float(np.degrees(np.arctan2(v1[1], v1[0])) % 90),
            "n_inliers": int(good.sum())}


def draw_lattice(gray, pts, basis, seed=None, span=6):
    """Debug overlay: dots (amber) + a local lattice mesh (cyan) from `seed`."""
    vis = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    for p in pts:
        cv2.circle(vis, tuple(np.round(p).astype(int)), 2, (0, 190, 255), -1)
    if seed is None and len(pts):
        seed = pts[np.argmin(np.hypot(*(pts - pts.mean(0)).T))]
    v1, v2 = basis["v1"], basis["v2"]
    for i in range(-span, span + 1):
        for j in range(-span, span + 1):
            q = seed + i * v1 + j * v2
            cv2.drawMarker(vis, tuple(np.round(q).astype(int)), (255, 220, 0),
                           cv2.MARKER_CROSS, 9, 1)
    return vis
