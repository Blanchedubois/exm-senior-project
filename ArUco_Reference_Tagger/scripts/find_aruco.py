#!/usr/bin/env python3
"""
find_aruco.py — Phase 1 command-line entry point.

    python scripts/find_aruco.py IMAGE [--design FOLDER] [--um-per-px 0.51]
                                 [--psf 2.5] [--edge-band-um 48] [--no-invert]
                                 [--dict DICT_4X4_50] [--out DIR]

Decodes every ArUco tag in one image (16-bit TIFF or any 8-bit image), prints
one line per tag and one for the frame, and writes <image>_tags.csv (every
field of the per-tag record) and <image>_tags.png (the frame with each tag's
quad, id, corner order and rotation drawn). With --design it also reports which
decoded ids are not in the design and which design nodes were not seen, and
fits the design -> image affine (expansion factor from the tag centres).
"""
from __future__ import annotations
import argparse
import csv
import os
import sys

import numpy as np
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from rwtag import io                                                     # noqa: E402
from rwtag.aruco import ArucoParams, Design, decode_tags, frame_pose, fit_affine   # noqa: E402

_COLOR = {"clean": (60, 230, 90), "corrected": (255, 190, 0),
          "ambiguous": (255, 60, 60), "duplicate": (255, 0, 255)}


def draw(u8, tags, pose, path):
    vis = cv2.cvtColor(u8, cv2.COLOR_GRAY2BGR)
    for t in tags.values():
        col = _COLOR[t.decode_class]
        if t.in_edge_band:
            col = (0, 160, 255)
        c = np.round(t.corners_px).astype(int)
        cv2.polylines(vis, [c.reshape(-1, 1, 2)], True, col[::-1], 2)
        cv2.circle(vis, tuple(c[0]), 5, (255, 255, 255), -1)                # TL marked
        cv2.arrowedLine(vis, tuple(c[0]), tuple(c[1]), col[::-1], 2, tipLength=0.25)
        cx, cy = np.round(t.centre_px).astype(int)
        cv2.putText(vis, f"{t.aruco_id} {t.rot_deg:+.1f}", (cx + 8, cy - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, col[::-1], 2, cv2.LINE_AA)
    cv2.putText(vis, pose.summary(), (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (255, 255, 255), 2, cv2.LINE_AA)
    cv2.imwrite(path, vis)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--design", help="design folder (reference_tags.json [+ spec_sheet.json])")
    ap.add_argument("--um-per-px", type=float, default=0.510)
    ap.add_argument("--psf", type=float, default=2.5)
    ap.add_argument("--edge-band-um", type=float, default=48.0)
    ap.add_argument("--no-invert", action="store_true", help="image is already dark-on-light")
    ap.add_argument("--dict", default="DICT_4X4_50")
    ap.add_argument("--out", default=None, help="output folder (default: beside the image)")
    a = ap.parse_args(argv)

    img = io.load_tiff(a.image)
    u8 = io.to_uint8_robust(img)           # never saturates the tags (see rwtag.io)
    params = ArucoParams(um_per_px=a.um_per_px, psf_fwhm_um=a.psf, edge_band_um=a.edge_band_um,
                         invert=not a.no_invert)
    design = Design.load_folder(a.design) if a.design else None
    dict_name = design.dict_name if design else a.dict
    tags, info = decode_tags(u8, params, dict_name, tag_um=design.tag_um if design else None)
    A = finfo = None
    if design is not None:
        A, finfo = fit_affine(design, tags)
    pose = frame_pose(tags, design, affine_sign=(finfo["sign"] if A is not None and finfo.get("sign_source") == "affine" else None))

    print(f"{os.path.basename(a.image)}  {u8.shape[1]}x{u8.shape[0]} px  "
          f"raw {info['n_raw']} · usable {info['n_usable']} · edge-band {info['n_edge_band']} · "
          f"ambiguous {info['n_ambiguous']} · dupes {info['dupes']}")
    for i in sorted(tags):
        t = tags[i]
        flag = ("" if t.usable else "  [" + ", ".join(f for f, on in (("edge", t.in_edge_band),
                 ("dup", t.duplicate), ("ambiguous", t.margin_bits <= 1)) if on) + "]")
        print(f"  id {i:>3}  ({t.centre_px[0]:8.2f}, {t.centre_px[1]:8.2f})  rot {t.rot_deg:+7.2f} deg  "
              f"side {t.side_px:6.2f} px  bits corr {t.n_bits_corrected} margin {t.margin_bits} mirror {t.mirror_dist}  "
              f"border err {t.border_errors}  contrast {t.contrast:5.1f}{flag}")
    print("  frame: " + pose.summary())
    if design is not None:
        if A is not None:
            lam = finfo["scale_px_per_um"] * a.um_per_px
            print(f"  design -> image: {finfo['method']} · {finfo['n_matched']} tags · "
                  f"centre rms {finfo['centre_rms_px']:.2f} px · {finfo['scale_px_per_um']:.4f} px/um "
                  f"-> expansion {lam:.4f}x at {a.um_per_px} um/px · rot {finfo['rot_deg']:+.2f} deg")
        else:
            print("  design -> image: no usable tag in the design")
        if pose.missing_nodes:
            print(f"  design nodes not seen: {len(pose.missing_nodes)}")

    out = a.out or os.path.dirname(os.path.abspath(a.image))
    os.makedirs(out, exist_ok=True)
    base = os.path.join(out, os.path.splitext(os.path.basename(a.image))[0].replace(".ome", ""))
    rows = [t.as_row() for _i, t in sorted(tags.items())]
    if design is not None:
        n = design.id_to_node()
        for r in rows:
            ij = n.get(r["aruco_id"])
            r["in_design"] = ij is not None
            r["node_i"], r["node_j"] = (ij if ij else ("", ""))
    with open(base + "_tags.csv", "w", newline="") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
        else:
            f.write("aruco_id\n")
    draw(u8, tags, pose, base + "_tags.png")
    print(f"  wrote {base}_tags.csv  {base}_tags.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
