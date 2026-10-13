#!/usr/bin/env python3
"""
w9_candidate_montage.py — Workshop W9 (Rev D, Phase 4). THE DECISION TABLE.

QUESTION
    Which candidate works at which actual PSF? Each candidate is a PRINT sized
    for its design PSF (OPT 1.91, HEDGE 2.50, SAFE 3.18 um). Phase 1 will reveal
    the PSF the microscope actually delivers after the best focus. Cross the
    two: rows = the print, columns = the PSF at acquisition.

METHOD
    For every (candidate, actual PSF): lambda = 1..6 through the Phase-B
    simulator (real stitch FOV, drift, accumulating rotation, L2 noise,
    exposure ~ lambda^2 so brightness is fully compensated), the Phase-2
    detector settings (no CLAHE, errorCorrectionRate = 1.0, un-distortion edge
    band), and the production dot detector on un-distorted frames matched to
    lens-free ground truth (W8). Actual PSFs: 1.91, 2.50, 3.18 (measured) and
    3.80 (20% worse than measured, the stress case).

    Per cell:  tag decode min-per-frame and mean over lambda; dot efficiency in
    the WORST frame (the reference frame is the densest and breaks first); usable
    dots at lambda = 6. Two seeds with independent drift and noise.
    Cell verdict (Phase-B gate):  PASS = >= 4 tags in every frame, mean decode
    >= 90%, dot efficiency >= 90%;  MARGINAL = >= 1 tag in every frame (the
    plan's literal 1.2x criterion) and dot efficiency >= 80%;  FAIL otherwise.
    Dot efficiency is scored one-to-one (W8), so merged pairs count as lost.

    Decision rule (WORKSHOP_PLAN.md section 5), applied per PSF column: the
    most optimistic candidate that PASSES at that PSF and is at least MARGINAL
    at 1.2 x that PSF (next column up).

Run:  python w9_candidate_montage.py [--quick]
"""
from __future__ import annotations
import argparse
import contextlib
import io
import json
import math
import os
import sys
import time

import numpy as np
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "tools")))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "..", "Reference_Warp_Tagger")))
from aruco_grid import GridConfig, VARIANTS, build                          # noqa: E402
import simulate_v2 as V                                                     # noqa: E402
from rwtag.glyph import lattice as lt                                       # noqa: E402
from scipy.spatial import cKDTree                                           # noqa: E402
from w3_tag_integrity import detector                                       # noqa: E402

FIG_DIR = os.path.normpath(os.path.join(HERE, "..", "figures"))
OUT_JSON = os.path.join(FIG_DIR, "w9_candidate_montage.json")
CANDS = [("OPT", "optimistic"), ("HEDGE", "hedge"), ("SAFE", "conservative")]
PSFS = [1.91, 2.50, 3.18, 3.80]
LAMS = [1, 2, 3, 4, 5, 6]
NOISE = dict(read_noise=6.0, full_well=240.0, background=14.0)
AREA = (12, 220)


def cand_cfg(variant):
    v = VARIANTS[variant]
    return GridConfig(dict_name="DICT_4X4_50", tag_modules=6, tag_um=v["tag_um"],
                      psf_fwhm_um=v["psf_fwhm_um"], dot_side_um=2.125, dashes=True,
                      round_tags=True, fit="inside", field_um=750.0)


def geometry(islands, lam, sim, gcfg, lobes, theta, drift):
    """Tag and dot truth in the final frame: tags through the forward lens (they are
    decoded on the distorted frame, decode() un-distorts internally); dots WITHOUT
    the lens (they are detected on the un-distorted frame). Both with the W3 edge band."""
    rfov = sim.fov_um * sim.render_margin
    P0 = np.array([gcfg.field_um / 2.0, gcfg.field_um / 2.0])
    centre = np.array([rfov / 2.0, rfov / 2.0]) + np.asarray(drift, float)
    M = cv2.getRotationMatrix2D((rfov / 2, rfov / 2), theta, 1.0)
    lo = (rfov - sim.fov_um) / 2
    band = abs(sim.lens_k1) * sim.fov_um / 2.0 * 1.4
    out = {}
    for kind in ("aruco", "dot"):
        C = np.array([[i["cx"], i["cy"]] for i in islands if i["kind"] == kind], float)
        Cd = centre + lam * (C - P0) + V.warp_disp(C, lobes, sim.warp_sigma_um) * lam
        T = np.column_stack([Cd[:, 0], rfov - Cd[:, 1]])
        R = T @ M[:, :2].T + M[:, 2]
        if kind == "aruco":
            R = V.lens_forward(R, sim, sim.fov_um / 2.0, centre=(rfov / 2, rfov / 2))
            t = math.radians(theta)
            m = (gcfg.tag_um / 2) * (abs(math.cos(t)) + abs(math.sin(t))) + gcfg.module_um + band
        else:
            m = band
        ok = ((R[:, 0] > lo + m) & (R[:, 0] < lo + sim.fov_um - m) &
              (R[:, 1] > lo + m) & (R[:, 1] < lo + sim.fov_um - m))
        out[kind] = (R[ok] - lo) / sim.um_per_px - 0.5, ok
    ids = [i["aruco_id"] for i in islands if i["kind"] == "aruco"]
    out["tag_ids"] = {ids[j] for j in np.nonzero(out["aruco"][1])[0]}
    return out


