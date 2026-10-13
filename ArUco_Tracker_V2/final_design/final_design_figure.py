#!/usr/bin/env python3
"""
final_design_figure.py — the final Nanoscribe design (Rev D, OPT) tested in ONE figure.

Builds the OPT pattern with the production generator, renders it, images it through
the Phase-B camera model at lambda = 1 ... 6 (reference without warp, expanded frames
with a 2 um non-uniform field, rotation, drift, lens, vignette, L2 noise, exposure
compensated), runs the PRODUCTION pipeline (rwtag.aruco -> identity pairing) and
scores it against the injected truth. Panels:

  a  the print (750 x 750 um)              b  one box: tags, dashes, dots
  c  camera frame, lambda 1 (tags decoded) d  camera frame, lambda 4 (tags decoded)
  e  tags decoded and dots tagged vs lambda
  f  expansion recovered vs injected (pipeline error, gel dilation)
  g  strain field E_xx at lambda 3: recovered vs true

Run:  python final_design_figure.py [--variant optimistic]
      -> final_design/<variant>_one_figure.png + .json (+ copies of the CAD files)
"""
from __future__ import annotations
import argparse
import contextlib
import io
import json
import os
import shutil
import sys
import time

import numpy as np
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
V2 = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(V2, "tools"))
sys.path.insert(0, os.path.join(V2, "workshop", "scripts"))
sys.path.insert(0, os.path.normpath(os.path.join(V2, "..", "Reference_Warp_Tagger")))
from aruco_grid import build                                                   # noqa: E402
import simulate_v2 as V                                                        # noqa: E402
from phase_c_verify import cand_cfg, design_of, stage1, truth, NOISE           # noqa: E402
from phase_d_end_to_end import similarity, R_STRAIN                            # noqa: E402
from w8_lattice_density_field import local_strain                              # noqa: E402
from rwtag.aruco import ArucoParams, series as AS                              # noqa: E402
from rwtag import pairing as PR                                                # noqa: E402
from rwtag.glyph import stl_glyphs as sg                                       # noqa: E402

