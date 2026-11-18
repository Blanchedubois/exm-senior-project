#!/usr/bin/env python3
"""
build_designs.py — spacing-workshop phase S2: the three designs, each in its folder.

    designs/1_optimistic/     5.0 um   (the existing Rev D optimistic print, unchanged)
    designs/2_medium/         6.0 um
    designs/3_conservative/   7.0 um

Per folder: <name>.stl, <name>_merged.stl, reference_tags.json, ids.json,
spec_sheet.json, features.csv, verify.json, render.png.

GATE, per design (the Phase-A standard, plus the sheet):
    exact float geometry (every dot at its rectangle centre, size, pitch)
    render round-trip (every dot recovered < 1 px, all 36 tags decode, extent 750.00)
    zero overlapping features
    spec sheet re-read and checked against the rendered STL
    optimistic only: STL and merged STL byte-identical to cad/aruco_grid_optimistic*

Run:  python build_designs.py [--only medium]
"""
from __future__ import annotations
import argparse
import contextlib
import hashlib
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
from aruco_grid import (GridConfig, SPACING_DESIGNS, build, stl_triangles, write_stl,     # noqa: E402
                        verify, verify_geometry, verify_boxes)
from w11_print_budget import overlaps, merged_triangles                                   # noqa: E402
import spec_sheet as SS                                                                   # noqa: E402
from mesh_merge import manifold_triangles                                                 # noqa: E402

FOLDERS = {"optimistic": "1_optimistic", "medium": "2_medium", "conservative": "3_conservative"}
REF = dict(dots=6420, pitch=8.0, footprint=74140.0)          # the current print, for comparison


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def render_png(stl, cfg, name, path, n_dots):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from rwtag.glyph import stl_glyphs as sg
    full, *_ = sg.render_topdown(stl, px_per_um=3.0)
    hi, *_ = sg.render_topdown(stl, px_per_um=10.0)
    P, o, t = cfg.box_pitch, cfg.origin, cfg.tag_um
    x0 = y0 = o + 2 * P - 0.7 * t; side = P + 1.4 * t
    H = hi.shape[0]
    box = hi[int(H - (y0 + side) * 10):int(H - y0 * 10), int(x0 * 10):int((x0 + side) * 10)]
    cx = o + 2 * P + t / 2 + cfg.quiet_zone_um - 3; w = 45.0          # corner: tag, dashes, first dots
    zx0, zy0 = o + 2 * P - t / 2 - 3, o + 2 * P - t / 2 - 3
    zoom = hi[int(H - (zy0 + w) * 10):int(H - zy0 * 10), int(zx0 * 10):int((zx0 + w) * 10)]
    fig, ax = plt.subplots(1, 3, figsize=(16, 5.6), dpi=120)
    ax[0].imshow(full, cmap="gray", extent=[0, cfg.extent, 0, cfg.extent])
    ax[0].set_title(f"{name}: 750 × 750 µm · 36 tags ({t:g} µm) · {n_dots:,} dots", fontsize=10)
    ax[1].imshow(box, cmap="gray", extent=[x0, x0 + side, y0, y0 + side])
    ax[1].set_title(f"one box (node pitch {P:.1f} µm)", fontsize=10)
    ax[2].imshow(zoom, cmap="gray", extent=[zx0, zx0 + w, zy0, zy0 + w])
    ax[2].set_title(f"corner: dot {cfg.dot_side_um} µm, spacing {cfg.dot_pitch_um:.2f} µm, "
                    f"gap {cfg.dot_pitch_um - cfg.dot_side_um:.3f} µm", fontsize=10)
    for a in ax:
        a.set_xlabel("µm")
    ax[0].set_ylabel("µm")
    fig.tight_layout(); fig.savefig(path); plt.close(fig)


