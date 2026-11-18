"""
glyphtrack.reader
================
Read the glyphs once the box grid is known: detect glyph blobs, classify them
with the STL-trained model, use the fiducial-lattice fit to keep only interior
glyphs (dropping boundary dashes), and return their positions + characters +
confidence. The GUI draws these so the reads can be eyeballed.

NOTE: recognition on the REAL frames is currently limited (the classifier is
trained on STL-derived synthetic glyphs; real prints differ). Confidence is
reported so weak reads are visible; improving accuracy means training on real
crops — which this scaffold now makes collectable.
"""
from __future__ import annotations
import numpy as np
import cv2

from . import lattice as lt
from . import classifier as cl


def detect_glyph_blobs(gray, clahe_clip=2.0, tophat=41, area=(150, 3000), h=(18, 58)):
    """(crops, positions) of glyph-sized blobs — the candidates to classify."""
    clahe = cv2.createCLAHE(clahe_clip, (16, 16)).apply(gray)
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (tophat, tophat))
    th = cv2.morphologyEx(clahe, cv2.MORPH_TOPHAT, se)
    _, b = cv2.threshold(th, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    b = cv2.morphologyEx(b, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, L, st, ct = cv2.connectedComponentsWithStats(b, 8)
    crops, pos = [], []
    for i in range(1, n):
        a = st[i, cv2.CC_STAT_AREA]; w = st[i, cv2.CC_STAT_WIDTH]; hh = st[i, cv2.CC_STAT_HEIGHT]
        if not (area[0] <= a <= area[1] and h[0] <= hh <= h[1]):
            continue
        x, y = st[i, cv2.CC_STAT_LEFT], st[i, cv2.CC_STAT_TOP]
        pad = int(0.2 * max(w, hh))
        y0, y1 = max(0, y - pad), min(gray.shape[0], y + hh + pad)
        x0, x1 = max(0, x - pad), min(gray.shape[1], x + w + pad)
        g = clahe[y0:y1, x0:x1].copy(); g[L[y0:y1, x0:x1] != i] = 0
        crops.append(g); pos.append(ct[i])
    return crops, np.asarray(pos, float)


def _window_blobs(win, glyph_h):
    """Glyph-sized blobs inside a small slot window (dots are too short to pass,
    so they're excluded). Returns [(local centroid, masked crop), ...]."""
    clahe = cv2.createCLAHE(2.0, (8, 8)).apply(win)
    _, b = cv2.threshold(clahe, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    n, L, st, ct = cv2.connectedComponentsWithStats(b, 8)
    out = []
    for i in range(1, n):
        h = st[i, cv2.CC_STAT_HEIGHT]; w = st[i, cv2.CC_STAT_WIDTH]; a = st[i, cv2.CC_STAT_AREA]
        if h < 0.5 * glyph_h or h > 1.7 * glyph_h or a < 0.12 * glyph_h * glyph_h:
            continue                                     # dots/specks (small) & merges (big)
        x, y = st[i, cv2.CC_STAT_LEFT], st[i, cv2.CC_STAT_TOP]
        pad = int(0.2 * max(w, h))
        y0, y1 = max(0, y - pad), min(win.shape[0], y + h + pad)
        x0, x1 = max(0, x - pad), min(win.shape[1], x + w + pad)
        g = clahe[y0:y1, x0:x1].copy(); g[L[y0:y1, x0:x1] != i] = 0
        out.append((ct[i], g))
    return out


def read_slots(gray, clf, fit, slot_tol=0.14):
    """OCR only glyphs that actually sit AT a fiducial slot. Uses the good global
    blob detection, then keeps a blob only if it is within `slot_tol` (box
    fractions) of a slot centre — so dashes/strays that aren't on a slot are never
    classified — and classifies restricted to that slot's role. Returns per-glyph
    reads (box, slot, char, conf, kind)."""
    crops, pos = detect_glyph_blobs(gray)
    if len(crops) == 0:
        return []
    Minv = np.linalg.inv(np.column_stack([fit["U"], fit["V"]]))
    reads = []
    for k in range(len(crops)):
        bc = (pos[k] - fit["O"]) @ Minv.T
        bi, bj = int(np.floor(bc[0])), int(np.floor(bc[1]))
        fx, fy = bc[0] - bi, bc[1] - bj
        slot = _nearest_slot(fx, fy)
        sfx, sfy = lt.SLOT_FRACS[slot]
        if np.hypot(fx - sfx, fy - sfy) > slot_tol:      # not on a slot -> ignore
            continue
        letter = slot in lt.LETTER_SLOTS
        ch, conf = clf.predict_restricted(crops[k], LETTERS if letter else DIGITS)
        reads.append({"x": float(pos[k][0]), "y": float(pos[k][1]), "char": ch,
                      "conf": float(conf), "kind": "letter" if letter else "digit",
                      "interior": True, "box": (bi, bj), "slot": slot})
    return reads


def estimate_deskew(gray, clf, crop=1400):
    """Best deskew angle (deg) to make the glyphs upright. The dot lattice gives
    the tilt mod 90°; the four axis-aligned quadrants are then scored by mean
    glyph-recognition confidence on a centre crop (the upright one wins clearly)."""
    pts = lt.detect_dots(gray)
    if len(pts) < 50:
        return 0.0
    a = lt.estimate_basis(pts)["angle_deg"]
    h, w = gray.shape
    r = crop // 2
    sub = gray[max(0, h // 2 - r):h // 2 + r, max(0, w // 2 - r):w // 2 + r]
    best_deg, best_conf = 0.0, -1.0
    for deg in [-a + 90 * k for k in range(4)]:
        M = cv2.getRotationMatrix2D((sub.shape[1] / 2, sub.shape[0] / 2), deg, 1.0)
        rr = cv2.warpAffine(sub, M, (sub.shape[1], sub.shape[0]), flags=cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_REPLICATE)
        crops, _ = detect_glyph_blobs(rr)
        if not crops:
            continue
        preds = clf.predict_batch(crops)
        confs = [c for lab, c in preds if cl.is_glyph(lab)]
        conf = float(np.mean(confs)) if confs else 0.0
        if conf > best_conf:
            best_conf, best_deg = conf, deg
    return float((best_deg + 180) % 360 - 180)          # normalise to (-180, 180]


_SLOT_NAMES = list(lt.SLOT_FRACS.keys())
_SLOT_XY = np.array([lt.SLOT_FRACS[s] for s in _SLOT_NAMES])
DIGITS = list("0123456789")
LETTERS = list("ABCD")


def _nearest_slot(fx, fy):
    return _SLOT_NAMES[int(np.argmin(np.hypot(_SLOT_XY[:, 0] - fx, _SLOT_XY[:, 1] - fy)))]


def _slot_role(fx, fy):
    """Nearest fiducial slot to a fractional box position -> ('letter'|'digit',
    allowed labels)."""
    d = np.hypot(_SLOT_XY[:, 0] - fx, _SLOT_XY[:, 1] - fy)
    slot = _SLOT_NAMES[int(np.argmin(d))]
    return ("letter", LETTERS) if slot in lt.LETTER_SLOTS else ("digit", DIGITS)


def read_glyphs(gray, clf, grid, conf_min=0.6, interior=(0.09, 0.91)):
    """Detect glyph blobs, fit the fiducial lattice to the confident ones, then
    re-classify each interior glyph RESTRICTED to its slot's role (letters at edge
    slots, digits at corner/centre slots). Dashes sit on the box boundary and are
    dropped. Returns (records, fit); each record: x, y, char, conf, kind, interior."""
    crops, pos = detect_glyph_blobs(gray)
    if len(crops) == 0:
        return [], None
    preds = clf.predict_batch(crops)                     # pass 1: unrestricted, for the fit
    keep = np.array([cl.is_glyph(p) and c >= conf_min for p, c in preds])
    if keep.sum() < 8:
        return [], None
    fit = lt.fit_fiducial_lattice(pos[keep], grid)
    Minv = np.linalg.inv(np.column_stack([fit["U"], fit["V"]]))
    recs = []
    for i in range(len(crops)):                          # pass 2: slot-restricted
        bc = (pos[i] - fit["O"]) @ Minv.T
        box_i, box_j = int(np.floor(bc[0])), int(np.floor(bc[1]))
        fx, fy = bc[0] - box_i, bc[1] - box_j
        inside = (interior[0] < fx < interior[1]) and (interior[0] < fy < interior[1])
        if not inside:
            continue
        d = np.hypot(_SLOT_XY[:, 0] - fx, _SLOT_XY[:, 1] - fy)
        slot = _SLOT_NAMES[int(np.argmin(d))]
        kind = "letter" if slot in lt.LETTER_SLOTS else "digit"
        allowed = LETTERS if kind == "letter" else DIGITS
        ch, conf = clf.predict_restricted(crops[i], allowed)
        recs.append({"x": float(pos[i][0]), "y": float(pos[i][1]), "char": ch,
                     "conf": float(conf), "kind": kind, "interior": True,
                     "box": (box_i, box_j), "slot": slot, "fx": float(fx), "fy": float(fy)})
    return recs, fit
