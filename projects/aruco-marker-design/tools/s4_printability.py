#!/usr/bin/env python3
"""
s4_printability.py — spacing-workshop phase S4: can the three designs be printed?

BENCHMARK
    The reference print (base_design_for_nanoscribe_2026_01_14.stl) is the one thing
    known to print and to survive in the gel. So every design is measured with the
    same ruler as the reference, and the gate is "no harder to print than the
    reference" -- not a quoted resolution figure for a printer this script cannot see.
    Typical two-photon figures (63x, IP-Dip: ~0.2 um lateral feature, ~0.5 um gap) are
    reported alongside as ASSUMED, for orientation only.

MEASURED, per design (and for the reference where it applies)
    islands        separate solids the printer has to write (tags, dashes, dots)
    smallest gap   edge-to-edge clearance between any two islands, by pair type
    smallest free-standing feature, its aspect ratio (height / width)
    inside the tags: narrowest solid bridge and narrowest internal gap
    write time     laser scan length for a hatched solid (hatch 0.2, slice 0.3 um),
                   relative to the reference; island count relative to the reference
    mesh           zero overlaps; mesh volume == footprint x height; closed (every edge
                   shared by an even number of faces); coincident internal faces
                   (box STL) and their removal (merged STL)

WRITTEN, per design folder
    test_box.stl, test_box_merged.stl   one box with its four tags, at the origin, for
                                        the DeScribe dry run

GATE
    zero overlaps · smallest gap >= 0.5 um (assumed limit) · free-standing features no
    smaller and no slenderer than the reference's dots · both meshes closed with the
    right volume

Run:  python s4_printability.py  -> designs/docs/S4_printability.{json,png}
"""
from __future__ import annotations
import contextlib
import io
import json
import os
import struct
import sys
import time

import numpy as np
import cv2
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
V2 = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(V2, "workshop", "scripts"))
sys.path.insert(0, os.path.normpath(os.path.join(V2, "..", "reference-warp-tagger")))
from aruco_grid import GridConfig, SPACING_DESIGNS, build, stl_triangles, write_stl      # noqa: E402
from w11_print_budget import overlaps, merged_triangles, HEIGHT, HATCH, SLICE            # noqa: E402
from build_designs import FOLDERS                                                         # noqa: E402
from mesh_merge import manifold_triangles, islands_from_rects                             # noqa: E402
from rwtag.glyph import stl_glyphs as sg                                                  # noqa: E402

REF_STL = os.path.normpath(os.path.join(V2, "..", "reference-warp-tagger", "Markers CAD",
                                        "base_design_for_nanoscribe_2026_01_14.stl"))
ASSUMED = dict(min_feature_um=0.2, min_gap_um=0.5,
               note="typical 63x / IP-Dip two-photon figures; NOT measured on this printer")


def scan_m(area):
    return area * (HEIGHT / SLICE) / HATCH * 1e-6


# ------------------------------------------------------------------ geometry
def island_rects(info):
    R, I, K = [], [], []
    for k, isl in enumerate(info["islands"]):
        for (a, b, c, d) in isl["rel"]:
            R.append((isl["cx"] + a, isl["cy"] + b, isl["cx"] + c, isl["cy"] + d)); I.append(k); K.append(isl["kind"])
    return np.array(R, float), np.array(I), np.array(K)


