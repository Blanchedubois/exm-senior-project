#!/usr/bin/env python3
"""
w11_print_budget.py — Workshop W11 (Rev D, Phase 4).

QUESTION
    What does each candidate cost to print, and will the STL slice cleanly?

PART A — budget (from the generator's exact geometry)
    Per tier and total: footprint area, volume (x 2 um), triangle count, file
    size, and a WRITE-TIME PROXY: total laser scan length for a hatched solid,
    area x (height / slicing) / hatching, at the usual IP-Dip 63x settings
    (hatch 0.2 um, slice 0.3 um). A proxy only -- real time depends on scan
    speed, stage moves per island and the galvo field -- but it ranks the three
    prints and V1 on the same footing. V1 numbers from Phase A (STL analysis).

PART B — mesh checks (what can be verified without DeScribe)
    Every footprint rectangle is written as its own closed box. That is free of
    self-intersections (the rectangles never overlap -- checked here, pairwise,
    over the whole field), but rectangles that abut inside a tag share faces,
    and some slicers dislike coincident internal faces. Two things done about
    it:
      1. count them, so the risk is quantified per candidate;
      2. write a MERGED-OUTLINE variant of every STL: the same rectangle tiling
         on top and bottom, but side walls emitted ONLY along the outline of
         each connected region (shared edges between abutting rectangles are
         dropped, T-junction remainders are kept). No internal faces at all;
         each island is one closed solid.
    Plus a single-tag test STL in each style for the DeScribe dry run, which is
    the one step that needs the user's slicer.

PASS (WORKSHOP_PLAN.md section 4)
    Zero overlapping rectangles; a merged variant available; budget vs V1
    stated. DeScribe acceptance is reported back by the user.

Run:  python w11_print_budget.py
"""
from __future__ import annotations
import contextlib
import io
import json
import os
import struct

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.normpath(os.path.join(HERE, "..", "..", "tools"))
CAD = os.path.normpath(os.path.join(HERE, "..", "..", "cad"))
FIG_DIR = os.path.normpath(os.path.join(HERE, "..", "figures"))
OUT_JSON = os.path.join(FIG_DIR, "w11_print_budget.json")
import sys; sys.path.insert(0, TOOLS)                                        # noqa: E402
from aruco_grid import GridConfig, VARIANTS, build, stl_triangles, write_stl, tag_rects, module_map  # noqa: E402

CANDS = [("OPT", "optimistic"), ("HEDGE", "hedge"), ("SAFE", "conservative")]
HEIGHT, HATCH, SLICE = 2.0, 0.2, 0.3
V1 = dict(dots=6420, footprint=74140.0, volume=148122.0, triangles=131532, file_mb=6.6,
          tiers={"dot": 28939.0, "dash": 20341.0, "glyph": 24781.0})


def cand_cfg(variant):
    v = VARIANTS[variant]
    return GridConfig(dict_name="DICT_4X4_50", tag_modules=6, tag_um=v["tag_um"],
                      psf_fwhm_um=v["psf_fwhm_um"], dot_side_um=2.125, dashes=True,
                      round_tags=True, fit="inside", field_um=750.0)


def scan_length_m(area_um2):
    return area_um2 * (HEIGHT / SLICE) / HATCH * 1e-6       # um of scan -> m


# ------------------------------------------------------------- mesh checks
def overlaps(rects, tol=1e-9):
    """Number of rectangle pairs with positive-area intersection (sweep on x)."""
    R = np.asarray(rects, float)
    order = np.argsort(R[:, 0]); R = R[order]
    n = 0
    for i in range(len(R)):
        x1 = R[i, 2]
        j = i + 1
        while j < len(R) and R[j, 0] < x1 - tol:
            if R[j, 1] < R[i, 3] - tol and R[i, 1] < R[j, 3] - tol:
                n += 1
            j += 1
    return n


