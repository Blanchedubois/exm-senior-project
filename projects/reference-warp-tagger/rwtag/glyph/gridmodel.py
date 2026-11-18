"""
glyphtrack.gridmodel
===================
Grid inference & auto-complete. Turns per-glyph reads into a coherent 5x5 grid:
club digits into box numbers, vote each box from its 5 redundant copies, register
the whole grid (orientation from letters, integer offset from confident boxes via
the numbering rule N = col*5 + row + 1), then auto-complete every slot from what
the grid MUST say.

Policies (locked in): distance-threshold digit clubbing; conflicts flagged (read
kept); missing slots filled + marked predicted; per-glyph labels by state.
Headless: numpy only.
"""
from __future__ import annotations
from collections import Counter, defaultdict
import numpy as np

from . import lattice as lt

_SLOTS = list(lt.SLOT_FRACS.keys())
_SLOT_XY = np.array([lt.SLOT_FRACS[s] for s in _SLOTS])
NUMBER_SLOTS = lt.NUMBER_SLOTS
LETTER_SLOTS = list(lt.LETTER_SLOTS)


def _nearest_slot(fx, fy):
    return _SLOTS[int(np.argmin(np.hypot(_SLOT_XY[:, 0] - fx, _SLOT_XY[:, 1] - fy)))]


def _box_center(fit, i, j):
    return fit["O"] + (i + 0.5) * fit["U"] + (j + 0.5) * fit["V"]


# ------------------------------------------------------------ A. digit clubbing
def _dot_between(pa, pb, dots, band):
    """True if any dot lies on the segment between pa and pb (excluding the ends)."""
    if dots is None or len(dots) == 0:
        return False
    seg = pb - pa
    L2 = float(seg @ seg)
    if L2 < 1.0:
        return False
    t = (dots - pa) @ seg / L2
    proj = pa + np.outer(t, seg)
    perp = np.hypot(*(dots - proj).T)
    return bool(((t > 0.25) & (t < 0.75) & (perp < band)).any())


def club_digits(digits, box_pitch, thresh_frac=0.35, dots=None):
    """Club adjacent digits into number tokens (tens..units, left->right after
    deskew). Two digits join if they are within thresh_frac*box_pitch AND have NO
    fill dot between them — so the two digits of one number club, but digits of
    different numbers (always separated by the dot field) do not."""
    n = len(digits)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    thr = thresh_frac * box_pitch
    band = 0.7 * box_pitch / lt.BOX_PER_DOT              # ~ one dot pitch
    xy = np.array([[d["x"], d["y"]] for d in digits]) if n else np.zeros((0, 2))
    for i in range(n):
        for j in range(i + 1, n):
            if np.hypot(*(xy[i] - xy[j])) < thr and not _dot_between(xy[i], xy[j], dots, band):
                parent[find(i)] = find(j)
    groups = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)

    tokens = []
    for members in groups.values():
        ms = sorted((digits[k] for k in members), key=lambda d: d["x"])   # tens..units
        s = "".join(m["char"] for m in ms)
        try:
            value = int(s)
        except ValueError:
            value = None
        cx = float(np.mean([m["x"] for m in ms])); cy = float(np.mean([m["y"] for m in ms]))
        box = Counter(m["box"] for m in ms).most_common(1)[0][0]
        slot = Counter(m["slot"] for m in ms).most_common(1)[0][0]
        tokens.append({"value": value, "digits": ms, "x": cx, "y": cy, "box": box,
                       "slot": slot, "conf": float(np.mean([m["conf"] for m in ms]))})
    return tokens


# ------------------------------------------------------------ B. per-box vote
def vote_boxes(tokens):
    """Vote each box's number from its number-slot tokens (weighted by conf)."""
    by_box = defaultdict(list)
    for t in tokens:
        if t["value"] is not None and 1 <= t["value"] <= 25 and t["slot"] in NUMBER_SLOTS:
            by_box[t["box"]].append(t)
    boxes = {}
    for box, ts in by_box.items():
        w = defaultdict(float)
        for t in ts:
            w[t["value"]] += max(t["conf"], 0.1)
        best = max(w, key=w.get)
        agree = w[best] / sum(w.values())
        boxes[box] = {"number": best, "agree": float(agree), "n": len(ts)}
    return boxes


# ------------------------------------------------------------ C. registration
# a box node maps to design (col,row) via one of these 8 orientations, then
# N = col*5 + row + 1. The numbering rule (up = +1, down = -1, right column = +5)
# is enforced by scoring each orientation for consistency across confident boxes.
_ORIENTS = [(ca, cs, ra, rs) for ca in (0, 1) for ra in (0, 1) if ca != ra
            for cs in (-1, 1) for rs in (-1, 1)]


