#!/usr/bin/env python3
"""
s3_recognition.py — spacing-workshop phase S3: what the microscope can recognise.

QUESTION
    For each design (dot 2.125 um at 5 / 6 / 7 um, 23 um tags): up to what BLUR does
    the production pipeline still recognise it, at every expansion? This replaces the
    predicted "largest blur tolerated" of 01_DESIGN_PARAMETERS.md with a measurement,
    and measures the cost of keeping the tag at 23 um.

METHOD
    Each design is rendered through the Phase-B camera model (0.51 um/px, 1365 um
    field, lens, vignette, rotation, drift, 2 um non-uniform warp, L2 noise, exposure
    compensated as W6 requires) at lambda 1 ... 6, two seeds. Every render is then
    blurred at each PSF of the ladder, Stage-1 corrected, and run through
    rwtag.aruco.detect -> refwarp.tagframe (the production path, detector told the
    true PSF), and scored against the simulator's truth:

      recognised   dots given their CORRECT tag / dots in the frame
      tags         decoded / in frame;  registered = the frame got a design->image fit
      correct      tagged dots whose tag is right (mis-tagging check)

CRITERIA, per design and blur (all frames, both seeds)
    PASS      every frame registers · worst-frame recognised >= 90% · correct >= 99%
    MARGINAL  every frame registers · worst-frame recognised >= 80%
    FAIL      otherwise
    measured limit = the largest blur of the ladder up to which the design PASSES
    without interruption.

Run:  python s3_recognition.py [--quick]
      -> designs/docs/S3_recognition.{json,png}, designs/<n>_<name>/recognition.png
"""
from __future__ import annotations
import argparse
import contextlib
import io
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
V2 = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(V2, "..", "Reference_Warp_Tagger")))
from aruco_grid import GridConfig, SPACING_DESIGNS, build                       # noqa: E402
import simulate_v2 as V                                                         # noqa: E402
from phase_c_verify import design_of, stage1, score_frame, NOISE                # noqa: E402
from rwtag.aruco import ArucoParams                                             # noqa: E402
from build_designs import FOLDERS                                               # noqa: E402

LAMS = [1.0, 1.5, 2.0, 3.0, 4.0, 6.0]
PSFS = [1.5, 1.7, 1.9, 2.1, 2.3, 2.5, 2.7, 2.9, 3.1, 3.4, 3.7, 4.0]
TODAY = (2.7, 3.2)            # blur measured on the real series (0b: edge / dot methods)
FIXED = 1.9                   # blur expected once the focus is flattened (0b)


def verdict(cells):
    reg = all(c["registered"] for c in cells)
    worst = min(c["recovered"] for c in cells)
    corr = min(c["tag_correct"] for c in cells if c["registered"]) if reg else 0.0
    if reg and worst >= 0.90 and corr >= 0.99:
        return "PASS"
    if reg and worst >= 0.80:
        return "MARGINAL"
    return "FAIL"


