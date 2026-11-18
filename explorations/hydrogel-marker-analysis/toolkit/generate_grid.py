#!/usr/bin/env python3
"""
generate_grid.py  (Deliverable 3)
=================================
Generate the FULL pattern -- a grid of boxes with a CONJOINED ArUco tag at
every box corner (IDs from the curated pool) and a fine DOT grid inside each
box, plus a dashed per-box boundary -- and write it as BOTH:

    grid.svg           vector, microns (for Nanoscribe / direct-laser-write)
    grid.png           raster (detector-ready preview / analysis input)
    grid_metadata.json ground-truth: node ArUco IDs + coords, per-box dot coords

Geometry is computed once in microns (conjoined_lib) so PNG and SVG match.
Config in GridConfig below; all lengths in microns.
"""
from __future__ import annotations
import os, json
from dataclasses import dataclass, asdict
import cv2
from conjoined_lib import (marker_primitives, circle_primitive, dashed_rect,
                           render_png, render_svg, make_detector)


@dataclass
class GridConfig:
    n_boxes_x: int = 4
    n_boxes_y: int = 4
    box_um: float = 30.0
    margin_um: float = 6.0
    # ArUco address tier
    marker_um: float = 6.0
    strut_w_um: float = 0.20
    # dot measurement tier
    dot_pitch_um: float = 1.5
    dot_diameter_um: float = 0.7
    quiet_um: float = 2.0            # clear keep-out margin AROUND each corner marker
    dot_edge_margin_um: float = 1.6  # gap left between the dots and the dashed boundary
    # dashed box boundary
    boundary_width_um: float = 0.7
    boundary_dash_um: float = 1.6
    boundary_gap_um: float = 1.5
    # raster resolution for the PNG
    px_per_um: float = 20.0