def min_gaps(R, I, K, reach=9.0):
    """Smallest edge-to-edge distance between rectangles of DIFFERENT islands, per
    pair of kinds."""
    C = np.column_stack([(R[:, 0] + R[:, 2]) / 2, (R[:, 1] + R[:, 3]) / 2])
    hd = np.hypot(R[:, 2] - R[:, 0], R[:, 3] - R[:, 1]) / 2
    out = {}
    big = hd > 3.0                                    # the few long tag strips
    sets = [(np.nonzero(~big)[0], reach + 2 * 3.0)]
    if big.any():
        sets.append((None, reach + hd.max() + 3.0))   # pairs involving a big rect
    tree = cKDTree(C)
    pairs = tree.query_pairs(reach + 6.0, output_type="ndarray")
    if big.any():
        bi = np.nonzero(big)[0]
        nb = tree.query_ball_point(C[bi], reach + hd.max() + 3.0)
        extra = np.array([(i, j) for i, lst in zip(bi, nb) for j in lst if j != i], int).reshape(-1, 2)
        pairs = np.vstack([pairs, extra])
    a, b = pairs[:, 0], pairs[:, 1]
    keep = I[a] != I[b]
    a, b = a[keep], b[keep]
    dx = np.maximum(0, np.maximum(R[a, 0] - R[b, 2], R[b, 0] - R[a, 2]))
    dy = np.maximum(0, np.maximum(R[a, 1] - R[b, 3], R[b, 1] - R[a, 3]))
    d = np.hypot(dx, dy)
    kinds = np.array(["-".join(sorted((x, y))) for x, y in zip(K[a], K[b])])
    for k in np.unique(kinds):
        out[k] = float(d[kinds == k].min())
    return out


def runs(mask):
    """(min black run, min internal white run) over rows and columns, px."""
    mb, mw = 10 ** 9, 10 ** 9
    for M in (mask, mask.T):
        for row in M:
            if not row.any():
                continue
            d = np.diff(np.r_[0, row.astype(np.int8), 0])
            s, e = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
            mb = min(mb, int((e - s).min()))
            if len(s) > 1:
                mw = min(mw, int((s[1:] - e[:-1]).min()))
    return mb, mw


def tag_internals(info, ppu=40.0, coarse_um=1.0):
    """Per tag, on a 40 px/um raster: narrowest solid run and narrowest internal gap
    along x / y; whether the tag is STILL ONE SOLID when everything finer than
    `coarse_um` is removed (an opening with a disc of that diameter) -- i.e. whether
    its integrity depends on the necks and fillet tips printing; and the width of
    the finest detail that opening removes."""
    nb, nw, one, fine = [], [], [], []
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(coarse_um * ppu) | 1,) * 2)
    for isl in info["islands"]:
        if isl["kind"] != "aruco":
            continue
        rel = np.array(isl["rel"]); lo = rel[:, :2].min(0); ext = rel[:, 2:].max(0) - lo
        m = np.zeros((int(round(ext[1] * ppu)), int(round(ext[0] * ppu))), np.uint8)
        for a, b, c, d in rel:
            m[int(round((b - lo[1]) * ppu)):int(round((d - lo[1]) * ppu)),
              int(round((a - lo[0]) * ppu)):int(round((c - lo[0]) * ppu))] = 1
        b_, w_ = runs(m)
        nb.append(b_ / ppu); nw.append(w_ / ppu)
        mp = np.pad(m, 4)
        op = cv2.morphologyEx(mp, cv2.MORPH_OPEN, se)
        n, _l, st, _c = cv2.connectedComponentsWithStats(op, 4)
        one.append(int((st[1:, cv2.CC_STAT_AREA] > ppu * ppu).sum()) == 1)
        resid = (mp > 0) & (op == 0)
        fine.append(2.0 * float(cv2.distanceTransform(resid.astype(np.uint8), cv2.DIST_L2, 5).max()) / ppu
                    if resid.any() else 0.0)
    return float(min(nb)), float(min(nw)), bool(all(one)), float(max(fine)) if fine else 0.0