def run(design, lams, psfs, seeds):
    gcfg = GridConfig(**SPACING_DESIGNS[design])
    with contextlib.redirect_stdout(io.StringIO()):
        _r, recs, info = build(gcfg)
    dsg = design_of(gcfg, recs, info)
    islands = info["islands"]
    sim = V.SimConfig(); sim.signal_exp = 0.0
    lobes = V.make_lobes(gcfg.field_um, sim)
    band = abs(sim.lens_k1) * sim.fov_um / 2.0 * 1.4
    thetas = [sim.rotation_deg + k * sim.rotation_step_deg for k in range(len(LAMS))]
    cells = {p: [] for p in psfs}
    for seed in seeds:
        drng = np.random.default_rng(sim.drift_seed + 101 * seed)
        for lam in LAMS:
            drift = drng.uniform(-sim.drift_um, sim.drift_um, 2)
            if lam not in lams:
                continue
            k = LAMS.index(lam)
            rects, _tc, _tid = V.place(islands, lam, sim, lobes, gcfg.field_um, drift)
            base = V.render_scene(rects, sim, thetas[k])
            for p in psfs:
                lv = V.Level("S3", p, NOISE["read_noise"], NOISE["full_well"], NOISE["background"])
                img = V.degrade(base, sim, lv, np.random.default_rng(1000 * seed + 10 * k + int(10 * p)), lam=None)
                prm = ArucoParams(um_per_px=sim.um_per_px, psf_fwhm_um=p, edge_band_um=band)
                row, _det, _tr = score_frame(stage1(img, sim), dsg, prm, recs, islands, lam, sim, gcfg,
                                             lobes, thetas[k], drift)
                row.update(seed=seed, psf=p)
                cells[p].append({k2: row.get(k2) for k2 in (
                    "seed", "psf", "lam", "registered", "tags_in", "tags_dec", "dots_in", "n_det",
                    "n_assigned", "tag_correct", "recovered", "rms_px", "affine_method")})
    out = dict(design=design, pitch_um=gcfg.dot_pitch_um, dot_um=gcfg.dot_side_um, tag_um=gcfg.tag_um,
               psf_max_predicted=gcfg.psf_max_um(), tag_psf_limit_predicted=gcfg.module_um / 1.45,
               per_psf=[])
    for p in psfs:
        c = cells[p]
        out["per_psf"].append(dict(
            psf=p, verdict=verdict(c), registered=sum(x["registered"] for x in c), frames=len(c),
            recognised_worst=min(x["recovered"] for x in c),
            recognised_mean=float(np.mean([x["recovered"] for x in c])),
            recognised_l1=float(np.mean([x["recovered"] for x in c if x["lam"] == min(lams)])),
            correct_worst=min(x["tag_correct"] for x in c),
            tag_decode_mean=float(np.mean([x["tags_dec"] / max(x["tags_in"], 1) for x in c])),
            tag_decode_worst=min(x["tags_dec"] / max(x["tags_in"], 1) for x in c),
            tags_min=min(x["tags_dec"] for x in c),
            by_lam={str(l): float(np.mean([x["recovered"] for x in c if x["lam"] == l])) for l in lams},
            tags_by_lam={str(l): float(np.mean([x["tags_dec"] / max(x["tags_in"], 1) for x in c if x["lam"] == l]))
                         for l in lams},
            cells=c))
    lim = None
    for r in out["per_psf"]:
        if r["verdict"] != "PASS":
            break
        lim = r["psf"]
    out["psf_max_measured"] = lim
    lim_m = None
    for r in out["per_psf"]:
        if r["verdict"] == "FAIL":
            break
        lim_m = r["psf"]
    out["psf_max_marginal"] = lim_m
    # tag limit on its own: largest blur with mean decode >= 95% and every frame >= 1 tag
    tl = None
    for r in out["per_psf"]:
        if not (r["tag_decode_mean"] >= 0.95 and r["tags_min"] >= 1):
            break
        tl = r["psf"]
    out["tag_psf_limit_measured"] = tl
    return out


