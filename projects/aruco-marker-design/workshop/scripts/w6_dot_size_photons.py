#!/usr/bin/env python3
"""
w6_dot_size_photons.py — Workshop W6 (Rev D, Phase 3).

QUESTION
    Which dot size still detects at lambda_max, under which exposure policy?
    The measured signal law (Phase B: dot signal ~ lambda^-1.84, 15% left at
    4.2x) makes photons, not geometry, the limit above ~3x. W0 argued 3 um
    "insurance" dots are only needed if exposure cannot scale. Test it.
    Also (from W5): does the tile-Otsu detector help EFFICIENCY in dim frames,
    now that it is known not to help separation?

PART A — analytic budget, from the measured laws
    SNR(lambda, d, E) = 27.4 x (d/2.125)^2 x (lambda/1.5)^-1.84 x g(E)
    27.4 = measured SNR per 2.125 um dot at 1.5x, fixed exposure (Phase B).
    E = exposure relative to the 1.5x frame; g(E) = E if read-noise-limited,
    sqrt(E) if shot-noise-limited. Both bounds are reported because the real
    camera's regime is not known. Rose criterion: SNR >= 5.

PART B — empirical, through the simulator camera
    HEDGE geometry (PSF 2.5) with dot side 2.125 / 2.5 / 3.0 um (pitch derived
    per size), lambda 1..6, exposure policy p in {0, 1, 2} (E = lambda^p, capped
    so the brightest features never exceed full scale), L2 noise. Frame brightness
    = min(1, S(lambda) E(lambda)) applied BEFORE the Poisson step, so shot noise
    follows the photons and read noise stays fixed -- both regimes emerge from the
    model. Detection efficiency = detected dots matched to ground truth (< 3 px)
    over dots in the usable frame; localisation RMS of the matches.

PASS (WORKSHOP_PLAN.md section 4)
    SNR >= 5 at lambda = 6 for the chosen dot + exposure policy; empirically,
    >= 90% detection efficiency at lambda = 6.

Run:  python w6_dot_size_photons.py [--quick]
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
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "..", "reference-warp-tagger")))
from aruco_grid import GridConfig, VARIANTS, build                          # noqa: E402
import simulate_v2 as V                                                     # noqa: E402
from rwtag.glyph import lattice as lt                                       # noqa: E402
from w5_dot_separation_vs_psf import detect_dots_tiled                      # noqa: E402

FIG_DIR = os.path.normpath(os.path.join(HERE, "..", "figures"))
OUT_JSON = os.path.join(FIG_DIR, "w6_dot_size_photons.json")
SNR15, SIGEXP, REF = 27.4, -1.84, 1.5
DOTS = [2.125, 2.5, 3.0]
LAMS = [1, 2, 3, 4, 5, 6]
POLICIES = {"fixed": 0, "exposure ~ λ": 1, "exposure ~ λ²": 2}
NOISE = dict(read_noise=6.0, full_well=240.0, background=14.0)
AREA = (12, 220)


def S(lam):                       # signal fraction vs the 1.5x reference frame
    return min(1.0, (lam / REF) ** SIGEXP)


def E(lam, p):                    # exposure relative to the reference frame
    # never SHORTER than the reference exposure: the policy lengthens exposure as
    # the pattern dims, it does not under-expose the bright early frames
    return max(1.0, (lam / REF) ** p)


def snr_analytic(d, lam, p, regime):
    e = E(lam, p)
    g = e if regime == "read" else math.sqrt(e)
    return SNR15 * (d / 2.125) ** 2 * (lam / REF) ** SIGEXP * g


# ------------------------------------------------------------- empirical
def truth_px(islands, lam, sim, gcfg, lobes, theta, drift):
    """Ground-truth dot centres in the final frame's pixel coordinates."""
    C = np.array([[i["cx"], i["cy"]] for i in islands if i["kind"] == "dot"], float)
    P0 = np.array([gcfg.field_um / 2.0, gcfg.field_um / 2.0])
    rfov = sim.fov_um * sim.render_margin
    centre = np.array([rfov / 2.0, rfov / 2.0]) + np.asarray(drift, float)
    Cd = centre + lam * (C - P0) + V.warp_disp(C, lobes, sim.warp_sigma_um) * lam
    M = cv2.getRotationMatrix2D((rfov / 2, rfov / 2), theta, 1.0)
    T = np.column_stack([Cd[:, 0], rfov - Cd[:, 1]])               # y-up -> image y-down
    R = V.lens_forward(T @ M[:, :2].T + M[:, 2], sim, sim.fov_um / 2.0, centre=(rfov / 2, rfov / 2))
    lo = (rfov - sim.fov_um) / 2
    band = abs(sim.lens_k1) * sim.fov_um / 2.0 * 1.4               # W3 edge band
    ok = ((R[:, 0] > lo + band) & (R[:, 0] < lo + sim.fov_um - band) &
          (R[:, 1] > lo + band) & (R[:, 1] < lo + sim.fov_um - band))
    return (R[ok] - lo) / sim.um_per_px - 0.5        # cv2 centroids are pixel-index means


