"""The printed grid: rigid islands and the rectangles they are made of.

Ported from exm_sim.load_features. Every printed feature is one island with a
centre (design um, y up); an island is one or more axis-aligned rectangles
given as offsets from the island centre (design um, y up) and half sizes.
"""

import json
import os
from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def reference_dir():
    """Folder with reference_tags.json / spec_sheet.json. Override with
    EXM_REF_DIR; defaults to ../reference next to this package."""
    return os.environ.get("EXM_REF_DIR", os.path.join(os.path.dirname(HERE), "reference"))


@dataclass(frozen=True)
class Grid:
    xy: np.ndarray          # (N, 2) island centres, design um
    cat: np.ndarray         # (N,) 'dot' | 'dash' | 'aruco'
    tag: np.ndarray         # (N,) tag string from reference_tags.json
    aruco_id: np.ndarray    # (N,) aruco id or -1
    rect_isl: np.ndarray    # (M,) island index of each rectangle
    rect_off: np.ndarray    # (M, 2) offset from island centre, design um
    rect_half: np.ndarray   # (M, 2) half sizes (x, y), design um
    rect_kind: np.ndarray   # (M,) 0 dot, 1 dash H, 2 dash V, 3 tag module
    dot_pitch_um: float
    node_pitch_um: float

    @property
    def n(self):
        return len(self.xy)

    @property
    def tags(self):
        """Indices of the ArUco islands."""
        return np.nonzero(self.cat == "aruco")[0]


RECT_KINDS = ("dot", "dash_h", "dash_v", "tag_module")


@lru_cache(maxsize=4)
def load_grid(path=None):
    path = path or os.path.join(reference_dir(), "reference_tags.json")
    with open(path) as fh:
        ref = json.load(fh)
    recs = ref["records"]
    dside = ref["dot_side_um"] / 2
    cfg = ref["config"]
    dash_l, dash_w = cfg["dash_len_um"] / 2, cfg["dash_width_um"] / 2
    aruco = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)

    isl_xy, isl_cat, isl_tag, isl_id = [], [], [], []
    rect_isl, rect_off, rect_half, rect_kind = [], [], [], []
    for r in recs:
        k = len(isl_xy)
        isl_xy.append((r["x_um"], r["y_um"]))
        isl_cat.append(r["category"])
        isl_tag.append(r["tag"])
        cat = r["category"]
        if cat == "dot":
            isl_id.append(-1)
            rect_isl.append(k); rect_off.append((0.0, 0.0)); rect_half.append((dside, dside))
            rect_kind.append(0)
        elif cat == "dash":
            isl_id.append(-1)
            horiz = r["meta"]["line"].startswith("H")
            rect_isl.append(k); rect_off.append((0.0, 0.0))
            rect_half.append((dash_l, dash_w) if horiz else (dash_w, dash_l))
            rect_kind.append(1 if horiz else 2)
        else:  # aruco: 6x6 modules incl. border; black module = printed
            m = r["meta"]
            isl_id.append(m["aruco_id"])
            size = m["size_um"]
            nmod = 6
            mod = size / nmod
            bits = cv2.aruco.generateImageMarker(aruco, m["aruco_id"], nmod)
            for row in range(nmod):          # row 0 = top of the marker
                for col in range(nmod):
                    if bits[row, col] == 0:  # black = printed
                        dx = -size / 2 + (col + 0.5) * mod
                        dy = size / 2 - (row + 0.5) * mod   # design y-up
                        rect_isl.append(k); rect_off.append((dx, dy))
                        rect_half.append((mod / 2, mod / 2))
                        rect_kind.append(3)
    return Grid(xy=np.array(isl_xy), cat=np.array(isl_cat), tag=np.array(isl_tag),
                aruco_id=np.array(isl_id), rect_isl=np.array(rect_isl),
                rect_off=np.array(rect_off), rect_half=np.array(rect_half),
                rect_kind=np.array(rect_kind), dot_pitch_um=float(ref["dot_pitch"]),
                node_pitch_um=float(ref["box_um"]))


@lru_cache(maxsize=1)
def load_spec(path=None):
    path = path or os.path.join(reference_dir(), "spec_sheet.json")
    with open(path) as fh:
        return json.load(fh)
