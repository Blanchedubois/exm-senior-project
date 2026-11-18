#!/usr/bin/env python3
"""
build_spectrum.py — spacing-workshop phase S5: the spectrum test print.

One 750 x 750 um print, 25 boxes, 25 dot patterns (designs/docs/03_SPECTRUM_PRINT.md):
    gap between dots widens LEFT -> RIGHT   2.875  3.375  3.875  4.375  4.875 um
    dot size grows TOP -> BOTTOM            2.125  2.5    3.0    3.5    4.0   um
    top row = the three designs (optimistic, medium, conservative at columns 1, 3, 5)
    tags (23 um), their ids and the 480 dashes are exactly those of the three designs

Writes designs/4_spectrum/: spectrum.stl, spectrum_merged.stl, reference_tags.json,
ids.json, spec_sheet.json, features.csv, boxes.csv, verify.json, render.png.

GATE (the Phase-A standard, per box)
    every box: its own dot size, pitch, count and clearances, exact
    render round-trip: every dot recovered < 1 px, all 36 tags decode, extent 750.00
    zero overlapping features · manifold merged mesh with the right volume
    tags and dashes identical, feature for feature, to the optimistic design
    spec sheet (incl. the 25-box table) re-read and checked against the rendered STL

Run:  python build_spectrum.py
"""
from __future__ import annotations
import contextlib
import io
import json
import os
import sys
import time
from dataclasses import asdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
V2 = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(V2, "workshop", "scripts"))
sys.path.insert(0, os.path.normpath(os.path.join(V2, "..", "reference-warp-tagger")))
from aruco_grid import (GridConfig, SPACING_DESIGNS, OPT_DASH_KEEPOUT, build, stl_triangles,   # noqa: E402
                        write_stl, verify, verify_geometry, verify_boxes)
from w11_print_budget import overlaps                                                          # noqa: E402
from mesh_merge import manifold_triangles                                                      # noqa: E402
import spec_sheet as SS                                                                        # noqa: E402
import spectrum_layout as SL                                                                   # noqa: E402

OUT = os.path.join(V2, "designs", "4_spectrum")


def spectrum_cfg():
    # global dot / pitch = the conservative design's; they are used only by the
    # features that are NOT per-box (nothing, once every box has a spec)
    return GridConfig(tag_um=SL.TAG_UM, psf_fwhm_um=3.39, dot_pitch_override_um=7.0,
                      dash_keepout_um=OPT_DASH_KEEPOUT, box_specs=SL.box_specs(), variant="spectrum")


