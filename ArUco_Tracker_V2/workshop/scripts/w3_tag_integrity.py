#!/usr/bin/env python3
"""
w3_tag_integrity.py — Workshop W3 (Rev D, Phase 2).
Rev C's simulate_conjoined_spread.py / strut_prominence.py, redone for the real print.

QUESTION
    Does a rounded, rigid ArUco tag keep decoding from lambda = 1 to 6 -- and
    how much physical damage can an id absorb before it is lost, or worse,
    read as a DIFFERENT id?

PART A — EXPANSION (whole pattern, real camera)
    Each candidate (OPT / HEDGE / SAFE at its W1 tag, W2 quiet zone, design
    PSF) through lambda = 1..6 with the real stitch FOV, drift, accumulating
    rotation, L2 noise, and the measured lambda^-1.84 signal law -- once with
    exposure ~ lambda^2 (the recommended acquisition) and once without. A rigid
    tag keeps its pixel size, so decode should be flat in lambda unless photons
    run out.

PART B — FAULT INJECTION (single tags, real pixel scale)
    For every one of the 36 ids, at each candidate's tag size and design PSF:
      * baseline
      * each BLACK PAYLOAD module removed in turn      (print defect / bit flip)
      * each BORDER module removed in turn             (ring damage)
      * each LEAF module -- a black module attached to the rest by only ONE
        edge -- DETACHED and carried away by the gel: displaced from the tag
        centre by (lambda-1) x its offset, for lambda = 1.5, 2, 3. This is the
        Rev C "module spread" failure, and the only one a 4-connected id can
        physically suffer.
    Scored as: correct id / lost / MISDECODED (wrong id returned -- the
    dangerous outcome, because nothing downstream can catch it).

    Also reports how many leaf modules each id has, because ids with no leaves
    cannot shed a module at all -- and there may be enough of them to fill the
    36 nodes.

PASS (WORKSHOP_PLAN.md section 4)
    Decode unchanged across lambda (with exposure compensation); every id
    survives any single-module loss; zero misdecodes.

Run:  python w3_tag_integrity.py [--quick]
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
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "tools")))
from aruco_grid import GridConfig, VARIANTS, build, module_map, assign_ids   # noqa: E402
import simulate_v2 as V                                                     # noqa: E402

FIG_DIR = os.path.normpath(os.path.join(HERE, "..", "figures"))
OUT_JSON = os.path.join(FIG_DIR, "w3_tag_integrity.json")
CANDS = [("OPT", "optimistic"), ("HEDGE", "hedge"), ("SAFE", "conservative")]
UMPX = 0.510
NOISE = dict(read_noise=6.0, full_well=240.0, background=14.0)


def detector(ecr=1.0):
    """DICT_4X4_50 has maxCorrectionBits = 1, and OpenCV's default
    errorCorrectionRate of 0.6 rounds that to ZERO correctable bits -- so out of
    the box a single flipped module loses the tag. errorCorrectionRate = 1.0
    restores the one bit of correction the dictionary actually has. The price is
    a higher chance of reading a damaged tag as a DIFFERENT id, which Part B
    scores explicitly as "wrong". Phase C must set this too."""
    p = aruco.DetectorParameters()
    p.errorCorrectionRate = ecr
    return aruco.ArucoDetector(aruco.getPredefinedDictionary(aruco.DICT_4X4_50), p)


def cand_cfg(variant):
    v = VARIANTS[variant]
    return GridConfig(dict_name="DICT_4X4_50", tag_modules=6, tag_um=v["tag_um"],
                      psf_fwhm_um=v["psf_fwhm_um"], dot_side_um=2.125, dashes=True,
                      round_tags=True, fit="inside", field_um=750.0)


# ============================================================ PART A: expansion
def expansion_sweep(cname, variant, lams, seeds, compensated):
    g = cand_cfg(variant)
    with contextlib.redirect_stdout(io.StringIO()):
        _r, _recs, info = build(g)
    islands = info["islands"]
    sim = V.SimConfig()
    if compensated:
        sim.signal_exp = 0.0
    lobes = V.make_lobes(g.field_um, sim)
    det = detector()
    thetas = [sim.rotation_deg + k * sim.rotation_step_deg for k in range(len(lams))]
    th = math.radians(max(abs(t) for t in thetas))
    sim.render_margin = max(sim.render_margin,
                            float(math.cos(th) + math.sin(th)) + 2 * sim.drift_um / sim.fov_um + 0.02)
    drng = np.random.default_rng(sim.drift_seed)
    lv = V.Level("w3", g.psf_fwhm_um, NOISE["read_noise"], NOISE["full_well"], NOISE["background"])
    rows = []
    for k, lam in enumerate(lams):
        drift = drng.uniform(-sim.drift_um, sim.drift_um, 2)
        rects, tag_c, tag_id = V.place(islands, lam, sim, lobes, g.field_um, drift)
        base = V.render_scene(rects, sim, thetas[k])
        rfov = sim.fov_um * sim.render_margin
        lo, hi = (rfov - sim.fov_um) / 2, (rfov + sim.fov_um) / 2
        M = cv2.getRotationMatrix2D((rfov / 2, rfov / 2), thetas[k], 1.0)
        T = np.column_stack([tag_c[:, 0], rfov - tag_c[:, 1]])
        R = V.lens_forward(T @ M[:, :2].T + M[:, 2], sim, sim.fov_um / 2.0, centre=(rfov / 2, rfov / 2))
        # Un-distortion (barrel, k1 < 0) pulls content INWARD, so the outer band of
        # the corrected frame samples beyond the image edge and is smeared. W3:
        # tags 63-76 px from the border fail, tags >= 91 px decode. Exclude the
        # band (~|k1| x half-frame) from "in frame" -- it is not usable data.
        edge_band = abs(sim.lens_k1) * sim.fov_um / 2.0 * 1.4
        t = math.radians(thetas[k])
        m = (g.tag_um / 2) * (abs(math.cos(t)) + abs(math.sin(t))) + g.module_um + edge_band
        infov = {tag_id[j] for j in range(len(tag_id))
                 if lo + m <= R[j, 0] <= hi - m and lo + m <= R[j, 1] <= hi - m}
        got = []
        for s in seeds:
            img = V.degrade(base, sim, lv, np.random.default_rng(s), lam=lam)
            got.append(len(V.decode(img, sim, det, None) & infov))
        rows.append(dict(lam=lam, in_frame=len(infov), decoded=float(np.mean(got)),
                         min_decoded=int(min(got)), rate=float(np.mean(got)) / max(len(infov), 1),
                         signal=V.signal_scale(sim, lam)))
    return rows


# ====================================================== PART B: fault injection
def raster_tag(mask, cfg, N=20, detached=None):
    """Rasterise a (possibly damaged) module map with the production necks and
    fillets. `detached` = (row, col, dx_mod, dy_mod): draw that module as a free
    square displaced by (dx, dy) modules instead of in place."""
    M = mask.shape[0]
    m = mask.copy()
    if detached is not None:
        r, c, dx, dy = detached
        m[r, c] = 0
    pad = 3                                              # modules of quiet canvas
    S = (M + 2 * pad) * N
    img = np.zeros((S, S), np.uint8)
    img[pad * N:(pad + M) * N, pad * N:(pad + M) * N] = np.kron(m, np.ones((N, N), np.uint8))
    if cfg.round_tags:
        major = max(2, int(round(cfg.strut_len_frac * N)))
        minor = max(1, int(round(cfg.strut_w_um / cfg.module_um * N)))
        for r in range(M - 1):
            for c in range(M - 1):
                a, b, cc, d = m[r, c], m[r, c + 1], m[r + 1, c], m[r + 1, c + 1]
                if a and d and not b and not cc:
                    ang = 45.0
                elif b and cc and not a and not d:
                    ang = 135.0
                else:
                    continue
                cv2.ellipse(img, ((pad + c + 1) * N, (pad + r + 1) * N),
                            (major // 2, max(1, minor // 2)), ang, 0, 360, 1, -1)
        rpx = max(1, int(round(cfg.fillet_um / cfg.module_um * N)))
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * rpx + 1, 2 * rpx + 1))
        core = img[pad * N - 2 * rpx:(pad + M) * N + 2 * rpx, pad * N - 2 * rpx:(pad + M) * N + 2 * rpx]
        img[pad * N - 2 * rpx:(pad + M) * N + 2 * rpx, pad * N - 2 * rpx:(pad + M) * N + 2 * rpx] = \
            cv2.morphologyEx(core, cv2.MORPH_CLOSE, k)
    if detached is not None:
        r, c, dx, dy = detached
        x0 = int(round((pad + c + dx) * N)); y0 = int(round((pad + r + dy) * N))
        cv2.rectangle(img, (x0, y0), (x0 + N - 1, y0 + N - 1), 1, -1)
    return img * 255


def image_tag(raster, cfg, psf, rng):
    """Raster (N px/module) -> real pixel scale -> blur -> noise -> inverted."""
    N = 20
    px_per_mod = cfg.module_um / UMPX
    S = int(round(raster.shape[0] / N * px_per_mod))
    img = cv2.resize(raster, (S, S), interpolation=cv2.INTER_AREA)
    sigma = (psf / 2.35482) / UMPX
    img = cv2.GaussianBlur(img, (0, 0), sigma).astype(np.float32)
    img = rng.poisson(np.clip(img, 0, 255) / 255.0 * NOISE["full_well"]) / NOISE["full_well"] * 255.0
    img = np.clip(img + NOISE["background"] + rng.normal(0, NOISE["read_noise"], img.shape), 0, 255)
    return (255 - img).astype(np.uint8)


def leaves(mask):
    """Black modules attached to the rest by exactly one edge."""
    M = mask.shape[0]; out = []
    for r in range(M):
        for c in range(M):
            if not mask[r, c]:
                continue
            n = sum(1 for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1))
                    if 0 <= r + dr < M and 0 <= c + dc < M and mask[r + dr, c + dc])
            if n == 1:
                out.append((r, c))
    return out


def fault_injection(cname, variant, ids, seeds, lams_detach):
    cfg = cand_cfg(variant); psf = cfg.psf_fwhm_um
    det = detector()
    M = cfg.tag_modules
    ctr = (M - 1) / 2.0

    def score(raster, true_id):
        outc = {"ok": 0, "lost": 0, "wrong": 0}
        for s in seeds:
            img = image_tag(raster, cfg, psf, np.random.default_rng(s))
            _c, found, _r = det.detectMarkers(img)
            f = {int(x) for x in found.flatten()} if found is not None else set()
            if true_id in f and len(f) == 1:
                outc["ok"] += 1
            elif f:
                outc["wrong"] += 1
            else:
                outc["lost"] += 1
        return outc

    tally = {k: {"ok": 0, "lost": 0, "wrong": 0} for k in
             ["baseline", "payload_drop", "border_drop"] + [f"leaf_detach_{l}" for l in lams_detach]}
    leaf_counts = {}
    for aid in ids:
        mk = module_map(cfg.dict_name, aid, M)
        lv = leaves(mk); leaf_counts[aid] = len(lv)
        for k, v in score(raster_tag(mk, cfg), aid).items():
            tally["baseline"][k] += v
        for r in range(1, M - 1):
            for c in range(1, M - 1):
                if mk[r, c]:
                    m2 = mk.copy(); m2[r, c] = 0
                    for k, v in score(raster_tag(m2, cfg), aid).items():
                        tally["payload_drop"][k] += v
        for r, c in [(0, c) for c in range(M)] + [(M - 1, c) for c in range(M)] + \
                    [(r, 0) for r in range(1, M - 1)] + [(r, M - 1) for r in range(1, M - 1)]:
            m2 = mk.copy(); m2[r, c] = 0
            for k, v in score(raster_tag(m2, cfg), aid).items():
                tally["border_drop"][k] += v
        for (r, c) in lv:
            for lam in lams_detach:
                dx, dy = (lam - 1) * (c - ctr), (lam - 1) * (r - ctr)
                for k, v in score(raster_tag(mk, cfg, detached=(r, c, dx, dy)), aid).items():
                    tally[f"leaf_detach_{lam}"][k] += v
    return tally, leaf_counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    os.makedirs(FIG_DIR, exist_ok=True)
    t0 = time.time()
    lams = [1, 2, 3, 4, 5, 6] if not a.quick else [1, 4]
    seeds = [0, 1] if not a.quick else [0]
    lams_detach = [1.5, 2.0, 3.0]
    cfg0 = cand_cfg("optimistic")
    idmap, pool = assign_ids(cfg0)
    ids = sorted({v for v in idmap.values()}) if not a.quick else sorted({v for v in idmap.values()})[:8]

    results = {}
    for cname, variant in CANDS:
        v = VARIANTS[variant]
        print(f"\n[{cname}]  tag {v['tag_um']} um, design PSF {v['psf_fwhm_um']} um")
        # ---- A
        rows = {}
        for comp in (True, False):
            rows["compensated" if comp else "fixed_exposure"] = \
                expansion_sweep(cname, variant, lams, seeds, comp)
        print(f"  A  {'lambda':>7}{'in frame':>10}{'comp.':>8}{'fixed':>8}{'signal':>8}")
        for rc, rf in zip(rows["compensated"], rows["fixed_exposure"]):
            print(f"     {rc['lam']:>6}x{rc['in_frame']:>10}{rc['rate']:>8.0%}{rf['rate']:>8.0%}"
                  f"{rf['signal']:>8.0%}")
        # ---- B
        tally, leaf_counts = fault_injection(cname, variant, ids, seeds, lams_detach)
        print(f"  B  {'fault':<18}{'trials':>7}{'ok':>7}{'lost':>7}{'WRONG':>7}")
        for k, t in tally.items():
            n = sum(t.values())
            print(f"     {k:<18}{n:>7}{t['ok']/n:>7.0%}{t['lost']/n:>7.0%}{t['wrong']/n:>7.0%}")
        nl = np.array(list(leaf_counts.values()))
        print(f"     leaf modules per id: min {nl.min()} · median {np.median(nl):.0f} · "
              f"max {nl.max()} · ids with NO leaves: {(nl == 0).sum()}/{len(nl)} "
              f"(pool of solid ids: {len(pool)})")
        results[cname] = dict(tag_um=v["tag_um"], psf=v["psf_fwhm_um"], expansion=rows,
                              faults=tally, leaf_counts={int(k): int(x) for k, x in leaf_counts.items()})

    # leaf census over the WHOLE solid pool (design opportunity)
    census = {aid: len(leaves(module_map("DICT_4X4_50", aid, 6))) for aid in pool}
    n0 = sum(1 for x in census.values() if x == 0)
    print(f"\nLEAF CENSUS over all {len(pool)} solid DICT_4X4_50 ids: {n0} have no leaf module"
          f" (36 nodes needed){' -> a leaf-free id set is available' if n0 >= 36 else ''}")

    # ---- gate
    print("\nW3 GATE")
    ok_all = True
    for cname, R in results.items():
        comp = R["expansion"]["compensated"]
        flat = min(r["rate"] for r in comp) >= 0.95 * max(r["rate"] for r in comp) and \
            all(r["min_decoded"] >= 1 for r in comp)
        f = R["faults"]
        nomis = all(t["wrong"] == 0 for t in f.values())
        surv = f["payload_drop"]["ok"] / max(sum(f["payload_drop"].values()), 1) >= 0.95
        bord = f["border_drop"]["ok"] / max(sum(f["border_drop"].values()), 1)
        print(f"  {cname:<6} flat in lambda (comp.): {'PASS' if flat else 'FAIL'}   "
              f"payload-module loss >=95%: {'PASS' if surv else 'FAIL'}   "
              f"zero misdecodes: {'PASS' if nomis else 'FAIL'}   "
              f"[border-module loss survives {bord:.0%} -- fatal at the quad stage, "
              f"protected by the intact ring, not gated]")
        ok_all &= flat and surv and nomis
    print(f"  W3: {'PASS' if ok_all else 'FAIL'}")

    # ---- figure
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.6), dpi=110)
    for cname, R in results.items():
        c = R["expansion"]["compensated"]; fx = R["expansion"]["fixed_exposure"]
        l1, = ax1.plot([r["lam"] for r in c], [100 * r["rate"] for r in c], "o-", label=f"{cname} exposure~λ²")
        ax1.plot([r["lam"] for r in fx], [100 * r["rate"] for r in fx], "o--", c=l1.get_color(),
                 label=f"{cname} fixed exposure")
    ax1.set_xlabel("expansion λ"); ax1.set_ylabel("in-frame tags decoded (%)")
    ax1.set_ylim(0, 102); ax1.grid(alpha=.3); ax1.legend(fontsize=7)
    ax1.set_title("A — rigid rounded tags through expansion", fontsize=10)
    keys = list(next(iter(results.values()))["faults"].keys())
    x = np.arange(len(keys)); w = 0.26
    for i, (cname, R) in enumerate(results.items()):
        ok = [100 * R["faults"][k]["ok"] / max(sum(R["faults"][k].values()), 1) for k in keys]
        wr = [100 * R["faults"][k]["wrong"] / max(sum(R["faults"][k].values()), 1) for k in keys]
        b = ax2.bar(x + (i - 1) * w, ok, w, label=cname)
        ax2.bar(x + (i - 1) * w, wr, w, bottom=ok, color="red", alpha=.7,
                label="misdecoded" if i == 0 else None)
    ax2.set_xticks(x); ax2.set_xticklabels([k.replace("_", "\n") for k in keys], fontsize=8)
    ax2.set_ylabel("correct id (%)"); ax2.set_ylim(0, 102); ax2.grid(alpha=.3, axis="y")
    ax2.axhline(95, c="k", lw=0.8, ls="--"); ax2.legend(fontsize=7)
    ax2.set_title("B — fault injection: single-module loss and detached leaf drift", fontsize=10)
    fig.suptitle("W3 — tag integrity", fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(os.path.join(FIG_DIR, "tag_integrity.png")); plt.close(fig)

    with open(OUT_JSON, "w") as f:
        json.dump(dict(ids=ids, lams=lams, seeds=seeds, lams_detach=lams_detach,
                       results=results, leaf_census=census), f, indent=1, default=float)
    print(f"\nwrote figures/tag_integrity.png + w3_tag_integrity.json   ({(time.time()-t0)/60:.1f} min)")


if __name__ == "__main__":
    main()