def outline_sides(rects, h, tol=1e-9):
    """Side-wall quads only where a rectangle edge is NOT shared with a neighbour.
    Returns (triangles, n_shared_edges)."""
    R = np.asarray(rects, float)
    tris, shared = [], 0
    # index rectangles by their edge lines for fast lookup
    from collections import defaultdict
    byx0, byx1, byy0, byy1 = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    key = lambda v: round(v, 6)
    for k, (x0, y0, x1, y1) in enumerate(R):
        byx0[key(x0)].append(k); byx1[key(x1)].append(k); byy0[key(y0)].append(k); byy1[key(y1)].append(k)

    def free_intervals(lo, hi, others):
        """Parts of [lo, hi] not covered by the intervals in `others`."""
        segs = [(lo, hi)]
        for a, b in others:
            nxt = []
            for s0, s1 in segs:
                if b <= s0 + tol or a >= s1 - tol:
                    nxt.append((s0, s1))
                else:
                    if a > s0 + tol: nxt.append((s0, a))
                    if b < s1 - tol: nxt.append((b, s1))
            segs = nxt
        return segs

    for k, (x0, y0, x1, y1) in enumerate(R):
        # left edge x = x0: shared with rects whose x1 == x0 and y-overlap
        for (side, x, store, ny, other_key) in (("L", x0, byx1, -1, key(x0)), ("R", x1, byx0, +1, key(x1))):
            others = [(R[m, 1], R[m, 3]) for m in store.get(other_key, []) if m != k
                      and R[m, 1] < y1 - tol and R[m, 3] > y0 + tol]
            if others:
                shared += 1
            for a, b in free_intervals(y0, y1, others):
                p = [(x, a, 0.0), (x, b, 0.0), (x, b, h), (x, a, h)]
                if ny > 0:
                    tris += [((1, 0, 0), p[0], p[1], p[2]), ((1, 0, 0), p[0], p[2], p[3])]
                else:
                    tris += [((-1, 0, 0), p[0], p[2], p[1]), ((-1, 0, 0), p[0], p[3], p[2])]
        for (side, y, store, ny, other_key) in (("B", y0, byy1, -1, key(y0)), ("T", y1, byy0, +1, key(y1))):
            others = [(R[m, 0], R[m, 2]) for m in store.get(other_key, []) if m != k
                      and R[m, 0] < x1 - tol and R[m, 2] > x0 + tol]
            if others:
                shared += 1
            for a, b in free_intervals(x0, x1, others):
                p = [(a, y, 0.0), (b, y, 0.0), (b, y, h), (a, y, h)]
                if ny > 0:
                    tris += [((0, 1, 0), p[0], p[2], p[1]), ((0, 1, 0), p[0], p[3], p[2])]
                else:
                    tris += [((0, -1, 0), p[0], p[1], p[2]), ((0, -1, 0), p[0], p[2], p[3])]
    return tris, shared


def merged_triangles(rects, h):
    """Top + bottom as the rectangle tiling, sides only along the outline."""
    tris = []
    for (x0, y0, x1, y1) in rects:
        a0, b0, c0, d0 = (x0, y0, 0.0), (x1, y0, 0.0), (x1, y1, 0.0), (x0, y1, 0.0)
        a1, b1, c1, d1 = (x0, y0, h), (x1, y0, h), (x1, y1, h), (x0, y1, h)
        tris += [((0, 0, 1), a1, b1, c1), ((0, 0, 1), a1, c1, d1),
                 ((0, 0, -1), a0, c0, b0), ((0, 0, -1), a0, d0, c0)]
    sides, shared = outline_sides(rects, h)
    return tris + sides, shared