def render_png(stl, cfg, info, path):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from rwtag.glyph import stl_glyphs as sg
    img, *_ = sg.render_topdown(stl, px_per_um=4.0)
    fig = plt.figure(figsize=(15.5, 9.6), dpi=130)
    ax = fig.add_axes([0.04, 0.06, 0.58, 0.86])
    ax.imshow(img, cmap="gray", extent=[0, cfg.extent, 0, cfg.extent])
    for b in info["boxes"]:
        x, y, P = b["x0_um"], b["y0_um"], cfg.box_pitch
        lab = SL.LABELS.get((b["col"], b["row"]), "")
        ax.text(x + P / 2, y + P / 2, f"{lab + chr(10) if lab else ''}dot {b['dot_um']:g}\nspacing {b['pitch_um']:.3f}\n"
                                      f"gap {b['gap_um']:.3f}\n{b['count']} dots",
                ha="center", va="center", fontsize=6.6, color="#ffd21f", weight="bold",
                bbox=dict(boxstyle="round,pad=0.25", fc="black", ec="#ffd21f", lw=0.6, alpha=0.82))
    n = cfg.grid_n
    for c, g in enumerate(SL.GAPS):
        ax.text(cfg.origin + (c + 0.5) * cfg.box_pitch, cfg.extent + 8, f"gap {g:g} µm", ha="center", fontsize=8)
    for k, d in enumerate(SL.SIZES):
        ax.text(-8, cfg.origin + (n - 1 - k + 0.5) * cfg.box_pitch, f"dot {d:g} µm", va="center", ha="right",
                fontsize=8, rotation=90)
    ax.set_xlim(-22, cfg.extent + 4); ax.set_ylim(-4, cfg.extent + 22)
    ax.set_xlabel("µm"); ax.set_title("spectrum print — spacing widens left → right, dot size grows top → bottom",
                                      fontsize=10, pad=18)
    # close-ups of the four corner boxes
    from rwtag.glyph import stl_glyphs as sg2
    hi, *_ = sg2.render_topdown(stl, px_per_um=12.0)
    H = hi.shape[0]
    corners = [((0, n - 1), "top-left"), ((n - 1, n - 1), "top-right"), ((0, 0), "bottom-left"), ((n - 1, 0), "bottom-right")]
    for i, ((c, r), name) in enumerate(corners):
        b = next(x for x in info["boxes"] if x["col"] == c and x["row"] == r)
        a = fig.add_axes([0.66 + 0.17 * (i % 2), 0.52 - 0.46 * (i // 2), 0.155, 0.40])
        w = 46.0
        x0 = b["x0_um"] + cfg.box_pitch / 2 - w / 2; y0 = b["y0_um"] + cfg.box_pitch / 2 - w / 2
        a.imshow(hi[int(H - (y0 + w) * 12):int(H - y0 * 12), int(x0 * 12):int((x0 + w) * 12)], cmap="gray",
                 extent=[0, w, 0, w])
        a.set_title(f"{name}: dot {b['dot_um']:g}, spacing {b['pitch_um']:.3f} µm", fontsize=8)
        a.set_xlabel("µm", fontsize=7); a.tick_params(labelsize=7)
    fig.savefig(path); plt.close(fig)


def main():
    t0 = time.time()
    os.makedirs(OUT, exist_ok=True)
    cfg = spectrum_cfg()
    with contextlib.redirect_stdout(io.StringIO()):
        rects, recs, info = build(cfg)
    stl = os.path.join(OUT, "spectrum.stl")
    write_stl(stl, stl_triangles(rects, cfg.height_um))
    mt, _n = manifold_triangles(info["islands"], cfg.height_um)
    write_stl(os.path.join(OUT, "spectrum_merged.stl"), mt)
    with open(os.path.join(OUT, "reference_tags.json"), "w") as f:
        json.dump({"box_um": cfg.box_pitch, "grid_n": cfg.grid_n, "dot_pitch": cfg.dot_pitch_um,
                   "dot_phase": info["dot_phase"], "dot_side_um": cfg.dot_side_um, "generator": "aruco_grid.py",
                   "config": asdict(cfg), "boxes": info["boxes"], "records": recs}, f)
    with open(os.path.join(OUT, "ids.json"), "w") as f:
        json.dump({"dict": cfg.dict_name, "modules": cfg.tag_modules, "nodes": cfg.ids}, f, indent=1)

    with contextlib.redirect_stdout(io.StringIO()):
        gerr, gsides, _gp = verify_geometry(info["dot_rects"], recs)
        okr, stats = verify(stl, cfg, recs)
        okb, rows = verify_boxes(cfg, recs, info)
        ocfg = GridConfig(**SPACING_DESIGNS["optimistic"])
        _r, orecs, _i = build(ocfg)
    fixed = lambda R: [(r["tag"], r["x_um"], r["y_um"]) for r in R if r["category"] != "dot"]
    from s4_printability import mesh_stats
    mm = mesh_stats(os.path.join(OUT, "spectrum_merged.stl"))
    area = sum((c - a) * (d - b) for a, b, c, d in rects)
    checks = dict(stats["checks"])
    checks["exact geometry: every dot at its rectangle centre, sizes are the five specified"] = bool(
        gerr < 1e-9 and gsides == set(SL.SIZES))
    checks["every box: its own size, pitch, count and clearances (exact)"] = bool(okb and len(rows) == 25)
    checks["zero overlapping features"] = overlaps(rects) == 0
    checks["tags and dashes identical to the optimistic design"] = fixed(recs) == fixed(orecs)
    top = {b["col"]: b for b in info["boxes"] if b["row"] == cfg.grid_n - 1}
    checks["top row carries the three designs (5.0 / 6.0 / 7.0 um at 2.125 um)"] = (
        [top[c]["pitch_um"] for c in (0, 2, 4)] == [5.0, 6.0, 7.0] and all(b["dot_um"] == 2.125 for b in top.values()))
    checks["merged mesh manifold, volume == footprint x height"] = bool(
        mm["edges_two"] == 1.0 and abs(mm["volume_um3"] - area * cfg.height_um) < 1e-3 * area * cfg.height_um)
    files = {"stl": "spectrum.stl", "stl_merged": "spectrum_merged.stl", "features": "features.csv",
             "boxes": "boxes.csv", "tag_map": "reference_tags.json", "ids": "ids.json", "gate": "verify.json",
             "render": "render.png", "analysis": "analyse_spectrum.py", "examples": "example/",
             "design_spec": "DESIGN_SPEC.md"}
    paths = SS.write(OUT, "spectrum", cfg, recs, info, revision="spacing-workshop S5", files=files, labels=SL.LABELS)
    oks, sch = SS.verify_against_stl(paths["spec"], paths["features"], stl)
    checks["spec sheet and 25-box table agree with the rendered STL"] = bool(oks)
    sp = json.load(open(paths["spec"]))
    tl = next(b for b in sp["boxes"] if b["label"] == "OPTIMISTIC"); br = next(b for b in sp["boxes"] if b["label"] == "SAFEST")
    checks["OPTIMISTIC is top-left, SAFEST is bottom-right"] = tl["position"] == "top-left" and br["position"] == "bottom-right"
    ok = all(checks.values())
    SS.write(OUT, "spectrum", cfg, recs, info, revision="spacing-workshop S5", files=files, labels=SL.LABELS,
             gate={"passed": bool(ok), "checked": time.strftime("%Y-%m-%d"), "record": "verify.json"})
    n = {k: sum(r["category"] == k for r in recs) for k in ("aruco", "dash", "dot")}
    with open(os.path.join(OUT, "verify.json"), "w") as f:
        json.dump(dict(passed=bool(ok), checks=checks, spec_checks=sch, counts=n, footprint_um2=area,
                       fill=area / cfg.extent ** 2, boxes=info["boxes"], mesh_merged=mm,
                       render=dict(max_pos_err_um=stats["max_pos_err_um"], tags_decoded=stats["tags_decoded"])),
                  f, indent=1, default=float)
    render_png(stl, cfg, info, os.path.join(OUT, "render.png"))

    print(f"spectrum: {n['aruco']} tags · {n['dash']} dashes · {n['dot']:,} dots · footprint {area:,.0f} um2 "
          f"({100*area/cfg.extent**2:.1f} %) · {os.path.getsize(stl)/1e6:.1f} MB\n")
    print("   dot / spacing : dots           (rows top -> bottom, columns left -> right)")
    for b in sorted(info["boxes"], key=lambda b: (-b["row"], b["col"])):
        print(("   " if b["col"] == 0 else "") + f"{b['dot_um']:.3f}/{b['pitch_um']:.3f}:{b['count']:>4}   ",
              end="\n" if b["col"] == cfg.grid_n - 1 else "")
    print()
    for k, v in checks.items():
        print(f"    [{'PASS' if v else 'FAIL'}] {k}")
    print(f"\n  SPECTRUM BUILD GATE: {'PASS' if ok else 'FAIL'}   ({time.time()-t0:.0f} s)")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
