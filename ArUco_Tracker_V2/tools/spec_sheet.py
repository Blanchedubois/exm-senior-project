#!/usr/bin/env python3
"""
spec_sheet.py — the machine-readable spec sheet of a design (spacing workshop, S1).

Format: designs/docs/02_SPEC_SHEET_FORMAT.md. Three rules:
  1. every number is written from the SAME objects the STL was built from
     (GridConfig, records, build info) -- nothing is typed by hand;
  2. micrometres are the truth; *_px values are derived and carry the um_per_px
     they assumed;
  3. verify_against_stl() re-reads the written files and checks them against a
     render of the written STL, so a sheet that disagrees with its print cannot
     pass the gate.

    write(out_dir, name, cfg, recs, info)      -> spec_sheet.json, features.csv[, boxes.csv]
    verify_against_stl(spec, features, stl)    -> (ok, checks)
"""
from __future__ import annotations
import csv
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "Reference_Warp_Tagger")))

NOTES = {
    "frame": "Design frame: origin at the bottom-left corner of the print, x right, y UP. "
             "Images are y-DOWN, so design -> image is a REFLECTION: any fit between the two "
             "must allow det = -1 (or flip y first) and should assert the sign it finds.",
    "polarity": "Printed material = the tag's BLACK modules. In fluorescence the print is "
                "BRIGHT on dark, so invert the image before cv2.aruco. No CLAHE.",
    "corner_order": "cv2.aruco corner order TL,TR,BR,BL corresponds to design "
                    "(x-s,y+s),(x+s,y+s),(x+s,y-s),(x-s,y-s) with s = tag size / 2.",
    "rigid": "Every printed feature is a rigid island: it keeps its PRINTED size at every "
             "expansion; only the spacing between features grows.",
    "registration": "Affine through decoded tag CENTRES (>= 3 tags), similarity (2 tags), or "
                    "one tag's corners for rotation + dot-lattice pitch for scale (1 tag). "
                    "Never fit across tags through their corners: they do not follow the expansion.",
    "exposure": "Signal falls as lambda^-1.84: exposure must rise as lambda^2 "
                "(never below the reference exposure).",
    "px": "Every *_px value assumes optics_assumed.um_per_px and no expansion unless stated.",
}


def _position_words(col, row, n):
    h = "left" if col == 0 else "right" if col == n - 1 else f"column {col + 1} from the left"
    v = "top" if row == n - 1 else "bottom" if row == 0 else f"row {n - row} from the top"
    return f"{v}-{h}" if (col in (0, n - 1) and row in (0, n - 1)) else f"{v}, {h}"


def _expected(dot, pitch, psf, umpp):
    return {"dot_pitch_px": pitch / umpp, "dot_fwhm_px": math.hypot(dot, psf) / umpp,
            "dot_side_px": dot / umpp}


