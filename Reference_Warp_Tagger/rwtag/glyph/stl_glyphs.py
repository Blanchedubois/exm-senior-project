"""
glyphtrack.stl_glyphs
=====================
Turn the reference Nanoscribe STL into an AUTO-LABELLED glyph set.

The design is a 5x5 grid of 25 boxes (numbered 1..25, bottom-to-top then
left-to-right). Each box carries its number at the 4 corners + centre and the
letters A/B/C/D at the left/bottom/right/top edge midpoints. Because that content
is fully known, every glyph blob in a clean top-down render of the STL can be
labelled by *where* it sits — giving a labelled training set with no hand work.

Headless: numpy + OpenCV only.
"""
from __future__ import annotations
import struct
import numpy as np
import cv2

BOXES = 5                       # 5 x 5 grid
BOX_UM = 150.0                  # each box is 150 um (750 um / 5)
GRID_UM = BOXES * BOX_UM


# ----------------------------------------------------------------- STL parsing
def load_stl_triangles(path: str) -> np.ndarray:
    """Return (N,3,3) triangle vertices from a binary STL."""
    data = open(path, "rb").read()
    n = struct.unpack("<I", data[80:84])[0]
    rec = np.frombuffer(data[84:84 + n * 50], dtype=np.uint8).reshape(n, 50)
    f = rec[:, :48].copy().view("<f4").reshape(n, 12)
    normals = f[:, 0:3]
    verts = f[:, 3:12].reshape(n, 3, 3)
    return verts, normals


def render_topdown(path: str, px_per_um: float = 3.0, pad_px: int = 12):
    """Rasterise a clean BINARY top-down footprint of the raised features.
    Returns (image uint8, to_px(X_um,Y_um)->(px,py), bounds)."""
    verts, normals = load_stl_triangles(path)
    xy = verts[:, :, :2]
    mn = xy.reshape(-1, 2).min(0)
    mx = xy.reshape(-1, 2).max(0)
    W = int((mx[0] - mn[0]) * px_per_um) + 2 * pad_px
    H = int((mx[1] - mn[1]) * px_per_um) + 2 * pad_px
    img = np.zeros((H, W), np.uint8)
    top = normals[:, 2] > 0.3                    # up-facing = the printed top surface
    for tri in verts[top]:
        px = ((tri[:, 0] - mn[0]) * px_per_um + pad_px).astype(np.int32)
        py = (H - pad_px - (tri[:, 1] - mn[1]) * px_per_um).astype(np.int32)
        cv2.fillConvexPoly(img, np.stack([px, py], 1), 255)

    def to_px(x_um, y_um):
        return ((x_um - mn[0]) * px_per_um + pad_px,
                H - pad_px - (y_um - mn[1]) * px_per_um)

    def to_um(px, py):
        return ((px - pad_px) / px_per_um + mn[0],
                (H - pad_px - py) / px_per_um + mn[1])

    return img, to_px, to_um, (mn, mx, px_per_um, pad_px, W, H)


# ------------------------------------------------------- labelled glyph mining
def _slot_of(rx, ry):
    """Box-relative (rx,ry) in [0,BOX_UM], y-up -> a fiducial slot.
    Returns ('num', corner-id) or ('letter', 'A'|'B'|'C'|'D')."""
    t = BOX_UM / 3.0
    cx = 0 if rx < t else (1 if rx < 2 * t else 2)      # 0=left,1=mid,2=right
    cy = 0 if ry < t else (1 if ry < 2 * t else 2)      # 0=bottom,1=mid,2=top
    if (cx, cy) == (1, 1):
        return ("num", "center")
    if cx == 1 and cy == 2:
        return ("letter", "D")                          # top
    if cx == 1 and cy == 0:
        return ("letter", "B")                          # bottom
    if cx == 0 and cy == 1:
        return ("letter", "A")                          # left
    if cx == 2 and cy == 1:
        return ("letter", "C")                          # right
    return ("num", f"corner{cx}{cy}")                   # a corner -> number


def _cluster(centroids, eps):
    """Union-find proximity clustering: blobs within eps px join one group."""
    n = len(centroids)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a

    for i in range(n):
        for j in range(i + 1, n):
            if np.hypot(*(centroids[i] - centroids[j])) < eps:
                parent[find(i)] = find(j)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _glyph_components(stats, n, px_per_um):
    """Indices of glyph blobs. Glyphs are TALL and OPEN (fill ~0.45 of bbox);
    boundary dashes are short SOLID bars (fill ~1.0) and dots are tiny — both
    are rejected by a height + fill(extent) filter (scaled to px_per_um)."""
    s = px_per_um / 3.0                          # thresholds calibrated at 3 px/um
    keep = []
    for i in range(1, n):
        a = stats[i, cv2.CC_STAT_AREA]
        w = stats[i, cv2.CC_STAT_WIDTH]
        h = stats[i, cv2.CC_STAT_HEIGHT]
        ext = a / max(w * h, 1)
        if (350 * s * s) <= a <= (2500 * s * s) and (28 * s) <= h <= (95 * s) and ext < 0.75:
            keep.append(i)
    return keep


