#!/usr/bin/env python3
"""
generate_conjoined_marker.py  (Deliverable 2)
=============================================
Generate individual CONJOINED ArUco markers (smooth struts bridging diagonal
pinches -> one rigid piece) as PNG and SVG.

Reads the curated ID list (conjoined_marker_ids.json); if absent it is built.
Each requested ID is emitted as:
    markers/aruco_<id>.png    raster (detector-ready)
    markers/aruco_<id>.svg    vector (microns; for Nanoscribe / lithography)
and the PNG is verified to decode back to <id>.

Config at the bottom: which IDs, tag size (um), strut width (um), resolution.
"""
from __future__ import annotations
import os, json
import cv2
from conjoined_lib import (marker_primitives, render_png, render_svg,
                           decodes, scan_conjoinable, n_components, module_map)


def build_marker(marker_id, size_um=6.0, strut_w_um=0.20, px_per_um=40.0,
                 pad_um=None, out_dir="markers"):
    os.makedirs(out_dir, exist_ok=True)
    pad = size_um * 0.35 if pad_um is None else pad_um     # white quiet border
    W = H = size_um + 2 * pad
    cx = cy = W / 2.0
    prims = marker_primitives(marker_id, cx, cy, size_um, strut_w_um=strut_w_um)

    png = render_png(prims, W, H, px_per_um)
    svg = render_svg(prims, W, H)
    png_path = os.path.join(out_dir, f"aruco_{marker_id}.png")
    svg_path = os.path.join(out_dir, f"aruco_{marker_id}.svg")
    cv2.imwrite(png_path, png)
    with open(svg_path, "w") as f:
        f.write(svg)

    ok = decodes(png, marker_id)
    n4, n8 = n_components(module_map(marker_id), 4), n_components(module_map(marker_id), 8)
    return {"id": marker_id, "png": png_path, "svg": svg_path,
            "decodes": ok, "pieces_edge": n4, "strutted": n4 > 1, "conjoinable": n8 == 1}


def load_ids():
    path = "conjoined_marker_ids.json"
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(scan_conjoinable(1000), f, indent=1)
    return json.load(open(path))["conjoinable_ids"]


def main(ids=None, size_um=6.0, strut_w_um=0.20, px_per_um=40.0, count=8):
    pool = load_ids()
    if ids is None:
        ids = pool[:count]
    else:
        bad = [i for i in ids if i not in pool]
        if bad:
            print(f"WARNING: {bad} are not in the conjoinable pool; struts may not fully join them.")
    print(f"Generating {len(ids)} conjoined markers "
          f"(tag {size_um} um, strut {strut_w_um} um, {px_per_um:.0f} px/um):")
    all_ok = True
    for i in ids:
        r = build_marker(i, size_um, strut_w_um, px_per_um)
        all_ok &= r["decodes"]
        print(f"  ID {i:<4} pieces={r['pieces_edge']} strutted={r['strutted']!s:<5} "
              f"decodes={r['decodes']!s:<5} -> {r['png']}, {r['svg']}")
    print(f"\nAll decoded: {all_ok}. Output in ./markers/")


if __name__ == "__main__":
    # EDIT HERE: specify IDs or a count from the curated pool
    main(ids=None, size_um=6.0, strut_w_um=0.20, px_per_um=40.0, count=8)