def build_spec(name, cfg, recs, info, um_per_px=0.510, revision="spacing-workshop", files=None,
               gate=None, labels=None, measured=None):
    from rwtag.aruco import ArucoParams
    n = cfg.grid_n
    idmap = {(i, j): v for i, j, v in cfg.ids}
    tags = [r for r in recs if r["category"] == "aruco"]
    dashes = [r for r in recs if r["category"] == "dash"]
    dots = [r for r in recs if r["category"] == "dot"]
    psf = cfg.psf_max_um() if cfg.dot_pitch_override_um > 0 else cfg.psf_fwhm_um
    prm = ArucoParams(um_per_px=um_per_px, psf_fwhm_um=psf)
    spec = {
        "name": name, "revision": revision, "units": "um",
        "generator": "tools/aruco_grid.py + tools/spec_sheet.py",
        "frame": {"origin": "bottom-left corner of the print", "x": "right", "y": "UP",
                  "design_to_image": "reflection (det = -1)"},
        "envelope": {"x": cfg.extent, "y": cfg.extent, "z": cfg.height_um},
        "grid": {"boxes": [n, n], "nodes": [n + 1, n + 1], "node_origin": cfg.origin,
                 "node_pitch": cfg.box_pitch,
                 "box_numbering": f"N = col*{n} + row + 1, column-major; col and row count from "
                                  "the bottom-left box"},
        "tags": {"dictionary": cfg.dict_name, "modules": cfg.tag_modules, "size": cfg.tag_um,
                 "module": cfg.module_um, "count": len(tags), "rigid": True,
                 "rounding": ({"neck_width": cfg.strut_w_um, "neck_length_modules": cfg.strut_len_frac,
                               "fillet_radius": cfg.fillet_um} if cfg.round_tags else None),
                 "tag_format": "aruco|N{i}_{j}|{id}",
                 "ids": [{"node": [r["meta"]["node_i"], r["meta"]["node_j"]],
                          "id": r["meta"]["aruco_id"], "x": r["x_um"], "y": r["y_um"]} for r in tags]},
        "dashes": ({"length": cfg.dash_len_um, "width": cfg.dash_width_um,
                    "per_box_edge": cfg.dashes_per_edge, "count": len(dashes),
                    "on": "grid lines x = node_origin + i*node_pitch and y = node_origin + j*node_pitch",
                    "tag_format": "dash|H{j}|{m} (horizontal line j) / dash|V{i}|{m} (vertical line i)"}
                   if cfg.dashes else None),
        "optics_assumed": {"um_per_px": um_per_px, "psf_fwhm_design": psf,
                           "psf_fwhm_max_measured": None, "separation_rule": cfg.sep_rule},
        "scaling_with_expansion": {"dot_pitch_px": "x lambda", "node_pitch_px": "x lambda",
                                   "dot_fwhm_px": "constant (rigid islands)",
                                   "tag_side_px": "constant (rigid islands)",
                                   "signal": "x lambda^-1.84 -> exposure must rise as lambda^2"},
        "detector_settings": {"class": "rwtag.aruco.ArucoParams", "clahe": False,
                              "error_correction_rate": prm.error_correction_rate,
                              "dot_area_px2": list(prm.dot_area), "noise_k": prm.noise_k,
                              "refine": prm.refine, "edge_band_um": "abs(k1) * FOV_um / 2 * 1.4",
                              "match_gate_pitch_fraction": 0.45},
        "registration": {"handedness_expected": -1},
        "files": files or {}, "gate": gate or {}, "_notes": NOTES,
    }
    if measured:                       # phase S3: what the production pipeline recognised
        spec["optics_assumed"]["psf_fwhm_max_measured"] = measured.get("psf_max_measured")
        spec["recognition_measured"] = measured
    tag_px = {"tag_side_px": cfg.tag_um / um_per_px, "tag_module_px": cfg.module_um / um_per_px,
              "node_pitch_px": cfg.box_pitch / um_per_px}
    if cfg.box_specs:
        labels = labels or {}
        boxes = []
        for b in info["boxes"]:
            c, r = b["col"], b["row"]
            boxes.append({
                "box": b["box"], "col": c, "row": r, "position": _position_words(c, r, n),
                "label": labels.get((c, r), ""),
                "corner_tag_ids": [idmap[(c, r)], idmap[(c + 1, r)], idmap[(c, r + 1)], idmap[(c + 1, r + 1)]],
                "x0": b["x0_um"], "y0": b["y0_um"], "side": cfg.box_pitch,
                "dot": b["dot_um"], "gap": b["gap_um"], "pitch": b["pitch_um"],
                "per_row": b["per_row"], "phase_in_box": b["phase_um"], "count": b["count"],
                "clearance_from_tag": b["gap_um"], "clearance_from_dash": b["gap_um"],
                "psf_fwhm_max_predicted": b["psf_max_um"],
                "tophat_px": prm.__class__(um_per_px=um_per_px, psf_fwhm_um=max(b["psf_max_um"], 1.0)
                                           ).tophat_px(b["dot_um"]),
                "expected_at_expansion_1": _expected(b["dot_um"], b["pitch_um"],
                                                     max(b["psf_max_um"], 0.0), um_per_px)})
        spec["boxes"] = boxes
        spec["dots"] = {"shape": "square", "height": cfg.height_um, "count": len(dots),
                        "per_box": "see boxes[]", "lattice": "square, axis-aligned, centred in each box",
                        "sizes": sorted({b["dot_um"] for b in info["boxes"]}),
                        "pitches": sorted({round(b["pitch_um"], 6) for b in info["boxes"]}),
                        "tag_format": "dot|B{N}|{di}_{dj}"}
        spec["expected_in_image"] = {"at_expansion_1": tag_px}
    else:
        b0 = info["boxes"][0]
        spec["dots"] = {"shape": "square", "side": cfg.dot_side_um, "height": cfg.height_um,
                        "pitch": cfg.dot_pitch_um, "pitch_nominal": round(cfg.dot_pitch_um, 2),
                        "gap": cfg.dot_pitch_um - cfg.dot_side_um,
                        "lattice": "square, axis-aligned, centred in each box",
                        "per_box_row": b0["per_row"], "phase_in_box": b0["phase_um"],
                        "clearance_from_tag": cfg.quiet_zone_um,
                        "clearance_from_dash": cfg.dot_pitch_um - cfg.dot_side_um,
                        "count": len(dots), "per_box": {str(b["box"]): b["count"] for b in info["boxes"]},
                        "psf_fwhm_max_predicted": cfg.psf_max_um(),
                        "tag_format": "dot|B{N}|{di}_{dj}  (di, dj = lattice index inside box N)"}
        spec["detector_settings"]["tophat_px"] = prm.tophat_px(cfg.dot_side_um)
        spec["expected_in_image"] = {"at_expansion_1": dict(
            _expected(cfg.dot_side_um, cfg.dot_pitch_um, psf, um_per_px), **tag_px)}
    return spec