def extract_labeled_glyphs(stl_path: str, px_per_um: float = 3.0, crop=28):
    """Return {label: [uint8 crop, ...]} for labels '0'..'9','A'..'D',
    auto-mined from the STL. `crop` = square side of each normalised glyph."""
    img, to_px, to_um, meta = render_topdown(stl_path, px_per_um)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(img, 8)
    keep = _glyph_components(stats, n, px_per_um)
    cents = np.array([cent[i] for i in keep])
    boxes = {i: (int(stats[i, cv2.CC_STAT_LEFT]), int(stats[i, cv2.CC_STAT_TOP]),
                 int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT]))
             for i in keep}

    # group blobs that belong to one token (a 2-digit number = 2 close blobs)
    glyph_h = np.median([boxes[i][3] for i in keep])
    groups = _cluster(cents, eps=glyph_h * 0.9)

    out = {c: [] for c in list("0123456789ABCD")}
    for g in groups:
        members = [keep[k] for k in g]
        gc = cents[g].mean(0)
        x_um, y_um = to_um(*gc)
        col = min(BOXES - 1, max(0, int(x_um // BOX_UM)))
        row = min(BOXES - 1, max(0, int(y_um // BOX_UM)))
        rx, ry = x_um - col * BOX_UM, y_um - row * BOX_UM
        kind, slot = _slot_of(rx, ry)
        box_num = col * BOXES + row + 1
        if kind == "letter":
            labels = [slot]
            members = [members[int(np.argmax([stats[m, cv2.CC_STAT_AREA] for m in members]))]]
        else:                                            # number: split into digits by x
            digits = list(str(box_num))
            members = sorted(members, key=lambda m: cent[m][0])   # left-to-right
            if len(members) != len(digits):              # merged/extra blob -> skip ambiguous
                continue
            labels = digits
        for m, ch in zip(members, labels):
            x, y, w, h = boxes[m]
            pad = int(0.22 * max(w, h))
            y0, y1 = max(0, y - pad), min(img.shape[0], y + h + pad)
            x0, x1 = max(0, x - pad), min(img.shape[1], x + w + pad)
            g_img = img[y0:y1, x0:x1].copy()
            g_img[lab[y0:y1, x0:x1] != m] = 0             # mask out neighbouring glyphs
            if g_img.size:
                out[ch].append(cv2.resize(g_img, (crop, crop), interpolation=cv2.INTER_AREA))
    return {k: v for k, v in out.items() if v}


def extract_negatives(stl_path: str, px_per_um: float = 3.0, crop=28, cap=400):
    """Mine NON-glyph templates from the STL for reject classes:
    'dash' (solid boundary bars) and 'dot' (fill lattice). These train the
    classifier to actively reject the two structures that surround the glyphs."""
    img, to_px, to_um, meta = render_topdown(stl_path, px_per_um)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(img, 8)
    s = px_per_um / 3.0
    dashes, dots = [], []
    for i in range(1, n):
        a = stats[i, cv2.CC_STAT_AREA]; w = stats[i, cv2.CC_STAT_WIDTH]
        h = stats[i, cv2.CC_STAT_HEIGHT]; ext = a / max(w * h, 1)
        if (150 * s * s) <= a <= (450 * s * s) and ext > 0.80:          # solid bar = dash
            bucket = dashes
        elif a <= (60 * s * s) and max(w, h) <= (16 * s):              # tiny = dot
            bucket = dots
        else:
            continue
        if len(bucket) >= cap:
            continue
        x, y = stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP]
        pad = int(0.3 * max(w, h))
        y0, y1 = max(0, y - pad), min(img.shape[0], y + h + pad)
        x0, x1 = max(0, x - pad), min(img.shape[1], x + w + pad)
        g = img[y0:y1, x0:x1].copy(); g[lab[y0:y1, x0:x1] != i] = 0
        if g.size:
            bucket.append(cv2.resize(g, (crop, crop), interpolation=cv2.INTER_AREA))
    return {"dash": dashes, "dot": dots}


def label_montage(labeled: dict, per=12, crop=28):
    """Contact sheet: one row per class, up to `per` examples — for eyeballing."""
    rows = []
    for ch in sorted(labeled):
        exs = labeled[ch][:per]
        strip = [np.full((crop, crop), 40, np.uint8)]        # label gutter
        cv2.putText(strip[0], ch, (6, crop - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.8, 255, 2)
        strip += exs + [np.zeros((crop, crop), np.uint8)] * (per - len(exs))
        rows.append(np.hstack(strip))
    return np.vstack(rows)