def efficiency(found, truth, tol=3.0):
    if not len(found) or not len(truth):
        return 0.0, float("nan")
    from scipy.spatial import cKDTree
    d, _ = cKDTree(found).query(truth)
    hit = d < tol
    return float(hit.mean()), float(np.sqrt(np.mean(d[hit] ** 2))) if hit.any() else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    os.makedirs(FIG_DIR, exist_ok=True)
    t0 = time.time()
    dots = DOTS if not a.quick else [2.125]
    lams = LAMS if not a.quick else [1, 6]

    # ---------------------------------------------------------------- A
    print("A — analytic SNR per dot at lambda = 6  (read-limited / shot-limited bound)")
    print(f"{'dot um':>7}" + "".join(f"{p:>22}" for p in POLICIES))
    A = {}
    for d in dots:
        row = {}
        for pname, p in POLICIES.items():
            row[pname] = dict(read=snr_analytic(d, 6.0, p, "read"), shot=snr_analytic(d, 6.0, p, "shot"))
        A[str(d)] = row
        print(f"{d:>7.3f}" + "".join(f"{row[p]['read']:>11.1f} /{row[p]['shot']:>8.1f}" for p in POLICIES))
    print("  Rose limit 5. Fixed exposure fails for every dot size; ~λ² passes for every size in both regimes.")

    # ---------------------------------------------------------------- B
    sim = V.SimConfig(); sim.signal_exp = 0.0          # brightness applied here, explicitly
    thetas = [sim.rotation_deg + k * sim.rotation_step_deg for k in range(6)]
    th = math.radians(max(thetas))
    sim.render_margin = max(sim.render_margin,
                            math.cos(th) + math.sin(th) + 2 * sim.drift_um / sim.fov_um + 0.02)
    v = VARIANTS["hedge"]
    B = {}
    print(f"\nB — empirical detection efficiency (HEDGE geometry, PSF {v['psf_fwhm_um']} um, L2 noise)")
    for d in dots:
        gcfg = GridConfig(dict_name="DICT_4X4_50", tag_modules=6, tag_um=v["tag_um"],
                          psf_fwhm_um=v["psf_fwhm_um"], dot_side_um=d, dashes=True,
                          round_tags=True, fit="inside", field_um=750.0)
        with contextlib.redirect_stdout(io.StringIO()):
            _r, _recs, info = build(gcfg)
        islands = info["islands"]; lobes = V.make_lobes(gcfg.field_um, sim)
        drng = np.random.default_rng(sim.drift_seed)
        lv = V.Level("w6", v["psf_fwhm_um"], NOISE["read_noise"], NOISE["full_well"], NOISE["background"])
        B[str(d)] = dict(pitch_um=gcfg.dot_pitch_um, rows=[])
        print(f"\n  dot {d} um, pitch {gcfg.dot_pitch_um:.2f} um")
        print(f"  {'λ':>3}{'bright':>8}{'in view':>9}" +
              "".join(f"{p[:12]:>14}" for p in POLICIES) + "   (global | tile efficiency)")
        for k, lam in enumerate(lams):
            kk = LAMS.index(lam)
            drift = drng.uniform(-sim.drift_um, sim.drift_um, 2)
            rects, _tc, _tid = V.place(islands, float(lam), sim, lobes, gcfg.field_um, drift)
            base = V.render_scene(rects, sim, thetas[kk])
            truth = truth_px(islands, float(lam), sim, gcfg, lobes, thetas[kk], drift)
            row = dict(lam=lam, in_view=int(len(truth)), policies={})
            cells = []
            for pname, p in POLICIES.items():
                b = min(1.0, S(lam) * E(lam, p))
                img = V.degrade(np.clip(base.astype(np.float32) * b, 0, 255).astype(np.uint8),
                                sim, lv, np.random.default_rng(0), lam=None)
                eg, rg = efficiency(lt.detect_dots(img, tophat=15, dot_area=AREA), truth)
                et, rt = efficiency(detect_dots_tiled(img, tophat=15, dot_area=AREA), truth)
                row["policies"][pname] = dict(brightness=b, eff_global=eg, eff_tile=et,
                                              rms_global=rg, rms_tile=rt)
                cells.append(f"{eg:>5.0%} |{et:>5.0%}")
            B[str(d)]["rows"].append(row)
            print(f"  {lam:>3}{S(lam):>8.0%}{len(truth):>9,}" + "".join(f"{c:>14}" for c in cells))

    # ---------------------------------------------------------------- gate
    print("\nW6 GATE  (λ = 6, exposure ~ λ²)")
    ok_all = True
    for d in dots:
        snr = A[str(d)]["exposure ~ λ²"]["shot"]
        r6 = next((r for r in B[str(d)]["rows"] if r["lam"] == 6), None)
        eff = r6["policies"]["exposure ~ λ²"]["eff_global"] if r6 else float("nan")
        ok = snr >= 5 and (eff >= 0.90 if r6 else True)
        ok_all &= ok
        print(f"  dot {d:5.3f} um: SNR(shot bound) {snr:5.1f}   efficiency {eff:4.0%}   {'PASS' if ok else 'FAIL'}")
    print(f"  W6: {'PASS' if ok_all else 'FAIL'}")

    # ---------------------------------------------------------------- figure
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 1 + len(dots), figsize=(4.6 * (1 + len(dots)), 4.4), dpi=110)
    ax = axes[0]
    lam_f = np.linspace(1, 6, 60)
    for d, ls in zip(dots, ("-", "--", ":")):
        for pname, p in POLICIES.items():
            ax.plot(lam_f, [snr_analytic(d, l, p, "shot") for l in lam_f], ls,
                    label=f"{d} um, {pname}" if d == dots[0] else None)
    ax.axhline(5, c="k", lw=0.8, ls="--"); ax.set_yscale("log"); ax.set_ylim(0.5, 300)
    ax.set_xlabel("expansion λ"); ax.set_ylabel("SNR per dot (shot-limited bound)")
    ax.set_title("A — analytic (line style = dot size)", fontsize=9); ax.grid(alpha=.3); ax.legend(fontsize=6)
    for ax, d in zip(axes[1:], dots):
        for pname in POLICIES:
            rows = B[str(d)]["rows"]
            ax.plot([r["lam"] for r in rows], [100 * r["policies"][pname]["eff_global"] for r in rows],
                    "o-", label=f"{pname} · global")
            ax.plot([r["lam"] for r in rows], [100 * r["policies"][pname]["eff_tile"] for r in rows],
                    "x--", label=f"{pname} · tile")
        ax.axhline(90, c="k", lw=0.8, ls="--"); ax.set_ylim(0, 105); ax.grid(alpha=.3)
        ax.set_xlabel("expansion λ"); ax.set_title(f"B — dot {d} um, detection efficiency", fontsize=9)
        ax.legend(fontsize=6)
    axes[1].set_ylabel("dots detected (%)")
    fig.suptitle("W6 — dot size vs photons vs exposure policy", fontsize=10)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(os.path.join(FIG_DIR, "dot_photons.png")); plt.close(fig)
    with open(OUT_JSON, "w") as f:
        json.dump(dict(analytic=A, empirical=B, lams=lams, dots=dots), f, indent=1, default=float)
    print(f"wrote figures/dot_photons.png + w6_dot_size_photons.json  ({(time.time()-t0)/60:.1f} min)")


if __name__ == "__main__":
    main()