def figures(res, lams, psfs):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    col = {"optimistic": "#d1495b", "medium": "#edae49", "conservative": "#00798c"}
    # --- combined --------------------------------------------------------------
    fig, ax = plt.subplots(1, 3, figsize=(16, 4.6), dpi=120)
    for d, r in res.items():
        P = [x["psf"] for x in r["per_psf"]]
        ax[0].plot(P, [x["recognised_worst"] for x in r["per_psf"]], "o-", c=col[d],
                   label=f"{d} ({r['pitch_um']:.0f} µm)")
        ax[0].axvline(r["psf_max_predicted"], c=col[d], ls=":", lw=1)
        ax[1].plot(P, [x["tag_decode_mean"] for x in r["per_psf"]], "o-", c=col[d], label=d)
        ax[1].plot(P, [x["tag_decode_worst"] for x in r["per_psf"]], ":", c=col[d], lw=1)
        ax[2].plot(P, [x["by_lam"][str(min(lams))] for x in r["per_psf"]], "o-", c=col[d], label=f"{d}, λ = {min(lams):g}")
        ax[2].plot(P, [x["by_lam"][str(max(lams))] for x in r["per_psf"]], "s--", c=col[d], lw=1, label=f"{d}, λ = {max(lams):g}")
    for a in ax:
        a.axvspan(*TODAY, color="grey", alpha=0.15); a.axvline(FIXED, c="k", ls="--", lw=0.7)
        a.set_xlabel("blur — PSF FWHM (µm)"); a.set_ylim(0, 1.03); a.grid(alpha=.3); a.legend(fontsize=7)
    ax[0].axhline(0.9, c="k", lw=0.6); ax[0].set_ylabel("dots recognised, worst frame")
    ax[0].set_title("dots: worst frame over λ 1–6   (dotted: predicted limit)", fontsize=9)
    ax[1].axhline(0.95, c="k", lw=0.6); ax[1].set_ylabel("tags decoded / in frame")
    ax[1].set_title("23 µm tags: mean (solid) and worst frame (dotted)", fontsize=9)
    ax[2].set_ylabel("dots recognised"); ax[2].set_title("dense reference frame vs most expanded frame", fontsize=9)
    fig.suptitle("S3 — what the pipeline recognises vs blur   (grey band: blur measured today · dashed: after focus fix)",
                 fontsize=10)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(os.path.join(V2, "designs", "docs", "S3_recognition.png")); plt.close(fig)
    # --- per design ------------------------------------------------------------
    for d, r in res.items():
        M = np.array([[x["by_lam"][str(l)] for x in r["per_psf"]] for l in lams])
        T = np.array([[x["tags_by_lam"][str(l)] for x in r["per_psf"]] for l in lams])
        fig, ax = plt.subplots(1, 3, figsize=(16, 4.4), dpi=120, gridspec_kw=dict(width_ratios=[1.2, 1.2, 1]))
        for a, A, ttl in ((ax[0], M, "dots recognised"), (ax[1], T, "tags decoded / in frame")):
            im = a.imshow(A, vmin=0, vmax=1, cmap="RdYlGn", aspect="auto", origin="lower")
            a.set_xticks(range(len(psfs))); a.set_xticklabels([f"{p:g}" for p in psfs], fontsize=7)
            a.set_yticks(range(len(lams))); a.set_yticklabels([f"{l:g}×" for l in lams])
            a.set_xlabel("blur — PSF FWHM (µm)"); a.set_ylabel("expansion λ"); a.set_title(ttl, fontsize=9)
            for i in range(A.shape[0]):
                for j in range(A.shape[1]):
                    a.text(j, i, f"{100*A[i, j]:.0f}", ha="center", va="center", fontsize=6.5)
            fig.colorbar(im, ax=a, fraction=0.046, pad=0.02)
        P = [x["psf"] for x in r["per_psf"]]
        ax[2].plot(P, [x["recognised_worst"] for x in r["per_psf"]], "o-", c=col[d], label="dots, worst frame")
        ax[2].plot(P, [x["tag_decode_mean"] for x in r["per_psf"]], "s--", c="k", lw=1, label="tags, mean")
        ax[2].axvline(r["psf_max_predicted"], c=col[d], ls=":", label=f"predicted dot limit {r['psf_max_predicted']:.2f}")
        if r["psf_max_measured"]:
            ax[2].axvline(r["psf_max_measured"], c=col[d], lw=2, alpha=.5, label=f"measured limit {r['psf_max_measured']:g}")
        ax[2].axvspan(*TODAY, color="grey", alpha=0.15, label="blur today")
        ax[2].axhline(0.9, c="k", lw=0.6); ax[2].set_ylim(0, 1.03); ax[2].grid(alpha=.3)
        ax[2].set_xlabel("blur — PSF FWHM (µm)"); ax[2].legend(fontsize=7); ax[2].set_title("limits", fontsize=9)
        fig.suptitle(f"{d}: dot {r['dot_um']} µm at {r['pitch_um']:.2f} µm, tag {r['tag_um']:g} µm — "
                     f"recognised by the production pipeline (2 seeds)", fontsize=10)
        fig.tight_layout(rect=[0, 0, 1, 0.93])
        fig.savefig(os.path.join(V2, "designs", FOLDERS[d], "recognition.png")); plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    lams = [1.0, 3.0, 6.0] if a.quick else LAMS
    psfs = [1.9, 2.7, 3.4] if a.quick else PSFS
    seeds = [0] if a.quick else [0, 1]
    t0 = time.time()
    res = {}
    for d in SPACING_DESIGNS:
        res[d] = run(d, lams, psfs, seeds)
        r = res[d]
        print(f"\n=== {d.upper()}  dot {r['dot_um']} um at {r['pitch_um']:.2f} um · tag {r['tag_um']:g} um · "
              f"predicted dot limit {r['psf_max_predicted']:.2f} · predicted tag limit {r['tag_psf_limit_predicted']:.2f} ===")
        print(f"{'PSF':>5}{'verdict':>10}{'reg':>7}{'dots worst':>12}{'dots mean':>11}{'dots λ1':>9}"
              f"{'correct':>9}{'tags mean':>11}{'tags worst':>12}{'min tags':>10}")
        for x in r["per_psf"]:
            print(f"{x['psf']:>5.1f}{x['verdict']:>10}{x['registered']:>4}/{x['frames']:<2}{x['recognised_worst']:>12.1%}"
                  f"{x['recognised_mean']:>11.1%}{x['recognised_l1']:>9.1%}{x['correct_worst']:>9.1%}"
                  f"{x['tag_decode_mean']:>11.1%}{x['tag_decode_worst']:>12.1%}{x['tags_min']:>10}")
        print(f"  measured limit: PASS to {r['psf_max_measured']} um · MARGINAL to {r['psf_max_marginal']} um · "
              f"tags alone to {r['tag_psf_limit_measured']} um   ({(time.time()-t0)/60:.1f} min)", flush=True)
    if not a.quick:
        with open(os.path.join(V2, "designs", "docs", "S3_recognition.json"), "w") as f:
            json.dump(dict(lams=lams, psfs=psfs, seeds=seeds, today=TODAY, after_focus_fix=FIXED, designs=res),
                      f, indent=1, default=float)
        figures(res, lams, psfs)
        print("\nwrote designs/docs/S3_recognition.{json,png} and recognition.png in each design folder")
    print(f"done in {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
