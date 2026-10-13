#!/usr/bin/env python3
"""
phase_d_end_to_end.py — Phase D gate: the whole V2 pipeline against known truth.

WHAT PHASE C DID NOT TEST
    Phase C scored positions: does every dot get its tag, and how close is the
    centre to truth. Phase D scores what the app actually reports -- the expansion
    factor and the non-uniform deformation field -- derived from PAIRED frames
    exactly as the pairing / strain stages derive them, and asks whether pipeline
    bias and gel physics separate (the +6.5%-at-4.2x question of the V1 series).

SET-UP (W8 note: the simulator's warp is a print distortion applied in every frame,
so it is switched OFF for the reference)
    reference   lambda = 1, no warp, rotation 2 deg, drift
    expanded    lambda in {1.5, 2, 3, 4, 6}, warp w(X) (14 lobes, 2 um, sigma 90 um)
                so that x' = R [ lambda (X + w(X)) ] + t, rotation + drift per frame,
                exposure fully compensated (W6), L2 noise
    pipeline    rwtag.aruco.series.process_frames -> pair_table (tags by identity)
                -> per frame: similarity design->expanded (lambda, rigid motion),
                   residual = recovered w(X); local affine over R = 25 um -> Green
                   strain (as W8); rwtag.refwarp.strain.strain (the app's number)

SCORED AGAINST TRUTH, per lambda
    lambda      recovered / injected - 1 (global similarity through all paired dots)
    warp        RMS |w_rec - w_true| over paired dots (design um) and the correlation
                of the two fields; w_true from the simulator's own warp_disp
    strain      RMS error of the Green strain field at R = 25 um vs the analytic field
    pairing     paired dots vs the in-frame truth count

GATE
    |lambda error| < 0.5% at every level · warp RMS error < 0.35 um (17% of the 2 um
    amplitude) and correlation > 0.9 · strain RMS error at R = 25 um < 0.006 (W8's
    OPT/HEDGE/SAFE band) · every frame paired by identity with >= 90% of its truth dots (W9's floor)

Run:  python phase_d_end_to_end.py [--variant optimistic] [--all]
      -> docs/phase_d_end_to_end.{png,json}
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
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "workshop", "scripts")))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "Reference_Warp_Tagger")))
from aruco_grid import build                                                     # noqa: E402
import simulate_v2 as V                                                          # noqa: E402
from phase_c_verify import cand_cfg, design_of, stage1, truth, NOISE, DOCS       # noqa: E402
from w8_lattice_density_field import local_strain, true_strain                   # noqa: E402
from rwtag.aruco import ArucoParams, series as AS                                # noqa: E402
from rwtag import pairing as PR                                                  # noqa: E402
from rwtag.refwarp import strain as ST                                           # noqa: E402

LAMS = [1.5, 2.0, 3.0, 4.0, 6.0]
R_STRAIN = 25.0


def similarity(X, Y):
    """Y ~ s R X + t with R ORTHOGONAL -- reflection allowed. Design (y-up) to image
    (y-down) IS a reflection, and forcing a proper rotation here (Umeyama's usual
    det = +1 constraint) fits s ~ 0 with a 100% "lambda error" -- the 0d / Phase-B /
    W8 / Phase-C handedness bug, once more. Returns s, R, t, sign(det R)."""
    mx, my = X.mean(0), Y.mean(0)
    A, B = X - mx, Y - my
    U, sv, Vt = np.linalg.svd(A.T @ B)
    R = (U @ Vt).T
    s = float(sv.sum() / (A ** 2).sum())
    return s, R, my - s * R @ mx, float(np.sign(np.linalg.det(R)))


def run(variant):
    gcfg = cand_cfg(variant)
    with contextlib.redirect_stdout(io.StringIO()):
        _r, recs, info = build(gcfg)
    design = design_of(gcfg, recs, info)
    islands = info["islands"]
    dot_recs = [r for r in recs if r["category"] == "dot"]
    X_by_tag = {r["tag"]: np.array([r["x_um"], r["y_um"]]) for r in dot_recs}

    sim = V.SimConfig(); sim.signal_exp = 0.0
    sim0 = V.SimConfig(); sim0.signal_exp = 0.0; sim0.warp_amp_um = 0.0     # reference: no warp
    lobes = V.make_lobes(gcfg.field_um, sim)
    lobes0 = V.make_lobes(gcfg.field_um, sim0)
    band_um = abs(sim.lens_k1) * sim.fov_um / 2.0 * 1.4
    params = ArucoParams(um_per_px=sim.um_per_px, psf_fwhm_um=gcfg.psf_fwhm_um, edge_band_um=band_um)
    lv = V.Level("D", gcfg.psf_fwhm_um, NOISE["read_noise"], NOISE["full_well"], NOISE["background"])
    drng = np.random.default_rng(sim.drift_seed + 7)

    frames, geo, truth_px_by_tag = [], {}, {}
    for k, lam in enumerate([1.0] + LAMS):
        s_, lb = (sim0, lobes0) if lam == 1.0 else (sim, lobes)
        theta = sim.rotation_deg + k * sim.rotation_step_deg
        drift = drng.uniform(-sim.drift_um, sim.drift_um, 2)
        rects, _tc, _tid = V.place(islands, lam, s_, lb, gcfg.field_um, drift)
        img = V.degrade(V.render_scene(rects, s_, theta), s_, lv, np.random.default_rng(100 + k), lam=None)
        frames.append((lam, stage1(img, s_)))
        Td, okd, _ = truth(islands, "dot", lam, s_, gcfg, lb, theta, drift)
        geo[lam] = dict(Td=Td, okd=okd)
        truth_px_by_tag[lam] = {r["tag"]: Td[i] for i, r in enumerate(dot_recs)}

    t0 = time.time()
    sf = AS.process_frames(frames, design, params)
    t_pipe = time.time() - t0
    assert all(f.ok for f in sf), [(f.label, f.reason) for f in sf if not f.ok]
    ref = sf[0]
    rows = []
    print(f"\n=== {variant.upper()}  tag {gcfg.tag_um} um · PSF {gcfg.psf_fwhm_um} · pitch "
          f"{gcfg.dot_pitch_um:.2f} um · pipeline {t_pipe:.1f} s for {len(sf)} frames ===")
    print(f"{'λ':>5}{'paired':>8}{'truth':>7}{'λ rec':>9}{'λ eff':>8}{'pipe err':>9}{'gel':>8}{'app λ':>8}"
          f"{'w true':>8}{'w err':>7}{'corr':>7}{'E true':>8}{'E err':>8}{'N@25':>6}")
    for f in sf[1:]:
        lam = f.label
        pairs = PR.pair_tags(ref.tags, f.tags, kinds=("dot",))
        tags = sorted(pairs)
        X = np.array([X_by_tag[t] for t in tags])                          # design um
        Y = np.array([pairs[t][2:] for t in tags])                         # expanded px
        s, R, t, hand = similarity(X, Y)
        lam_rec = s * sim.um_per_px
        # TRUTH through the same estimator, on the same dots. A random lobe field has a
        # non-zero mean gradient, so the similarity that best fits the TRUE positions is
        # not exactly lambda: lambda_eff = lambda x (1 + mean dilation in view). That is
        # gel physics, not pipeline bias -- and separating the two is the point of
        # Phase D. Pipeline error = lambda_rec / lambda_eff - 1; gel = lambda_eff / lambda - 1.
        Tpx = np.array([truth_px_by_tag[lam][tg] for tg in tags])
        s_t, R_t, t_t, _ = similarity(X, Tpx)
        lam_eff = s_t * sim.um_per_px
        # non-similarity part of the deformation, recovered vs true, design um
        w_rec = ((Y - t) @ R) / s - X
        w_true = ((Tpx - t_t) @ R_t) / s_t - X
        w_err = float(np.sqrt(np.mean(np.sum((w_rec - w_true) ** 2, 1))))
        corr = float(np.corrcoef(w_rec.ravel(), w_true.ravel())[0, 1])
        # strain of the DE-EXPANDED field (Rev C/D pipeline: affine de-expansion, then
        # local F -> Green strain), so noise enters once and the gate does not scale as
        # lambda^2; recovered vs the truth positions through the same estimator
        E, N = local_strain(X, X + w_rec, R_STRAIN)
        Et, _ = local_strain(X, X + w_true, R_STRAIN)
        good = np.isfinite(E[:, 0]) & np.isfinite(Et[:, 0]) & (N >= 30)
        e_rms = float(np.sqrt(np.mean((E[good] - Et[good]) ** 2))) if good.any() else float("nan")
        e_true_rms = float(np.sqrt(np.mean(Et[good] ** 2))) if good.any() else float("nan")
        app = ST.strain(ref.tags, f.tags, 1.0, lam)
        n_truth = int(geo[lam]["okd"].sum())
        row = dict(lam=lam, paired=len(pairs), truth_in=n_truth, paired_frac=len(pairs) / n_truth,
                   lam_rec=lam_rec, lam_eff=lam_eff, lam_err=lam_rec / lam_eff - 1,
                   gel_dilation=lam_eff / lam - 1, app_lam=app.get("mean", float("nan")),
                   app_sigma=app.get("sigma", float("nan")), warp_rms_um=float(w_err), warp_corr=corr,
                   warp_true_rms_um=float(np.sqrt(np.mean(np.sum(w_true ** 2, 1)))), strain_true_rms=e_true_rms,
                   strain_rms=e_rms, n_at_25=float(np.median(N[good])) if good.any() else 0.0,
                   handedness=hand)
        rows.append(row)
        print(f"{lam:>5.1f}{len(pairs):>8,}{n_truth:>7,}{lam_rec:>9.4f}{lam_eff:>8.4f}{100*row['lam_err']:>+8.3f}%"
              f"{100*row['gel_dilation']:>+7.2f}%{row['app_lam']:>8.3f}{row['warp_true_rms_um']:>8.3f}{w_err:>7.3f}"
              f"{corr:>7.3f}{e_true_rms:>8.4f}{e_rms:>8.4f}{row['n_at_25']:>6.0f}")
    gate = {
        "|λ pipeline error| < 0.5% at every level": all(abs(r["lam_err"]) < 0.005 for r in rows),
        "warp RMS error < 0.35 um and corr > 0.9": all(r["warp_rms_um"] < 0.35 and r["warp_corr"] > 0.9 for r in rows),
        "strain RMS error at R=25 < 0.006": all(r["strain_rms"] < 0.006 for r in rows),
        # W9's PASS floor for worst-frame dot efficiency is 90%; SAFE runs at 91-97% and
        # the shortfall is detection (crowding at the 1.75x rule), not pairing
        ">= 90% of in-frame truth dots paired by identity (W9 floor)": all(r["paired_frac"] >= 0.90 for r in rows),
        "design -> image handedness -1 on every frame": all(r["handedness"] == -1 for r in rows),
    }
    for k, v in gate.items():
        print(f"    [{'PASS' if v else 'FAIL'}] {k}")
    ok = all(gate.values())
    print(f"  PHASE-D GATE ({variant}): {'PASS' if ok else 'FAIL'}")
    return dict(rows=rows, gate=gate, pass_=ok, tag_um=gcfg.tag_um, psf=gcfg.psf_fwhm_um,
                warp_amp_um=sim.warp_amp_um, t_pipeline=t_pipe)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="optimistic")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    os.makedirs(DOCS, exist_ok=True)
    t0 = time.time()
    res = {v: run(v) for v in (["optimistic", "hedge", "conservative"] if a.all else [a.variant])}
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 3, figsize=(13, 3.9), dpi=110)
    for v, r in res.items():
        L = [x["lam"] for x in r["rows"]]
        ax[0].plot(L, [100 * x["lam_err"] for x in r["rows"]], "o-", label=f"{v} pipeline (vs λ_eff)")
        ax[0].plot(L, [100 * x["gel_dilation"] for x in r["rows"]], "s:", label=f"{v} gel: λ_eff/λ − 1")
        ax[1].plot(L, [x["warp_rms_um"] for x in r["rows"]], "o-", label=v)
        ax[2].plot(L, [x["strain_rms"] for x in r["rows"]], "o-", label=v)
    ax[0].axhline(0, c="k", lw=0.6); ax[0].set_ylabel("%")
    ax[0].set_title("expansion factor", fontsize=10)
    ax[1].plot(L, [x["warp_true_rms_um"] for x in res[list(res)[0]]["rows"]], "k--", lw=0.8, label="true non-uniform RMS")
    ax[1].set_ylabel("RMS |w_rec − w_true| (µm, design)"); ax[1].set_title("non-uniform warp field", fontsize=10)
    ax[2].axhline(0.006, c="k", ls="--", lw=0.7); ax[2].set_ylabel("Green-strain RMS error, R = 25 µm (de-expanded)")
    ax[2].set_title("strain field vs analytic", fontsize=10)
    for x in ax:
        x.set_xlabel("λ"); x.grid(alpha=.3); x.legend(fontsize=7)
    fig.suptitle("Phase D — end-to-end V2 pipeline vs injected truth", fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.93]); fig.savefig(os.path.join(DOCS, "phase_d_end_to_end.png"))
    with open(os.path.join(DOCS, "phase_d_end_to_end.json"), "w") as fh:
        json.dump(res, fh, indent=1, default=float)
    ok = all(r["pass_"] for r in res.values())
    print(f"\nwrote docs/phase_d_end_to_end.png + .json ({(time.time()-t0)/60:.1f} min)\nPHASE-D GATE: {'PASS' if ok else 'FAIL'}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
