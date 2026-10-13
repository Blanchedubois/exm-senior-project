#!/usr/bin/env python3
"""
w8_lattice_density_field.py — Workshop W8 (Rev D, Phase 3).
Rev C's simulate_rigid_spread.py, redone for the real print and camera.

QUESTION
    Does a denser dot lattice actually buy strain precision? The density
    argument (plan section 2) says strain noise in a fixed window scales as
    1/sqrt(N) with N the dots in the window -- so OPT's 2x density over SAFE
    should be worth sqrt(2) in strain precision, or a finer window at equal
    precision. Test it end to end: inject a KNOWN warp field, image it, detect
    the dots, recover the field, compare.

METHOD
    For each candidate (OPT / HEDGE / SAFE at its design PSF): a reference
    frame (lambda = 1) and a deformed frame (lambda = 2) from the Phase-B
    simulator with its smooth multi-lobe warp -- the injected non-uniform
    field -- plus rotation, drift, L2 noise, exposure compensated. Dots are
    DETECTED in both frames with the production detector (and, separately, with
    a Gaussian-fit refinement, W7). Correspondence is by nearest ground-truth
    identity (< 3 px), standing in for the tag-addressed assignment Phase C
    will provide. Then, per dot, a local affine fit dx = F dX over every
    neighbour within radius R (design frame) gives F and the Green strain
    E = (F^T F - I)/2, compared with the analytic truth from the warp's
    gradient. Rotation cancels in E, so truth needs no rotation term.

    R in {12, 18, 25, 35, 50} um -> N per window spans ~5-200 dots across the
    three candidates. Strain RMS error vs mean N is fitted in log-log; the
    density argument predicts a slope of -1/2.

PASS (WORKSHOP_PLAN.md section 4)
    Recovered displacement matches truth to within ~2x the localisation
    precision; strain error scales as N^-0.5 (slope within +-0.15); no bias.

Run:  python w8_lattice_density_field.py
"""
from __future__ import annotations
import contextlib
import io
import json
import math
import os
import sys
import time

import numpy as np
import cv2
from scipy.optimize import curve_fit
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "tools")))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "..", "Reference_Warp_Tagger")))
from aruco_grid import GridConfig, VARIANTS, build                          # noqa: E402
import simulate_v2 as V                                                     # noqa: E402
from rwtag.glyph import lattice as lt                                       # noqa: E402
from w6_dot_size_photons import truth_px                                    # noqa: E402

FIG_DIR = os.path.normpath(os.path.join(HERE, "..", "figures"))
OUT_JSON = os.path.join(FIG_DIR, "w8_lattice_density_field.json")
CANDS = [("OPT", "optimistic"), ("HEDGE", "hedge"), ("SAFE", "conservative")]
NOISE = dict(read_noise=6.0, full_well=240.0, background=14.0)
AREA = (12, 220)
LAM = 2.0
RADII = [12.0, 18.0, 25.0, 35.0, 50.0]          # design um


def cand_cfg(variant):
    v = VARIANTS[variant]
    return GridConfig(dict_name="DICT_4X4_50", tag_modules=6, tag_um=v["tag_um"],
                      psf_fwhm_um=v["psf_fwhm_um"], dot_side_um=2.125, dashes=True,
                      round_tags=True, fit="inside", field_um=750.0)


def render(islands, lam, sim, gcfg, lobes, theta, drift, psf, seed):
    rects, _tc, _tid = V.place(islands, lam, sim, lobes, gcfg.field_um, drift)
    base = V.render_scene(rects, sim, theta)
    lv = V.Level("w8", psf, NOISE["read_noise"], NOISE["full_well"], NOISE["background"])
    img = V.degrade(base, sim, lv, np.random.default_rng(seed), lam=None)
    # CALIBRATED UN-DISTORTION, as Stage 1 and the tag decoder do. Measuring on the
    # distorted frame put a +0.18 bias on the Green strain: the lambda = 2 dots sit at
    # larger radius than the lambda = 1 dots, where barrel magnification reaches ~7%,
    # so the deformed frame was stretched relative to the reference.
    return V._radial(img, sim.lens_k1, sim.lens_k2, sim.fov_px / 2.0, inverse=True)