def run_cell(cname, variant, psf, lams, sim_base, det, seeds=(0, 1)):
    gcfg = cand_cfg(variant)
    with contextlib.redirect_stdout(io.StringIO()):
        _r, _recs, info = build(gcfg)
    islands = info["islands"]
    sim = V.SimConfig(); sim.render_margin = sim_base.render_margin; sim.signal_exp = 0.0
    lobes = V.make_lobes(gcfg.field_um, sim)
    thetas = [sim.rotation_deg + k * sim.rotation_step_deg for k in range(6)]
    lv = V.Level("w9", psf, NOISE["read_noise"], NOISE["full_well"], NOISE["background"])
    rows = []
    # each seed gets its OWN drift sequence (pattern placement in the frame) as well
    # as its own noise, so a single lucky/unlucky placement at high lambda -- where
    # only a few hundred dots are in frame -- cannot decide a cell
    for seed in seeds:
      drng = np.random.default_rng(sim.drift_seed + 101 * seed)
      for lam in lams:
        k = LAMS.index(lam)
        drift = drng.uniform(-sim.drift_um, sim.drift_um, 2)
        rects, _tc, _tid = V.place(islands, float(lam), sim, lobes, gcfg.field_um, drift)
        base = V.render_scene(rects, sim, thetas[k])
        img = V.degrade(base, sim, lv, np.random.default_rng(k + 10 * seed), lam=None)   # fully compensated
        g = geometry(islands, float(lam), sim, gcfg, lobes, thetas[k], drift)
        found = V.decode(img, sim, det, None)
        n_tag = len(g["tag_ids"]); dec = len(found & g["tag_ids"])
        und = V._radial(img, sim.lens_k1, sim.lens_k2, sim.fov_px / 2.0, inverse=True)
        pts = lt.detect_dots(und, tophat=15, dot_area=AREA)
        truth = g["dot"][0]
        # ONE-TO-ONE matching (as W8). Nearest-detection matching lets two dots that
        # merged into one blob both count as detected through the shared centroid --
        # precisely the failure that appears when a print is imaged at a worse PSF
        # than it was designed for, so it must not be hidden here.
        eff = 0.0
        if len(pts) and len(truth):
            d, j = cKDTree(pts).query(truth)
            used, hits = set(), 0
            for i in np.argsort(d):
                if d[i] < 3.0 and int(j[i]) not in used:
                    used.add(int(j[i])); hits += 1
            eff = hits / len(truth)
        rows.append(dict(seed=seed, lam=lam, tags_in=n_tag, tags_dec=dec, dots_in=int(len(truth)), dot_eff=eff))
    tag_rates = [r["tags_dec"] / max(r["tags_in"], 1) for r in rows]
    l6 = [r for r in rows if r["lam"] == max(lams)]
    # The dot criterion uses the WORST frame, not the mean over lambda. The mean hid
    # that an off-design print loses most of its dots in the REFERENCE frame
    # (lambda = 1, the densest) -- OPT imaged at 3.18 um kept 36% there while
    # averaging 86% -- and a pattern whose reference is two-thirds empty is not
    # marginal, it is unusable, however well its tags decode.
    cell = dict(rows=rows, tag_min=min(r["tags_dec"] for r in rows),
                tag_mean=float(np.mean(tag_rates)),
                dot_eff=float(np.mean([r["dot_eff"] for r in rows])),
                dot_eff_min=float(min(r["dot_eff"] for r in rows)),
                dot_eff_l1=float(np.mean([r["dot_eff"] for r in rows if r["lam"] == 1])) if any(r["lam"] == 1 for r in rows) else float("nan"),
                dots_l6=int(np.mean([r["dots_in"] * r["dot_eff"] for r in l6])))
    if cell["tag_min"] >= 4 and cell["tag_mean"] >= 0.90 and cell["dot_eff_min"] >= 0.90:
        cell["verdict"] = "PASS"
    # MARGINAL = the plan's literal 1.2x-PSF criterion (registration survives: >= 1
    # tag in every frame) plus a usable-field floor: >= 80% of dots in EVERY frame.
    elif cell["tag_min"] >= 1 and cell["dot_eff_min"] >= 0.80:
        cell["verdict"] = "MARGINAL"
    else:
        cell["verdict"] = "FAIL"
    return cell


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    os.makedirs(FIG_DIR, exist_ok=True)
    t0 = time.time()
    cands = CANDS if not a.quick else CANDS[:1]
    psfs = PSFS if not a.quick else [1.91, 3.18]
    lams = LAMS if not a.quick else [1, 6]

    sim_base = V.SimConfig()
    th = math.radians(sim_base.rotation_deg + 5 * sim_base.rotation_step_deg)
    sim_base.render_margin = max(sim_base.render_margin,
                                 math.cos(th) + math.sin(th) + 2 * sim_base.drift_um / sim_base.fov_um + 0.02)
    det = detector(1.0)

    table = {}
    print("W9  rows = print (sized for its design PSF), columns = ACTUAL PSF at acquisition")
    print("cell: verdict · min tags/frame · mean tag decode · WORST-frame dot efficiency · usable dots at 6x (2 seeds)\n")
    hdr = f"{'':<8}" + "".join(f"{'PSF ' + str(p) + ' um':>34}" for p in psfs)
    print(hdr)
    for cname, variant in cands:
        table[cname] = {}
        line = f"{cname:<8}"
        for psf in psfs:
            c = run_cell(cname, variant, psf, lams, sim_base, det)
            table[cname][str(psf)] = c
            line += f"{c['verdict']:>10} {c['tag_min']:>2}t {c['tag_mean']:>4.0%} {c['dot_eff_min']:>4.0%} {c['dots_l6']:>6,}"
        print(line)

    # ---- decision rule, per actual-PSF column
    order = [c for c, _v in cands]                       # OPT first = most optimistic
    decision = {}
    print("\nDECISION (plan section 5): most optimistic print that PASSES at the actual PSF and is"
          "\n  at least MARGINAL one column up (~1.2x worse)")
    for i, psf in enumerate(psfs):
        nxt = psfs[i + 1] if i + 1 < len(psfs) else None
        pick = None
        for cname in order:
            c = table[cname][str(psf)]
            up_ok = (nxt is None) or table[cname][str(nxt)]["verdict"] in ("PASS", "MARGINAL")
            if c["verdict"] == "PASS" and up_ok:
                pick = cname; break
        decision[str(psf)] = pick
        print(f"  actual PSF {psf:4.2f} um -> print {pick if pick else 'NONE (no candidate passes)'}")

    # ---- figure: verdict grid with numbers
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    col = {"PASS": "#4caf50", "MARGINAL": "#ffb300", "FAIL": "#e53935"}
    fig, ax = plt.subplots(figsize=(2.6 * len(psfs) + 2, 1.3 * len(cands) + 2), dpi=110)
    for r, (cname, _v) in enumerate(cands):
        for cidx, psf in enumerate(psfs):
            c = table[cname][str(psf)]
            ax.add_patch(plt.Rectangle((cidx, len(cands) - 1 - r), 1, 1, color=col[c["verdict"]], alpha=.85))
            ax.text(cidx + .5, len(cands) - 1 - r + .5,
                    f"{c['verdict']}\nmin {c['tag_min']} tags · decode {c['tag_mean']:.0%}\n"
                    f"dots (worst frame) {c['dot_eff_min']:.0%} · {c['dots_l6']:,} @6x", ha="center", va="center", fontsize=8)
    for cidx, psf in enumerate(psfs):
        if decision[str(psf)]:
            r = order.index(decision[str(psf)])
            ax.add_patch(plt.Rectangle((cidx + .04, len(cands) - 1 - r + .04), .92, .92, fill=False, lw=3, ec="k"))
    ax.set_xlim(0, len(psfs)); ax.set_ylim(0, len(cands))
    ax.set_xticks([i + .5 for i in range(len(psfs))]); ax.set_xticklabels([f"actual PSF {p} um" for p in psfs])
    ax.set_yticks([len(cands) - 1 - i + .5 for i in range(len(cands))])
    ax.set_yticklabels([f"{c} print\n(tag {VARIANTS[v]['tag_um']:.0f} um, design PSF {VARIANTS[v]['psf_fwhm_um']})"
                        for c, v in cands], fontsize=8)
    ax.set_title("W9 — decision table (λ 1–6, exposure ∝ λ²); black box = §5 choice per column", fontsize=10)
    ax.tick_params(length=0)
    fig.tight_layout(); fig.savefig(os.path.join(FIG_DIR, "candidate_grid.png")); plt.close(fig)
    with open(OUT_JSON, "w") as f:
        json.dump(dict(psfs=psfs, lams=lams, table=table, decision=decision), f, indent=1, default=float)
    print(f"\nwrote figures/candidate_grid.png + w9_candidate_montage.json  ({(time.time()-t0)/60:.1f} min)")


if __name__ == "__main__":
    main()