def feature_rows(cfg, recs):
    for r in recs:
        m, c = r["meta"], r["category"]
        row = dict(tag=r["tag"], category=c, x_um=r["x_um"], y_um=r["y_um"], w_um="", h_um="",
                   box="", node_i="", node_j="", aruco_id="", di="", dj="", dot_um="", pitch_um="", gap_um="")
        if c == "aruco":
            row.update(w_um=cfg.tag_um, h_um=cfg.tag_um, node_i=m["node_i"], node_j=m["node_j"],
                       aruco_id=m["aruco_id"])
        elif c == "dash":
            horiz = m["line"].startswith("H")
            row.update(w_um=cfg.dash_len_um if horiz else cfg.dash_width_um,
                       h_um=cfg.dash_width_um if horiz else cfg.dash_len_um)
        elif c == "dot":
            d = m.get("dot_um", cfg.dot_side_um); p = m.get("pitch_um", cfg.dot_pitch_um)
            row.update(w_um=d, h_um=d, box=m["box"], di=m["di"], dj=m["dj"], dot_um=d, pitch_um=p,
                       gap_um=p - d)
        yield row


def write(out_dir, name, cfg, recs, info, **kw):
    os.makedirs(out_dir, exist_ok=True)
    spec = build_spec(name, cfg, recs, info, **kw)
    sp = os.path.join(out_dir, "spec_sheet.json")
    with open(sp, "w") as f:
        json.dump(spec, f, indent=1, default=float)
    fp = os.path.join(out_dir, "features.csv")
    rows = list(feature_rows(cfg, recs))
    with open(fp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    out = {"spec": sp, "features": fp}
    if cfg.box_specs:
        bp = os.path.join(out_dir, "boxes.csv")
        keys = ["box", "col", "row", "position", "label", "dot", "gap", "pitch", "per_row", "phase_in_box", "count",
                "psf_fwhm_max_predicted", "tophat_px", "x0", "y0", "side", "corner_tag_ids"]
        with open(bp, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys); w.writeheader()
            for b in spec["boxes"]:
                w.writerow({k: (" ".join(map(str, b[k])) if k == "corner_tag_ids" else b[k]) for k in keys})
        out["boxes"] = bp
    return out


def verify_against_stl(spec_path, features_path, stl_path, ppu=6.0):
    """Re-read the WRITTEN sheet and check it against a render of the WRITTEN STL."""
    import cv2
    from cv2 import aruco
    from scipy.spatial import cKDTree
    from rwtag.glyph import stl_glyphs as sg
    spec = json.load(open(spec_path))
    feats = list(csv.DictReader(open(features_path)))
    img, to_px, to_um, _ = sg.render_topdown(stl_path, px_per_um=ppu)
    v, _n = sg.load_stl_triangles(stl_path)
    ext = np.ptp(v.reshape(-1, 3), axis=0)
    checks = {"envelope": bool(abs(ext[0] - spec["envelope"]["x"]) < 1e-6
                               and abs(ext[1] - spec["envelope"]["y"]) < 1e-6
                               and abs(ext[2] - spec["envelope"]["z"]) < 1e-6)}
    n, _lab, st, cen = cv2.connectedComponentsWithStats((img > 0).astype(np.uint8), 8)
    w, h = st[1:, cv2.CC_STAT_WIDTH] / ppu, st[1:, cv2.CC_STAT_HEIGHT] / ppu
    C = np.array([to_um(c[0] + 0.5, c[1] + 0.5) for c in cen[1:]], float)
    dots = [f for f in feats if f["category"] == "dot"]
    checks["dot rows == spec count"] = len(dots) == spec["dots"]["count"]
    # every dot row has a rendered component of its size within one pixel
    D = np.array([[float(f["x_um"]), float(f["y_um"])] for f in dots])
    S = np.array([float(f["dot_um"]) for f in dots])
    d, j = cKDTree(C).query(D)
    checks["every dot found in the render (< 1 px)"] = bool((d < 1.0 / ppu).all())
    tol = 1.8 / ppu                       # the raster can grow a feature by up to ~1.5 px
    checks[f"rendered dot size matches the sheet (< {tol:.2f} um)"] = bool(
        (np.abs(w[j] - S) < tol).all() and (np.abs(h[j] - S) < tol).all())
    # pitch per box from the feature rows, exact
    pit = {}
    for f in dots:
        pit.setdefault(f["box"], []).append((float(f["x_um"]), float(f["y_um"]), float(f["pitch_um"])))
    okp = True
    for b, rows in pit.items():
        P = np.array(rows)
        if len(P) > 4:
            okp &= abs(cKDTree(P[:, :2]).query(P[:, :2], k=2)[0][:, 1].min() - P[0, 2]) < 1e-9
    checks["pitch in features.csv is the true nearest-neighbour spacing"] = bool(okp)
    if "boxes" in spec:
        cnt = {}
        for f in dots:
            cnt[int(f["box"])] = cnt.get(int(f["box"]), 0) + 1
        checks["per-box counts match"] = all(cnt.get(b["box"], 0) == b["count"] for b in spec["boxes"])
    # tags: decode the render, compare ids and positions
    det = aruco.ArucoDetector(aruco.getPredefinedDictionary(getattr(aruco, spec["tags"]["dictionary"])),
                              aruco.DetectorParameters())
    cs, ids, _ = det.detectMarkers(255 - img)
    found = {}
    if ids is not None:
        for c, i in zip(cs, ids.flatten()):
            m = c.reshape(4, 2).mean(0)
            found[int(i)] = np.array(to_um(m[0] + 0.5, m[1] + 0.5))
    err = [np.hypot(*(found[t["id"]] - [t["x"], t["y"]])) if t["id"] in found else 1e9
           for t in spec["tags"]["ids"]]
    checks[f"all {len(err)} tag ids decode at the listed positions (< 0.5 um)"] = bool(max(err) < 0.5)
    return all(checks.values()), checks