def build(cfg: GridConfig, id_pool):
    nnx, nny = cfg.n_boxes_x + 1, cfg.n_boxes_y + 1
    need = nnx * nny
    if len(id_pool) < need:
        raise ValueError(f"need {need} conjoinable IDs, pool has {len(id_pool)}")
    node_xy = lambda i, j: (cfg.margin_um + i * cfg.box_um, cfg.margin_um + j * cfg.box_um)
    W = 2 * cfg.margin_um + cfg.n_boxes_x * cfg.box_um
    H = 2 * cfg.margin_um + cfg.n_boxes_y * cfg.box_um

    prims, dashed = [], []
    # node id map
    node_id = {}
    k = 0
    nodes_meta = []
    for j in range(nny):
        for i in range(nnx):
            aid = id_pool[k]; k += 1
            node_id[(i, j)] = aid
            x, y = node_xy(i, j)
            nodes_meta.append({"node_i": i, "node_j": j, "aruco_id": aid,
                               "x_um": round(x, 4), "y_um": round(y, 4)})

    # dashed boundary = node-lattice grid lines, with gaps at nodes
    off = cfg.marker_um / 2 + cfg.boundary_gap_um
    for j in range(nny):
        for bi in range(cfg.n_boxes_x):
            xa, y = node_xy(bi, j); xb, _ = node_xy(bi + 1, j)
            dashed.append(("dline", xa + off, y, xb - off, y,
                           cfg.boundary_width_um, cfg.boundary_dash_um, cfg.boundary_gap_um))
    for i in range(nnx):
        for bj in range(cfg.n_boxes_y):
            x, ya = node_xy(i, bj); _, yb = node_xy(i, bj + 1)
            dashed.append(("dline", x, ya + off, x, yb - off,
                           cfg.boundary_width_um, cfg.boundary_dash_um, cfg.boundary_gap_um))

    # fine dots FILL the whole box up to the dashed boundary, with a clear
    # keep-out disk around each corner marker so the ArUco tags stay recognizable
    keepout = cfg.marker_um / 2 + cfg.quiet_um
    edge = cfg.dot_edge_margin_um
    boxes_meta = []
    dot_prims = []
    rdot = cfg.dot_diameter_um / 2
    for bj in range(cfg.n_boxes_y):
        for bi in range(cfg.n_boxes_x):
            x0, y0 = node_xy(bi, bj)
            span = cfg.box_um - 2 * edge
            ndx = int(span // cfg.dot_pitch_um) + 1
            block = (ndx - 1) * cfg.dot_pitch_um
            ox = x0 + edge + (span - block) / 2
            oy = y0 + edge + (span - block) / 2
            box_corners = [node_xy(bi, bj), node_xy(bi + 1, bj),
                           node_xy(bi, bj + 1), node_xy(bi + 1, bj + 1)]
            feats = []
            for cj in range(ndx):
                for ci in range(ndx):
                    fx, fy = ox + ci * cfg.dot_pitch_um, oy + cj * cfg.dot_pitch_um
                    if any((fx - xn) ** 2 + (fy - yn) ** 2 < keepout ** 2 for xn, yn in box_corners):
                        continue                      # keep clear of the corner markers
                    dot_prims.append(circle_primitive(fx, fy, rdot))
                    feats.append({"i": ci, "j": cj, "x_um": round(fx, 4), "y_um": round(fy, 4)})
            boxes_meta.append({
                "box_i": bi, "box_j": bj,
                "corner_aruco_ids": {"tl": node_id[(bi, bj)], "tr": node_id[(bi + 1, bj)],
                                     "bl": node_id[(bi, bj + 1)], "br": node_id[(bi + 1, bj + 1)]},
                "dot_pitch_um": cfg.dot_pitch_um, "n_dots": len(feats), "dots": feats})

    # markers last (drawn on top)
    marker_prims = []
    for (i, j), aid in node_id.items():
        x, y = node_xy(i, j)
        marker_prims += marker_primitives(aid, x, y, cfg.marker_um, strut_w_um=cfg.strut_w_um)

    all_prims = dashed + dot_prims + marker_prims
    meta = {"config": asdict(cfg), "field_um": [round(W, 3), round(H, 3)],
            "n_nodes": len(nodes_meta), "n_boxes": len(boxes_meta),
            "aruco_dict": "DICT_6X6_1000",
            "nodes": nodes_meta, "boxes": boxes_meta}
    return all_prims, W, H, meta


def main(cfg: GridConfig = None, out_prefix="grid"):
    cfg = cfg or GridConfig()
    pool = json.load(open("conjoined_marker_ids.json"))["conjoinable_ids"] \
        if os.path.exists("conjoined_marker_ids.json") else None
    if pool is None:
        from conjoined_lib import scan_conjoinable
        pool = scan_conjoinable(1000)["conjoinable_ids"]

    prims, W, H, meta = build(cfg, pool)

    svg = render_svg(prims, W, H)
    with open(f"{out_prefix}.svg", "w") as f:
        f.write(svg)
    png = render_png(prims, W, H, cfg.px_per_um)
    cv2.imwrite(f"{out_prefix}.png", png)
    with open(f"{out_prefix}_metadata.json", "w") as f:
        json.dump(meta, f, indent=1)

    # verify PNG decodes all tags
    _, ids, _ = make_detector().detectMarkers(png)
    n_dec = 0 if ids is None else len(ids)
    total = meta["n_nodes"]
    print(f"Field         : {W:.1f} x {H:.1f} um  ({cfg.n_boxes_x}x{cfg.n_boxes_y} boxes)")
    print(f"Tags          : {total} conjoined ArUco (6 um, strut {cfg.strut_w_um} um)")
    print(f"Dots/box      : {meta['boxes'][0]['n_dots']}  (pitch {cfg.dot_pitch_um} um)")
    print(f"PNG decode    : {n_dec}/{total} markers")
    print(f"Outputs       : {out_prefix}.svg, {out_prefix}.png, {out_prefix}_metadata.json")


if __name__ == "__main__":
    main()
