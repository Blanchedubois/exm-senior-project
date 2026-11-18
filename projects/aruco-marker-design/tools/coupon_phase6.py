#!/usr/bin/env python3
"""
coupon_phase6.py — the Phase-6 test coupon (Rev D, Phase-5 deliverable).

WHAT IT IS
    One 750 x 750 um print, the same envelope as the full pattern so it fits the
    same DeScribe job and the same 1365 um stitch, that answers on the REAL gel
    and the REAL microscope the four questions the workshop could only answer on
    synthetic frames:

      1. Which candidate decodes at the real PSF?     three MINI-PATTERNS (one box,
         four tags each) of OPT / HEDGE / SAFE, built by the production generator
         with distinct ids, so the three prints are compared side by side in one
         frame at every lambda.
      2. Where is the real separation threshold?       a DOT-PITCH LADDER of eight
         70 um patches, 3.5 -> 9.0 um pitch, straddling the W5 threshold
         (4.6-6.6 um at PSF 1.9-3.2; 7.6 um at 3.8). The first pitch that resolves
         to >= 95% of its dots IS the rule for this microscope.
      3. Do the dots stay anchored, and how bright?    a DOT-SIZE LADDER 2.125 /
         2.5 / 3.0 um at the HEDGE pitch rule (W6/W7: size buys nothing optically,
         so only anchoring can justify a change).
      4. Does a tag pinch the gel?                     two STIFFENING FIELDS, 260 um
         of HEDGE-pitch dots with a single 34 um (SAFE) or 23 um (OPT) tag at the
         centre, for the 0d/W4 stacked-residual test (sensitivity ~0.7%).

    Every patch on the ladders has its own 27 um tag beside it, so a patch is
    addressed by id, not by position, and the pairing works at any lambda without
    the lattice registration V1 needed. An L-shaped datum at the bottom fixes
    handedness (design y-up vs image y-down bit three earlier scripts).

    The coupon carries 24 ArUco ids out of the 43 strut-free ids in DICT_4X4_50.

GATE (same standard as the full print, Phase A)
    exact float geometry (every dot record at its rectangle centre, configured
    size) · zero overlapping rectangles · outer extent exactly 750 x 750 um ·
    render round-trip at 6 px/um: every dot component recovered per region and
    ALL 24 tags decode.

Run:  python coupon_phase6.py            -> cad/coupon_phase6.{stl,_merged.stl,
                                             reference_tags.json,ids.json,verify.json}
                                             + workshop/figures/coupon_phase6.png
"""
from __future__ import annotations
import argparse
import json
import math
import os
import sys
from dataclasses import asdict

import numpy as np
import cv2
from cv2 import aruco

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "workshop", "scripts")))
from aruco_grid import (GridConfig, VARIANTS, build, tag_rects, solid_ids,        # noqa: E402
                        n_leaves, module_map, stl_triangles, write_stl)
from w11_print_budget import overlaps, merged_triangles                          # noqa: E402

FIELD = 750.0
HEIGHT = 2.0
DICT, MODULES = "DICT_4X4_50", 6
DOT = 2.125                                   # the anchoring-proven size (V1)
SEP = 1.75                                    # Rev D separation rule (0c / W5)
PSF = {"OPT": 1.91, "HEDGE": 2.50, "SAFE": 3.18}


def rule_pitch(dot, psf, sep=SEP):
    return sep * math.hypot(dot, psf)


# ---------------------------------------------------------------- layout (um, y-UP)
MINI_FIELD = 175.0                            # one box + tags, ~ the full print's 145 um pitch
MINI = [("OPT", "optimistic", 0.0), ("HEDGE", "hedge", 287.5), ("SAFE", "conservative", 575.0)]
MINI_Y0 = FIELD - MINI_FIELD                  # top band, 575..750

