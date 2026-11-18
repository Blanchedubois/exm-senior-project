#!/usr/bin/env python3
"""
fiducial_stiffening.py — Phase 0d of the V2 implementation plan.

QUESTION (plan risk R6)
    The printed fiducials are rigid resin islands sitting in a gel that swells
    around them. Do they locally HOLD THE GEL BACK, biasing the very deformation
    field we are trying to measure?

    It matters for V2 because a 4x4 ArUco tag is ~20 um across -- comparable to
    the 12 x 18 um glyphs already printed -- so whatever the current glyphs do,
    the new tags will do too. If the effect is real and large, the tag tier has
    to get smaller, sparser, or mechanically decoupled.

THE TEST — a stacked residual field around every fiducial
    For each expanded frame:
      1. Pair dots to the initial frame by tag (exact correspondence, no matching
         heuristics -- this is what the tag map buys).
      2. Fit the best global similarity init -> expanded (uniform expansion +
         rotation + translation) and keep the per-dot residual as a VECTOR.
         `pairing.similarity_residuals` returns only scalar distances, so the fit
         is redone here to retain direction.
      3. Rotate residuals into DESIGN coordinates and scale to um, so all frames
         and all fiducials can be stacked in one common frame.
      4. For each dot, find the nearest fiducial IN DESIGN SPACE (exact, from the
         CAD tag map -- no fiducial detection needed, so no detection bias) and
         project its residual onto the outward radial direction from that
         fiducial.

    SIGN CONVENTION
        radial residual < 0  ->  the dot sits CLOSER to the fiducial than uniform
                                 expansion predicts: it lagged behind, which is
                                 what local stiffening looks like.
        radial residual > 0  ->  pushed away.
        no effect            ->  flat, zero at all distances.

CONTROLS
    * PHANTOM fiducials: the identical analysis about random positions that hold
      no printed feature. Any apparent trend there is method artifact, and sets
      the noise floor the real signal must clear.
    * Dashes: also rigid, but much smaller. If stiffening is real, dashes should
      show a weaker version of the same signature.

KNOWN LIMIT
    Stage-3 drops dots that sit ON a glyph (`dotfilter` "on_glyph"), so the
    innermost ring around each fiducial is empty by construction. This test is
    blind inside ~1 glyph radius and can only measure the surrounding field.

Run:  python fiducial_stiffening.py [--frames 2.0,2.5,3.0,3.5,4.2] [--bin 4]
"""
from __future__ import annotations
import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RWT = os.path.normpath(os.path.join(HERE, "..", "..", "reference-warp-tagger"))
sys.path.insert(0, RWT)

from rwtag import project as P, pairing as PA                      # noqa: E402
from rwtag.glyph import detect as D                                # noqa: E402
from rwtag.refwarp import reftags                                  # noqa: E402

MODEL = os.path.join(RWT, "reference", "glyph_knn.yml")
CACHE = os.path.join(HERE, "..", "docs", "phase0", ".tagcache.npz")


# ------------------------------------------------------------------ geometry
def similarity_vec(P0, P1):
    """Umeyama similarity P1 ~ s.R.P0 + t. Returns (s, R, residual VECTORS)."""
    c0, c1 = P0.mean(0), P1.mean(0)
    A, B = P0 - c0, P1 - c1
    R = PA.kabsch_rotation(A, B)
    RA = A @ R.T
    s = float((RA * B).sum() / max((RA * RA).sum(), 1e-12))
    return s, R, B - s * RA


def design_to_image_frame(Dxy, P0):
    """Design coords are y-UP, image coords are y-DOWN, so design -> image is a
    REFLECTION. Kabsch returns a pure rotation (det = +1) and cannot represent
    that, which silently wrecks the fit (residual 638 px vs 11 px on real data).
    Try both handednesses and keep the one that actually fits."""
    best = None
    for flip in (+1, -1):
        Dv = Dxy * np.array([1.0, flip])
        s0, R0, r0 = similarity_vec(Dv, P0)
        rms = float(np.sqrt((r0 ** 2).sum(1).mean()))
        if best is None or rms < best[0]:
            best = (rms, flip, s0, R0)
    rms, flip, s0, R0 = best
    return flip, s0, R0, rms


def design_lookup(records):
    """tag -> design (x_um, y_um), plus fiducial and dash position arrays."""
    pos = {r["tag"]: (r["x_um"], r["y_um"]) for r in records}
    fid = np.array([[r["x_um"], r["y_um"]] for r in records
                    if r["category"] in ("number", "letter")], float)
    dash = np.array([[r["x_um"], r["y_um"]] for r in records
                     if r["category"] == "dash"], float)
    return pos, fid, dash