# ------------------------------------------------------------------ meshes
def read_stl(path):
    with open(path, "rb") as f:
        f.read(80); n = struct.unpack("<I", f.read(4))[0]
        a = np.frombuffer(f.read(50 * n), dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    return a["v"].astype(np.float64)


def mesh_stats(path):
    v = read_stl(path)
    vol = float(np.abs(np.einsum("ij,ij->i", v[:, 0], np.cross(v[:, 1], v[:, 2])).sum()) / 6.0)
    area2 = np.linalg.norm(np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]), axis=1)
    q = np.round(v * 1e4).astype(np.int64)
    key = q[..., 0] * 73856093 ^ q[..., 1] * 19349663 ^ q[..., 2] * 83492791      # vertex hash
    e = np.stack([np.stack([key[:, i], key[:, (i + 1) % 3]], 1) for i in range(3)], 1).reshape(-1, 2)
    e.sort(axis=1)
    _u, cnt = np.unique(e, axis=0, return_counts=True)
    return dict(triangles=int(len(v)), volume_um3=vol, degenerate=int((area2 < 1e-9).sum()),
                edges=int(len(cnt)), edges_even=float((cnt % 2 == 0).mean()),
                edges_two=float((cnt == 2).mean()), mb=os.path.getsize(path) / 1e6)


# ------------------------------------------------------------------ reference
def reference(ppu=8.0):
    img, to_px, to_um, _ = sg.render_topdown(REF_STL, px_per_um=ppu)
    b = (img > 0).astype(np.uint8)
    n, lab, st, cen = cv2.connectedComponentsWithStats(b, 8)
    w, h, a = st[1:, 2] / ppu, st[1:, 3] / ppu, st[1:, 4] / ppu ** 2
    x0, y0 = st[1:, 0] / ppu, st[1:, 1] / ppu
    R = np.column_stack([x0, y0, x0 + w, y0 + h])
    dot = (np.abs(w - 2.125) < 0.3) & (np.abs(h - 2.125) < 0.3)
    # reference dashes are 8.125 long and 2.125 (outer lines) or 4.125 (inner lines) wide
    dash = (np.abs(np.maximum(w, h) - 8.125) < 0.4) & (np.minimum(w, h) < 4.5)
    K = np.where(dot, "dot", np.where(dash, "dash", "glyph"))
    gaps = min_gaps(R, np.arange(len(R)), K)          # bounding boxes: a lower bound for glyphs
    v = read_stl(REF_STL)
    vol = float(np.abs(np.einsum("ij,ij->i", v[:, 0], np.cross(v[:, 1], v[:, 2])).sum()) / 6.0)
    return dict(islands=int(n - 1), dots=int(dot.sum()), dashes=int(dash.sum()), glyphs=int((K == "glyph").sum()),
                footprint_um2=float(a.sum()), volume_um3=vol, scan_m=scan_m(float(a.sum())),
                min_gap=gaps, min_gap_all=float(min(gaps.values())),
                dot_um=2.125, dot_aspect=HEIGHT / 2.125, resolution_um=1 / ppu,
                smallest_bbox_side_um=float(np.minimum(w, h).min()))