LADDER_TAG = 27.0                             # HEDGE size: decodes >= 95% up to PSF 3.18 (W1)
PATCH = 70.0                                  # patch side
TAG_GAP = 8.0                                 # tag edge -> first dot edge (>= any quiet zone here)
UNIT_X = [32.0 + u * 145.0 for u in range(5)]  # five units per row; unit = tag + gap + patch
ROW_YC = {"A": 470.0, "B": 365.0}
# (region, dot side, pitch)   -- pitch ladder at 2.125 um, then the size ladder at HEDGE rule
LADDER = [
    ("A", "PITCH_3.50", DOT, 3.50), ("A", "PITCH_4.00", DOT, 4.00), ("A", "PITCH_4.50", DOT, 4.50),
    ("A", "PITCH_5.00", DOT, 5.00), ("A", "PITCH_5.74", DOT, rule_pitch(DOT, PSF["HEDGE"])),
    ("B", "PITCH_6.69", DOT, rule_pitch(DOT, PSF["SAFE"])), ("B", "PITCH_7.50", DOT, 7.50),
    ("B", "PITCH_9.00", DOT, 9.00),
    ("B", "SIZE_2.50", 2.50, rule_pitch(2.50, PSF["HEDGE"])),
    ("B", "SIZE_3.00", 3.00, rule_pitch(3.00, PSF["HEDGE"])),
]

STIFF_FIELD = 260.0                           # bottom corners, 0..260 and 490..750
STIFF = [("STIFF_34", 34.0, 0.0), ("STIFF_23", 23.0, FIELD - STIFF_FIELD)]
STIFF_PITCH = rule_pitch(DOT, PSF["HEDGE"])

DATUM = dict(x0=360.0, y0=0.0, arm=30.0, w=2.5)    # L on the bottom edge: long arm +y, short +x -> handedness;
                                                   # also the only feature that reaches y = 0 (dot fields are inset)


# ---------------------------------------------------------------- pieces
def dot_patch(region, x0, y0, size, dot, pitch, exclude=None):
    """Centred square lattice inside [x0,x0+size] x [y0,y0+size]; `exclude`
    (cx, cy, half_chebyshev) drops dots inside a square keep-out."""
    n = int(math.floor((size - dot) / pitch)) + 1
    phase = (size - (n - 1) * pitch) / 2.0
    h = dot / 2.0
    rects, recs = [], []
    for dj in range(n):
        for di in range(n):
            x, y = x0 + phase + di * pitch, y0 + phase + dj * pitch
            if exclude and max(abs(x - exclude[0]), abs(y - exclude[1])) < exclude[2]:
                continue
            rects.append((x - h, y - h, x + h, y + h))
            recs.append(dict(tag=f"dot|{region}|{di}_{dj}", category="dot",
                             x_um=float(x), y_um=float(y),
                             meta=dict(region=region, di=di, dj=dj, dot_um=dot, pitch_um=pitch)))
    return rects, recs


def lone_tag(region, aid, cx, cy, size):
    cfg = GridConfig(tag_um=size, dict_name=DICT, tag_modules=MODULES)
    tr, npin = tag_rects(cfg, aid, cx, cy)
    rec = dict(tag=f"aruco|{region}|{aid}", category="aruco", x_um=float(cx), y_um=float(cy),
               meta=dict(region=region, aruco_id=int(aid), dict=DICT, size_um=size))
    return tr, rec, npin


