#!/usr/bin/env python3
"""
generate_pattern.py
===================
Generate a fiducial pattern for mapping the local warpage of an expanding
hydrogel under a microscope.

Architecture
------------
The field is tiled into a grid of BOXES. At every box CORNER (grid node)
sits a 6x6 ArUco marker whose ID encodes the node's absolute (i, j)
coordinate -> the coarse ADDRESS tier ("which box am I in?").
Each box INTERIOR is filled with a fine measurement pattern -- a dense DOT
GRID (default) or a checkerboard -- whose feature positions are the dense
MEASUREMENT tier ("how is the gel distorting here?").
An optional DASHED BOUNDARY outlines every box.

Because correspondence is solved by the ArUco IDs (globally unique, error
corrected), the pattern is trackable through 2-5x expansion with only a
before/after image -- no time-lapse required. Each marker decodes from its
OWN local pixels, so it keeps working no matter how far apart the markers
move as the gel expands (see notes in the accompanying design doc).

Outputs
-------
  <out>_full.png       high-res, black-on-white, OpenCV-detectable master
  <out>_preview.png    annotated preview (node IDs, one box highlighted, scale bar)
  <out>_box_zoom.png   zoom of a single box
  <out>_metadata.json  GROUND-TRUTH: config, node IDs+coords, per-box feature
                       (dot / corner) coordinates = undeformed reference

All geometry is in microns; `px_per_um` only sets raster resolution.

Requires: opencv-contrib-python, numpy, matplotlib
"""

from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
import cv2
import cv2.aruco as aruco


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
@dataclass
class PatternConfig:
    # --- grid layout ---
    n_boxes_x: int = 4
    n_boxes_y: int = 4
    box_size_um: float = 30.0            # node-to-node spacing (undeformed)

    # --- ArUco address tier ---
    aruco_dict: str = "DICT_6X6_1000"    # 6x6 dictionary, up to 1000 IDs
    marker_um: float = 5.0
    marker_border_bits: int = 1

    # --- interior measurement tier ---
    interior_style: str = "dots"         # "dots" | "checker"
    dot_pitch_um: float = 1.5            # fine dot spacing (distortion sampling)
    dot_diameter_um: float = 0.7
    checker_pitch_um: float = 3.0        # used only if interior_style == "checker"
    quiet_um: float = 2.0                # blank gap between corner marker and interior

    # --- dashed box boundary ---
    draw_box_boundary: bool = True
    boundary_dash_um: float = 1.2
    boundary_gap_um: float = 1.0
    boundary_thickness_um: float = 0.3

    # --- rasterization ---
    px_per_um: float = 20.0
    margin_um: float = 6.0

    # --- misc ---
    invert: bool = False
    highlight_box: tuple = (1, 1)
    store_full_features: bool = True

    def node_id(self, i: int, j: int) -> int:
        return j * (self.n_boxes_x + 1) + i


ARUCO_DICTS = {name: getattr(aruco, name) for name in dir(aruco) if name.startswith("DICT_")}


# ----------------------------------------------------------------------
# ArUco helpers (version-tolerant)
# ----------------------------------------------------------------------
def get_dictionary(name: str):
    if name not in ARUCO_DICTS:
        raise ValueError(f"Unknown ArUco dictionary '{name}'.")
    key = ARUCO_DICTS[name]
    try:
        return aruco.getPredefinedDictionary(key)
    except AttributeError:
        return aruco.Dictionary_get(key)


def draw_marker(dictionary, marker_id, side_px, border_bits):
    try:
        return aruco.generateImageMarker(dictionary, marker_id, side_px, borderBits=border_bits)
    except AttributeError:
        return aruco.drawMarker(dictionary, marker_id, side_px, borderBits=border_bits)


def make_detector(dictionary):
    try:
        detector = aruco.ArucoDetector(dictionary, aruco.DetectorParameters())
        return lambda img: detector.detectMarkers(img)[:2]
    except AttributeError:
        params = aruco.DetectorParameters_create()
        return lambda img: aruco.detectMarkers(img, dictionary, parameters=params)[:2]