def _colrow(node, orient):
    ca, cs, ra, rs = orient
    return cs * node[ca], rs * node[ra]                  # before offset


def _letter_char(L, orient, fit):
    """The design letter implied by a detected letter's position under `orient`."""
    Minv = np.linalg.inv(np.column_stack([fit["U"], fit["V"]]))
    du, dv = Minv @ (np.array([L["x"], L["y"]]) - _box_center(fit, *L["box"]))
    ca, cs, ra, rs = orient
    colc = cs * (du if ca == 0 else dv)
    rowc = rs * (du if ra == 0 else dv)
    if abs(colc) >= abs(rowc):
        return "C" if colc > 0 else "A"
    return "D" if rowc > 0 else "B"


def _letter_score(letters, orient, fit, weight=1.0):
    return sum(weight for L in letters if _letter_char(L, orient, fit) == L["char"])


def register(boxes, letters, fit, min_anchors=2, manual_numbers=None, manual_letters=None):
    """Choose the orientation + integer offset that best fits the NUMBERING ORDER
    (N = col*5 + row + 1) across confident boxes — so the vertical +1 / horizontal
    +5 rule drives the result — with letters (and any manual anchors) as extra
    evidence. Returns dict(registered, orient, offset, n_anchors[, reason])."""
    anchors = [(node, info["number"], 1.0) for node, info in boxes.items()
               if info["agree"] >= 0.6]
    if manual_numbers:
        anchors += [(tuple(node), int(N), 6.0) for node, N in manual_numbers]   # trusted
    letters = list(letters or [])
    manual_letters = list(manual_letters or [])

    best = None
    for orient in _ORIENTS:
        by_off = defaultdict(lambda: [0.0, set()])       # offset -> [weight, {nodes}]
        for node, N, wt in anchors:
            dcol, drow = (N - 1) // 5, (N - 1) % 5
            c, r = _colrow(node, orient)
            off = (dcol - c, drow - r)
            by_off[off][0] += wt
            by_off[off][1].add(node)
        ls = _letter_score(letters, orient, fit) + \
            _letter_score(manual_letters, orient, fit, weight=6.0)
        if by_off:
            off, (w, nodes) = max(by_off.items(), key=lambda kv: kv[1][0])
            ndist = len(nodes)
        else:
            off, w, ndist = (0, 0), 0.0, 0
        score = w + ls
        if best is None or score > best["score"]:
            best = {"orient": orient, "offset": off, "w": w, "ndist": ndist,
                    "ls": ls, "score": score}

    if best is None or (best["ndist"] == 0 and best["ls"] == 0):
        return {"registered": False, "reason": "no anchors — identify a box",
                "n_anchors": 0}
    # need enough independent evidence: >=2 agreeing boxes, or 1 box + letters
    if not (best["ndist"] >= min_anchors or (best["ndist"] >= 1 and best["ls"] >= 1)):
        need = "another box" if best["ndist"] >= 1 else "a box"
        return {"registered": False, "n_anchors": best["ndist"],
                "reason": f"not enough to lock orientation — identify {need}"}
    return {"registered": True, "orient": best["orient"], "offset": best["offset"],
            "n_anchors": int(best["ndist"])}


def box_colrow(node, reg):
    """(col, row, N) for a box node, or (col, row, None) if outside the 5x5."""
    c, r = _colrow(node, reg["orient"])
    col, row = c + reg["offset"][0], r + reg["offset"][1]
    N = col * 5 + row + 1 if (0 <= col <= 4 and 0 <= row <= 4) else None
    return col, row, N


def box_number(node, reg):
    """Design number N (or None if the node falls outside the 5x5) for a box node."""
    return box_colrow(node, reg)[2]


# ------------------------------------------------------------ letter ideals
def _letter_ideals(reg):
    """Map each fit letter-slot -> the design letter it should hold, under the
    solved orientation."""
    ca, cs, ra, rs = reg["orient"]
    cu = np.zeros(2); cu[ca] = cs                        # +col unit in (U,V)/frac space
    ru = np.zeros(2); ru[ra] = rs                        # +row unit
    ideal_frac = {"C": np.array([0.5, 0.5]) + 0.31 * cu,
                  "A": np.array([0.5, 0.5]) - 0.31 * cu,
                  "D": np.array([0.5, 0.5]) + 0.31 * ru,
                  "B": np.array([0.5, 0.5]) - 0.31 * ru}
    mapping = {}
    for slot in LETTER_SLOTS:
        f = np.array(lt.SLOT_FRACS[slot])
        mapping[slot] = min(ideal_frac, key=lambda L: np.hypot(*(ideal_frac[L] - f)))
    return mapping                                       # fit-slot -> design letter