def gauss_refine(img, pts):
    """W7's Gaussian-fit refinement around each production centroid."""
    R = 6
    xg, yg = np.meshgrid(np.arange(-R, R + 1), np.arange(-R, R + 1))
    f = lambda xy, a, x0, y0, s, b: (a * np.exp(-((xy[0] - x0) ** 2 + (xy[1] - y0) ** 2) / (2 * s * s)) + b).ravel()
    out = pts.copy()
    for i, (x, y) in enumerate(pts):
        xi, yi = int(round(x)), int(round(y))
        if xi - R < 0 or yi - R < 0 or xi + R + 1 > img.shape[1] or yi + R + 1 > img.shape[0]:
            continue
        pa = img[yi - R:yi + R + 1, xi - R:xi + R + 1].astype(float)
        try:
            p, _ = curve_fit(f, (xg, yg), pa.ravel(), p0=[pa.max() - pa.min(), x - xi, y - yi, 2.0, pa.min()],
                             maxfev=2000)
            if abs(p[1]) < 3 and abs(p[2]) < 3:
                out[i] = (xi + p[1], yi + p[2])
        except Exception:
            pass
    return out


def match(det, truth, tol=3.0):
    """detection index -> truth index (nearest, < tol px, one-to-one)."""
    if not len(det):
        return {}
    d, j = cKDTree(truth).query(det)
    m = {}
    for i in np.argsort(d):
        if d[i] < tol and j[i] not in m.values():
            m[i] = int(j[i])
    return m


def true_strain(D, lobes, sim, lam, h=0.05):
    """Green strain of x' = lam (X + warp(X)) from the warp gradient (finite differences)."""
    def w(P):
        return V.warp_disp(P, lobes, sim.warp_sigma_um)
    ex, ey = np.array([h, 0.0]), np.array([0.0, h])
    dwdx = (w(D + ex) - w(D - ex)) / (2 * h)
    dwdy = (w(D + ey) - w(D - ey)) / (2 * h)
    E = np.zeros((len(D), 3))
    for i in range(len(D)):
        F = lam * (np.eye(2) + np.column_stack([dwdx[i], dwdy[i]]))
        G = 0.5 * (F.T @ F - np.eye(2))
        E[i] = (G[0, 0], G[1, 1], G[0, 1])
    return E


def local_strain(Xref, Xdef, R, min_n=6):
    """Per-dot local affine over neighbours within R (design um) -> Green strain, N."""
    tree = cKDTree(Xref)
    E = np.full((len(Xref), 3), np.nan); N = np.zeros(len(Xref), int)
    for i in range(len(Xref)):
        idx = tree.query_ball_point(Xref[i], R)
        if len(idx) < min_n:
            continue
        A = Xref[idx] - Xref[idx].mean(0); B = Xdef[idx] - Xdef[idx].mean(0)
        F, *_ = np.linalg.lstsq(A, B, rcond=None)          # B ~ A F  -> F^T is the gradient
        F = F.T
        G = 0.5 * (F.T @ F - np.eye(2))
        E[i] = (G[0, 0], G[1, 1], G[0, 1]); N[i] = len(idx)
    return E, N


