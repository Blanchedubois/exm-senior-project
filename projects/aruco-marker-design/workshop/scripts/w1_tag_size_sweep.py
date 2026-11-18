#!/usr/bin/env python3
"""
w1_tag_size_sweep.py — Workshop W1 (Rev D, Phase 2).

QUESTION
    How big must an ArUco tag be to decode through the measured blur -- WITH
    MARGIN -- and does the dictionary choice change the answer?

WHY AGAIN
    The Phase-B sweep tested isolated tags on a clean background and found
    module >= 1.8 x PSF. But in the full simulated scene decode was ~2x worse
    than that at the same blur. The difference is everything the isolated test
    left out: vignetting (tags at the field edge are dark), lens distortion and
    its un-distortion resampling, the 2 degree stage rotation, and the dot
    lattice crowding the quiet zone. W1 keeps all of it.

FIRST FINDING (before the sweep even ran)
    The "2x worse in-scene" was almost entirely the DECODER, not the scene.
    Isolating effects one at a time showed centre tags failing MORE than edge
    tags (4% vs 40%) -- the opposite of what vignette or lens would do -- and
    replacing the V1-simulator's CLAHE step with plain inversion took a 36 um
    tag at PSF 3.18 from 28% to 100%. CLAHE over a dense dot field re-maps the
    local histogram until ArUco's dark modules stop being dark. The simulator's
    decode() no longer uses CLAHE, and neither should the Phase-C detector.

METHOD
    Two sub-experiments, both through the real simulator path
    (place -> render -> lens -> blur -> vignette -> noise -> calibrated decode):

    (1) DESIGN CURVE. For each dictionary and each PSF, build the full pattern
        at that PSF (quiet zone and dot pitch follow the PSF, as they will in
        the print), sweep the tag size, and decode all 36 tags at lambda = 1 in
        a field of view that puts the pattern's outer tags in the CORNERS of the
        frame -- the darkest, most distorted place a tag can be. This is the
        worst case by construction.

    (2) MARGIN CHECK. For each named candidate (OPT / HEDGE / SAFE), build the
        pattern for its design PSF at three tag margins (0 / +10% / +20%), then
        image it at BOTH the design PSF and 1.2x the design PSF -- i.e. "the
        focus fix landed 20% short". Report decode and the minimum number of
        tags decoded across seeds.

PASS (from WORKSHOP_PLAN.md section 4)
    >= 95% decode at the design PSF, and >= 1 decoded tag per frame at 1.2x
    the design PSF. Fixes the rounding margin the Phase-A variants guessed at.

Run:  python w1_tag_size_sweep.py [--quick]
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
from cv2 import aruco

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.normpath(os.path.join(HERE, "..", "..", "tools"))
sys.path.insert(0, TOOLS)
from aruco_grid import GridConfig, build, solid_ids                        # noqa: E402
import simulate_v2 as V                                                    # noqa: E402

FIG_DIR = os.path.normpath(os.path.join(HERE, "..", "figures"))
OUT_JSON = os.path.join(FIG_DIR, "w1_tag_size_sweep.json")

# the as-designed noise rung (L2) -- fixed, so only blur varies
NOISE = dict(read_noise=6.0, full_well=240.0, background=14.0)
DICTS = [("DICT_4X4_50", 6, 50), ("DICT_4X4_100", 6, 100), ("DICT_5X5_100", 7, 100)]
CANDIDATES = {"OPT": 1.91, "HEDGE": 2.50, "SAFE": 3.18}


def make_cfg(dict_name, modules, tag_um, psf):
    return GridConfig(dict_name=dict_name, tag_modules=modules, tag_um=float(tag_um),
                      psf_fwhm_um=psf, dot_side_um=2.125, dashes=True, round_tags=True,
                      fit="inside", field_um=750.0)


def scene(gcfg, sim, theta=2.0):
    """Full pattern at lambda=1, corners of the pattern in the corners of the frame."""
    with contextlib.redirect_stdout(io.StringIO()):
        _r, _recs, info = build(gcfg)
    islands = info["islands"]
    lobes = V.make_lobes(gcfg.field_um, sim)
    rects, tag_c, tag_id = V.place(islands, 1.0, sim, lobes, gcfg.field_um, (0.0, 0.0))
    base = V.render_scene(rects, sim, theta)
    # in-frame set, with the y-flip that Phase B taught us
    rfov = sim.fov_um * sim.render_margin
    lo, hi = (rfov - sim.fov_um) / 2, (rfov + sim.fov_um) / 2
    M = cv2.getRotationMatrix2D((rfov / 2, rfov / 2), theta, 1.0)
    T = np.column_stack([tag_c[:, 0], rfov - tag_c[:, 1]])
    R = T @ M[:, :2].T + M[:, 2]
    t = math.radians(theta)
    m = (gcfg.tag_um / 2) * (abs(math.cos(t)) + abs(math.sin(t))) + gcfg.module_um
    infov = {tag_id[j] for j in range(len(tag_id))
             if lo + m <= R[j, 0] <= hi - m and lo + m <= R[j, 1] <= hi - m}
    return base, infov


def decode_rate(base, infov, sim, gcfg, psf, seeds):
    det = aruco.ArucoDetector(aruco.getPredefinedDictionary(getattr(aruco, gcfg.dict_name)),
                              aruco.DetectorParameters())
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    lv = V.Level("w1", psf, NOISE["read_noise"], NOISE["full_well"], NOISE["background"])
    counts = []
    for s in seeds:
        img = V.degrade(base, sim, lv, np.random.default_rng(s), lam=1.0)
        found = V.decode(img, sim, det, clahe)
        counts.append(len(found & infov))
    n = max(len(infov), 1)
    return float(np.mean(counts)) / n, int(min(counts)), n


def sim_config():
    sim = V.SimConfig()
    # pattern (750 um) fills the frame: outer tags land in the frame corners
    sim.fov_um = 900.0              # 860 clipped the 4 corner tags once barrel
                                    # distortion pushed them outward (89% ceiling)
    sim.drift_um = 0.0
    sim.signal_exp = 0.0            # lambda = 1 only; brightness law irrelevant here
    th = math.radians(2.0)
    sim.render_margin = max(sim.render_margin, math.cos(th) + math.sin(th) + 0.02)
    return sim


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    os.makedirs(FIG_DIR, exist_ok=True)
    sim = sim_config()
    t0 = time.time()

    tags = [18, 21, 24, 27, 30, 33, 36, 40] if not a.quick else [21, 30, 40]
    psfs = [1.5, 1.91, 2.5, 3.18, 3.5] if not a.quick else [1.91, 3.18]
    seeds = [0, 1] if not a.quick else [0]

    print(f"W1  frame {sim.fov_px}x{sim.fov_px} px at {sim.um_per_px} um/px, "
          f"{len(tags)} tag sizes x {len(psfs)} PSFs x {len(DICTS)} dictionaries x "
          f"{len(seeds)} seeds")

    # ---------------------------------------------------------------- (1) curve
    curve = {}
    for dname, mods, nids in DICTS:
        ok = len(solid_ids(dname, mods, nids))
        print(f"\n[{dname}]  {mods} modules, {ok} strut-free ids (36 needed)")
        if ok < 36:
            print("   -> insufficient strut-free ids for a 5x5 grid; skipped"); continue
        curve[dname] = {}
        for psf in psfs:
            row = []
            for tag in tags:
                g = make_cfg(dname, mods, tag, psf)
                base, infov = scene(g, sim)
                rate, mn, n = decode_rate(base, infov, sim, g, psf, seeds)
                row.append(dict(tag_um=tag, module_um=tag / mods, rate=rate, min_decoded=mn,
                                in_frame=n))
            curve[dname][str(psf)] = row
            need = next((r["tag_um"] for r in row if r["rate"] >= 0.95), None)
            print(f"   PSF {psf:4.2f}: " + " ".join(f"{r['tag_um']:>2}:{r['rate']:4.0%}" for r in row)
                  + f"   -> first >=95%: {need if need else 'none'} um"
                  + (f"  (module/PSF = {need/mods/psf:.2f})" if need else ""))

    # ------------------------------------------------------------ (2) margin
    print("\nMARGIN CHECK  (geometry built for the design PSF, imaged at design and 1.2x design)")
    print(f"{'cand':<6}{'PSF':>5}{'margin':>8}{'tag':>6}{'@design':>10}{'@1.2x':>8}"
          f"{'min tags @1.2x':>16}")
    margin = {}
    dname, mods, nids = DICTS[0]                     # DICT_4X4_50, the chosen dictionary
    for cname, psf in CANDIDATES.items():
        base_tag = 6 * 1.8 * psf
        margin[cname] = []
        for mfrac in (0.0, 0.10, 0.20):
            tag = math.ceil(base_tag * (1 + mfrac))
            g = make_cfg(dname, mods, tag, psf)
            base, infov = scene(g, sim)
            r0, _m0, _n = decode_rate(base, infov, sim, g, psf, seeds)
            r1, m1, _n = decode_rate(base, infov, sim, g, 1.2 * psf, seeds)
            rec = dict(margin=mfrac, tag_um=tag, rate_design=r0, rate_1p2=r1,
                       min_tags_1p2=m1, passes=bool(r0 >= 0.95 and m1 >= 1))
            margin[cname].append(rec)
            print(f"{cname:<6}{psf:>5.2f}{mfrac:>7.0%}{tag:>6}{r0:>10.0%}{r1:>8.0%}"
                  f"{m1:>16}   {'PASS' if rec['passes'] else 'fail'}")

    # ---------------------------------------------------------------- figure
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ncol = max(len(curve), 1)
    fig, axes = plt.subplots(1, ncol, figsize=(5.2 * ncol, 4.4), dpi=110, sharey=True)
    axes = np.atleast_1d(axes)
    for ax, (dname, per_psf) in zip(axes, curve.items()):
        for psf, row in per_psf.items():
            ax.plot([r["tag_um"] for r in row], [100 * r["rate"] for r in row],
                    marker="o", label=f"PSF {psf} um")
        ax.axhline(95, ls="--", c="k", lw=0.8)
        ax.set_title(dname, fontsize=10); ax.set_xlabel("tag size (um)")
        ax.set_ylim(0, 102); ax.grid(alpha=.3)
    axes[0].set_ylabel("tags decoded (%)\nall 36 ids, in-scene, worst case")
    axes[-1].legend(fontsize=8)
    fig.suptitle("W1 — tag size vs blur, full-scene decode at lambda = 1", fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(os.path.join(FIG_DIR, "tag_size_sweep.png")); plt.close(fig)

    with open(OUT_JSON, "w") as f:
        json.dump(dict(frame_px=sim.fov_px, um_per_px=sim.um_per_px, noise=NOISE,
                       tags=tags, psfs=psfs, seeds=seeds, curve=curve, margin=margin), f,
                  indent=1)
    print(f"\nwrote figures/tag_size_sweep.png + w1_tag_size_sweep.json   "
          f"({(time.time()-t0)/60:.1f} min)")


if __name__ == "__main__":
    main()