# ------------------------------------------------------------------ one design
def one(design, ref):
    out_dir = os.path.join(V2, "designs", FOLDERS[design])
    cfg = GridConfig(**SPACING_DESIGNS[design])
    with contextlib.redirect_stdout(io.StringIO()):
        rects, recs, info = build(cfg)
    R, I, K = island_rects(info)
    area = float(((R[:, 2] - R[:, 0]) * (R[:, 3] - R[:, 1])).sum())
    by_kind = {k: float(((R[K == k, 2] - R[K == k, 0]) * (R[K == k, 3] - R[K == k, 1])).sum()) for k in np.unique(K)}
    n_isl = {k: int(sum(i["kind"] == k for i in info["islands"])) for k in ("aruco", "dash", "dot")}
    gaps = min_gaps(R, I, K)
    bridge, tgap, one_piece, finest = tag_internals(info)

    # single-box files for the DeScribe dry run: box (2,2) with its four tags
    o, P, t = cfg.origin, cfg.box_pitch, cfg.tag_um
    lo, hi = o + 2 * P - t / 2 - 1e-6, o + 3 * P + t / 2 + 1e-6
    keep = [k for k, i in enumerate(info["islands"]) if lo <= i["cx"] - 0 and i["cx"] <= hi and lo <= i["cy"] <= hi
            and all(lo <= i["cx"] + r[0] and i["cx"] + r[2] <= hi and lo <= i["cy"] + r[1] and i["cy"] + r[3] <= hi
                    for r in i["rel"])]
    sel = np.isin(I, keep)
    box = [(a - lo, b - lo, c - lo, d - lo) for a, b, c, d in R[sel]]
    write_stl(os.path.join(out_dir, "test_box.stl"), stl_triangles(box, cfg.height_um))
    mt, _s = manifold_triangles(islands_from_rects(box, I[sel]), cfg.height_um)
    write_stl(os.path.join(out_dir, "test_box_merged.stl"), mt)

    full = mesh_stats(os.path.join(out_dir, f"{design}.stl"))
    merged = mesh_stats(os.path.join(out_dir, f"{design}_merged.stl"))
    tb = mesh_stats(os.path.join(out_dir, "test_box.stl"))
    res = dict(
        design=design, pitch_um=cfg.dot_pitch_um, dot_um=cfg.dot_side_um, tag_um=cfg.tag_um,
        islands=n_isl, islands_total=int(sum(n_isl.values())), footprint_um2=area, footprint_by_kind=by_kind,
        fill=area / cfg.extent ** 2, volume_um3=area * cfg.height_um, scan_m=scan_m(area),
        scan_vs_ref=scan_m(area) / ref["scan_m"], islands_vs_ref=sum(n_isl.values()) / ref["islands"],
        dots_per_scan_m=n_isl["dot"] / scan_m(area),
        min_gap=gaps, min_gap_all=float(min(gaps.values())),
        free_standing_min_um=min(cfg.dot_side_um, cfg.dash_width_um), dot_aspect=cfg.height_um / cfg.dot_side_um,
        tag_narrowest_bridge_um=bridge, tag_narrowest_internal_gap_um=tgap,
        tag_one_piece_without_fine_detail=one_piece, tag_finest_detail_um=finest,
        overlaps=int(overlaps(rects)), mesh_box=full, mesh_merged=merged,
        coincident_faces_in_box_mesh=int(round((1 - full["edges_two"]) * full["edges"])),
        test_box=dict(files=["test_box.stl", "test_box_merged.stl"], size_um=hi - lo, islands=len(keep),
                      dots=int(sum(info["islands"][k]["kind"] == "dot" for k in keep)), triangles=tb["triangles"],
                      mb=tb["mb"]))
    vol = area * cfg.height_um
    res["checks"] = {
        "zero overlapping features": res["overlaps"] == 0,
        f"smallest gap >= {ASSUMED['min_gap_um']} um (assumed limit)": res["min_gap_all"] >= ASSUMED["min_gap_um"],
        "free-standing features no smaller than the reference's dots": res["free_standing_min_um"] >= ref["dot_um"] - 1e-9,
        "dots no slenderer than the reference's (height / width)": res["dot_aspect"] <= ref["dot_aspect"] + 1e-9,
        "every tag is still ONE solid if nothing finer than 1 um prints": one_piece,
        "narrowest gap inside a tag >= the reference's smallest gap": tgap >= ref["min_gap_all"] - 1e-9,
        "box mesh: every solid closed, volume == footprint x height":
            full["edges_even"] == 1.0 and abs(full["volume_um3"] - vol) < 1e-3 * vol,
        "merged mesh: MANIFOLD (every edge shared by exactly two faces)": merged["edges_two"] == 1.0,
        "merged mesh: same volume, no degenerate faces":
            abs(merged["volume_um3"] - vol) < 1e-3 * vol and merged["degenerate"] == 0,
    }
    res["passed"] = all(res["checks"].values())
    return res