def main():
    os.makedirs(FIG_DIR, exist_ok=True)
    print(f"write-time proxy: scan length = area x (h/{SLICE}) / {HATCH}  [IP-Dip 63x hatch/slice]")
    print(f"V1 print: footprint {V1['footprint']:,.0f} um2, volume {V1['volume']:,.0f} um3, "
          f"scan {scan_length_m(V1['footprint']):.1f} m, {V1['triangles']:,} tris, {V1['file_mb']} MB\n")
    rows = {}
    print(f"{'print':<7}{'dots':>7}{'tags um2':>10}{'dash um2':>10}{'dots um2':>10}{'total um2':>11}"
          f"{'fill':>7}{'vol um3':>10}{'scan m':>8}{'vs V1':>7}{'tris':>9}{'MB':>6}{'overlap':>9}{'shared':>8}")
    for cname, variant in CANDS:
        cfg = cand_cfg(variant)
        with contextlib.redirect_stdout(io.StringIO()):
            rects, recs, info = build(cfg)
        isl = info["islands"]
        area = {k: 0.0 for k in ("aruco", "dash", "dot")}
        for i in isl:
            area[i["kind"]] += sum((c - a) * (d - b) for a, b, c, d in i["rel"])
        tot = sum(area.values())
        n_over = overlaps(rects)
        merged, shared = merged_triangles(rects, cfg.height_um)
        stl = os.path.join(CAD, f"aruco_grid_{variant}.stl")
        n_tris = 12 * len(rects); mb = os.path.getsize(stl) / 1e6 if os.path.exists(stl) else float("nan")
        mpath = os.path.join(CAD, f"aruco_grid_{variant}_merged.stl")
        write_stl(mpath, merged)
        # single-tag test files, both styles
        aid = next(i for i in isl if i["kind"] == "aruco")["aruco_id"]
        tr, _n = tag_rects(cfg, aid, cfg.tag_um, cfg.tag_um)
        write_stl(os.path.join(CAD, f"test_tag_{variant}_boxes.stl"), stl_triangles(tr, cfg.height_um))
        mt, ms = merged_triangles(tr, cfg.height_um)
        write_stl(os.path.join(CAD, f"test_tag_{variant}_merged.stl"), mt)
        rows[cname] = dict(variant=variant, dots=sum(1 for r in recs if r["category"] == "dot"),
                           area=area, footprint=tot, fill=tot / 750.0 ** 2, volume=tot * cfg.height_um,
                           scan_m=scan_length_m(tot), scan_vs_v1=scan_length_m(tot) / scan_length_m(V1["footprint"]),
                           triangles=n_tris, file_mb=mb, overlaps=n_over, shared_faces=shared,
                           merged_triangles=len(merged), merged_mb=os.path.getsize(mpath) / 1e6,
                           test_tag_id=int(aid), test_tag_shared_faces=ms)
        r = rows[cname]
        print(f"{cname:<7}{r['dots']:>7,}{area['aruco']:>10,.0f}{area['dash']:>10,.0f}{area['dot']:>10,.0f}"
              f"{tot:>11,.0f}{r['fill']:>7.1%}{r['volume']:>10,.0f}{r['scan_m']:>8.1f}{r['scan_vs_v1']:>6.2f}x"
              f"{n_tris:>9,}{mb:>6.1f}{n_over:>9}{shared:>8,}")
    print("\noverlap = rectangle pairs with positive-area intersection (must be 0)")
    print("shared  = rectangle edges shared with an abutting rectangle (coincident internal faces in the box-style STL)")
    print("\nmerged-outline STLs written (no internal faces):")
    for cname, r in rows.items():
        print(f"  {cname:<7} aruco_grid_{r['variant']}_merged.stl  {r['merged_triangles']:,} tris, {r['merged_mb']:.1f} MB  "
              f"| test_tag_{r['variant']}_boxes.stl / _merged.stl (id {r['test_tag_id']}, "
              f"{r['test_tag_shared_faces']} shared edges in the box style)")
    ok = all(r["overlaps"] == 0 for r in rows.values())
    print(f"\nW11 (zero overlaps, merged variants available, budget vs V1 stated): {'PASS' if ok else 'FAIL'}"
          f"   — DeScribe dry run of test_tag_*_boxes.stl vs _merged.stl: user")

    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.5, 4.2), dpi=110)
    names = ["V1"] + list(rows)
    tiers = [("tags / glyphs", [V1["tiers"]["glyph"]] + [rows[c]["area"]["aruco"] for c in rows]),
             ("dashes", [V1["tiers"]["dash"]] + [rows[c]["area"]["dash"] for c in rows]),
             ("dots", [V1["tiers"]["dot"]] + [rows[c]["area"]["dot"] for c in rows])]
    bottom = np.zeros(len(names))
    for lab, vals in tiers:
        ax1.bar(names, vals, bottom=bottom, label=lab); bottom += np.array(vals)
    ax1.set_ylabel("printed footprint (um²)"); ax1.legend(fontsize=8); ax1.set_title("printed material by tier", fontsize=10)
    ax1.grid(alpha=.3, axis="y")
    dots = [V1["dots"]] + [rows[c]["dots"] for c in rows]
    scan = [scan_length_m(V1["footprint"])] + [rows[c]["scan_m"] for c in rows]
    for n, d, s in zip(names, dots, scan):
        ax2.scatter(s, d, s=60); ax2.annotate(n, (s, d), textcoords="offset points", xytext=(6, 4), fontsize=9)
    ax2.set_xlabel("write-time proxy: scan length (m)"); ax2.set_ylabel("measurement dots")
    ax2.grid(alpha=.3); ax2.set_title("dots per unit of write time", fontsize=10)
    fig.suptitle("W11 — print budget", fontsize=10); fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(os.path.join(FIG_DIR, "print_budget.png")); plt.close(fig)
    with open(OUT_JSON, "w") as f:
        json.dump(dict(v1=V1, hatch=HATCH, slice=SLICE, rows=rows), f, indent=1, default=float)
    print("wrote figures/print_budget.png + w11_print_budget.json")


if __name__ == "__main__":
    main()