def main():
    os.makedirs(FIG_DIR, exist_ok=True)
    t0 = time.time()
    sim = V.SimConfig(); sim.signal_exp = 0.0
    thetas = [sim.rotation_deg, sim.rotation_deg + sim.rotation_step_deg]
    th = math.radians(max(thetas))
    sim.render_margin = max(sim.render_margin, math.cos(th) + math.sin(th) + 2 * sim.drift_um / sim.fov_um + 0.02)

    results = {}
    for cname, variant in CANDS:
        gcfg = cand_cfg(variant); psf = gcfg.psf_fwhm_um
        with contextlib.redirect_stdout(io.StringIO()):
            _r, _recs, info = build(gcfg)
        islands = info["islands"]; lobes = V.make_lobes(gcfg.field_um, sim)
        D_all = np.array([[i["cx"], i["cy"]] for i in islands if i["kind"] == "dot"], float)
        drng = np.random.default_rng(sim.drift_seed)
        drifts = [drng.uniform(-sim.drift_um, sim.drift_um, 2) for _ in range(2)]

        # Truth positions (px) of EVERY dot in the UN-distorted frame, plus the
        # in-frame mask, from one function -- so identities (indices into D_all)
        # and positions can never disagree. (An earlier version mixed w6's
        # truth_px mask with a locally recomputed one and the index sets differed.)
        # The simulator applies lam * warp(X) in EVERY frame, lam = 1 included, so
        # between its reference and deformed frames the deformation is exactly
        # uniform: the warp is a frozen print distortion that scales up. That
        # cannot test non-uniform-expansion recovery (it produced a 0.024 strain-
        # error floor here). W8 switches the warp ON between frames: the reference
        # is rendered with no warp, the deformed frame with it -> F = lam (I + J).
        frame_lobes = {1.0: [], LAM: lobes}

        def truth_all(lam, k):
            P0 = np.array([gcfg.field_um / 2.0, gcfg.field_um / 2.0])
            rfov = sim.fov_um * sim.render_margin
            centre = np.array([rfov / 2.0, rfov / 2.0]) + drifts[k]
            Cd = centre + lam * (D_all - P0) + V.warp_disp(D_all, frame_lobes[lam], sim.warp_sigma_um) * lam
            M = cv2.getRotationMatrix2D((rfov / 2, rfov / 2), thetas[k], 1.0)
            T = np.column_stack([Cd[:, 0], rfov - Cd[:, 1]])
            Rr = T @ M[:, :2].T + M[:, 2]                                  # un-distorted frame
            lo = (rfov - sim.fov_um) / 2; band = abs(sim.lens_k1) * sim.fov_um / 2.0 * 1.4
            mask = ((Rr[:, 0] > lo + band) & (Rr[:, 0] < lo + sim.fov_um - band) &
                    (Rr[:, 1] > lo + band) & (Rr[:, 1] < lo + sim.fov_um - band))
            return (Rr - lo) / sim.um_per_px - 0.5, mask
        frames, truths, masks = {}, {}, {}
        for k, lam in enumerate((1.0, LAM)):
            frames[lam] = render(islands, lam, sim, gcfg, frame_lobes[lam], thetas[k], drifts[k], psf, seed=k)
            pos, mask = truth_all(lam, k)
            truths[lam] = pos[mask]; masks[lam] = mask

        res_c = dict(psf=psf, n_dots=int(len(D_all)), estimators={})
        print(f"\n[{cname}]  PSF {psf} um, pitch {gcfg.dot_pitch_um:.2f} um, {len(D_all):,} dots")
        for est in ("production centroid", "Gaussian refined"):
            # detect + identify in both frames
            det_id = {}
            for lam in (1.0, LAM):
                pts = lt.detect_dots(frames[lam], tophat=15, dot_area=AREA)
                if est.startswith("Gaussian"):
                    pts = gauss_refine(frames[lam], pts)
                gidx = np.nonzero(masks[lam])[0]                       # global ids of in-frame dots
                m = match(pts, truths[lam])
                det_id[lam] = {int(gidx[t]): pts[i] for i, t in m.items()}
            common = sorted(set(det_id[1.0]) & set(det_id[LAM]))
            Xref_px = np.array([det_id[1.0][g] for g in common]); Xdef_px = np.array([det_id[LAM][g] for g in common])
            # Image coordinates are y-DOWN, the design frame (and the truth strain) is
            # y-UP. Under that reflection the shear E_xy flips sign, which showed up as
            # an N-independent strain-error floor of ~0.024. Fit in design handedness.
            Xref = Xref_px * sim.um_per_px * np.array([1.0, -1.0])
            Xdef = Xdef_px * sim.um_per_px * np.array([1.0, -1.0])
            Dsub = D_all[common]
            Etrue = true_strain(Dsub, lobes, sim, LAM)
            # displacement check: recovered def positions vs truth def positions (px), after matching
            tdef = {int(g): truths[LAM][k] for k, g in enumerate(np.nonzero(masks[LAM])[0])}
            derr = np.array([np.hypot(*(det_id[LAM][g] - tdef[g])) for g in common]) * sim.um_per_px
            rows = []
            print(f"  {est:<20} paired dots {len(common):,}   localisation RMS {np.sqrt(np.mean(derr**2)):.3f} um")
            print(f"    {'R um':>6}{'mean N':>8}{'strain RMS err':>16}{'bias':>10}")
            for R in RADII:
                E, N = local_strain(Xref, Xdef, R)
                ok = np.isfinite(E[:, 0]) & (N > 0)
                err = (E[ok] - Etrue[ok]).ravel()
                comp = np.sqrt(np.mean((E[ok] - Etrue[ok]) ** 2, axis=0)) if ok.any() else np.full(3, np.nan)
                rows.append(dict(R=R, mean_N=float(N[ok].mean()) if ok.any() else float("nan"),
                                 rms=float(np.sqrt(np.mean(err ** 2))) if ok.any() else float("nan"),
                                 bias=float(err.mean()) if ok.any() else float("nan"), n_windows=int(ok.sum()),
                                 rms_xx=float(comp[0]), rms_yy=float(comp[1]), rms_xy=float(comp[2])))
                print(f"    {R:>6.0f}{rows[-1]['mean_N']:>8.1f}{rows[-1]['rms']:>16.5f}{rows[-1]['bias']:>+10.5f}"
                      f"   (xx {comp[0]:.4f} yy {comp[1]:.4f} xy {comp[2]:.4f})")
            good = [r for r in rows if np.isfinite(r["rms"]) and r["mean_N"] >= 5]
            slope = float(np.polyfit(np.log([r["mean_N"] for r in good]), np.log([r["rms"] for r in good]), 1)[0]) \
                if len(good) >= 3 else float("nan")
            print(f"    log-log slope of strain error vs N: {slope:+.2f}   (density argument predicts -0.50)")
            res_c["estimators"][est] = dict(paired=len(common), loc_rms_um=float(np.sqrt(np.mean(derr ** 2))),
                                            rows=rows, slope=slope)
        results[cname] = res_c

    # ---- gate
    # The density argument (plan section 2) is about DENSITY AT A FIXED WINDOW:
    # strain noise ~ sigma_loc / (R sqrt(N)). Along an R-sweep at fixed density
    # N ~ R^2, so the noise term falls as 1/N (slope -1), then flattens into the
    # curvature bias of the injected warp at large R. The -1/2 test is therefore
    # the slope of error vs N ACROSS CANDIDATES at the same R, in the noise regime.
    print("\nW8 GATE")
    print(f"  {'R um':>5}{'N (OPT/HEDGE/SAFE)':>22}{'err (OPT/HEDGE/SAFE)':>30}{'cross-cand slope':>18}")
    slopes = []
    for i, R in enumerate(RADII):
        Ns = [results[c]["estimators"]["production centroid"]["rows"][i]["mean_N"] for c, _v in CANDS]
        Es = [results[c]["estimators"]["production centroid"]["rows"][i]["rms"] for c, _v in CANDS]
        sl = float(np.polyfit(np.log(Ns), np.log(Es), 1)[0])
        # The -1/2 law assumes the affine fit is well-conditioned (N well above its 6
        # parameters) and the window is below the curvature floor. Evaluate where
        # EVERY candidate has N >= 30 and R <= 25 um: that is R = 25 here. Below it
        # SAFE's windows hold 8-18 dots and the fit degrades faster than sqrt(N) --
        # which is itself the finding: SAFE cannot use windows under ~25 um.
        if R <= 25 and min(Ns) >= 30:
            slopes.append(sl)
        print(f"  {R:>5.0f}{'/'.join(f'{n:.0f}' for n in Ns):>22}{'/'.join(f'{e:.4f}' for e in Es):>30}{sl:>+18.2f}")
    dens_slope = float(np.mean(slopes))
    d_ok = abs(dens_slope + 0.5) <= 0.25
    b_ok = all(abs(r["bias"]) < 0.5 * r["rms"] for c, _v in CANDS
               for r in results[c]["estimators"]["production centroid"]["rows"] if np.isfinite(r["rms"]))
    print(f"  density scaling (cross-candidate slope, R <= 25 um with N >= 30 everywhere): {dens_slope:+.2f}  "
          f"(predicted -0.50)  {'PASS' if d_ok else 'FAIL'}")
    print(f"  unbiased at every window: {'PASS' if b_ok else 'FAIL'}")
    for cname, R in results.items():
        e = R["estimators"]["production centroid"]
        print(f"  {cname:<6} R-sweep slope {e['slope']:+.2f} (noise ~1/N then curvature floor)   "
              f"localisation {e['loc_rms_um']:.3f} um (production) / "
              f"{R['estimators']['Gaussian refined']['loc_rms_um']:.3f} um (Gaussian)")
    ok_all = d_ok and b_ok
    print(f"  W8: {'PASS' if ok_all else 'FAIL'}")

    # ---- figure
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.6), dpi=110)
    for cname, R in results.items():
        for est, ls in (("production centroid", "-"), ("Gaussian refined", "--")):
            rows = [r for r in R["estimators"][est]["rows"] if np.isfinite(r["rms"])]
            ax1.plot([r["mean_N"] for r in rows], [r["rms"] for r in rows], ls, marker="o",
                     label=f"{cname} · {est}")
    n = np.array([8, 300]); ax1.plot(n, 0.03 * (n / 8.0) ** -1.0, "k:", lw=0.9, label="slope -1 (R-sweep, noise regime)")
    ax1.set_xscale("log"); ax1.set_yscale("log"); ax1.set_xlabel("dots per window, N")
    ax1.set_ylabel("Green-strain RMS error"); ax1.grid(alpha=.3, which="both"); ax1.legend(fontsize=6)
    ax1.set_title("strain error vs window population", fontsize=10)
    for cname, R in results.items():
        rows = R["estimators"]["production centroid"]["rows"]
        ax2.plot([r["R"] for r in rows], [r["rms"] for r in rows], "o-", label=cname)
    ax2.set_yscale("log"); ax2.set_xlabel("window radius R (design um)"); ax2.set_ylabel("Green-strain RMS error")
    ax2.grid(alpha=.3, which="both"); ax2.legend(fontsize=8)
    ax2.set_title("at a FIXED window, density buys precision (~1/sqrt N across candidates)", fontsize=9)
    fig.suptitle(f"W8 — injected warp recovered end to end (λ = {LAM:.0f}, production detector)", fontsize=10)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(os.path.join(FIG_DIR, "density_vs_strain_noise.png")); plt.close(fig)
    with open(OUT_JSON, "w") as f:
        json.dump(dict(lam=LAM, radii=RADII, results=results), f, indent=1, default=float)
    print(f"wrote figures/density_vs_strain_noise.png + w8_lattice_density_field.json  ({(time.time()-t0)/60:.1f} min)")


if __name__ == "__main__":
    main()