def assemble():
    # the SAME leaf-free-first ordering assign_ids() uses, so the mini-patterns
    # (id_start 0/4/8 into this pool) and the lone tags (from 12) never collide
    pool = sorted(solid_ids(DICT, MODULES, 50),
                  key=lambda i: (n_leaves(module_map(DICT, i, MODULES)), i))
    rects, recs, regions, tags, dot_rects = [], [], {}, [], []
    n_pinch = 0

    # 1. mini-patterns ------------------------------------------------------
    for k, (name, variant, ox) in enumerate(MINI):
        cfg = GridConfig(**VARIANTS[variant], field_um=MINI_FIELD, grid_n=1, id_start=4 * k)
        r, rc, info = build(cfg)
        oy = MINI_Y0
        rects += [(a + ox, b + oy, c + ox, d + oy) for a, b, c, d in r]
        dot_rects += [(a + ox, b + oy, c + ox, d + oy) for a, b, c, d in info["dot_rects"]]
        for x in rc:
            x = dict(x); x["x_um"] += ox; x["y_um"] += oy
            x["tag"] = x["tag"].replace("|", f"|MINI_{name}.", 1)
            x["meta"] = dict(x["meta"], region=f"MINI_{name}")
            recs.append(x)
            if x["category"] == "aruco":
                tags.append(dict(region=f"MINI_{name}", aruco_id=x["meta"]["aruco_id"],
                                 x_um=x["x_um"], y_um=x["y_um"], size_um=cfg.tag_um))
        n_pinch += info["n_pinch"]
        regions[f"MINI_{name}"] = dict(kind="mini", variant=variant, tag_um=cfg.tag_um,
                                       dot_um=cfg.dot_side_um, pitch_um=cfg.dot_pitch_um,
                                       box=[ox, oy, ox + MINI_FIELD, oy + MINI_FIELD],
                                       n_dots=sum(1 for x in rc if x["category"] == "dot"),
                                       ids=[v for _i, _j, v in cfg.ids])
    next_id = 4 * len(MINI)

    # 2/3. pitch + size ladders, one tag per patch ----------------------------
    cursor = {"A": 0, "B": 0}
    for row, region, dot, pitch in LADDER:
        ux = UNIT_X[cursor[row]]; cursor[row] += 1
        yc = ROW_YC[row]
        tcx, tcy = ux + LADDER_TAG / 2.0, yc
        px0, py0 = ux + LADDER_TAG + TAG_GAP, yc - PATCH / 2.0
        aid = pool[next_id]; next_id += 1
        tr, trec, npin = lone_tag(region, aid, tcx, tcy, LADDER_TAG)
        pr, prec = dot_patch(region, px0, py0, PATCH, dot, pitch)
        rects += tr + pr; recs += [trec] + prec; n_pinch += npin; dot_rects += pr
        tags.append(dict(region=region, aruco_id=aid, x_um=tcx, y_um=tcy, size_um=LADDER_TAG))
        regions[region] = dict(kind="pitch" if region.startswith("PITCH") else "size",
                               dot_um=dot, pitch_um=pitch, tag_um=LADDER_TAG, aruco_id=aid,
                               box=[px0, py0, px0 + PATCH, py0 + PATCH], n_dots=len(prec),
                               sep_over_imaged={k: pitch / math.hypot(dot, p) for k, p in PSF.items()})

    # 4. stiffening fields ----------------------------------------------------
    for region, tsize, x0 in STIFF:
        cx = x0 + STIFF_FIELD / 2.0; cy = STIFF_FIELD / 2.0
        aid = pool[next_id]; next_id += 1
        tr, trec, npin = lone_tag(region, aid, cx, cy, tsize)
        keep = tsize / 2.0 + (STIFF_PITCH - DOT) + DOT / 2.0        # quiet = pitch - dot (W2)
        pr, prec = dot_patch(region, x0, 0.0, STIFF_FIELD, DOT, STIFF_PITCH, exclude=(cx, cy, keep))
        rects += tr + pr; recs += [trec] + prec; n_pinch += npin; dot_rects += pr
        tags.append(dict(region=region, aruco_id=aid, x_um=cx, y_um=cy, size_um=tsize))
        regions[region] = dict(kind="stiffening", tag_um=tsize, aruco_id=aid, dot_um=DOT,
                               pitch_um=STIFF_PITCH, box=[x0, 0.0, x0 + STIFF_FIELD, STIFF_FIELD],
                               n_dots=len(prec), keepout_um=keep)

    # 5. handedness datum -----------------------------------------------------
    d = DATUM
    rects += [(d["x0"], d["y0"], d["x0"] + d["w"], d["y0"] + d["arm"]),            # long, +y
              (d["x0"] + d["w"], d["y0"], d["x0"] + d["arm"] * 0.6, d["y0"] + d["w"])]  # short, +x
    recs.append(dict(tag="datum|L", category="datum", x_um=d["x0"], y_um=d["y0"],
                     meta=dict(region="DATUM", note="long arm +y, short arm +x")))
    regions["DATUM"] = dict(kind="datum", **d)
    return rects, recs, regions, tags, n_pinch, len(pool), dot_rects


