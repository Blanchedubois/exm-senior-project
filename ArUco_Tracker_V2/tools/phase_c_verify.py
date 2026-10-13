#!/usr/bin/env python3
"""
phase_c_verify.py — Phase C gate: the rwtag ArUco detection path against known truth.

WHAT IS TESTED (IMPLEMENTATION_PLAN.md, Phase C "Verify")
    Synthetic frames of a gated V2 print through the Phase-B camera model (real
    pixel size and FOV, lens + vignette + rotation + drift + non-uniform warp,
    ladder noise, exposure fully compensated as W6 requires), Stage-1 corrected
    (un-distorted, flat-fielded), then the PRODUCTION path:

        rwtag.aruco.detect  ->  refwarp.tagframe.tag_frame  ->  tags {tag: px}

    scored against the simulator's ground truth, dot by dot and tag by tag:
      registration  every frame registers; handedness sign is the reflection a
                    y-up design must have in a y-down image (-1); the tag-affine
                    predicts the in-frame truth dots to a fraction of a pitch
      tag recovery  >= 99% of the dots the pipeline TAGS carry the right tag
                    (mis-tag rate <= 1%); detection efficiency reported (W9 owns
                    that number, this script does not gate it)
      residual      RMS of correctly-tagged centres vs truth, below the Phase-B
                    noise floor (0.5 px); the three refinements (none / Gaussian-
                    mask / W7 least-squares fit) compared on the same frames
      series        rwtag.aruco.series.process_frames accepts every frame

Run:  python phase_c_verify.py [--variant optimistic] [--quick] [--all]
      -> docs/phase_c_verify.{png,json}
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
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "Reference_Warp_Tagger")))
from aruco_grid import GridConfig, VARIANTS, build                              # noqa: E402
from dataclasses import asdict                                                  # noqa: E402
import simulate_v2 as V                                                         # noqa: E402
from rwtag.aruco import ArucoParams, Design, detect, series as AS               # noqa: E402
from rwtag.refwarp import tagframe as TF                                        # noqa: E402

DOCS = os.path.normpath(os.path.join(HERE, "..", "docs"))
NOISE = dict(read_noise=6.0, full_well=240.0, background=14.0)      # L2 "as designed"
LAMS = [1.0, 1.5, 2.0, 3.0, 4.0, 6.0]


def cand_cfg(variant):
    v = VARIANTS[variant]
    return GridConfig(dict_name="DICT_4X4_50", tag_modules=6, tag_um=v["tag_um"],
                      psf_fwhm_um=v["psf_fwhm_um"], dot_side_um=2.125, dashes=True,
                      round_tags=True, fit="inside", field_um=750.0)


def design_of(cfg, recs, info):
    return Design.from_dict({"box_um": cfg.box_pitch, "grid_n": cfg.grid_n,
                             "dot_pitch": cfg.dot_pitch_um, "dot_phase": info["dot_phase"],
                             "dot_side_um": cfg.dot_side_um, "config": asdict(cfg),
                             "records": recs})


def stage1(img, sim):
    """What Stage 1 does to a real frame: un-distort, divide out the vignette.
    Bright-on-dark uint8 (the detector inverts for ArUco itself)."""
    d = V._radial(img, sim.lens_k1, sim.lens_k2, sim.fov_px / 2.0, inverse=True)
    return np.clip(d.astype(np.float32) / np.clip(V._vignette(d.shape, sim), 0.10, 1.0),
                   0, 255).astype(np.uint8)


def truth(islands, kind, lam, sim, gcfg, lobes, theta, drift):
    """Ground-truth centres of every island of `kind`, in the UN-DISTORTED frame's
    pixel coordinates (aligned with the records of that kind), plus the in-frame
    mask (inside the W3 edge band). y-up design -> y-down image happens here."""
    rfov = sim.fov_um * sim.render_margin
    P0 = np.array([gcfg.field_um / 2.0, gcfg.field_um / 2.0])
    centre = np.array([rfov / 2.0, rfov / 2.0]) + np.asarray(drift, float)
    M = cv2.getRotationMatrix2D((rfov / 2, rfov / 2), theta, 1.0)
    C = np.array([[i["cx"], i["cy"]] for i in islands if i["kind"] == kind], float)
    Cd = centre + lam * (C - P0) + V.warp_disp(C, lobes, sim.warp_sigma_um) * lam
    T = np.column_stack([Cd[:, 0], rfov - Cd[:, 1]])
    R = T @ M[:, :2].T + M[:, 2]
    lo = (rfov - sim.fov_um) / 2
    band = abs(sim.lens_k1) * sim.fov_um / 2.0 * 1.4
    m = band + ((gcfg.tag_um / 2) * (abs(math.cos(math.radians(theta))) + abs(math.sin(math.radians(theta))))
                if kind == "aruco" else 0.0)
    ok = ((R[:, 0] > lo + m) & (R[:, 0] < lo + sim.fov_um - m) &
          (R[:, 1] > lo + m) & (R[:, 1] < lo + sim.fov_um - m))
    return (R - lo) / sim.um_per_px - 0.5, ok, band


def score_frame(u8, design, params, recs, islands, lam, sim, gcfg, lobes, theta, drift):
    dot_recs = [r for r in recs if r["category"] == "dot"]
    tag_recs = [r for r in recs if r["category"] == "aruco"]
    Td, okd, band = truth(islands, "dot", lam, sim, gcfg, lobes, theta, drift)
    Ta, oka, _ = truth(islands, "aruco", lam, sim, gcfg, lobes, theta, drift)
    ids_in = {int(r["meta"]["aruco_id"]) for r, o in zip(tag_recs, oka) if o}
    truth_px = {r["tag"]: Td[k] for k, r in enumerate(dot_recs)}
    n_truth_in = int(okd.sum())

    t0 = time.time()
    det = detect(u8, design, params)
    t_det = time.time() - t0
    m = det.model
    row = dict(lam=lam, theta=theta, tags_in=len(ids_in), tags_dec=0, registered=bool(m.get("registered")),
               sign=float(m.get("sign", 0)), dots_in=n_truth_in, n_det=int(len(det.dots)),
               t_detect=t_det)
    if not m.get("registered"):
        row.update(tag_correct=0.0, recovered=0.0, wrong=1.0, rms_px=float("nan"), affine_med_px=float("nan"))
        return row, det, None
    row["tags_dec"] = len(set(m["aruco_xy"]) & ids_in)
    # tag-affine accuracy on the in-frame truth (no warp refinement yet)
    D = np.array([[r["x_um"], r["y_um"]] for r in dot_recs], float)[okd]
    A = m["affine"]
    pred = D @ A[:, :2].T + A[:, 2]
    row["affine_med_px"] = float(np.median(np.hypot(*(pred - Td[okd]).T)))

    filt = AS.filter_frame(det)
    t0 = time.time()
    tr = TF.tag_frame(det, filt, design.records, tps=True)
    row["t_tag"] = time.time() - t0
    if tr is None:
        row.update(tag_correct=0.0, recovered=0.0, wrong=1.0, rms_px=float("nan"))
        return row, det, None
    assigned = [(t, xy) for t, xy in tr.tags.items() if t.startswith("dot|")]
    err = np.array([np.hypot(*(np.array(xy) - truth_px[t])) for t, xy in assigned]) if assigned else np.zeros(0)
    correct = err < 3.0
    dv = np.array([np.array(xy) - truth_px[t] for t, xy in assigned]) if assigned else np.zeros((0, 2))
    bias = dv[correct].mean(0) if correct.any() else np.full(2, np.nan)
    rms_deb = float(np.sqrt(np.mean(np.sum((dv[correct] - bias) ** 2, 1)))) if correct.any() else float("nan")
    row.update(bias_px=[float(bias[0]), float(bias[1])], rms_debiased_px=rms_deb,
               affine_method=m["affine_info"]["method"])
    row.update(n_assigned=len(assigned), n_correct=int(correct.sum()),
               tag_correct=float(correct.mean()) if len(err) else 0.0,
               wrong=float((~correct).mean()) if len(err) else 0.0,
               recovered=float(correct.sum() / max(n_truth_in, 1)),
               rms_px=float(np.sqrt(np.mean(err[correct] ** 2))) if correct.any() else float("nan"),
               warp_resid=float(tr.warp["per_det_median"]), warp_matched=float(tr.warp["matched_frac"]),
               warp_kind=tr.warp["kind"], band_um=band)
    return row, det, tr


def refinement_rms(u8, design, params, truth_px_all, okd):
    """RMS vs truth for the three centre refinements, one-to-one matched."""
    out = {}
    T = truth_px_all[okd]
    for r in ("none", "gauss", "fit"):
        p = ArucoParams(**dict(asdict(params), refine=r))
        t0 = time.time()
        det = detect(u8, design, p)
        dt = time.time() - t0
        d, j = cKDTree(det.dots).query(T)
        hit = d < 3.0
        dv = det.dots[j[hit]] - T[hit]; bias = dv.mean(0)
        out[r] = dict(rms_px=float(np.sqrt(np.mean(d[hit] ** 2))), eff=float(hit.mean()), t=dt,
                      bias_px=[float(bias[0]), float(bias[1])],
                      rms_debiased_px=float(np.sqrt(np.mean(np.sum((dv - bias) ** 2, 1)))))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="optimistic")
    ap.add_argument("--all", action="store_true", help="run all three candidates")
    ap.add_argument("--quick", action="store_true", help="lambda 1, 2, 4 only, one seed")
    ap.add_argument("--seeds", type=int, default=2)
    a = ap.parse_args()
    os.makedirs(DOCS, exist_ok=True)
    variants = ["optimistic", "hedge", "conservative"] if a.all else [a.variant]
    lams = [1.0, 2.0, 4.0] if a.quick else LAMS
    seeds = [0] if a.quick else list(range(a.seeds))
    t_start = time.time()
    results, gate_all = {}, True
    for variant in variants:
        gcfg = cand_cfg(variant)
        with contextlib.redirect_stdout(io.StringIO()):
            _r, recs, info = build(gcfg)
        design = design_of(gcfg, recs, info)
        islands = info["islands"]
        sim = V.SimConfig(); sim.signal_exp = 0.0            # exposure policy applied (W6)
        lobes = V.make_lobes(gcfg.field_um, sim)
        band_um = abs(sim.lens_k1) * sim.fov_um / 2.0 * 1.4
        params = ArucoParams(um_per_px=sim.um_per_px, psf_fwhm_um=gcfg.psf_fwhm_um,
                             edge_band_um=band_um)
        lv = V.Level("C", gcfg.psf_fwhm_um, NOISE["read_noise"], NOISE["full_well"], NOISE["background"])
        thetas = [sim.rotation_deg + k * sim.rotation_step_deg for k in range(len(LAMS))]
        rows, frames_for_series, refine = [], [], None
        print(f"\n=== {variant.upper()}  tag {gcfg.tag_um} um · PSF {gcfg.psf_fwhm_um} · pitch "
              f"{gcfg.dot_pitch_um:.2f} um · top-hat {params.tophat_px(gcfg.dot_side_um)} px · "
              f"edge band {band_um:.0f} um ===")
        print(f"{'seed':>4}{'λ':>5}{'tags':>8}{'sign':>6}{'affine':>8}{'dots in':>9}{'det':>7}"
              f"{'tagged':>8}{'correct':>9}{'recov':>7}{'rms px':>8}{'bias x,y':>13}{'rms-b':>7}{'warp':>7}{'t(s)':>6}")
        for seed in seeds:
            drng = np.random.default_rng(sim.drift_seed + 101 * seed)
            for lam in lams:
                k = LAMS.index(lam)
                drift = drng.uniform(-sim.drift_um, sim.drift_um, 2)
                rects, _tc, _tid = V.place(islands, lam, sim, lobes, gcfg.field_um, drift)
                base = V.render_scene(rects, sim, thetas[k])
                img = V.degrade(base, sim, lv, np.random.default_rng(k + 10 * seed), lam=None)
                u8 = stage1(img, sim)
                row, det, tr = score_frame(u8, design, params, recs, islands, lam, sim, gcfg,
                                           lobes, thetas[k], drift)
                row["seed"] = seed
                rows.append(row)
                if seed == seeds[0]:
                    frames_for_series.append((lam, u8))
                if seed == seeds[0] and lam in (1.0, 4.0):
                    Td, okd, _ = truth(islands, "dot", lam, sim, gcfg, lobes, thetas[k], drift)
                    refine = refine or {}
                    refine[str(lam)] = refinement_rms(u8, design, params, Td, okd)
                print(f"{seed:>4}{lam:>5.1f}{row['tags_dec']:>4}/{row['tags_in']:<3}{row['sign']:>+6.0f}"
                      f"{row['affine_med_px']:>8.2f}{row['dots_in']:>9,}{row['n_det']:>7,}"
                      f"{row.get('n_assigned', 0):>8,}{row['tag_correct']:>9.1%}{row['recovered']:>7.0%}"
                      f"{row['rms_px']:>8.3f}{str([round(x, 2) for x in row.get('bias_px', [float('nan')] * 2)]):>13}"
                      f"{row.get('rms_debiased_px', float('nan')):>7.3f}{row.get('warp_resid', float('nan')):>7.2f}"
                      f"{row['t_detect'] + row.get('t_tag', 0):>6.1f}")

        # degraded registration: the highest-lambda seed-0 frame with the reference map
        # cut down to 2 and then 1 of its in-frame tags (exercises the similarity and
        # single-tag + dot-lattice-scale paths that a sparse real frame will hit)
        degraded = []
        lam_hi = lams[-1]; k = LAMS.index(lam_hi)
        drng = np.random.default_rng(sim.drift_seed); drift = None
        for l in lams:
            drift = drng.uniform(-sim.drift_um, sim.drift_um, 2)
        u8_hi = frames_for_series[-1][1]
        Ta, oka, _ = truth(islands, "aruco", lam_hi, sim, gcfg, lobes, thetas[k], drift)
        tag_recs = [r for r in recs if r["category"] == "aruco"]
        in_ids = [int(r["meta"]["aruco_id"]) for r, o in zip(tag_recs, oka) if o]
        for n_keep in (2, 1):
            keep = set(in_ids[:n_keep])
            sub = [r for r in recs if r["category"] != "aruco" or int(r["meta"]["aruco_id"]) in keep]
            dsub = Design.from_dict({"box_um": gcfg.box_pitch, "grid_n": gcfg.grid_n,
                                     "dot_pitch": gcfg.dot_pitch_um, "dot_side_um": gcfg.dot_side_um,
                                     "config": asdict(gcfg), "records": sub})
            row, _d, _t = score_frame(u8_hi, dsub, params, sub, islands, lam_hi, sim, gcfg, lobes,
                                      thetas[k], drift)
            row["n_known_tags"] = n_keep
            degraded.append(row)
            print(f"  degraded map, λ{lam_hi:g}, {n_keep} known tag(s): {row.get('affine_method')} · "
                  f"affine {row['affine_med_px']:.1f} px · correct {row['tag_correct']:.1%} · "
                  f"recovered {row['recovered']:.0%}")

        # series driver on seed-0 frames
        sf = AS.process_frames(frames_for_series, design, params)
        ser = [dict(lam=f.label, ok=f.ok, source=f.source, n_tags=f.n_tags, reason=f.reason,
                    confidence=f.confidence) for f in sf]
        print("  series: " + " · ".join(f"λ{s['lam']:g} {'OK' if s['ok'] else 'REJECT'}"
                                        f"({s['source'] or s['reason']}, {s['n_tags']})" for s in ser))
        if refine:
            print("  refinement (seed 0):  " + "   ".join(
                f"λ{l}: " + " ".join(f"{r} {v['rms_px']:.3f}px (de-biased {v['rms_debiased_px']:.3f}) {v['t']:.1f}s" for r, v in d.items())
                for l, d in refine.items()))

        gate = {
            "every frame registered": all(r["registered"] for r in rows),
            "handedness = -1 (mirror) on every frame": all(r["sign"] == -1 for r in rows),
            "tag affine within 0.5 pitch of truth": all(
                r["affine_med_px"] < 0.5 * gcfg.dot_pitch_um / sim.um_per_px for r in rows),
            "tag correctness >= 99% on every frame": all(r["tag_correct"] >= 0.99 for r in rows),
            "RMS of correct tags < 0.5 px": all(r["rms_px"] < 0.5 for r in rows),
            ">= 1 tag decoded on every frame": all(r["tags_dec"] >= 1 for r in rows),
            "series driver accepts every frame": all(s["ok"] for s in ser),
            "2-tag and 1-tag registration still >= 99% correct": all(r["tag_correct"] >= 0.99 for r in degraded),
        }
        for kk, v in gate.items():
            print(f"    [{'PASS' if v else 'FAIL'}] {kk}")
        ok = all(gate.values()); gate_all &= ok
        print(f"  PHASE-C GATE ({variant}): {'PASS' if ok else 'FAIL'}")
        results[variant] = dict(rows=rows, series=ser, refine=refine, degraded=degraded, gate=gate, pass_=ok,
                                params=asdict(params), tag_um=gcfg.tag_um, psf=gcfg.psf_fwhm_um,
                                pitch_um=gcfg.dot_pitch_um)

    # figure
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 3, figsize=(13, 3.9), dpi=110)
    for variant, res in results.items():
        rows = res["rows"]
        L = sorted({r["lam"] for r in rows})
        f = lambda key: [np.mean([r[key] for r in rows if r["lam"] == l]) for l in L]
        ax[0].plot(L, f("tag_correct"), "o-", label=f"{variant} correct")
        ax[0].plot(L, f("recovered"), "s:", label=f"{variant} recovered/in-frame")
        ax[1].plot(L, f("rms_px"), "o-", label=variant)
        ax[2].plot(L, f("affine_med_px"), "o-", label=f"{variant} tag affine")
        ax[2].plot(L, f("warp_resid"), "s:", label=f"{variant} warp median")
    ax[0].set_ylim(0, 1.02); ax[0].set_ylabel("fraction"); ax[0].set_title("tag correctness / recovery", fontsize=10)
    ax[0].axhline(0.99, c="k", ls="--", lw=0.7)
    ax[1].set_ylabel("RMS vs truth (px)"); ax[1].set_title("residual of correctly tagged dots", fontsize=10)
    ax[1].axhline(0.5, c="k", ls="--", lw=0.7)
    ax[2].set_ylabel("px"); ax[2].set_title("registration: tag affine vs truth; warp residual", fontsize=10)
    for x in ax:
        x.set_xlabel("λ"); x.grid(alpha=.3); x.legend(fontsize=7)
    fig.suptitle("Phase C — rwtag ArUco path vs synthetic truth", fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(os.path.join(DOCS, "phase_c_verify.png")); plt.close(fig)
    with open(os.path.join(DOCS, "phase_c_verify.json"), "w") as fh:
        json.dump(results, fh, indent=1, default=float)
    print(f"\nwrote docs/phase_c_verify.png + .json  ({(time.time() - t_start) / 60:.1f} min)")
    print(f"PHASE-C GATE: {'PASS' if gate_all else 'FAIL'}")
    raise SystemExit(0 if gate_all else 1)


if __name__ == "__main__":
    main()
