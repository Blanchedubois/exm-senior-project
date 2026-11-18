#!/usr/bin/env python3
"""
separation_threshold.py — Phase 0c of the V2 implementation plan.

QUESTION
    docs/IMPLEMENTATION_PLAN.md section 2.3 assumes a dot pitch of >= 2.0 x the
    imaged-spot FWHM. That multiplier was an engineering guess, and every density
    figure in the plan scales with it (at 1.5x, all of them improve by 1.78x).
    This measures it instead.

METHOD
    Empirical, against the REAL Stage-2 detector and REAL image statistics:

      1. Detect dots in a real corrected frame.
      2. Build a dot template by subpixel-aligning and averaging many ISOLATED
         real dots -- this carries the true PSF, the true amplitude and the true
         profile shape, with no Gaussian assumption.
      3. Harvest genuine empty-background tiles from the same frame.
      4. For each trial separation s, splice a synthetic test patch INTO the real
         frame: pairs of templates at random orientation, added over real
         background. Splicing (rather than testing a standalone patch) keeps the
         GLOBAL Otsu threshold and top-hat background authentic, since
         lattice.detect_dots thresholds over the whole image.
      5. Run lattice.detect_dots with the exact pipeline parameters and score
         each site: 2 detections (resolved), 1 (merged), or 0 (rejected).

    Dots are bright-on-dark fluorescence, so templates are added in intensity
    above the local background -- the physically correct superposition for two
    overlapping emitters.

WHY THE FAILURE MODE MATTERS
    detect_dots filters on area (30..220 px^2), aspect (<= 1.7) and extent
    (>= 0.55), and the measured 0/1/2 breakdown shows THREE regimes, not two:

      < ~1.4 x FWHM   the pair fuses into one near-round blob that PASSES the
                      filters -> a single detection, badly mis-placed (~2-3 px).
                      Over-dense dots therefore corrupt positions, they do not
                      merely cost yield.
      ~1.4-1.6 x      the blob is elongated enough to fail aspect/extent ->
                      BOTH dots rejected. Yield collapses, positions stay clean.
      >= ~1.6 x       two clean centroids, localisation RMS ~0.25 px.

    The first regime is the dangerous one: it produces confident wrong points
    rather than missing ones, which no downstream filter can recover.

Run:  python separation_threshold.py [--frames 1.5,4.2] [--out DIR]
"""
from __future__ import annotations
import argparse
import json
import os
import sys

import numpy as np
import cv2

# --- reach the reference-warp-tagger package (the pipeline under test) --------
HERE = os.path.dirname(os.path.abspath(__file__))
RWT = os.path.normpath(os.path.join(HERE, "..", "..", "reference-warp-tagger"))
sys.path.insert(0, RWT)

from rwtag import io, project as P                      # noqa: E402
from rwtag.glyph import lattice as lt                   # noqa: E402

# pipeline defaults, from rwtag.glyph.detect.detect_grid -- must not drift
DOT_AREA, TOPHAT = (30, 220), 15
CROP = 12                    # template half-size, px
IMAGED_FWHM_PX = 7.5         # measured; used only to report s in FWHM units


