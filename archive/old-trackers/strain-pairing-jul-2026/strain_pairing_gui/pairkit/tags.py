"""
pairkit.tags
===========
Canonical tag geometry, measured from the reference Nanoscribe STL. Every filtered
point is given an ABSOLUTE tag from its position in the design frame, so the same
physical point gets the same tag in every image and pairing is a tag join.

Three separate coordinate grids (box = 150 um):
  DOTS      global 8.0 um square lattice, phase 5.0 um  -> tag  dot|B{n}|{Di}_{Dj}
  FIDUCIALS 3x3 slots per box; numbers are 2 digits at +-6.9 um
            -> tags  num|B{n}|{slot}|{tens|units}  and  let|B{n}|{slot}
  DASHES    10 per box edge at 12 + 14k um, on the box-boundary lines
            -> tag  dash|{H|V}{line}|{ordinal}
"""
from __future__ import annotations
import math
import numpy as np

BOX_UM = 150.0
DOT_PITCH = 8.0
DOT_PHASE = 5.0                     # dots at DOT_PHASE + k*DOT_PITCH (design um)
DIGIT_HALF = 6.9                    # tens/units digit offset from the number-slot centre
DASH_START = 12.0
DASH_SPACING = 14.0
DASHES_PER_EDGE = 10

# fiducial slot centres, box-local micrometres (design frame)
FIDUCIALS_UM = {
    "corner00": (23, 24), "corner02": (23, 127), "corner20": (127, 24),
    "corner22": (127, 127), "center": (75, 75),
    "A": (27, 74), "B": (74, 27), "C": (122, 75), "D": (74, 123),
}
NUMBER_SLOTS = ["corner00", "corner02", "corner20", "corner22", "center"]
LETTER_SLOTS = ["A", "B", "C", "D"]


# ------------------------------------------------------------ DOTS (global lattice)
def dot_index(gx_um, gy_um):
    """Global 8 um lattice index (Di, Dj) of a dot at design position (gx, gy)."""
    return (round((gx_um - DOT_PHASE) / DOT_PITCH),
            round((gy_um - DOT_PHASE) / DOT_PITCH))


def dot_ideal_um(Di, Dj):
    return (Di * DOT_PITCH + DOT_PHASE, Dj * DOT_PITCH + DOT_PHASE)


def dot_ideals_in_box(col, row):
    """Ideal (Di, Dj, gx, gy) of every lattice node whose centre lies in box (col,row)."""
    x0, y0 = col * BOX_UM, row * BOX_UM
    out = []
    i0 = math.ceil((x0 - DOT_PHASE) / DOT_PITCH); i1 = math.floor((x0 + BOX_UM - DOT_PHASE) / DOT_PITCH)
    j0 = math.ceil((y0 - DOT_PHASE) / DOT_PITCH); j1 = math.floor((y0 + BOX_UM - DOT_PHASE) / DOT_PITCH)
    for Di in range(i0, i1 + 1):
        for Dj in range(j0, j1 + 1):
            gx, gy = dot_ideal_um(Di, Dj)
            out.append((Di, Dj, gx, gy))
    return out


def dot_tag(box_number, Di, Dj):
    return f"dot|B{box_number}|{Di}_{Dj}"


def robust_dot_indices(xy, boxes, approx_ij, v1, v2, origin):
    """Exact, tilt/shift-proof global dot indices for one image.

    The box-local fraction (hence `approx_ij`) comes from the fiducial fit and is
    only good to a few % of a box — enough to jump a whole 8 um node between two
    differently-tilted images. So instead we snap every dot to the image's OWN
    detected dot lattice (`origin`, `v1`, `v2` from refine_basis — sub-pixel
    exact), giving integer lattice coords (m, n) with an arbitrary per-image
    origin. The lattice is the design lattice up to a signed permutation S and an
    integer shift, so we fit S once (least squares → rounded) and, per box, take
    the ROBUST MEDIAN integer offset between the noisy `approx_ij` and S·(m,n).
    Result: Di,Dj = S·(m,n) + offset[box] — exact within the box (no per-dot
    quantisation jitter) and anchored to the shared design frame, so the same
    physical dot gets the same (Di,Dj) in every image.

    Returns (idx int (N,2), snap_px (N,), ok bool). ok=False -> caller should fall
    back to rounding approx_ij (degenerate lattice/permutation)."""
    xy = np.asarray(xy, float); approx = np.asarray(approx_ij, float)
    boxes = np.asarray(boxes)
    B = np.column_stack([np.asarray(v1, float), np.asarray(v2, float)])
    O = np.asarray(origin, float)
    if len(xy) < 4 or abs(np.linalg.det(B)) < 1e-9:
        return np.rint(approx).astype(int), np.zeros(len(xy)), False
    Binv = np.linalg.inv(B)
    mn = np.rint((xy - O) @ Binv.T).astype(int)          # exact lattice nodes
    node = O + mn @ B.T
    snap = np.hypot(*(xy - node).T)
    A = np.column_stack([mn, np.ones(len(mn))])
    sol, *_ = np.linalg.lstsq(A, approx, rcond=None)     # approx ~ S·mn + t
    S = np.rint(sol[:2].T)                                # 2x2 signed permutation
    if abs(round(np.linalg.det(S))) != 1:                # not a valid orientation
        return np.rint(approx).astype(int), snap, False
    base = mn @ S.T
    out = base.astype(int).copy()
    resid = approx - base
    for b in np.unique(boxes):
        m = boxes == b
        off = np.rint(np.median(resid[m], axis=0)).astype(int)
        out[m] = base[m].astype(int) + off
    return out, snap, True