def build_one(design):
    t0 = time.time()
    out = os.path.join(V2, "designs", FOLDERS[design])
    os.makedirs(out, exist_ok=True)
    cfg = GridConfig(**SPACING_DESIGNS[design])
    with contextlib.redirect_stdout(io.StringIO()):
        rects, recs, info = build(cfg)
    stl = os.path.join(out, f"{design}.stl")
    write_stl(stl, stl_triangles(rects, cfg.height_um))
    # one closed MANIFOLD solid per island (S4): no internal faces, no T-junctions
    mt, shared = manifold_triangles(info["islands"], cfg.height_um)
    write_stl(os.path.join(out, f"{design}_merged.stl"), mt)
    with open(os.path.join(out, "reference_tags.json"), "w") as f:
        json.dump({"box_um": cfg.box_pitch, "grid_n": cfg.grid_n, "dot_pitch": cfg.dot_pitch_um,
                   "dot_phase": info["dot_phase"], "dot_side_um": cfg.dot_side_um,
                   "generator": "aruco_grid.py", "config": asdict(cfg), "records": recs}, f)
    with open(os.path.join(out, "ids.json"), "w") as f:
        json.dump({"dict": cfg.dict_name, "modules": cfg.tag_modules, "nodes": cfg.ids}, f, indent=1)

    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        gerr, gsides, gpitch = verify_geometry(info["dot_rects"], recs)
        okr, stats = verify(stl, cfg, recs)
        okb, _rows = verify_boxes(cfg, recs, info)
    n_over = overlaps(rects)
    checks = dict(stats["checks"])
    checks["exact geometry (centres, size, pitch)"] = bool(
        gerr < 1e-9 and gsides == {cfg.dot_side_um} and abs(gpitch - cfg.dot_pitch_um) < 1e-9)
    checks["every box: count, pitch and clearances exact"] = bool(okb)
    checks["zero overlapping features"] = n_over == 0
    if design == "optimistic":
        cad = os.path.join(V2, "cad", "aruco_grid_optimistic")
        checks["STL byte-identical to the existing optimistic print"] = md5(stl) == md5(cad + ".stl")
    measured = None
    s3 = os.path.join(V2, "designs", "docs", "S3_recognition.json")
    if os.path.exists(s3):
        r = json.load(open(s3))["designs"].get(design)
        if r:
            measured = dict(
                source="tools/s3_recognition.py (synthetic frames, production pipeline, 2 seeds, lambda 1-6)",
                psf_max_measured=r["psf_max_measured"], psf_max_marginal=r["psf_max_marginal"],
                psf_max_predicted=r["psf_max_predicted"],
                tag_psf_limit_measured=r["tag_psf_limit_measured"],
                criterion="every frame registers, worst-frame dots recognised >= 90%, tags correct >= 99%",
                by_psf=[{k: x[k] for k in ("psf", "verdict", "recognised_worst", "recognised_mean",
                                           "tag_decode_mean", "tags_min")} for x in r["per_psf"]])
    files = {"stl": f"{design}.stl", "stl_merged": f"{design}_merged.stl", "features": "features.csv",
             "tag_map": "reference_tags.json", "ids": "ids.json", "gate": "verify.json",
             "render": "render.png", "recognition": "recognition.png", "printability": "printability.json",
             "test_box": "test_box.stl", "test_box_merged": "test_box_merged.stl", "design_spec": "DESIGN_SPEC.md"}
    paths = SS.write(out, design, cfg, recs, info, revision="spacing-workshop S2", files=files, measured=measured)
    oks, schecks = SS.verify_against_stl(paths["spec"], paths["features"], stl)
    checks["spec sheet agrees with the rendered STL"] = bool(oks)
    ok = all(checks.values())
    area = sum((c - a) * (d - b) for a, b, c, d in rects)
    n = {k: sum(r["category"] == k for r in recs) for k in ("aruco", "dash", "dot")}
    gate = {"passed": bool(ok), "checked": time.strftime("%Y-%m-%d"), "record": "verify.json"}
    SS.write(out, design, cfg, recs, info, revision="spacing-workshop S2", files=files, measured=measured, gate=gate)
    summary = dict(design=design, folder=FOLDERS[design], passed=bool(ok), checks=checks,
                   spec_checks=schecks, dot_um=cfg.dot_side_um, pitch_um=cfg.dot_pitch_um,
                   gap_um=cfg.dot_pitch_um - cfg.dot_side_um, tag_um=cfg.tag_um,
                   node_pitch_um=cfg.box_pitch, counts=n, per_box_row=info["dots_per_row"],
                   psf_max_um=cfg.psf_max_um(), footprint_um2=area, fill=area / cfg.extent ** 2,
                   vs_reference_dots=n["dot"] / REF["dots"], n_pinch=info["n_pinch"],
                   coincident_faces_removed=int(shared), md5_stl=md5(stl),
                   stl_mb=os.path.getsize(stl) / 1e6, exact_pitch_um=gpitch,
                   render=dict(max_pos_err_um=stats["max_pos_err_um"], tags_decoded=stats["tags_decoded"],
                               extent_um=stats["extent_um"]))
    with open(os.path.join(out, "verify.json"), "w") as f:
        json.dump(summary, f, indent=1, default=float)
    render_png(stl, cfg, design, os.path.join(out, "render.png"), n["dot"])
    summary["seconds"] = time.time() - t0
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=list(FOLDERS), default=None)
    a = ap.parse_args()
    res = [build_one(d) for d in ([a.only] if a.only else FOLDERS)]
    print(f"\n{'design':<14}{'dot':>7}{'spacing':>10}{'gap':>8}{'tag':>6}{'dots':>9}{'vs ref':>8}"
          f"{'dashes':>8}{'fill':>7}{'PSF max':>9}{'STL MB':>8}  gate")
    for s in res:
        print(f"{s['design']:<14}{s['dot_um']:>7.3f}{s['exact_pitch_um']:>10.5f}{s['gap_um']:>8.3f}"
              f"{s['tag_um']:>6.0f}{s['counts']['dot']:>9,}{s['vs_reference_dots']:>7.2f}x"
              f"{s['counts']['dash']:>8}{100*s['fill']:>6.1f}%{s['psf_max_um']:>9.2f}{s['stl_mb']:>8.1f}"
              f"  {'PASS' if s['passed'] else 'FAIL'}")
    for s in res:
        print(f"\n  {s['folder']}/")
        for k, v in s["checks"].items():
            print(f"    [{'PASS' if v else 'FAIL'}] {k}")
        for k, v in s["spec_checks"].items():
            if not v:
                print(f"      spec: FAIL {k}")
    ok = all(s["passed"] for s in res)
    with open(os.path.join(V2, "designs", "docs", "S2_gate.json"), "w") as f:
        json.dump(res, f, indent=1, default=float)
    print(f"\n  S2 GATE: {'PASS' if ok else 'FAIL'}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
