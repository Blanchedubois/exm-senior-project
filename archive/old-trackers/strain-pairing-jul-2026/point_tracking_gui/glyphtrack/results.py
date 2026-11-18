"""
glyphtrack.results
=================
Stage 3 consolidation: turn the solved grid model into a clean, exportable result
— one number per box, the A/B/C/D letters, and every fill dot tagged to its box +
local position. Display/export only; all recognition lives in Stages 1-2.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import os
import csv
import numpy as np

from . import lattice as lt
from . import gridmodel as gm


@dataclass
class DotTag:
    x: float; y: float
    box_i: int; box_j: int
    box_number: object          # int or None (outside the 5x5)
    fx: float; fy: float        # local position inside the box, [0,1]


@dataclass
class DashTag:
    x: float; y: float
    box_i: int; box_j: int
    edge: str                   # 'u0'|'u1'|'v0'|'v1' — which box boundary it sits on
    box_number: object          # int or None


@dataclass
class BoxResult:
    box_i: int; box_j: int
    col: int; row: int; number: int
    letters: dict               # design letter per fit letter-slot
    cx: float; cy: float        # box centre (image px)


@dataclass
class GridResult:
    registered: bool
    boxes: list = field(default_factory=list)
    dots: list = field(default_factory=list)
    dashes: list = field(default_factory=list)
    labels: list = field(default_factory=list)   # per-slot completed state labels
    summary: str = ""

    def write_csv(self, out_dir):
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "boxes.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["box_i", "box_j", "col", "row", "number", "center_x", "center_y"])
            for b in sorted(self.boxes, key=lambda b: b.number):
                w.writerow([b.box_i, b.box_j, b.col, b.row, b.number,
                            round(b.cx, 1), round(b.cy, 1)])
        with open(os.path.join(out_dir, "glyphs.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["x_px", "y_px", "text", "state", "kind"])
            for L in self.labels:
                w.writerow([round(L["x"], 1), round(L["y"], 1), L["text"], L["state"], L["kind"]])
        with open(os.path.join(out_dir, "dots.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["dot_id", "x_px", "y_px", "box_i", "box_j", "box_number",
                        "local_fx", "local_fy"])
            for i, d in enumerate(self.dots):
                w.writerow([i, round(d.x, 1), round(d.y, 1), d.box_i, d.box_j,
                            "" if d.box_number is None else d.box_number,
                            round(d.fx, 3), round(d.fy, 3)])
        with open(os.path.join(out_dir, "dashes.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["dash_id", "x_px", "y_px", "box_i", "box_j", "edge", "box_number"])
            for i, d in enumerate(self.dashes):
                w.writerow([i, round(d.x, 1), round(d.y, 1), d.box_i, d.box_j, d.edge,
                            "" if d.box_number is None else d.box_number])
        return out_dir


def tag_dots(dots, fit, reg):
    """Tag every fill dot with its box (i,j), box number N, and local (fx,fy)."""
    if dots is None or len(dots) == 0:
        return []
    Minv = np.linalg.inv(np.column_stack([fit["U"], fit["V"]]))
    out = []
    for d in np.asarray(dots, float):
        bc = (d - fit["O"]) @ Minv.T
        bi, bj = int(np.floor(bc[0])), int(np.floor(bc[1]))
        N = gm.box_number((bi, bj), reg)
        out.append(DotTag(float(d[0]), float(d[1]), bi, bj, N,
                          float(bc[0] - bi), float(bc[1] - bj)))
    return out


def tag_dashes(dashes, fit, reg=None):
    """Tag each boundary dash with the box it borders, which edge ('u0/u1/v0/v1'),
    and (if registered) that box's number."""
    if dashes is None or len(dashes) == 0:
        return []
    Minv = np.linalg.inv(np.column_stack([fit["U"], fit["V"]]))
    out = []
    for d in np.asarray(dashes, float):
        bc = (d - fit["O"]) @ Minv.T
        bi, bj = int(np.floor(bc[0])), int(np.floor(bc[1]))
        fx, fy = bc[0] - bi, bc[1] - bj
        if min(fx, 1 - fx) <= min(fy, 1 - fy):          # nearer a u-boundary
            edge = "u0" if fx < 0.5 else "u1"
        else:
            edge = "v0" if fy < 0.5 else "v1"
        N = gm.box_number((bi, bj), reg) if reg else None
        out.append(DashTag(float(d[0]), float(d[1]), bi, bj, edge, N))
    return out


def finalize(model, fit, dots, dashes=None):
    """Build a GridResult from the solved model + fit + detected dots + dashes."""
    if not model.get("registered"):
        return GridResult(registered=False, labels=model.get("labels", []),
                          dashes=tag_dashes(dashes, fit, None),
                          summary="not registered — " + model.get("reason", ""))
    reg = model["reg"]
    lmap = gm._letter_ideals(reg)                     # fit-slot -> design letter
    boxes = []
    for nd, N in model["node_num"].items():
        if N is None:
            continue
        col, row, _ = gm.box_colrow(nd, reg)
        c = lt.fslot_point(fit, nd[0], nd[1], (75, 75))
        boxes.append(BoxResult(nd[0], nd[1], col, row, N, dict(lmap),
                               float(c[0]), float(c[1])))
    dtags = tag_dots(dots, fit, reg)
    dashtags = tag_dashes(dashes, fit, reg)
    tagged = sum(1 for d in dtags if d.box_number is not None)
    summary = (f"{len(boxes)} boxes solved · numbers "
               f"{sorted(b.number for b in boxes)} · "
               f"{tagged}/{len(dtags)} dots tagged · {len(dashtags)} dashes tagged")
    return GridResult(True, boxes, dtags, dashtags, model["labels"], summary)