def main():
    t0 = time.time()
    ref = reference()
    print(f"reference print: {ref['islands']:,} islands ({ref['dots']:,} dots, {ref['dashes']} dashes, "
          f"{ref['glyphs']} glyph pieces) · footprint {ref['footprint_um2']:,.0f} um2 · scan {ref['scan_m']:.2f} m · "
          f"smallest gap {ref['min_gap_all']:.2f} um {ref['min_gap']}")
    res = {d: one(d, ref) for d in SPACING_DESIGNS}
    print(f"\n{'design':<14}{'islands':>9}{'vs ref':>8}{'footprint':>11}{'scan m':>8}{'vs ref':>8}{'dots/m':>8}"
          f"{'min gap':>9}{'bridge':>8}{'tag gap':>9}{'finest':>10}")
    for d, r in res.items():
        print(f"{d:<14}{r['islands_total']:>9,}{r['islands_vs_ref']:>7.2f}x{r['footprint_um2']:>11,.0f}{r['scan_m']:>8.2f}"
              f"{r['scan_vs_ref']:>7.2f}x{r['dots_per_scan_m']:>8,.0f}{r['min_gap_all']:>9.3f}"
              f"{r['tag_narrowest_bridge_um']:>8.3f}{r['tag_narrowest_internal_gap_um']:>9.3f}{r['tag_finest_detail_um']:>10.3f}")
    for d, r in res.items():
        print(f"\n  {d}: gaps {{" + ", ".join(f"{k}: {v:.3f}" for k, v in sorted(r['min_gap'].items())) + "}")
        print(f"     box mesh {r['mesh_box']['triangles']:,} tris, closed {r['mesh_box']['edges_even']:.0%}, "
              f"edges shared by exactly 2 faces {r['mesh_box']['edges_two']:.1%} · merged {r['mesh_merged']['triangles']:,} tris, "
              f"closed {r['mesh_merged']['edges_even']:.0%}, exactly-2 {r['mesh_merged']['edges_two']:.1%}")
        print(f"     test box: {r['test_box']['size_um']:.1f} um, {r['test_box']['dots']} dots, {r['test_box']['mb']:.2f} MB")
        for k, v in r["checks"].items():
            print(f"    [{'PASS' if v else 'FAIL'}] {k}")

    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    names = ["reference"] + list(res); col = ["#888888", "#d1495b", "#edae49", "#00798c"]
    fig, ax = plt.subplots(1, 4, figsize=(16, 4), dpi=120)
    ax[0].bar(names, [ref["scan_m"]] + [r["scan_m"] for r in res.values()], color=col)
    ax[0].set_ylabel("laser scan length (m)"); ax[0].set_title("write time (proxy)", fontsize=9)
    ax[1].bar(names, [ref["islands"]] + [r["islands_total"] for r in res.values()], color=col)
    ax[1].set_ylabel("separate solids"); ax[1].set_title("islands to write", fontsize=9)
    ax[2].bar(names, [ref["min_gap_all"]] + [r["min_gap_all"] for r in res.values()], color=col)
    ax[2].axhline(ASSUMED["min_gap_um"], c="k", ls="--", lw=0.8); ax[2].set_ylabel("µm")
    ax[2].set_title("smallest gap between any two features", fontsize=9)
    ax[3].bar(names, [ref["dots"] / ref["scan_m"]] + [r["dots_per_scan_m"] for r in res.values()], color=col)
    ax[3].set_ylabel("dots per metre of scan"); ax[3].set_title("measurement points per unit write time", fontsize=9)
    for a in ax:
        a.grid(axis="y", alpha=.3); a.tick_params(axis="x", labelsize=8)
    fig.suptitle("S4 — printability of the three designs against the reference print", fontsize=10)
    fig.tight_layout(rect=[0, 0, 1, 0.94]); fig.savefig(os.path.join(V2, "designs", "docs", "S4_printability.png"))
    ok = all(r["passed"] for r in res.values())
    with open(os.path.join(V2, "designs", "docs", "S4_printability.json"), "w") as f:
        json.dump(dict(reference=ref, assumed_limits=ASSUMED, settings=dict(height=HEIGHT, hatch=HATCH, slice=SLICE),
                       designs=res), f, indent=1, default=float)
    print(f"\n  S4 GATE: {'PASS' if ok else 'FAIL'}   ({time.time()-t0:.0f} s)")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