# ------------------------------------------------------------ D. auto-complete
def build_grid_model(reads, fit, thresh_frac=0.35, conf_ok=0.5, min_anchors=2, dots=None,
                     manual=None):
    """Full inference. Returns dict with per-slot display `labels`
    (x, y, text, state, kind) and a `summary`. `manual` = optional user anchors
    {'numbers': [(node, N)], 'letters': [{box, x, y, char}]}."""
    box_pitch = fit["box_pitch"]
    digits = [r for r in reads if r["kind"] == "digit"]
    letters = [r for r in reads if r["kind"] == "letter"]
    tokens = club_digits(digits, box_pitch, thresh_frac, dots=dots)
    boxes = vote_boxes(tokens)
    manual = manual or {}
    reg = register(boxes, letters, fit, min_anchors,
                   manual_numbers=manual.get("numbers"),
                   manual_letters=manual.get("letters"))

    labels = []
    if not reg["registered"]:
        # unregistered: just show the raw clubbed reads (no grid to complete against)
        for t in tokens:
            labels.append({"x": t["x"], "y": t["y"],
                           "text": str(t["value"]) if t["value"] is not None else "?",
                           "state": "raw", "kind": "digit"})
        for L in letters:
            labels.append({"x": L["x"], "y": L["y"], "text": L["char"],
                           "state": "raw", "kind": "letter"})
        return {"registered": False, "reason": reg.get("reason", ""), "labels": labels,
                "boxes": boxes, "summary": f"not registered ({reg.get('reason','')})"}

    lmap = _letter_ideals(reg)
    # which box nodes are in view -> their numbers
    nodes = set(r["box"] for r in reads)
    node_num = {nd: box_number(nd, reg) for nd in nodes}
    tok_by = {(t["box"], t["slot"]): t for t in tokens}
    let_by = {(L["box"], L["slot"]): L for L in letters}
    n_conf = n_corr = n_pred = n_confl = 0

    for nd in sorted(nodes):
        N = node_num.get(nd)
        if N is None:
            continue
        # ---- number slots (one label per clubbed number) ----
        ideal = str(N)
        for slot in NUMBER_SLOTS:
            t = tok_by.get((nd, slot))
            if t is not None and t["value"] is not None:
                tv = str(t["value"])
                partial = set(tv) <= set(ideal) and len(tv) <= len(ideal)   # e.g. "1" of "13"
                if tv == ideal and t["conf"] >= conf_ok:
                    st, txt = "confirmed", ideal; n_conf += 1
                elif tv == ideal or t["conf"] < conf_ok or partial:
                    st, txt = "corrected", ideal; n_corr += 1   # weak / one digit missed
                else:
                    st, txt = "conflict", tv; n_confl += 1      # genuine disagreement
                labels.append({"x": t["x"], "y": t["y"], "text": txt,
                               "state": st, "kind": "digit", "ideal": ideal})
            else:                                        # missing -> predict
                p = lt.fslot_point(fit, nd[0], nd[1], lt.FIDUCIALS[slot])
                labels.append({"x": float(p[0]), "y": float(p[1]), "text": ideal,
                               "state": "predicted", "kind": "digit", "ideal": ideal})
                n_pred += 1
        # ---- letter slots ----
        for slot in LETTER_SLOTS:
            ideal_L = lmap[slot]
            L = let_by.get((nd, slot))
            if L is not None:
                if L["char"] == ideal_L and L["conf"] >= conf_ok:
                    st, txt = "confirmed", L["char"]; n_conf += 1
                elif L["conf"] < conf_ok:
                    st, txt = "corrected", ideal_L; n_corr += 1
                else:
                    st, txt = "conflict", L["char"]; n_confl += 1
                labels.append({"x": L["x"], "y": L["y"], "text": txt, "state": st,
                               "kind": "letter", "ideal": ideal_L})
            else:
                p = lt.fslot_point(fit, nd[0], nd[1], lt.FIDUCIALS[slot])
                labels.append({"x": float(p[0]), "y": float(p[1]), "text": ideal_L,
                               "state": "predicted", "kind": "letter", "ideal": ideal_L})
                n_pred += 1

    solved = sum(1 for nd in nodes if node_num.get(nd) is not None)
    summary = (f"registered: {reg['n_anchors']} anchors · {solved} boxes solved · "
               f"{n_conf} confirmed, {n_corr} corrected, {n_pred} predicted, {n_confl} conflicts")
    return {"registered": True, "labels": labels, "boxes": boxes, "reg": reg,
            "node_num": node_num, "summary": summary}