LAMS = [1.0, 1.5, 2.0, 3.0, 4.0, 6.0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="optimistic")
    a = ap.parse_args()
    t0 = time.time()
    name = {"optimistic": "OPT", "hedge": "HEDGE", "conservative": "SAFE"}[a.variant]
    gcfg = cand_cfg(a.variant)
    with contextlib.redirect_stdout(io.StringIO()):
        _r, recs, info = build(gcfg)
    design = design_of(gcfg, recs, info)
    islands = info["islands"]
    dot_recs = [r for r in recs if r["category"] == "dot"]
    tag_recs = [r for r in recs if r["category"] == "aruco"]
    X_by_tag = {r["tag"]: np.array([r["x_um"], r["y_um"]]) for r in dot_recs}

    # --- CAD copies next to the figure ------------------------------------------
    for ext in (".stl", "_merged.stl", ".reference_tags.json", ".ids.json", ".verify.json"):
        src = os.path.join(V2, "cad", f"aruco_grid_{a.variant}{ext}")
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(HERE, os.path.basename(src)))

    # --- design renders ---------------------------------------------------------
    stl = os.path.join(V2, "cad", f"aruco_grid_{a.variant}.stl")
    full, _tp, _tu, _ = sg.render_topdown(stl, px_per_um=2.0)
    box, _tp, _tu, _ = sg.render_topdown(stl, px_per_um=8.0)
    o = gcfg.origin; P = gcfg.box_pitch
    x0, y0 = o + 2 * P - gcfg.tag_um * 0.7, o + 2 * P - gcfg.tag_um * 0.7      # box (2,2) + its tags
    side = P + 1.4 * gcfg.tag_um
    H8 = box.shape[0]
    box_crop = box[int(H8 - (y0 + side) * 8):int(H8 - y0 * 8), int(x0 * 8):int((x0 + side) * 8)]

    # --- synthetic series through the production pipeline -----------------------
    sim = V.SimConfig(); sim.signal_exp = 0.0
    sim0 = V.SimConfig(); sim0.signal_exp = 0.0; sim0.warp_amp_um = 0.0
    lobes, lobes0 = V.make_lobes(gcfg.field_um, sim), V.make_lobes(gcfg.field_um, sim0)
    band_um = abs(sim.lens_k1) * sim.fov_um / 2.0 * 1.4
    params = ArucoParams(um_per_px=sim.um_per_px, psf_fwhm_um=gcfg.psf_fwhm_um, edge_band_um=band_um)
    lv = V.Level("F", gcfg.psf_fwhm_um, NOISE["read_noise"], NOISE["full_well"], NOISE["background"])
    drng = np.random.default_rng(sim.drift_seed + 7)
    frames, tr_dots, tr_tags = [], {}, {}
    for k, lam in enumerate(LAMS):
        s_, lb = (sim0, lobes0) if lam == 1.0 else (sim, lobes)
        theta = sim.rotation_deg + k * sim.rotation_step_deg
        drift = drng.uniform(-sim.drift_um, sim.drift_um, 2)
        rects, _tc, _tid = V.place(islands, lam, s_, lb, gcfg.field_um, drift)
        img = V.degrade(V.render_scene(rects, s_, theta), s_, lv, np.random.default_rng(100 + k), lam=None)
        frames.append((lam, stage1(img, s_)))
        Td, okd, _ = truth(islands, "dot", lam, s_, gcfg, lb, theta, drift)
        Ta, oka, _ = truth(islands, "aruco", lam, s_, gcfg, lb, theta, drift)
        tr_dots[lam] = ({r["tag"]: Td[i] for i, r in enumerate(dot_recs)}, int(okd.sum()))
        tr_tags[lam] = {int(r["meta"]["aruco_id"]) for r, ok in zip(tag_recs, oka) if ok}
    sf = AS.process_frames(frames, design, params)
    assert all(f.ok for f in sf), [(f.label, f.reason) for f in sf if not f.ok]
    ref = sf[0]

    rows, strain_panel = [], None
    for f in sf:
        lam = f.label
        m = f.det.model
        truth_px, n_in = tr_dots[lam]
        dots = [(t, xy) for t, xy in f.tags.items() if t.startswith("dot|")]
        err = np.array([np.hypot(*(np.array(xy) - truth_px[t])) for t, xy in dots])
        row = dict(lam=lam, tags_in=len(tr_tags[lam]), tags_dec=len(set(m["aruco_xy"]) & tr_tags[lam]),
                   dots_in=n_in, tagged=len(dots), correct=float((err < 3).mean()),
                   recovered=float((err < 3).sum() / n_in), rms_px=float(np.sqrt(np.mean(err[err < 3] ** 2))))
        if lam > 1.0:
            pairs = PR.pair_tags(ref.tags, f.tags, kinds=("dot",))
            tags = sorted(pairs)
            X = np.array([X_by_tag[t] for t in tags]); Y = np.array([pairs[t][2:] for t in tags])
            s, R, t, hand = similarity(X, Y)
            Tpx = np.array([truth_px[t] for t in tags]); s_t, R_t, t_t, _ = similarity(X, Tpx)
            w_rec = ((Y - t) @ R) / s - X; w_true = ((Tpx - t_t) @ R_t) / s_t - X
            row.update(paired=len(pairs), lam_rec=s * sim.um_per_px, lam_eff=s_t * sim.um_per_px,
                       pipe_err=s / s_t - 1, gel=s_t * sim.um_per_px / lam - 1, handedness=hand,
                       warp_err_um=float(np.sqrt(np.mean(np.sum((w_rec - w_true) ** 2, 1)))))
            if lam == 3.0:
                E, N = local_strain(X, X + w_rec, R_STRAIN); Et, _ = local_strain(X, X + w_true, R_STRAIN)
                g = np.isfinite(E[:, 0]) & np.isfinite(Et[:, 0]) & (N >= 30)
                strain_panel = (X[g], E[g, 0], Et[g, 0], float(np.sqrt(np.mean((E[g] - Et[g]) ** 2))))
        rows.append(row)

    # --- figure -------------------------------------------------------------------
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import gridspec
    fig = plt.figure(figsize=(17, 9.6), dpi=120)
    gs = gridspec.GridSpec(2, 4, figure=fig, height_ratios=[1.15, 1], hspace=0.32, wspace=0.28)

    ax = fig.add_subplot(gs[0, 0]); ax.imshow(full, cmap="gray", extent=[0, 750, 0, 750]); ax.set_title(
        f"a  the print — {name}, 750 × 750 µm\n36 ArUco tags ({gcfg.tag_um:g} µm) · "
        f"{sum(r['category']=='dash' for r in recs)} dashes · {len(dot_recs):,} dots", fontsize=8.5)
    ax.set_xlabel("µm"); ax.set_ylabel("µm")
    ax = fig.add_subplot(gs[0, 1]); ax.imshow(box_crop, cmap="gray", extent=[0, side, 0, side]); ax.set_title(
        f"b  one box\n{gcfg.dot_side_um} µm dots at {gcfg.dot_pitch_um:.2f} µm pitch, "
        f"{gcfg.quiet_zone_um:.1f} µm clear of tags/dashes", fontsize=8.5)
    ax.set_xlabel("µm"); ax.set_yticks([])
    for col, lam in ((2, 1.0), (3, 4.0)):
        f = sf[LAMS.index(lam)]
        ax = fig.add_subplot(gs[0, col]); ax.imshow(f.det.u8, cmap="gray", vmin=0, vmax=255)
        for aid, tg in f.det.model["tags"].items():
            c = tg["corners"]; ax.plot(np.r_[c[:, 0], c[0, 0]], np.r_[c[:, 1], c[0, 1]], "-", c="#ffb000", lw=0.9)
            ax.text(c[:, 0].mean(), c[:, 1].min() - 14, str(aid), color="#ffb000", fontsize=6, ha="center")
        r = rows[LAMS.index(lam)]
        ax.set_title(f"{'c' if col == 2 else 'd'}  camera frame, λ = {lam:g}  (1365 µm field, 0.51 µm/px, PSF {gcfg.psf_fwhm_um} µm)\n"
                     f"{r['tags_dec']}/{r['tags_in']} tags decoded · {r['tagged']:,} dots tagged, {r['correct']:.0%} correct", fontsize=8.5)
        ax.set_xticks([]); ax.set_yticks([])

    L = [r["lam"] for r in rows]
    ax = fig.add_subplot(gs[1, 0])
    ax.plot(L, [r["tags_dec"] / max(r["tags_in"], 1) for r in rows], "o-", label="tags decoded / in frame")
    ax.plot(L, [r["recovered"] for r in rows], "s-", label="dots tagged / in frame")
    ax.plot(L, [r["correct"] for r in rows], "^:", label="tag correctness")
    ax.set_ylim(0, 1.05); ax.set_xlabel("λ"); ax.grid(alpha=.3); ax.legend(fontsize=7, loc="lower left")
    ax.set_title("e  decode and tagging vs expansion", fontsize=9)
    for r in rows:
        ax.annotate(f"{r['tagged']:,}", (r["lam"], r["recovered"]), textcoords="offset points", xytext=(0, 5), fontsize=6, ha="center")

    ax = fig.add_subplot(gs[1, 1])
    ex = [r for r in rows if "lam_rec" in r]
    ax.plot([r["lam"] for r in ex], [100 * r["pipe_err"] for r in ex], "o-", label="pipeline: λ_rec / λ_eff − 1")
    ax.plot([r["lam"] for r in ex], [100 * r["gel"] for r in ex], "s:", label="gel: λ_eff / λ − 1 (injected field)")
    ax.axhline(0, c="k", lw=0.6); ax.set_xlabel("λ"); ax.set_ylabel("%"); ax.grid(alpha=.3); ax.legend(fontsize=7)
    ax.set_title("f  expansion factor recovered (Phase D)", fontsize=9)
    for r in ex:
        ax.annotate(f"{r['lam_rec']:.4f}", (r["lam"], 100 * r["pipe_err"]), textcoords="offset points", xytext=(0, -11), fontsize=6, ha="center")

    Xs, Er, Et, e_rms = strain_panel
    vmax = float(np.percentile(np.abs(Et), 99))
    for col, (vals, ttl) in enumerate(((Er, "recovered"), (Et, "true"))):
        ax = fig.add_subplot(gs[1, 2 + col])
        sc = ax.scatter(Xs[:, 0], Xs[:, 1], c=vals, s=3, cmap="RdBu_r", vmin=-vmax, vmax=vmax)
        ax.set_aspect("equal"); ax.set_xlim(0, 750); ax.set_ylim(0, 750); ax.set_xlabel("µm")
        ax.set_title(f"g  Green strain E_xx, λ = 3, R = 25 µm\n{ttl}" + (f"  (RMS error {e_rms:.4f})" if col == 0 else ""), fontsize=8.5)
        if col == 1:
            fig.colorbar(sc, ax=ax, fraction=0.046, pad=0.03)
    r6 = rows[-1]
    fig.suptitle(f"Final Nanoscribe design — Rev D {name}: tag {gcfg.tag_um:g} µm · dot {gcfg.dot_side_um} µm at "
                 f"{gcfg.dot_pitch_um:.2f} µm · {len(dot_recs):,} dots (V1: 6,420)\n"
                 f"tested end to end through the camera model and the production pipeline: "
                 f"{r6['tags_dec']}/{r6['tags_in']} tags and {r6['tagged']:,} dots still tagged at 6×, "
                 f"λ recovered to {100*max(abs(r['pipe_err']) for r in ex):.3f}%, strain to {e_rms:.4f}",
                 fontsize=11)
    out = os.path.join(HERE, f"{a.variant}_one_figure.png")
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)
    with open(os.path.join(HERE, f"{a.variant}_one_figure.json"), "w") as fh:
        json.dump(dict(variant=a.variant, tag_um=gcfg.tag_um, psf=gcfg.psf_fwhm_um, pitch_um=gcfg.dot_pitch_um,
                       n_dots=len(dot_recs), rows=rows, strain_rms_err=e_rms), fh, indent=1, default=float)
    print(f"{'λ':>5}{'tags':>8}{'dots in':>9}{'tagged':>8}{'correct':>9}{'λ rec':>9}{'pipe':>9}{'gel':>8}")
    for r in rows:
        print(f"{r['lam']:>5.1f}{r['tags_dec']:>4}/{r['tags_in']:<3}{r['dots_in']:>9,}{r['tagged']:>8,}{r['correct']:>9.1%}"
              + (f"{r['lam_rec']:>9.4f}{100*r['pipe_err']:>+8.3f}%{100*r['gel']:>+7.2f}%" if "lam_rec" in r else ""))
    print(f"strain RMS err at λ=3, R=25: {e_rms:.4f}\nwrote {out}  ({time.time()-t0:.0f} s)")


if __name__ == "__main__":
    main()
