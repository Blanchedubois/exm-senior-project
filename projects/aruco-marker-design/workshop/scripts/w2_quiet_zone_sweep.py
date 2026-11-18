#!/usr/bin/env python3
"""
w2_quiet_zone_sweep.py — Workshop W2 (Rev D, Phase 2).

QUESTION
    How much clear space does a tag need around it before the first dot, and
    what would a second fluorescence channel (tags and dots imaged separately)
    buy?

WHY IT MATTERS
    The quiet zone is the one geometric parameter that costs dots directly: the
    keep-out radius is tag/2 + quiet + dot/2, and the dots it removes are the
    ones nearest every node. Phase B set quiet = max(module, 1.5 x PSF) after
    finding that 3 um of clearance collapsed lambda = 1 decode to 50%. That was
    measured with the CLAHE decoder that W1 showed to be the real problem, so
    the rule may be looser than it needs to be.

METHOD
    For each named candidate (OPT / HEDGE / SAFE at its W1 tag size and design
    PSF), build the full three-tier pattern with the quiet zone forced to
    0.25 .. 2.5 modules, and decode all 36 tags at lambda = 1 in the W1
    worst-case placement (pattern corners in the frame corners, vignette, lens,
    rotation, L2 noise, 2 seeds). Repeat at 1.2 x the design PSF for margin.

    Two-channel variants, same geometry, ArUco channel rendered with
      (a) tags + grid dashes   -- dots in the other colour
      (b) tags only            -- dots and dashes in the other colour
    so the crowding term is removed and what remains is the tag alone.

    The dot count per configuration is recorded, because that is the price.

PASS (WORKSHOP_PLAN.md section 4)
    Smallest quiet zone with >= 95% decode at the design PSF, per candidate;
    two-channel gain quantified in dots.

Run:  python w2_quiet_zone_sweep.py [--quick]
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
from aruco_grid import GridConfig, VARIANTS, build                          # noqa: E402
import simulate_v2 as V                                                     # noqa: E402
import w1_tag_size_sweep as W1                                              # noqa: E402

FIG_DIR = os.path.normpath(os.path.join(HERE, "..", "figures"))
OUT_JSON = os.path.join(FIG_DIR, "w2_quiet_zone_sweep.json")
CANDS = [("OPT", "optimistic"), ("HEDGE", "hedge"), ("SAFE", "conservative")]
QUIET_FRACS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5]     # in modules


def make_cfg(variant, quiet_frac):
    v = VARIANTS[variant]
    module = v["tag_um"] / 6.0
    return GridConfig(dict_name="DICT_4X4_50", tag_modules=6, tag_um=v["tag_um"],
                      psf_fwhm_um=v["psf_fwhm_um"], dot_side_um=2.125, dashes=True,
                      round_tags=True, fit="inside", field_um=750.0,
                      quiet_um=max(quiet_frac * module, 1e-6))


def scene_kinds(gcfg, sim, kinds, theta=2.0):
    """W1.scene(), but rendering only the island kinds given (two-channel model)."""
    with contextlib.redirect_stdout(io.StringIO()):
        _r, recs, info = build(gcfg)
    islands = [i for i in info["islands"] if i["kind"] in kinds]
    n_dots = sum(1 for r in recs if r["category"] == "dot")
    lobes = V.make_lobes(gcfg.field_um, sim)
    rects, tag_c, tag_id = V.place(islands, 1.0, sim, lobes, gcfg.field_um, (0.0, 0.0))
    base = V.render_scene(rects, sim, theta)
    rfov = sim.fov_um * sim.render_margin
    lo, hi = (rfov - sim.fov_um) / 2, (rfov + sim.fov_um) / 2
    M = cv2.getRotationMatrix2D((rfov / 2, rfov / 2), theta, 1.0)
    T = np.column_stack([tag_c[:, 0], rfov - tag_c[:, 1]])
    R = T @ M[:, :2].T + M[:, 2]
    t = math.radians(theta)
    m = (gcfg.tag_um / 2) * (abs(math.cos(t)) + abs(math.sin(t))) + gcfg.module_um
    infov = {tag_id[j] for j in range(len(tag_id))
             if lo + m <= R[j, 0] <= hi - m and lo + m <= R[j, 1] <= hi - m}
    return base, infov, n_dots


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    os.makedirs(FIG_DIR, exist_ok=True)
    sim = W1.sim_config()
    seeds = [0, 1] if not a.quick else [0]
    fracs = QUIET_FRACS if not a.quick else [0.25, 1.0, 2.0]
    t0 = time.time()

    results = {}
    for cname, variant in CANDS:
        v = VARIANTS[variant]; psf = v["psf_fwhm_um"]; module = v["tag_um"] / 6.0
        rule_quiet = max(module, 1.5 * psf)
        print(f"\n[{cname}]  tag {v['tag_um']} um, module {module:.2f} um, design PSF {psf} um, "
              f"Phase-B rule quiet = {rule_quiet:.1f} um = {rule_quiet/module:.2f} modules")
        print(f"{'quiet(mod)':>11}{'quiet um':>10}{'dots':>8}{'1-ch @P':>9}{'@1.2P':>7}"
              f"{'tags+dash':>11}{'tags only':>11}")
        rows = []
        for q in fracs:
            g = make_cfg(variant, q)
            base, infov, n_dots = scene_kinds(g, sim, {"aruco", "dot", "dash"})
            r1, _m, n = W1.decode_rate(base, infov, sim, g, psf, seeds)
            r2, _m, n = W1.decode_rate(base, infov, sim, g, 1.2 * psf, seeds)
            base_td, infov_td, _ = scene_kinds(g, sim, {"aruco", "dash"})
            r3, _m, _n = W1.decode_rate(base_td, infov_td, sim, g, psf, seeds)
            base_t, infov_t, _ = scene_kinds(g, sim, {"aruco"})
            r4, _m, _n = W1.decode_rate(base_t, infov_t, sim, g, psf, seeds)
            rows.append(dict(quiet_mod=q, quiet_um=g.quiet_zone_um, dots=n_dots,
                             one_ch=r1, one_ch_1p2=r2, two_ch_tags_dash=r3, two_ch_tags=r4))
            print(f"{q:>11.2f}{g.quiet_zone_um:>10.2f}{n_dots:>8,}{r1:>9.0%}{r2:>7.0%}"
                  f"{r3:>11.0%}{r4:>11.0%}")
        need = next((r for r in rows if r["one_ch"] >= 0.95), None)
        need2 = next((r for r in rows if r["two_ch_tags_dash"] >= 0.95), None)
        gain = (need2["dots"] - need["dots"]) if (need and need2) else None
        results[cname] = dict(tag_um=v["tag_um"], module_um=module, psf=psf,
                              rule_quiet_um=rule_quiet, rows=rows,
                              min_quiet_1ch=need, min_quiet_2ch=need2, two_ch_gain_dots=gain)
        print(f"   -> single-channel: smallest quiet >=95% = "
              + (f"{need['quiet_mod']:.2f} modules ({need['quiet_um']:.1f} um), {need['dots']:,} dots"
                 if need else "none in sweep")
              + (f"\n   -> two-channel (tags+dashes): {need2['quiet_mod']:.2f} modules, "
                 f"{need2['dots']:,} dots  => gain {gain:+,} dots" if need2 and gain is not None else ""))

    # ------------------------------------------------------------------ figure
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(15.5, 4.6), dpi=110, sharey=True)
    for ax, (cname, _v) in zip(axes, CANDS):
        R = results[cname]; rows = R["rows"]
        q = [r["quiet_mod"] for r in rows]
        ax.plot(q, [100 * r["one_ch"] for r in rows], "o-", label="single channel @ design PSF")
        ax.plot(q, [100 * r["one_ch_1p2"] for r in rows], "o--", label="single channel @ 1.2x PSF")
        ax.plot(q, [100 * r["two_ch_tags_dash"] for r in rows], "s-", label="two-channel: tags + dashes")
        ax.plot(q, [100 * r["two_ch_tags"] for r in rows], "^:", label="two-channel: tags only")
        ax.axhline(95, c="k", lw=0.8, ls="--")
        ax.axvline(R["rule_quiet_um"] / R["module_um"], c="grey", lw=0.8, ls=":",
                   label="Phase-B rule")
        ax2 = ax.twinx()
        ax2.plot(q, [r["dots"] for r in rows], "x-", c="tab:red", alpha=.5, lw=0.8)
        ax2.set_ylabel("dots in pattern", color="tab:red", fontsize=8)
        ax2.tick_params(axis="y", labelcolor="tab:red", labelsize=7)
        ax.set_title(f"{cname}: tag {R['tag_um']:.0f} um, PSF {R['psf']} um", fontsize=10)
        ax.set_xlabel("quiet zone (modules)"); ax.set_ylim(0, 102); ax.grid(alpha=.3)
    axes[0].set_ylabel("tags decoded (%)\nall 36 ids, lambda = 1, worst case")
    axes[0].legend(fontsize=7, loc="lower right")
    fig.suptitle("W2 — quiet zone vs decode, with the two-channel alternative", fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(os.path.join(FIG_DIR, "quiet_zone_sweep.png")); plt.close(fig)

    with open(OUT_JSON, "w") as f:
        json.dump(dict(fracs=fracs, seeds=seeds, results=results), f, indent=1, default=float)
    print(f"\nwrote figures/quiet_zone_sweep.png + w2_quiet_zone_sweep.json   "
          f"({(time.time()-t0)/60:.1f} min)")


if __name__ == "__main__":
    main()
