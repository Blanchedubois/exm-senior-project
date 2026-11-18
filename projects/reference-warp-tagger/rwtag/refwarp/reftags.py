"""
refwarp.reftags
===============
Build (and load) the CANONICAL REFERENCE TAG MAP from the Nanoscribe STL.

Every printed feature is detected in a clean top-down render of the STL, classified
(intersection dot / dash / interior dot / glyph), and given a unique, grid-relative
tag plus its exact design position in micrometres. The result is a pure-data file
(`reference/reference_tags.json`) that downstream warping/tagging consumes — no STL
needed at runtime.

Tag schemes (design frame, y-up, box N = col*5+row+1 column-major):
  node|{i}_{j}                 intersection dot at (150 i, 150 j),      i,j 0..5
  dash|V{i}|{m}                dash on vertical line x=150 i,  m=10*span+k (span 0..4, k 0..9)
  dash|H{j}|{m}                dash on horizontal line y=150 j
  dot|B{N}|{di}_{dj}           interior lattice dot, (di,dj) box-relative lattice index
  num|B{N}|{slot}|{k}          number digit, slot in the 5 number slots, k = left..right index
  let|B{N}|{slot}              orientation letter, slot in {A,B,C,D}
"""
from __future__ import annotations
import json
import os
import numpy as np
import cv2

from rwtag.glyph import stl_glyphs as sg

# ---- design constants (measured from the STL; see docs) ----
BOX_UM = 150.0
GRID_N = 5                       # 5x5 boxes
LINE_N = GRID_N + 1              # 6 grid lines per axis
DOT_PITCH = 8.0
DOT_PHASE = 5.0                  # interior dots at DOT_PHASE + 8k
DASH_START = 12.0
DASH_SPACING = 14.0
DASHES_PER_EDGE = 10
NODE_TOL = 3.0                   # um: a dot within this of a grid crossing is an intersection dot

NUMBER_SLOTS = ["corner00", "corner02", "corner20", "corner22", "center"]
LETTER_SLOTS = ["A", "B", "C", "D"]

# project root = reference-warp-tagger/ (this file is rwtag/refwarp/reftags.py)
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_STL = os.path.join(_ROOT, "Markers CAD", "base_design_for_nanoscribe_2026_01_14.stl")
DEFAULT_JSON = os.path.join(_ROOT, "reference", "reference_tags.json")


# ------------------------------------------------------------------ helpers
def box_number(col, row):
    return col * GRID_N + row + 1


def _slot_of(rx, ry):
    """Box-local (rx,ry) um (y-up) -> ('num', cornerXX|center) or ('let', A|B|C|D)."""
    t = BOX_UM / 3.0
    cx = 0 if rx < t else (1 if rx < 2 * t else 2)
    cy = 0 if ry < t else (1 if ry < 2 * t else 2)
    if (cx, cy) == (1, 1):
        return ("num", "center")
    if (cx, cy) == (1, 2):
        return ("let", "D")
    if (cx, cy) == (1, 0):
        return ("let", "B")
    if (cx, cy) == (0, 1):
        return ("let", "A")
    if (cx, cy) == (2, 1):
        return ("let", "C")
    return ("num", f"corner{cx}{cy}")


def _components_um(stl_path, ppu=10.0):
    """Detect every raised feature; return per-component (x_um, y_um, area_um2, w_um,
    h_um, extent, bbox_px, label_id) and the label image + to_um."""
    img, to_px, to_um, meta = sg.render_topdown(stl_path, px_per_um=ppu)
    nc, lab, stats, cent = cv2.connectedComponentsWithStats(img, 8)
    out = []
    for i in range(1, nc):
        a = stats[i, cv2.CC_STAT_AREA]
        w = stats[i, cv2.CC_STAT_WIDTH]; h = stats[i, cv2.CC_STAT_HEIGHT]
        x, y = to_um(cent[i, 0], cent[i, 1])
        out.append(dict(id=i, x=float(x), y=float(y), area=a / (ppu * ppu),
                        w=w / ppu, h=h / ppu, ext=a / max(w * h, 1),
                        bbox=(int(stats[i, cv2.CC_STAT_LEFT]), int(stats[i, cv2.CC_STAT_TOP]), int(w), int(h)),
                        cxpx=float(cent[i, 0]), cypx=float(cent[i, 1])))
    return out, lab, img, to_um


def _classify(comps):
    """Split components into dots / dashes / glyphs by size & solidity."""
    dots, dashes, glyphs = [], [], []
    for c in comps:
        if c["h"] > 15 and c["ext"] < 0.72 and c["area"] > 15:
            glyphs.append(c)
        elif 8 <= c["area"] < 70 and c["ext"] > 0.6:
            dashes.append(c)
        elif c["area"] < 10 and c["ext"] > 0.45:
            dots.append(c)
    return dots, dashes, glyphs