# ---------------------------------------------------------------- gate
def verify(stl_path, rects, recs, regions, tags, dotrects, ppu=6.0):
    sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "reference-warp-tagger")))
    from rwtag.glyph import stl_glyphs as sg
    from scipy.spatial import cKDTree

    checks = {}
    # exact geometry, in floating point
    dotrecs = [r for r in recs if r["category"] == "dot"]
    err = max(max(abs((r[0] + r[2]) / 2 - c["x_um"]), abs((r[1] + r[3]) / 2 - c["y_um"]))
              for r, c in zip(dotrects, dotrecs))
    checks["exact geometry (rect centre == record)"] = len(dotrects) == len(dotrecs) and err < 1e-9
    checks["zero overlapping rectangles"] = overlaps(rects) == 0
    ext = (max(r[2] for r in rects) - min(r[0] for r in rects),
           max(r[3] for r in rects) - min(r[1] for r in rects))
    checks["outer extent == 750 x 750 um"] = abs(ext[0] - FIELD) < 1e-6 and abs(ext[1] - FIELD) < 1e-6

    # render round-trip
    v, _ = sg.load_stl_triangles(stl_path)
    img, to_px, to_um, _ = sg.render_topdown(stl_path, px_per_um=ppu)
    n, lab, st, cen = cv2.connectedComponentsWithStats((img > 0).astype(np.uint8), 8)
    w = st[1:, cv2.CC_STAT_WIDTH] / ppu; h = st[1:, cv2.CC_STAT_HEIGHT] / ppu
    C = np.array([to_um(c[0] + 0.5, c[1] + 0.5) for c in cen[1:]], float)
    per_region = {}
    for name, rg in regions.items():
        if "n_dots" not in rg:
            continue
        bx = rg["box"]; side = rg["dot_um"]
        m = ((np.abs(w - side) < 0.4) & (np.abs(h - side) < 0.4)
             & (C[:, 0] >= bx[0]) & (C[:, 0] <= bx[2]) & (C[:, 1] >= bx[1]) & (C[:, 1] <= bx[3]))
        got = int(m.sum())
        ref = np.array([[r["x_um"], r["y_um"]] for r in dotrecs if r["meta"]["region"] == name])
        e = float(cKDTree(ref).query(C[m])[0].max()) if got else float("nan")
        per_region[name] = dict(expected=rg["n_dots"], recovered=got, max_err_um=e)
        checks[f"dots recovered {name} ({rg['n_dots']})"] = got == rg["n_dots"] and e < 1.0 / ppu

    det = aruco.ArucoDetector(aruco.getPredefinedDictionary(getattr(aruco, DICT)),
                              aruco.DetectorParameters())
    _c, ids, _ = det.detectMarkers(255 - img)
    found = {int(x) for x in ids.flatten()} if ids is not None else set()
    want = {t["aruco_id"] for t in tags}
    checks[f"all {len(want)} tags decode"] = found >= want

    print(f"\n  STL extent {ext[0]:.2f} x {ext[1]:.2f} um · render {img.shape[1]}x{img.shape[0]} px "
          f"· exact-geometry err {err:.1e} um · tags {len(found & want)}/{len(want)}")
    for k, ok in checks.items():
        print(f"    [{'PASS' if ok else 'FAIL'}] {k}")
    ok = all(checks.values())
    print(f"\n  COUPON GATE: {'PASS' if ok else 'FAIL'}")
    return ok, dict(extent_um=ext, exact_err_um=err, per_region=per_region,
                    tags_decoded=sorted(found & want), tags_missing=sorted(want - found),
                    checks={k: bool(v) for k, v in checks.items()}, pass_=bool(ok)), img