def radial_profile(Dxy, res_um, centres, edges):
    """Project each dot's residual onto the outward direction from its nearest
    centre; bin by distance. Returns per-bin (n, mean, sem) of radial residual."""
    from scipy.spatial import cKDTree
    d, idx = cKDTree(centres).query(Dxy)
    v = Dxy - centres[idx]
    n = np.hypot(v[:, 0], v[:, 1])
    ok = n > 1e-6
    u = np.zeros_like(v)
    u[ok] = v[ok] / n[ok, None]
    radial = (res_um * u).sum(1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = ok & (d >= lo) & (d < hi)
        k = int(m.sum())
        if k < 20:
            out.append((lo, hi, k, np.nan, np.nan)); continue
        vals = radial[m]
        out.append((lo, hi, k, float(vals.mean()),
                    float(vals.std(ddof=1) / np.sqrt(k))))
    return out, radial, d


# ------------------------------------------------------------------ pipeline
def collect(frames, use_cache=True):
    """{label: {tag: (x_px, y_px)}} for the initial + requested expanded frames."""
    if use_cache and os.path.exists(CACHE):
        z = np.load(CACHE, allow_pickle=True)
        got = z["data"].item()
        if set(frames) <= set(got):
            print(f"  (tagging restored from {os.path.basename(CACHE)})")
            return got
    clf = D.load_classifier(MODEL)
    proj = P.Project.load(os.path.join(RWT, "Stitched Images", "project.rwproj.json"))
    out, accepted = {}, []
    for e in sorted(proj.images, key=lambda z: z.label):
        ok, msg = P.run_stages_validated(e, accepted, clf)
        print(f"    {e.label:>4}x  {'ok ' if ok else 'FAIL'} {msg}")
        if ok:
            accepted.append(e)
            out[e.label] = dict(e.pipeline.tagging.tags)
        e.unload_images()
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    np.savez_compressed(CACHE, data=np.array(out, dtype=object))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default="2.0,2.5,3.0,3.5,4.2")
    ap.add_argument("--bin", type=float, default=4.0, help="radial bin width, um")
    ap.add_argument("--maxd", type=float, default=48.0)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--out", default=os.path.join(HERE, "..", "docs", "phase0"))
    a = ap.parse_args()
    out_dir = os.path.normpath(a.out)

    recs = reftags.load()["records"]
    pos, fid, dash = design_lookup(recs)
    print(f"design: {len(fid)} fiducial glyphs, {len(dash)} dashes, {len(pos)} tags")

    print("\ntagging frames:")
    tagged = collect([float(x) for x in a.frames.split(",")], use_cache=not a.no_cache)
    init_label = min(tagged)
    init = tagged[init_label]
    print(f"\ninitial frame = {init_label:g}x  ({len(init)} tags)")

    edges = np.arange(0, a.maxd + a.bin, a.bin)
    rng = np.random.default_rng(0)
    lo_x, hi_x = fid[:, 0].min(), fid[:, 0].max()
    lo_y, hi_y = fid[:, 1].min(), fid[:, 1].max()
    # CONTROL 1: uniformly random positions.
    phantom = np.column_stack([rng.uniform(lo_x, hi_x, len(fid)),
                               rng.uniform(lo_y, hi_y, len(fid))])
    # CONTROL 2 (stronger): the REAL fiducial lattice, shifted half a box. Random
    # points do not reproduce the lattice structure of the true fiducials, so they
    # cannot reveal aliasing between that lattice and the smooth warp field. This
    # one has identical geometry and only the wrong phase.
    half = 0.5 * float(reftags.load()["box_um"])
    shifted = fid + np.array([half, half])
    shifted[:, 0] = lo_x + np.mod(shifted[:, 0] - lo_x, max(hi_x - lo_x, 1e-9))
    shifted[:, 1] = lo_y + np.mod(shifted[:, 1] - lo_y, max(hi_y - lo_y, 1e-9))

    stacks = {"fiducial": [], "dash": [], "phantom": [], "shifted-lattice": []}
    per_frame = []
    for label in sorted(tagged):
        if label == init_label:
            continue
        pairs = PA.pair_tags(init, tagged[label])
        P0, P1, tags = PA.pairs_xy(pairs, kinds=("dot",))
        if len(P0) < 50:
            print(f"  {label:g}x: only {len(P0)} paired dots — skipped")
            continue
        Dxy = np.array([pos[t] for t in tags], float)      # design um
        flip, s0, R0, fit_rms = design_to_image_frame(Dxy, P0)
        Dfit = Dxy * np.array([1.0, flip])                 # design in image handedness

        s, R, res = similarity_vec(P0, P1)                 # initial -> expanded px
        # Bring residuals back to the design frame and convert px -> um. The
        # residual lives in the EXPANDED image, so the scale to divide by is the
        # full design -> expanded chain, s0 * s (not s0 alone).
        res_um = ((res @ R) @ R0) / max(s0 * s, 1e-12)
        res_um = res_um * np.array([1.0, flip])            # undo the reflection

        row = {"label": label, "n": len(P0), "sim_scale": s,
               "design_fit_rms_px": fit_rms, "px_per_um": s0,
               "rms_um": float(np.sqrt((res_um ** 2).sum(1).mean()))}
        per_frame.append(row)
        print(f"  {label:g}x: {len(P0):>5} paired dots · similarity scale {s:.4f} · "
              f"design fit {fit_rms:5.2f} px · residual RMS {row['rms_um']:.3f} um")

        for name, centres in (("fiducial", fid), ("dash", dash),
                              ("phantom", phantom), ("shifted-lattice", shifted)):
            prof, radial, d = radial_profile(Dfit, res_um,
                                             centres * np.array([1.0, flip]), edges)
            stacks[name].append((prof, radial, d))

    if not per_frame:
        raise SystemExit("no frame yielded enough paired dots")

    # ---- pooled profile across all frames -----------------------------------
    print(f"\n{'='*78}\nSTACKED RADIAL RESIDUAL  (negative = dot lags TOWARD the "
          f"feature = stiffening)\n{'='*78}")
    results = {}
    for name in ("fiducial", "dash", "phantom", "shifted-lattice"):
        allr = np.concatenate([r for _p, r, _d in stacks[name]])
        alld = np.concatenate([d for _p, _r, d in stacks[name]])
        print(f"\n  --- {name.upper()} ---")
        print(f"{'dist um':>12}{'n dots':>9}{'mean radial um':>17}{'+- sem':>10}"
              f"{'  significance':>15}")
        rows = []
        for lo, hi in zip(edges[:-1], edges[1:]):
            m = (alld >= lo) & (alld < hi)
            k = int(m.sum())
            if k < 20:
                continue
            mu = float(allr[m].mean()); sem = float(allr[m].std(ddof=1) / np.sqrt(k))
            z = mu / sem if sem > 0 else 0.0
            flag = "***" if abs(z) > 3 else ("*" if abs(z) > 2 else "")
            print(f"{lo:>6.0f}-{hi:<5.0f}{k:>9}{mu:>17.4f}{sem:>10.4f}"
                  f"{z:>12.1f}s {flag}")
            rows.append(dict(lo=lo, hi=hi, n=k, mean_um=mu, sem_um=sem, z=z))
        results[name] = rows

    # ---- verdict ------------------------------------------------------------
    def near(rows, cut=12.0):
        sel = [r for r in rows if r["hi"] <= cut]
        if not sel:
            return None
        n = sum(r["n"] for r in sel)
        mu = sum(r["mean_um"] * r["n"] for r in sel) / n
        sem = np.sqrt(sum((r["sem_um"] * r["n"]) ** 2 for r in sel)) / n
        return dict(n=n, mean_um=mu, sem_um=sem, z=mu / sem if sem else 0.0)

    print(f"\n{'='*78}\nVERDICT\n{'='*78}")
    f_near, p_near = near(results["fiducial"]), near(results["phantom"])
    l_near = near(results["shifted-lattice"])
    for nm, v in (("fiducial", f_near), ("phantom (random)", p_near),
                  ("shifted lattice", l_near)):
        if v:
            print(f"  {nm:<20} inner 12 um: {v['mean_um']:+.4f} +- {v['sem_um']:.4f} um "
                  f"({v['z']:+.1f} sigma, n={v['n']:,})")
    verdict = []
    if f_near and p_near:
        excess = f_near["mean_um"] - p_near["mean_um"]
        sem = np.hypot(f_near["sem_um"], p_near["sem_um"])
        z = excess / sem if sem else 0.0
        print(f"  fiducial MINUS control: {excess:+.4f} +- {sem:.4f} um ({z:+.1f} sigma)")
        if z < -3:
            verdict.append(f"STIFFENING DETECTED: dots within 12 um lag {abs(excess):.3f} um "
                           "toward the fiducial, beyond the control")
        elif z > 3:
            verdict.append("dots near fiducials are pushed AWAY beyond the control "
                           "— not stiffening; investigate")
        else:
            verdict.append("no stiffening signal above the control noise floor")
        worst = max((abs(v["z"]) for v in (p_near, l_near) if v), default=0.0)
        if worst > 2:
            verdict.append(f"CAUTION: a null control is itself {worst:.1f} sigma from zero. "
                           "Residuals are spatially CORRELATED (the warp is a smooth field), "
                           "so dots are not independent and these SEMs understate the true "
                           f"error by roughly {max(worst,1):.0f}x. Read the bound, not the p-value.")
    for v in verdict:
        print(f"  - {v}")

    res = dict(init_label=init_label, per_frame=per_frame, bin_um=a.bin,
               profiles=results, fiducial_inner=f_near, phantom_inner=p_near,
               shifted_lattice_inner=l_near,
               verdict=verdict)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "fiducial_stiffening.json"), "w") as f:
        json.dump(res, f, indent=1)
    print(f"\nwrote {out_dir}/fiducial_stiffening.json")


if __name__ == "__main__":
    main()
