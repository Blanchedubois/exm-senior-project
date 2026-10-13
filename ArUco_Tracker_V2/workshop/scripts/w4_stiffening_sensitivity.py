#!/usr/bin/env python3
"""
w4_stiffening_sensitivity.py — Workshop W4 (Rev D, Phase 2).

QUESTION
    Phase 0d bounded fiducial stiffening below ~8% of full pinning -- for the V1
    glyphs (12-20 um). The V2 tags are 23-34 um, with a larger keep-out that
    removes exactly the dots closest to the tag. Can the 0d statistic still
    DETECT a few-percent pinning at this geometry, or is the test blind where it
    matters? Only worth printing the Phase-6 coupon if it can.

METHOD — a sensitivity calibration, not a measurement
    Synthetic pairs with a KNOWN injected stiffening, through the identical 0d
    statistic (`tools/fiducial_stiffening.py`: global similarity fit, residual
    VECTORS rotated to the design frame, projected on the outward radial from
    the nearest tag, binned by distance, compared against a shifted-lattice
    control). Image detection is NOT in the loop -- dot positions are ground
    truth plus the measured 0.25 px localisation noise (Phase 0c) -- so this
    isolates the statistical power of the test at the V2 geometry: dot pitch,
    keep-out, tags in view. Phase D closes the loop through real detection.

    Pinning model: relative to the tag, a dot at design radius r lags its
    uniform-expansion position by  f * w(r) * (lambda-1) * (r - r_tag), with
    w = 1 at the tag edge decaying as exp(-((r - r_tag)/(tag/2))^2). f = 1 is
    full pinning at the tag edge. Injected f in {0, 2, 5, 10, 20}% over the
    same lambda in {2, 3, 4}, warp lobes, rotation, drift and FOV as the
    simulator, pooled as 0d pooled the real frames.

PASS (WORKSHOP_PLAN.md section 4)
    The test detects f = 5% at every candidate (inner ring at least 3 sigma
    below the control, recovered magnitude within 2x of injected) and reports
    no effect at f = 0 (|z| < 2).

Run:  python w4_stiffening_sensitivity.py
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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "tools")))
from aruco_grid import GridConfig, VARIANTS, build                          # noqa: E402
import simulate_v2 as V                                                     # noqa: E402
from fiducial_stiffening import similarity_vec, radial_profile              # noqa: E402

FIG_DIR = os.path.normpath(os.path.join(HERE, "..", "figures"))
OUT_JSON = os.path.join(FIG_DIR, "w4_stiffening_sensitivity.json")
CANDS = [("OPT", "optimistic"), ("HEDGE", "hedge"), ("SAFE", "conservative")]
FRACS = [0.0, 0.02, 0.05, 0.10, 0.20]
LAMS = [2.0, 3.0, 4.0]
SEEDS = [0, 1, 2, 3, 4, 5]        # each seed = its OWN warp realisation
LOC_NOISE_UM = 0.25 * 0.510            # Phase 0c localisation RMS, in um
BIN_UM, MAXD_UM = 4.0, 48.0            # as 0d


def cand_cfg(variant):
    v = VARIANTS[variant]
    return GridConfig(dict_name="DICT_4X4_50", tag_modules=6, tag_um=v["tag_um"],
                      psf_fwhm_um=v["psf_fwhm_um"], dot_side_um=2.125, dashes=True,
                      round_tags=True, fit="inside", field_um=750.0)


def pin_lag(D, tags, f, lam, tag_um):
    """Displacement (design-frame um, to be scaled by lam) that pinning removes."""
    from scipy.spatial import cKDTree
    d, idx = cKDTree(tags).query(D)
    v = D - tags[idx]
    r = np.hypot(v[:, 0], v[:, 1])
    rt = tag_um / 2.0
    w = np.exp(-np.clip((r - rt) / rt, 0, None) ** 2)
    lag = f * w * (lam - 1.0) * np.clip(r - rt, 0, None)
    u = np.zeros_like(v); ok = r > 1e-9
    u[ok] = v[ok] / r[ok, None]
    return -u * lag[:, None]                       # toward the tag


def one_frame(D, tags, lam, f, cfg, sim, lobes, theta, drift, rng):
    """True expanded positions (um, y-up render frame) of the in-view dots, plus
    the matching reference positions, both with localisation noise."""
    P0c = np.array([cfg.field_um / 2.0, cfg.field_um / 2.0])
    rfov = sim.fov_um * sim.render_margin
    centre = np.array([rfov / 2.0, rfov / 2.0]) + drift
    Xexp = centre + lam * (D - P0c) + V.warp_disp(D, lobes, sim.warp_sigma_um) * lam \
        + pin_lag(D, tags, f, lam, cfg.tag_um) * 1.0
    # scene rotation about the frame centre (design frame, y-up)
    t = math.radians(theta); c, s = math.cos(t), math.sin(t)
    R = np.array([[c, -s], [s, c]])
    Xexp = (Xexp - rfov / 2.0) @ R.T + rfov / 2.0
    lo, hi = (rfov - sim.fov_um) / 2, (rfov + sim.fov_um) / 2
    inview = (Xexp[:, 0] > lo) & (Xexp[:, 0] < hi) & (Xexp[:, 1] > lo) & (Xexp[:, 1] < hi)
    P0 = D[inview] + rng.normal(0, LOC_NOISE_UM, (inview.sum(), 2))
    P1 = Xexp[inview] + rng.normal(0, LOC_NOISE_UM, (inview.sum(), 2))
    return D[inview], P0, P1


def stacked(D, tags, cfg, sim, lobes, f, seeds):
    """0d statistic pooled over LAMS and seeds. Returns per-bin profile for the
    tag set and for the shifted-lattice control, in the design frame."""
    thetas = [sim.rotation_deg + k * sim.rotation_step_deg for k in range(6)]
    edges = np.arange(0, MAXD_UM + BIN_UM, BIN_UM) + cfg.keepout_um    # from the keep-out out
    half = 0.5 * cfg.box_pitch
    shifted = tags + np.array([half, half])
    lo_x, hi_x = tags[:, 0].min(), tags[:, 0].max()
    shifted[:, 0] = lo_x + np.mod(shifted[:, 0] - lo_x, max(hi_x - lo_x, 1e-9))
    shifted[:, 1] = lo_x + np.mod(shifted[:, 1] - lo_x, max(hi_x - lo_x, 1e-9))
    allr = {"tag": [], "ctl": []}; alld = {"tag": [], "ctl": []}; n_pairs = 0
    per_seed = []                                   # inner-ring (tag - control) per realisation
    for s in seeds:
        rng = np.random.default_rng(1000 + s)
        drng = np.random.default_rng(sim.drift_seed + s)
        # A NEW warp field per seed. The 0d caveat -- residuals are spatially
        # correlated by the smooth warp -- means a single warp realisation carries a
        # systematic that per-dot SEMs cannot see. Sampling realisations lets the
        # significance come from the scatter BETWEEN them, which is honest.
        sim_s = V.SimConfig(); sim_s.render_margin = sim.render_margin
        sim_s.warp_seed = sim.warp_seed + 17 * s
        lobes_s = V.make_lobes(cfg.field_um, sim_s)
        seed_r = {"tag": [], "ctl": []}; seed_d = {"tag": [], "ctl": []}
        for k, lam in enumerate(LAMS):
            drift = drng.uniform(-sim.drift_um, sim.drift_um, 2)
            Dv, P0, P1 = one_frame(D, tags, lam, f, cfg, sim, lobes_s, thetas[k + 1], drift, rng)
            if len(P0) < 50:
                continue
            sc, R, res = similarity_vec(P0, P1)
            res_um = (res @ R) / max(sc, 1e-12)          # back to the design frame, um
            n_pairs += len(P0)
            for key, centres in (("tag", tags), ("ctl", shifted)):
                _p, radial, d = radial_profile(Dv, res_um, centres, edges)
                allr[key].append(radial); alld[key].append(d)
                seed_r[key].append(radial); seed_d[key].append(d)
        w = 12.0 + cfg.keepout_um
        mt = np.concatenate(seed_d["tag"]) < w; mc = np.concatenate(seed_d["ctl"]) < w
        mt &= np.concatenate(seed_d["tag"]) >= cfg.keepout_um
        mc &= np.concatenate(seed_d["ctl"]) >= cfg.keepout_um
        per_seed.append(float(np.concatenate(seed_r["tag"])[mt].mean()
                              - np.concatenate(seed_r["ctl"])[mc].mean()))
    out = {}
    for key in ("tag", "ctl"):
        r = np.concatenate(allr[key]); d = np.concatenate(alld[key])
        rows = []
        for lo, hi in zip(edges[:-1], edges[1:]):
            m = (d >= lo) & (d < hi); k = int(m.sum())
            if k < 20:
                continue
            rows.append(dict(lo=float(lo - cfg.keepout_um), hi=float(hi - cfg.keepout_um), n=k,
                             mean=float(r[m].mean()), sem=float(r[m].std(ddof=1) / math.sqrt(k))))
        out[key] = rows
    out["per_seed_diff"] = per_seed
    return out, n_pairs, edges


def inner(rows, width=12.0):
    sel = [r for r in rows if r["hi"] <= width + 1e-9]
    if not sel:
        return None
    n = sum(r["n"] for r in sel)
    mu = sum(r["mean"] * r["n"] for r in sel) / n
    sem = math.sqrt(sum((r["sem"] * r["n"]) ** 2 for r in sel)) / n
    return dict(n=n, mean=mu, sem=sem)


def main():
    os.makedirs(FIG_DIR, exist_ok=True)
    t0 = time.time()
    sim = V.SimConfig()
    th = math.radians(sim.rotation_deg + 5 * sim.rotation_step_deg)
    sim.render_margin = max(sim.render_margin,
                            math.cos(th) + math.sin(th) + 2 * sim.drift_um / sim.fov_um + 0.02)
    results = {}
    for cname, variant in CANDS:
        cfg = cand_cfg(variant)
        with contextlib.redirect_stdout(io.StringIO()):
            _r, _recs, info = build(cfg)
        D = np.array([[i["cx"], i["cy"]] for i in info["islands"] if i["kind"] == "dot"])
        tags = np.array([[i["cx"], i["cy"]] for i in info["islands"] if i["kind"] == "aruco"])
        lobes = V.make_lobes(cfg.field_um, sim)
        # expected FULL-pinning lag at the inner-ring centre, in design um, n-weighted over LAMS
        rc = cfg.keepout_um + 6.0
        full = float(np.mean([(lam - 1) * (rc - cfg.tag_um / 2)
                              * math.exp(-((rc - cfg.tag_um / 2) / (cfg.tag_um / 2)) ** 2)
                              for lam in LAMS])) / float(np.mean(LAMS))
        print(f"\n[{cname}]  tag {cfg.tag_um} um, keep-out {cfg.keepout_um:.1f} um, "
              f"{len(D):,} dots; full pinning at the inner ring = {full:.2f} um (design)")
        print(f"{'inject f':>9}{'pairs':>8}{'tag-ctl um':>13}{'SE (6 warps)':>13}{'z':>7}"
              f"{'recovered f':>13}")
        rows = []
        for f in FRACS:
            prof, n_pairs, _e = stacked(D, tags, cfg, sim, lobes, f, SEEDS)
            it, ic = inner(prof["tag"]), inner(prof["ctl"])
            ps = np.array(prof["per_seed_diff"])
            diff = float(ps.mean())
            sem = float(ps.std(ddof=1) / math.sqrt(len(ps)))     # across warp realisations
            z = diff / sem if sem > 0 else 0.0
            fhat = -diff / full if full > 0 else float("nan")
            rows.append(dict(f=f, pairs=n_pairs, inner=it, control=ic, diff_um=diff,
                             sem_um=sem, z=z, f_recovered=fhat))
            print(f"{f:>9.0%}{n_pairs:>8,}{diff:>+13.3f}{sem:>13.3f}{z:>+7.1f}{fhat:>13.1%}")
        # minimum detectable f: where z crosses -3 (linear interpolation on |z|)
        zs = [-r["z"] for r in rows]; fs = [r["f"] for r in rows]
        fmin = None
        for i in range(1, len(rows)):
            if zs[i - 1] < 3 <= zs[i]:
                fmin = fs[i - 1] + (3 - zs[i - 1]) * (fs[i] - fs[i - 1]) / (zs[i] - zs[i - 1]); break
        if fmin is None and zs and zs[1] >= 3:
            fmin = fs[1] * 3 / zs[1]
        r5 = next(r for r in rows if abs(r["f"] - 0.05) < 1e-9); r0 = rows[0]
        ok = (r5["z"] <= -3 and 0.5 <= r5["f_recovered"] / 0.05 <= 2.0 and abs(r0["z"]) < 2)
        print(f"   -> minimum detectable pinning ~{fmin:.1%}   |  f=0: z={r0['z']:+.1f}   "
              f"f=5%: z={r5['z']:+.1f}, recovered {r5['f_recovered']:.1%}   {'PASS' if ok else 'FAIL'}")
        results[cname] = dict(tag_um=cfg.tag_um, keepout_um=cfg.keepout_um, n_dots=len(D),
                              full_pinning_um=full, rows=rows, f_min_detectable=fmin, passes=ok)

    print(f"\nW4: {'PASS' if all(R['passes'] for R in results.values()) else 'FAIL'}")

    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.5, 4.6), dpi=110)
    for cname, R in results.items():
        f = [100 * r["f"] for r in R["rows"]]
        ax1.errorbar(f, [100 * r["f_recovered"] for r in R["rows"]],
                     yerr=[100 * r["sem_um"] / R["full_pinning_um"] for r in R["rows"]],
                     marker="o", capsize=3, label=f"{cname} (tag {R['tag_um']:.0f} um)")
        ax2.plot(f, [-r["z"] for r in R["rows"]], "o-", label=cname)
    lim = max(f) * 1.1
    ax1.plot([0, lim], [0, lim], "k--", lw=0.8, label="identity")
    ax1.set_xlabel("injected pinning (% of full)"); ax1.set_ylabel("recovered pinning (% of full)")
    ax1.grid(alpha=.3); ax1.legend(fontsize=8); ax1.set_title("recovery", fontsize=10)
    ax2.axhline(3, c="k", ls="--", lw=0.8, label="3σ detection")
    ax2.set_xlabel("injected pinning (% of full)"); ax2.set_ylabel("significance vs control (σ)")
    ax2.set_yscale("symlog", linthresh=3); ax2.grid(alpha=.3); ax2.legend(fontsize=8)
    ax2.set_title("detectability", fontsize=10)
    fig.suptitle("W4 — sensitivity of the 0d stiffening test at the V2 tag scale "
                 "(truth + 0.25 px noise, pooled λ 2–4)", fontsize=10)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(os.path.join(FIG_DIR, "stiffening_sensitivity.png")); plt.close(fig)
    with open(OUT_JSON, "w") as fh:
        json.dump(dict(fracs=FRACS, lams=LAMS, seeds=SEEDS, loc_noise_um=LOC_NOISE_UM,
                       results=results), fh, indent=1, default=float)
    print(f"wrote figures/stiffening_sensitivity.png + w4_stiffening_sensitivity.json  "
          f"({(time.time()-t0)/60:.1f} min)")


if __name__ == "__main__":
    main()