def preview(img, regions, path, ppu):
    H = img.shape[0]
    k = 1800 / max(img.shape)
    im = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
    for name, rg in regions.items():
        if "box" not in rg:
            continue
        x0, y0, x1, y1 = rg["box"]
        p0 = (int(x0 * ppu * k), int((H - y1 * ppu) * k)); p1 = (int(x1 * ppu * k), int((H - y0 * ppu) * k))
        cv2.rectangle(im, p0, p1, (0, 200, 255), 1)
        cv2.putText(im, name, (p0[0], p0[1] - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 200, 255), 1, cv2.LINE_AA)
    cv2.imwrite(path, im)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "..", "cad"))
    ap.add_argument("--fig", default=os.path.join(HERE, "..", "workshop", "figures"))
    ap.add_argument("--ppu", type=float, default=6.0)
    a = ap.parse_args()
    out = os.path.normpath(a.out); os.makedirs(out, exist_ok=True); os.makedirs(a.fig, exist_ok=True)

    rects, recs, regions, tags, n_pinch, n_pool, dot_rects = assemble()
    cat = {}
    for r in recs:
        cat[r["category"]] = cat.get(r["category"], 0) + 1
    area = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in rects)
    print("=== coupon_phase6 ===")
    print(f"  {len(tags)} ArUco ids of {n_pool} strut-free in {DICT} · {n_pinch} pinches bridged")
    print("  records: " + " · ".join(f"{k} {v:,}" for k, v in sorted(cat.items())))
    print(f"  footprint {area:,.0f} um^2 = {100*area/FIELD**2:.1f}% fill · volume {area*HEIGHT:,.0f} um^3")
    print("\n  region            kind        tag   dot    pitch   dots   pitch/imaged-FWHM @PSF 1.91/2.5/3.18")
    for name, rg in regions.items():
        if "n_dots" not in rg:
            continue
        s = rg.get("sep_over_imaged")
        s = "  ".join(f"{s[k]:.2f}" for k in ("OPT", "HEDGE", "SAFE")) if s else ""
        print(f"  {name:<17} {rg['kind']:<10} {rg['tag_um']:>5.1f} {rg['dot_um']:>5.3f} {rg['pitch_um']:>7.3f} "
              f"{rg['n_dots']:>6,}   {s}")

    stl = os.path.join(out, "coupon_phase6.stl")
    tris = stl_triangles(rects, HEIGHT); write_stl(stl, tris)
    mt, shared = merged_triangles(rects, HEIGHT); write_stl(os.path.join(out, "coupon_phase6_merged.stl"), mt)
    print(f"\n  wrote coupon_phase6.stl ({len(tris):,} tris) + _merged.stl ({len(mt):,} tris, "
          f"{shared:,} coincident faces removed)")
    with open(os.path.join(out, "coupon_phase6.reference_tags.json"), "w") as f:
        json.dump(dict(generator="coupon_phase6.py", field_um=FIELD, dot_side_um=DOT,
                       regions=regions, records=recs), f)
    with open(os.path.join(out, "coupon_phase6.ids.json"), "w") as f:
        json.dump(dict(dict=DICT, modules=MODULES, tags=tags), f, indent=1)

    ok, stats, img = verify(stl, rects, recs, regions, tags, dot_rects, ppu=a.ppu)
    preview(img, regions, os.path.join(a.fig, "coupon_phase6.png"), a.ppu)
    stats.update(regions=regions, footprint_um2=area, n_pinch=n_pinch)
    with open(os.path.join(out, "coupon_phase6.verify.json"), "w") as f:
        json.dump(stats, f, indent=1, default=float)
    print("  wrote .reference_tags.json, .ids.json, .verify.json, figures/coupon_phase6.png")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