# ------------------------------------------------------------------ template
def subpixel_crop(img, x, y, r=CROP):
    """Crop (2r+1)^2 centred on the SUBPIXEL point (x, y)."""
    xi, yi = int(round(x)), int(round(y))
    if xi - r - 2 < 0 or yi - r - 2 < 0 or xi + r + 3 > img.shape[1] or yi + r + 3 > img.shape[0]:
        return None
    pad = img[yi - r - 2:yi + r + 3, xi - r - 2:xi + r + 3].astype(np.float32)
    M = np.float32([[1, 0, xi - x], [0, 1, yi - y]])     # shift centre onto the grid
    sh = cv2.warpAffine(pad, M, (pad.shape[1], pad.shape[0]),
                        flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
    return sh[2:-2, 2:-2]


def build_template(u8, dots, min_isolation, n=400, rng=None):
    """Average many ISOLATED real dots -> (template_above_background, background)."""
    rng = rng or np.random.default_rng(0)
    from scipy.spatial import cKDTree
    tree = cKDTree(dots)
    nn = tree.query(dots, k=2)[0][:, 1]
    iso = dots[nn >= min_isolation]
    if len(iso) < 20:
        raise RuntimeError(f"only {len(iso)} isolated dots (need >= 20) — "
                           f"lower min_isolation ({min_isolation:.1f} px)")
    keep = iso[rng.permutation(len(iso))[:n]]
    stack = [c for c in (subpixel_crop(u8, x, y) for x, y in keep) if c is not None]
    tpl = np.mean(stack, axis=0)
    # background = the ring at the crop edge, well outside the dot
    yy, xx = np.ogrid[:tpl.shape[0], :tpl.shape[1]]
    rr = np.hypot(xx - CROP, yy - CROP)
    bg = float(np.median(tpl[rr >= CROP - 1]))
    return np.clip(tpl - bg, 0, None), bg, len(stack)


def harvest_background(u8, features, n_tiles, tile, min_clear, rng):
    """Real background tiles containing no detected feature."""
    from scipy.spatial import cKDTree
    tree = cKDTree(features)
    H, W = u8.shape
    tiles, tries = [], 0
    while len(tiles) < n_tiles and tries < n_tiles * 400:
        tries += 1
        x = rng.integers(tile, W - 2 * tile); y = rng.integers(tile, H - 2 * tile)
        cy, cx = y + tile / 2, x + tile / 2
        if tree.query([cx, cy])[0] < min_clear:
            continue
        tiles.append(u8[y:y + tile, x:x + tile].astype(np.float32))
    if not tiles:
        raise RuntimeError("no clear background tiles found")
    return tiles


# ------------------------------------------------------------------ the trial
def run_separation(u8, tpl, tiles, sep_px, region, spacing, rng):
    """Splice a patch of synthetic pairs at `sep_px` into the frame; detect;
    return (n_sites, counts{0,1,2}, centroid_rms_px for resolved pairs).

    `sep_px is None` places a SINGLE dot per site instead of a pair -- the
    control that measures the detector's per-dot efficiency, which is the
    ceiling any pair-resolution rate can reach."""
    y0, x0, hh, ww = region
    single = sep_px is None
    patch = np.zeros((hh, ww), np.float32)
    t = tiles[0].shape[0]
    for yy in range(0, hh, t):                              # real background bed
        for xx in range(0, ww, t):
            tile = tiles[rng.integers(len(tiles))]
            h = min(t, hh - yy); w = min(t, ww - xx)
            patch[yy:yy + h, xx:xx + w] = tile[:h, :w]

    sites, m = [], CROP + 2
    for cy in range(m + spacing // 2, hh - m, spacing):
        for cx in range(m + spacing // 2, ww - m, spacing):
            ang = rng.uniform(0, np.pi)
            d = (np.array([0.0, 0.0]) if single
                 else np.array([np.cos(ang), np.sin(ang)]) * sep_px / 2.0)
            pair = []
            for sgn in ((0,) if single else (+1, -1)):
                px, py = cx + sgn * d[0], cy + sgn * d[1]
                ix, iy = int(round(px)), int(round(py))
                M = np.float32([[1, 0, px - ix], [0, 1, py - iy]])
                sub = cv2.warpAffine(tpl, M, (tpl.shape[1], tpl.shape[0]),
                                     flags=cv2.INTER_CUBIC, borderValue=0)
                a, b = iy - CROP, ix - CROP
                if a < 0 or b < 0 or a + sub.shape[0] > hh or b + sub.shape[1] > ww:
                    pair = None; break
                patch[a:a + sub.shape[0], b:b + sub.shape[1]] += sub   # additive
                pair.append((px, py))
            if pair:
                sites.append(((cx, cy), pair))

    test = u8.copy()
    test[y0:y0 + hh, x0:x0 + ww] = np.clip(patch, 0, 255).astype(np.uint8)
    found = lt.detect_dots(test, tophat=TOPHAT, dot_area=DOT_AREA)

    # keep only detections inside the spliced region, in patch coordinates
    if len(found):
        inside = ((found[:, 0] >= x0) & (found[:, 0] < x0 + ww) &
                  (found[:, 1] >= y0) & (found[:, 1] < y0 + hh))
        local = found[inside] - np.array([x0, y0])
    else:
        local = np.empty((0, 2))

    counts = {0: 0, 1: 0, 2: 0}
    errs = []
    want = 1 if single else 2
    radius = spacing / 2.0 - 4                 # < half the site spacing: never
    for (cx, cy), pair in sites:               # steals a neighbour's detection
        if len(local):
            d = np.hypot(local[:, 0] - cx, local[:, 1] - cy)
            near = local[d <= radius]
        else:
            near = np.empty((0, 2))
        k = min(len(near), want)
        counts[k] = counts.get(k, 0) + 1
        if len(near) == want:            # centroid accuracy, 1-to-1 assignment
            T = np.asarray(pair, float)
            if want == 1:
                errs.append(float(np.hypot(*(near[0] - T[0]))))
            else:                        # two points: take the better pairing
                a = (np.hypot(*(near[0] - T[0])), np.hypot(*(near[1] - T[1])))
                b = (np.hypot(*(near[0] - T[1])), np.hypot(*(near[1] - T[0])))
                errs.extend(a if sum(a) <= sum(b) else b)
    rms = float(np.sqrt(np.mean(np.square(errs)))) if errs else float("nan")
    # Localisation over UNAMBIGUOUS matches only (< 3 px). The plain RMS above is
    # contaminated by spurious background detections standing in for a missed dot;
    # this is the number to feed into a strain-noise budget.
    tight = [e for e in errs if e < 3.0]
    rms_t = float(np.sqrt(np.mean(np.square(tight)))) if tight else float("nan")
    return len(sites), counts, rms, rms_t


def analyse(label, path, glyph_manual, out_dir, rng_seed=0):
    rng = np.random.default_rng(rng_seed)
    raw = io.load_tiff(path)
    side = io.sidecar_path(path)
    from rwtag import correct as C
    from rwtag.types import CorrectionParams, LevelsParams
    corr, lv = CorrectionParams(), LevelsParams()
    if os.path.exists(side):
        _, corr, lv, _ = io.load_session(side)
    u8 = io.to_uint8(C.process(raw, corr, lv))

    dots = lt.detect_dots(u8, tophat=TOPHAT, dot_area=DOT_AREA)
    dashes = lt.detect_dashes(u8)
    feats = np.vstack([dots, dashes]) if len(dashes) else dots
    tpl, bg, n_used = build_template(u8, dots, min_isolation=3 * IMAGED_FWHM_PX, rng=rng)
    tiles = harvest_background(u8, feats, n_tiles=64, tile=48, min_clear=40, rng=rng)

    print(f"\n{'='*78}\nFRAME {label}x   {os.path.basename(path)}   {u8.shape[1]}x{u8.shape[0]} px")
    print(f"{'='*78}")
    print(f"  real dots detected {len(dots):,} | template from {n_used} isolated dots "
          f"| background {bg:.1f} | template peak +{tpl.max():.1f}")

    region = (200, 200, 960, 960)                            # y0, x0, h, w
    spacing = 48

    # CONTROL: isolated single dots. Pair resolution can never beat (this)^2,
    # so it is the ceiling every rate below is measured against.
    n1, c1, rms1, rms1t = run_separation(u8, tpl, tiles, None, region, spacing, rng)
    eff = c1[1] / max(n1, 1)
    ceiling = 100.0 * eff ** 2
    print(f"\n  CONTROL (single isolated dots): {c1[1]}/{n1} detected = {eff:.1%} "
          f"per-dot efficiency, localisation RMS {rms1t:.3f} px (clean matches)")
    print(f"  => pair-resolution ceiling = {eff:.1%}^2 = {ceiling:.1f}%")

    print(f"\n{'sep px':>7}{'x FWHM':>8}{'sites':>7}{'both':>7}{'one':>6}"
          f"{'none':>6}{'  both %':>10}{'  vs ceiling':>13}{'  loc RMS px':>14}")
    rows = []
    for sep in range(4, 25):
        n, c, rms, rmst = run_separation(u8, tpl, tiles, sep, region, spacing, rng)
        pct = 100.0 * c[2] / max(n, 1)
        rel = 100.0 * pct / ceiling if ceiling else float("nan")
        print(f"{sep:>7}{sep/IMAGED_FWHM_PX:>8.2f}{n:>7}{c[2]:>7}{c[1]:>6}{c[0]:>6}"
              f"{pct:>9.1f}%{rel:>12.1f}%{rmst:>14.3f}")
        rows.append(dict(sep_px=sep, sep_fwhm=sep / IMAGED_FWHM_PX, sites=n,
                         both=c[2], one=c[1], none=c[0], both_pct=pct,
                         pct_of_ceiling=rel, centroid_rms_px=rms,
                         loc_rms_clean_px=rmst))

    def crossing(frac):
        """Smallest separation from which `both%` stays >= frac of the ceiling
        for every larger separation tested (so a single lucky row cannot win)."""
        ordered = sorted(rows, key=lambda z: z["sep_px"])
        best = None
        for i, r in enumerate(ordered):
            if all(q["pct_of_ceiling"] >= frac * 100 for q in ordered[i:]):
                best = r["sep_px"]
                break
        return best

    res = {"label": label, "file": os.path.basename(path), "n_dots": int(len(dots)),
           "template_dots": n_used, "imaged_fwhm_px": IMAGED_FWHM_PX,
           "background": bg, "per_dot_efficiency": eff,
           "single_dot_localisation_rms_px": rms1t, "ceiling_pct": ceiling,
           "rows": rows,
           "thresholds": {f"f{int(f*100)}": crossing(f) for f in (0.5, 0.9, 0.95, 0.99)}}
    print("\n  separation at which pair resolution reaches a fraction of the ceiling:")
    for f in (0.5, 0.9, 0.95, 0.99):
        s = res["thresholds"][f"f{int(f*100)}"]
        print(f"    {int(f*100):>3}% of ceiling: "
              + (f"{s} px = {s/IMAGED_FWHM_PX:.2f} x FWHM" if s else "not reached in sweep"))
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f"sep_threshold_{label}x.json"), "w") as f:
        json.dump(res, f, indent=1)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default="1.5,4.2",
                    help="comma-separated expansion labels to test")
    ap.add_argument("--out", default=os.path.join(HERE, "..", "docs", "phase0"))
    a = ap.parse_args()

    proj = P.Project.load(os.path.join(RWT, "Stitched Images", "project.rwproj.json"))
    want = {float(x) for x in a.frames.split(",")}
    out = os.path.normpath(a.out)
    results = [analyse(e.label, e.path, e.glyph_manual, out)
               for e in sorted(proj.images, key=lambda z: z.label) if e.label in want]

    print(f"\n{'='*78}\nSUMMARY — replaces the assumed 2.0x rule in plan section 2.3\n{'='*78}")
    print(f"{'frame':>7}{'per-dot eff':>13}{'90% ceiling':>14}{'95% ceiling':>14}"
          f"{'99% ceiling':>14}")
    for r in results:
        def fmt(k):
            s = r["thresholds"][k]
            return f"{s/IMAGED_FWHM_PX:.2f} x FWHM" if s else "not reached"
        print(f"{r['label']:>6}x{r['per_dot_efficiency']:>12.1%}"
              f"{fmt('f90'):>14}{fmt('f95'):>14}{fmt('f99'):>14}")
    print(f"\nwrote {out}/sep_threshold_*.json")


if __name__ == "__main__":
    main()