# ------------------------------------------------------------------ build
def build(stl_path=DEFAULT_STL, ppu=10.0):
    """Return (records, stats) — records = [{tag, category, x_um, y_um, meta}]."""
    comps, lab, img, to_um = _components_um(stl_path, ppu)
    dots, dashes, glyphs = _classify(comps)
    grid = np.arange(LINE_N) * BOX_UM                    # 0,150,...,750
    recs = []

    # (1) DOTS -> intersection nodes or box-interior lattice dots
    n_node = n_interior = 0
    for c in dots:
        i = int(round(c["x"] / BOX_UM)); j = int(round(c["y"] / BOX_UM))
        on_node = (0 <= i < LINE_N and 0 <= j < LINE_N
                   and abs(c["x"] - grid[i]) < NODE_TOL and abs(c["y"] - grid[j]) < NODE_TOL)
        if on_node:
            recs.append(dict(tag=f"node|{i}_{j}", category="node", x_um=c["x"], y_um=c["y"], meta={}))
            n_node += 1
        else:
            col = min(GRID_N - 1, max(0, int(c["x"] // BOX_UM)))
            row = min(GRID_N - 1, max(0, int(c["y"] // BOX_UM)))
            N = box_number(col, row)
            # lattice index within this box (relative to the box's first node)
            di0 = int(np.ceil((col * BOX_UM - DOT_PHASE) / DOT_PITCH))
            dj0 = int(np.ceil((row * BOX_UM - DOT_PHASE) / DOT_PITCH))
            Di = int(round((c["x"] - DOT_PHASE) / DOT_PITCH))
            Dj = int(round((c["y"] - DOT_PHASE) / DOT_PITCH))
            di, dj = Di - di0, Dj - dj0
            recs.append(dict(tag=f"dot|B{N}|{di}_{dj}", category="dot", x_um=c["x"], y_um=c["y"],
                             meta={"box": N, "di": di, "dj": dj}))
            n_interior += 1

    # (2) DASHES -> grid-line + ordinal
    n_dash = 0
    for c in dashes:
        vert = c["h"] >= c["w"]                           # tall bar -> on a vertical line
        if vert:
            i = int(round(c["x"] / BOX_UM)); axis, line, along, fixed = "V", i, c["y"], grid[i] if 0 <= i < LINE_N else None
        else:
            j = int(round(c["y"] / BOX_UM)); axis, line, along, fixed = "H", j, c["x"], grid[j] if 0 <= j < LINE_N else None
        if fixed is None or abs((c["x"] if vert else c["y"]) - fixed) > 8.0:
            continue                                     # not cleanly on a line
        span = int(along // BOX_UM); local = along - span * BOX_UM
        k = int(round((local - DASH_START) / DASH_SPACING))
        if not (0 <= span < GRID_N and 0 <= k < DASHES_PER_EDGE):
            continue
        m = span * DASHES_PER_EDGE + k
        recs.append(dict(tag=f"dash|{axis}{line}|{m}", category="dash", x_um=c["x"], y_um=c["y"],
                         meta={"axis": axis, "line": line, "m": m}))
        n_dash += 1

    # (3) GLYPHS -> box + slot (+ digit index for numbers). Value known from box number.
    n_num = n_let = 0
    gc = np.array([[g["cxpx"], g["cypx"]] for g in glyphs])
    glyph_h_px = np.median([g["bbox"][3] for g in glyphs]) if glyphs else 30.0
    groups = sg._cluster(gc, eps=glyph_h_px * 0.9) if len(gc) else []
    for grp in groups:
        members = [glyphs[k] for k in grp]
        cx = np.mean([m["x"] for m in members]); cy = np.mean([m["y"] for m in members])
        col = min(GRID_N - 1, max(0, int(cx // BOX_UM)))
        row = min(GRID_N - 1, max(0, int(cy // BOX_UM)))
        N = box_number(col, row)
        rx, ry = cx - col * BOX_UM, cy - row * BOX_UM
        kind, slot = _slot_of(rx, ry)
        if kind == "let":
            big = max(members, key=lambda m: m["area"])   # letter is one blob
            recs.append(dict(tag=f"let|B{N}|{slot}", category="letter", x_um=big["x"], y_um=big["y"],
                             meta={"box": N, "slot": slot, "value": slot}))
            n_let += 1
        else:
            digits = list(str(N))
            members = sorted(members, key=lambda m: m["x"])      # left -> right
            if len(members) != len(digits):
                continue                                          # ambiguous split -> skip
            for k, (mem, ch) in enumerate(zip(members, digits)):
                recs.append(dict(tag=f"num|B{N}|{slot}|{k}", category="number",
                                 x_um=mem["x"], y_um=mem["y"],
                                 meta={"box": N, "slot": slot, "idx": k, "value": ch}))
                n_num += 1

    stats = dict(node=n_node, dash=n_dash, interior_dot=n_interior, number=n_num, letter=n_let,
                 total=len(recs), n_components=len(comps))
    return recs, stats


def save(recs, path=DEFAULT_JSON):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"box_um": BOX_UM, "grid_n": GRID_N, "dot_pitch": DOT_PITCH,
                   "dot_phase": DOT_PHASE, "records": recs}, f)
    return path


def load(path=DEFAULT_JSON):
    with open(path) as f:
        return json.load(f)


if __name__ == "__main__":
    recs, stats = build()
    tags = [r["tag"] for r in recs]
    assert len(tags) == len(set(tags)), "DUPLICATE TAGS!"
    print("counts:", stats)
    print("unique tags:", len(set(tags)), "duplicates:", len(tags) - len(set(tags)))
    from collections import Counter
    print("by category:", Counter(r["category"] for r in recs))
    p = save(recs)
    print("wrote", p)