# ----------------------------------------------------------------------
# Drawing utilities
# ----------------------------------------------------------------------
def dashed_segment(img, x0, y0, x1, y1, dash_px, gap_px, thick, color=0):
    """Axis-aligned dashed segment."""
    length = np.hypot(x1 - x0, y1 - y0)
    if length <= 0:
        return
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    step = dash_px + gap_px
    d = 0.0
    while d < length:
        ax, ay = x0 + ux * d, y0 + uy * d
        e = min(d + dash_px, length)
        bx, by = x0 + ux * e, y0 + uy * e
        cv2.line(img, (int(round(ax)), int(round(ay))),
                 (int(round(bx)), int(round(by))), color, thick, cv2.LINE_AA)
        d += step


# ----------------------------------------------------------------------
# Core generator
# ----------------------------------------------------------------------
def generate(cfg: PatternConfig):
    dictionary = get_dictionary(cfg.aruco_dict)
    ppu = cfg.px_per_um
    um2px = lambda v: int(round(v * ppu))

    n_nodes_x, n_nodes_y = cfg.n_boxes_x + 1, cfg.n_boxes_y + 1
    node_xy = lambda i, j: (cfg.margin_um + i * cfg.box_size_um,
                            cfg.margin_um + j * cfg.box_size_um)

    width_um  = 2 * cfg.margin_um + cfg.n_boxes_x * cfg.box_size_um
    height_um = 2 * cfg.margin_um + cfg.n_boxes_y * cfg.box_size_um
    W, H = um2px(width_um), um2px(height_um)
    img = np.full((H, W), 255, np.uint8)

    marker_px = um2px(cfg.marker_um)
    inset_um  = cfg.marker_um / 2.0 + cfg.quiet_um

    # ---- dashed box boundary (node lattice grid lines, with gaps at nodes) ----
    if cfg.draw_box_boundary:
        off = cfg.marker_um / 2.0 + cfg.boundary_gap_um
        thick = max(1, um2px(cfg.boundary_thickness_um))
        dash_px, gap_px = cfg.boundary_dash_um * ppu, cfg.boundary_gap_um * ppu
        # horizontal edges
        for j in range(n_nodes_y):
            _, y_um = node_xy(0, j)
            for bi in range(cfg.n_boxes_x):
                xa, _ = node_xy(bi, j)
                xb, _ = node_xy(bi + 1, j)
                dashed_segment(img, (xa + off) * ppu, y_um * ppu,
                               (xb - off) * ppu, y_um * ppu, dash_px, gap_px, thick)
        # vertical edges
        for i in range(n_nodes_x):
            x_um, _ = node_xy(i, 0)
            for bj in range(cfg.n_boxes_y):
                _, ya = node_xy(i, bj)
                _, yb = node_xy(i, bj + 1)
                dashed_segment(img, x_um * ppu, (ya + off) * ppu,
                               x_um * ppu, (yb - off) * ppu, dash_px, gap_px, thick)

    # ---- interior measurement pattern per box ----
    boxes = []
    for bj in range(cfg.n_boxes_y):
        for bi in range(cfg.n_boxes_x):
            x0_um, y0_um = node_xy(bi, bj)
            x1_um, y1_um = node_xy(bi + 1, bj + 1)
            cx0, cy0 = x0_um + inset_um, y0_um + inset_um
            avail = (x1_um - inset_um) - cx0

            feats = []
            if cfg.interior_style == "dots":
                ndx = int(avail // cfg.dot_pitch_um) + 1
                block = (ndx - 1) * cfg.dot_pitch_um
                ox = cx0 + (avail - block) / 2.0
                oy = cy0 + (avail - block) / 2.0
                r = max(1, um2px(cfg.dot_diameter_um / 2.0))
                for cj in range(ndx):
                    for ci in range(ndx):
                        fx_um = ox + ci * cfg.dot_pitch_um
                        fy_um = oy + cj * cfg.dot_pitch_um
                        cv2.circle(img, (um2px(fx_um), um2px(fy_um)), r, 0, -1, cv2.LINE_AA)
                        if cfg.store_full_features:
                            feats.append({"i": ci, "j": cj,
                                          "x_um": round(fx_um, 4), "y_um": round(fy_um, 4)})
                nfx = ndx
                pitch = cfg.dot_pitch_um
            else:  # checker
                sq = um2px(cfg.checker_pitch_um)
                nsx = int(avail // cfg.checker_pitch_um)
                block = nsx * cfg.checker_pitch_um
                ox = cx0 + (avail - block) / 2.0
                oy = cy0 + (avail - block) / 2.0
                for a in range(nsx):
                    for b in range(nsx):
                        if (a + b) % 2 == 0:
                            x, y = um2px(ox + a * cfg.checker_pitch_um), um2px(oy + b * cfg.checker_pitch_um)
                            img[y:y + sq, x:x + sq] = 0
                if cfg.store_full_features:
                    for cj in range(1, nsx):
                        for ci in range(1, nsx):
                            feats.append({"i": ci, "j": cj,
                                          "x_um": round(ox + ci * cfg.checker_pitch_um, 4),
                                          "y_um": round(oy + cj * cfg.checker_pitch_um, 4)})
                nfx = nsx
                pitch = cfg.checker_pitch_um

            boxes.append({
                "box_i": bi, "box_j": bj,
                "corner_node_ids": {"tl": cfg.node_id(bi, bj), "tr": cfg.node_id(bi + 1, bj),
                                    "bl": cfg.node_id(bi, bj + 1), "br": cfg.node_id(bi + 1, bj + 1)},
                "interior_style": cfg.interior_style,
                "feature_pitch_um": pitch,
                "n_features_per_row": nfx,
                "n_features": len(feats),
                "features": feats,
            })

    # ---- ArUco markers at every node ----
    nodes = []
    for j in range(n_nodes_y):
        for i in range(n_nodes_x):
            mid = cfg.node_id(i, j)
            m = draw_marker(dictionary, mid, marker_px, cfg.marker_border_bits)
            xc_um, yc_um = node_xy(i, j)
            x0, y0 = um2px(xc_um) - marker_px // 2, um2px(yc_um) - marker_px // 2
            img[y0:y0 + marker_px, x0:x0 + marker_px] = m
            nodes.append({"id": mid, "i": i, "j": j,
                          "x_um": round(xc_um, 4), "y_um": round(yc_um, 4)})

    if cfg.invert:
        img = 255 - img

    meta = {
        "config": asdict(cfg),
        "field_size_um": [round(width_um, 3), round(height_um, 3)],
        "image_size_px": [W, H],
        "n_nodes": len(nodes), "n_boxes": len(boxes),
        "nodes": nodes, "boxes": boxes,
        "notes": ("ArUco ID = node_j*(n_boxes_x+1)+node_i. A box is addressed by its "
                  "four corner node IDs. Interior feature coords are the UNDEFORMED "
                  "ground truth; match expanded features by (box, i, j) and subtract to "
                  "get the displacement field. Each marker decodes from its own local "
                  "pixels, so growing gaps between markers do not affect decoding."),
    }
    return img, meta


# ----------------------------------------------------------------------
# Previews & validation
# ----------------------------------------------------------------------
def save_preview(img, meta, cfg, path):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    Wum, Hum = meta["field_size_um"]
    fig, ax = plt.subplots(figsize=(9, 9), dpi=130)
    ax.imshow(img, cmap="gray", vmin=0, vmax=255, extent=[0, Wum, Hum, 0])
    for nd in meta["nodes"]:
        ax.text(nd["x_um"], nd["y_um"], str(nd["id"]), color="#e0342b",
                fontsize=6, ha="center", va="center", fontweight="bold")
    hi, hj = cfg.highlight_box
    if hi < cfg.n_boxes_x and hj < cfg.n_boxes_y:
        x0 = cfg.margin_um + hi * cfg.box_size_um
        y0 = cfg.margin_um + hj * cfg.box_size_um
        ax.add_patch(Rectangle((x0, y0), cfg.box_size_um, cfg.box_size_um,
                               fill=False, edgecolor="#1f9d55", lw=2))
        ax.text(x0 + cfg.box_size_um / 2, y0 - 1.2, f"box ({hi},{hj})",
                color="#1f9d55", fontsize=9, ha="center", va="bottom", fontweight="bold")
    ax.plot([2, 12], [Hum - 2] * 2, "-", color="#1166cc", lw=3)
    ax.text(7, Hum - 3, "10 um", color="#1166cc", fontsize=8, ha="center", va="bottom")
    ax.set_title(f"Coded boxes (6x6 ArUco at corners) + fine {cfg.interior_style} + dashed boundary",
                 fontsize=11)
    ax.set_xlabel("microns"); ax.set_ylabel("microns")
    fig.tight_layout(); fig.savefig(path); plt.close(fig)


def save_box_zoom(img, meta, cfg, path, box=(1, 1)):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ppu = cfg.px_per_um
    bi, bj = box
    x0 = int((cfg.margin_um + bi * cfg.box_size_um - cfg.marker_um) * ppu)
    y0 = int((cfg.margin_um + bj * cfg.box_size_um - cfg.marker_um) * ppu)
    s = int((cfg.box_size_um + 2 * cfg.marker_um) * ppu)
    crop = img[max(0, y0):y0 + s, max(0, x0):x0 + s]
    fig, ax = plt.subplots(figsize=(6, 6), dpi=130)
    ax.imshow(crop, cmap="gray", vmin=0, vmax=255)
    ax.set_title(f"Single box ({bi},{bj}) — 4 corner ArUco IDs, fine dot grid, dashed edge",
                 fontsize=10)
    ax.axis("off"); fig.tight_layout(); fig.savefig(path); plt.close(fig)


def validate(img, cfg):
    detect = make_detector(get_dictionary(cfg.aruco_dict))
    corners, ids = detect(img)
    n_expected = (cfg.n_boxes_x + 1) * (cfg.n_boxes_y + 1)
    n_found = 0 if ids is None else len(ids)
    return {"expected": n_expected, "detected": n_found, "all_found": n_found == n_expected}


def main(out_prefix="pattern", cfg: Optional[PatternConfig] = None):
    cfg = cfg or PatternConfig()
    img, meta = generate(cfg)
    cv2.imwrite(f"{out_prefix}_full.png", img)
    with open(f"{out_prefix}_metadata.json", "w") as f:
        json.dump(meta, f, indent=2)
    save_preview(img, meta, cfg, f"{out_prefix}_preview.png")
    save_box_zoom(img, meta, cfg, f"{out_prefix}_box_zoom.png", box=cfg.highlight_box)
    v = validate(img, cfg)
    b0 = meta["boxes"][0]
    print(f"Field        : {meta['field_size_um'][0]:.1f} x {meta['field_size_um'][1]:.1f} um")
    print(f"Image        : {meta['image_size_px'][0]} x {meta['image_size_px'][1]} px ({cfg.px_per_um:.0f} px/um)")
    print(f"Boxes        : {cfg.n_boxes_x} x {cfg.n_boxes_y} (box = {cfg.box_size_um} um)")
    print(f"ArUco        : {cfg.aruco_dict}, marker = {cfg.marker_um} um, {meta['n_nodes']} markers")
    print(f"Interior     : {cfg.interior_style}, pitch = {b0['feature_pitch_um']} um, "
          f"{b0['n_features_per_row']}/row, {b0['n_features']} features/box")
    print(f"Boundary     : {'dashed' if cfg.draw_box_boundary else 'none'}")
    print(f"Validation   : detected {v['detected']}/{v['expected']} markers "
          f"-> {'ALL OK' if v['all_found'] else 'MISSING SOME'}")
    return img, meta, v


if __name__ == "__main__":
    main()