# ------------------------------------------------------------ FIDUCIALS (numbers/letters)
def fiducial_ideals():
    """box-local (lx, ly) um for each fiducial tag suffix (kind, slot, place)."""
    out = {}
    for slot in LETTER_SLOTS:
        out[("let", slot, "")] = FIDUCIALS_UM[slot]
    for slot in NUMBER_SLOTS:
        lx, ly = FIDUCIALS_UM[slot]
        out[("num", slot, "tens")] = (lx - DIGIT_HALF, ly)
        out[("num", slot, "units")] = (lx + DIGIT_HALF, ly)
    return out


def fiducial_tag(box_number, kind, slot, place):
    return f"{kind}|B{box_number}|{slot}" + (f"|{place}" if place else "")


# ------------------------------------------------------------ DASHES (boundary lines)
def dash_tag_for(gx_um, gy_um, tol=0.35):
    """Tag a dash from its global design position: nearest box-boundary line +
    ordinal along it. Returns (tag, ideal_gx, ideal_gy) or None if not on a line."""
    # distance (in box-fractions) to nearest vertical / horizontal boundary line
    lx = round(gx_um / BOX_UM); ly = round(gy_um / BOX_UM)
    dvx = abs(gx_um - lx * BOX_UM); dhy = abs(gy_um - ly * BOX_UM)
    if min(dvx, dhy) > tol * BOX_UM:
        return None
    if dvx <= dhy:                                     # on vertical line lx, runs in y
        axis, line, along, fixed = "V", lx, gy_um, lx * BOX_UM
        seg = int(along // BOX_UM); local = along - seg * BOX_UM
        k = round((local - DASH_START) / DASH_SPACING)
        if not (0 <= k < DASHES_PER_EDGE):
            return None
        ideal = (fixed, seg * BOX_UM + DASH_START + k * DASH_SPACING)
    else:                                             # on horizontal line ly, runs in x
        axis, line, along, fixed = "H", ly, gx_um, ly * BOX_UM
        seg = int(along // BOX_UM); local = along - seg * BOX_UM
        k = round((local - DASH_START) / DASH_SPACING)
        if not (0 <= k < DASHES_PER_EDGE):
            return None
        ideal = (seg * BOX_UM + DASH_START + k * DASH_SPACING, fixed)
    return (f"dash|{axis}{line}|{seg * DASHES_PER_EDGE + k}", ideal[0], ideal[1])


# spacings (um) used for the 0.5x assignment cutoff, per grid
SPACING = {"dot": DOT_PITCH, "num": 2 * DIGIT_HALF, "let": BOX_UM / 3, "dash": DASH_SPACING}


# ------------------------------------------------------------ assignment
def box_colrow(box_number):
    return (box_number - 1) // 5, (box_number - 1) % 5


def _fiducial_ideals_cache():
    if not hasattr(_fiducial_ideals_cache, "v"):
        _fiducial_ideals_cache.v = fiducial_ideals()
    return _fiducial_ideals_cache.v


def tag_point(rec):
    """Candidate (tag, residual_um, grid) for one PointRecord, or None."""
    col, row = box_colrow(rec.box_number)
    gx, gy = (col + rec.fx) * BOX_UM, (row + rec.fy) * BOX_UM      # global design um
    lx, ly = rec.fx * BOX_UM, rec.fy * BOX_UM                      # box-local um
    if rec.type == "dot":
        Di, Dj = dot_index(gx, gy); ix, iy = dot_ideal_um(Di, Dj)
        return dot_tag(rec.box_number, Di, Dj), math.hypot(gx - ix, gy - iy), "dot"
    if rec.type in ("digit", "letter"):
        want = "let" if rec.type == "letter" else "num"
        best = None
        for (kind, slot, place), (px, py) in _fiducial_ideals_cache().items():
            if kind != want:
                continue
            d = math.hypot(lx - px, ly - py)
            if best is None or d < best[1]:
                best = ((kind, slot, place), d)
        (kind, slot, place), d = best
        return fiducial_tag(rec.box_number, kind, slot, place), d, kind
    if rec.type == "dash":
        r = dash_tag_for(gx, gy)
        if r is None:
            return None
        tag, ix, iy = r
        return tag, math.hypot(gx - ix, gy - iy), "dash"
    return None


def assign_tags(point_table, cutoff_frac=0.5):
    """Tag dashes/glyphs by nearest ideal, one-to-one (nearest wins on collision),
    within cutoff_frac × that grid's spacing. DOTS are already tagged exactly by
    `process` via robust_dot_indices (lattice-snapped, box-anchored) — those tags
    are reserved as-is here so nothing else can collide with them. Sets rec.tag
    (or None). Returns (n_tagged, n_points)."""
    used = set()
    for rec in point_table.points:                  # reserve exact dot tags
        if rec.type == "dot" and rec.tag:
            used.add(rec.tag)
    cands = []
    for i, rec in enumerate(point_table.points):
        if rec.type == "dot":
            continue                                # dots handled in process
        rec.tag = None
        r = tag_point(rec)
        if r is None:
            continue
        tag, resid, grid = r
        if resid <= cutoff_frac * SPACING[grid]:
            cands.append((resid, i, tag))
    cands.sort()
    for resid, i, tag in cands:                     # nearest point wins each tag
        if tag in used:
            continue
        used.add(tag); point_table.points[i].tag = tag
    n = sum(1 for p in point_table.points if p.tag)
    return n, len(point_table.points)


def to_dict():
    return {"box_um": BOX_UM, "dot_pitch": DOT_PITCH, "dot_phase": DOT_PHASE,
            "digit_half": DIGIT_HALF, "dash_start": DASH_START, "dash_spacing": DASH_SPACING,
            "dashes_per_edge": DASHES_PER_EDGE, "fiducials_um": FIDUCIALS_UM}
