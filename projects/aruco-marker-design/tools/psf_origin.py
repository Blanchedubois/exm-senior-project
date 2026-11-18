#!/usr/bin/env python3
"""
psf_origin.py — Phase 0b of the V2 implementation plan.

QUESTION
    The measured system PSF is ~1.9-3.2 um FWHM (plan section 1.2). The plan
    currently treats that as a fixed property of the optics ("locked optics"),
    which caps achievable dot density. Is it actually NA/diffraction-limited, or
    is it defocus / field tilt / per-tile focus error in the MIST mosaic?

    It matters because the two have completely different costs. Diffraction is a
    hard wall needing a new objective. Focus error is free to fix, and plan
    section 3.1 re-opens at the optimistic end if that is what this is.

TWO MODES

  --field  (default; runs on the EXISTING stitched frames)
      A diffraction-limited system has a PSF that is UNIFORM across the field and
      ISOTROPIC. Defocus, field tilt, curvature and per-tile focus error all
      imprint spatial structure. So: fit an elliptical Gaussian to every detected
      dot, map the width across the field, and look for structure.

      The printed dot is a constant 2.125 um square everywhere, so it contributes
      a fixed term that CANCELS when comparing one part of the field to another --
      the spatial variation is pure PSF, independent of the disputed pixel size.

      Reported:
        * spatial spread of FWHM (best cell vs worst cell)
        * radial trend            -> field curvature / spherical aberration
        * anisotropy sx/sy        -> astigmatism
        * periodicity of the residual map -> per-tile focus error in the stitch
        * halo test: measured radial profile vs its best-fit Gaussian. Excess
          energy in the wings indicates scatter through the gel rather than a
          clean optical PSF.
        * IF the field were flattened to its best cell, the density that buys.

  --zstack PATH
      The direct test, for when a z-stack is acquired (see PROTOCOL below).
      Per-plane median dot FWHM; a clear minimum well below the stitched-frame
      value proves the single-plane blur is focus, not NA.

PROTOCOL for the z-stack (one field, no stitching needed)
    Same objective and settings as the expansion series. Pick a field with plenty
    of dots, ideally near a corner AND once near the centre (run this twice) so
    field curvature shows up. Step 0.5 um over +-10 um, >= 21 planes, save as a
    single multi-page TIFF. Nothing else changes.

Run:  python psf_origin.py [--frames 1.5,2.0] [--cells 12]
      python psf_origin.py --zstack path/to/stack.tif [--zstep 0.5]
"""
from __future__ import annotations
import argparse
import json
import os
import sys

import numpy as np
import cv2
from scipy.optimize import curve_fit

HERE = os.path.dirname(os.path.abspath(__file__))
RWT = os.path.normpath(os.path.join(HERE, "..", "..", "reference-warp-tagger"))
sys.path.insert(0, RWT)

from rwtag import io, project as P, correct as C                 # noqa: E402
from rwtag.types import CorrectionParams, LevelsParams           # noqa: E402
from rwtag.glyph import lattice as lt                            # noqa: E402

DOT_AREA, TOPHAT = (30, 220), 15
CAD_DOT_UM = 2.125
R = 9                      # fit window half-size, px
CALIBRATIONS = {"metadata": 0.510, "lattice": 0.381}


# --------------------------------------------------------------- elliptical fit
def _ellip(xy, a, x0, y0, sx, sy, th, b):
    x, y = xy
    ct, st = np.cos(th), np.sin(th)
    xr = (x - x0) * ct + (y - y0) * st
    yr = -(x - x0) * st + (y - y0) * ct
    return (a * np.exp(-(xr ** 2 / (2 * sx ** 2) + yr ** 2 / (2 * sy ** 2))) + b).ravel()


def fit_dots(u8, dots, max_n=4000, rng=None):
    """Elliptical-Gaussian fit per dot. Returns a record array of good fits."""
    rng = rng or np.random.default_rng(0)
    idx = rng.permutation(len(dots))[:max_n]
    xg, yg = np.meshgrid(np.arange(-R, R + 1), np.arange(-R, R + 1))
    out = []
    for i in idx:
        x, y = dots[i]
        xi, yi = int(round(x)), int(round(y))
        if xi - R < 0 or yi - R < 0 or xi + R + 1 > u8.shape[1] or yi + R + 1 > u8.shape[0]:
            continue
        pa = u8[yi - R:yi + R + 1, xi - R:xi + R + 1].astype(float)
        try:
            p, _ = curve_fit(_ellip, (xg, yg), pa.ravel(),
                             p0=[pa.max() - pa.min(), x - xi, y - yi, 2.5, 2.5, 0.0, pa.min()],
                             maxfev=6000)
        except Exception:
            continue
        a, _x0, _y0, sx, sy, _th, _b = p
        sx, sy = abs(sx), abs(sy)
        if not (0.5 < sx < 8 and 0.5 < sy < 8 and a > 5):
            continue
        out.append((x, y, sx, sy, a))
    arr = np.array(out, float)
    if len(arr) < 50:
        raise RuntimeError(f"only {len(arr)} usable fits")
    return arr


def cell_map(arr, shape, cells, min_n=6):
    """Median FWHM per grid cell. Returns (map, counts) with NaN where sparse."""
    H, W = shape
    fw = 2.3548 * np.sqrt(arr[:, 2] * arr[:, 3])
    gx = np.clip((arr[:, 0] / W * cells).astype(int), 0, cells - 1)
    gy = np.clip((arr[:, 1] / H * cells).astype(int), 0, cells - 1)
    m = np.full((cells, cells), np.nan)
    n = np.zeros((cells, cells), int)
    for j in range(cells):
        for i in range(cells):
            sel = fw[(gx == i) & (gy == j)]
            n[j, i] = len(sel)
            if len(sel) >= min_n:
                m[j, i] = np.median(sel)
    return m, n


def periodicity(m, min_lag=2):
    """Look for REPEATING (tile-like) structure in the cell map.

    A smooth field autocorrelates most strongly at lag 1 simply because adjacent
    cells resemble each other, so lag-1 is not evidence of tiling. Guard against
    that twice: subtract a smooth quadratic trend first (that is the focus/dome
    component, reported separately as the radial trend), then ignore all lags
    below `min_lag`."""
    v = m.copy()
    good = np.isfinite(v)
    if good.sum() < 25:
        return None
    c = v.shape[0]
    yy, xx = np.mgrid[0:c, 0:c] / (c - 1.0)
    A = np.stack([np.ones_like(xx), xx, yy, xx * xx, yy * yy, xx * yy], -1)
    coef, *_ = np.linalg.lstsq(A[good], v[good], rcond=None)
    resid = v - A @ coef                       # smooth trend removed
    resid[~good] = 0.0
    resid -= resid[good].mean()

    F = np.fft.fft2(resid)
    ac = np.real(np.fft.ifft2(F * np.conj(F)))
    ac /= max(ac.flat[0], 1e-12)

    best = None
    for ly in range(c):
        for lx in range(c):
            wy, wx = min(ly, c - ly), min(lx, c - lx)
            if max(wy, wx) < min_lag:          # skip zero lag and its neighbours
                continue
            s = float(ac[ly, lx])
            if best is None or s > best[2]:
                best = (wx, wy, s)
    if best is None:
        return None
    return dict(lag_cells=(int(best[0]), int(best[1])), strength=float(best[2]),
                min_lag=min_lag,
                detrended_amplitude_px=float(np.std(resid[good])))


def halo_test(u8, dots, rng):
    """Radial profile of the mean dot vs its best-fit Gaussian. Returns the
    fraction of total energy sitting beyond 1.5 x FWHM (wing excess)."""
    keep = dots[rng.permutation(len(dots))[:800]]
    Rh = 16
    acc, n = np.zeros((2 * Rh + 1, 2 * Rh + 1)), 0
    for x, y in keep:
        xi, yi = int(round(x)), int(round(y))
        if xi - Rh < 0 or yi - Rh < 0 or xi + Rh + 1 > u8.shape[1] or yi + Rh + 1 > u8.shape[0]:
            continue
        acc += u8[yi - Rh:yi + Rh + 1, xi - Rh:xi + Rh + 1].astype(float); n += 1
    prof = acc / max(n, 1)
    yy, xx = np.ogrid[-Rh:Rh + 1, -Rh:Rh + 1]
    rr = np.hypot(xx, yy)
    prof = prof - np.median(prof[rr >= Rh - 1])
    rad = np.array([prof[(rr >= k) & (rr < k + 1)].mean() for k in range(Rh)])
    rad = np.clip(rad, 0, None)
    # best-fit Gaussian to the inner half, extrapolated outward
    ks = np.arange(Rh)
    try:
        g, _ = curve_fit(lambda r, A, s: A * np.exp(-r ** 2 / (2 * s ** 2)),
                         ks[:Rh // 2], rad[:Rh // 2], p0=[rad[0], 3.0], maxfev=5000)
        model = g[0] * np.exp(-ks ** 2 / (2 * abs(g[1]) ** 2))
    except Exception:
        return None
    w = 2 * np.pi * np.maximum(ks, 0.5)               # annulus area weighting
    fwhm = 2.3548 * abs(g[1])
    far = ks > 1.5 * fwhm / 2
    tot = float((rad * w).sum())
    return dict(gauss_fwhm_px=float(fwhm),
                wing_excess=float(((rad - model)[far] * w[far]).sum() / max(tot, 1e-9)))


# --------------------------------------------------------------------- field
def load_frame(path):
    raw = io.load_tiff(path)
    corr, lv = CorrectionParams(), LevelsParams()
    side = io.sidecar_path(path)
    if os.path.exists(side):
        _, corr, lv, _ = io.load_session(side)
    return io.to_uint8(C.process(raw, corr, lv))


def analyse_field(label, path, cells, out_dir):
    rng = np.random.default_rng(0)
    u8 = load_frame(path)
    dots = lt.detect_dots(u8, tophat=TOPHAT, dot_area=DOT_AREA)
    arr = fit_dots(u8, dots, rng=rng)
    fw = 2.3548 * np.sqrt(arr[:, 2] * arr[:, 3])
    aniso = np.maximum(arr[:, 2], arr[:, 3]) / np.minimum(arr[:, 2], arr[:, 3])

    print(f"\n{'='*78}\nFRAME {label}x   {os.path.basename(path)}   {u8.shape[1]}x{u8.shape[0]} px")
    print(f"{'='*78}")
    print(f"  {len(dots):,} dots detected, {len(arr):,} usable elliptical fits")
    print(f"  imaged FWHM  median {np.median(fw):.2f} px   "
          f"p10 {np.percentile(fw,10):.2f}   p90 {np.percentile(fw,90):.2f}")
    print(f"  anisotropy   median {np.median(aniso):.3f}   p90 {np.percentile(aniso,90):.3f}")

    m, n = cell_map(arr, u8.shape, cells)
    good = np.isfinite(m)
    best, worst, med = np.nanmin(m), np.nanmax(m), np.nanmedian(m)
    spread = (worst - best) / med
    print(f"\n  FIELD MAP ({cells}x{cells} cells, {good.sum()} populated, "
          f"median {n[good].mean():.0f} dots/cell)")
    print(f"    best cell  {best:.2f} px     worst cell {worst:.2f} px")
    print(f"    spread     {spread*100:.1f}% of median  "
          f"({'STRUCTURED' if spread > 0.25 else 'fairly uniform'})")

    # radial trend
    H, W = u8.shape
    cy, cx = (np.arange(cells) + .5) / cells * H, (np.arange(cells) + .5) / cells * W
    GX, GY = np.meshgrid(cx, cy)
    rad = np.hypot(GX - W / 2, GY - H / 2)
    rr = np.corrcoef(rad[good], m[good])[0, 1]
    # SIGN MATTERS. r > 0 = blurrier toward the edges  -> classic field curvature
    # / spherical aberration (an OPTICS fault). r < 0 = blurrier in the MIDDLE,
    # which no ordinary objective does -> the sample is domed or tilted, or focus
    # was set on the periphery (a SAMPLE/FOCUS fault, and free to fix).
    if abs(rr) <= 0.4:
        radlab = "no clear radial trend"
    elif rr > 0:
        radlab = "blurrier at the EDGES -> field curvature / spherical (optics)"
    else:
        radlab = "blurrier in the CENTRE -> domed/tilted sample or focus set at the rim"
    print(f"    radial correlation r = {rr:+.3f}  ({radlab})")

    per = periodicity(m)
    if per:
        cw = W / cells
        lx, ly = per['lag_cells']
        print(f"    after removing the smooth trend: residual {per['detrended_amplitude_px']:.2f} px,"
              f" strongest repeat at lag >= {per['min_lag']} = {per['lag_cells']} cells"
              f" (~{max(lx,ly)*cw:.0f} px), strength {per['strength']:+.2f}")
        print(f"      -> {'tile-like structure' if per['strength'] > 0.45 else 'NO tiling signature'}")

    halo = halo_test(u8, dots, rng)
    if halo:
        print(f"\n  HALO  gaussian-core FWHM {halo['gauss_fwhm_px']:.2f} px, "
              f"wing excess beyond 1.5xFWHM = {halo['wing_excess']*100:+.1f}% of energy"
              f"  ({'scatter halo present' if halo['wing_excess'] > 0.10 else 'clean core'})")

    # what flattening the field would buy
    gain = (med / best) ** 2
    print(f"\n  IF the field were flattened to its best cell:")
    print(f"    FWHM {med:.2f} -> {best:.2f} px; dot pitch scales with FWHM, so "
          f"density gain = ({med:.2f}/{best:.2f})^2 = {gain:.2f}x")
    for nm, umpx in CALIBRATIONS.items():
        psf_now = np.sqrt(max((med * umpx) ** 2 - CAD_DOT_UM ** 2, 0))
        psf_best = np.sqrt(max((best * umpx) ** 2 - CAD_DOT_UM ** 2, 0))
        print(f"    [{nm:>10}] PSF {psf_now:.2f} -> {psf_best:.2f} um")

    # BONUS CONSTRAINT ON PHASE 0a.  The imaged spot can never be narrower than
    # the printed dot it contains, so the sharpest cell in the field puts a hard
    # FLOOR under the effective pixel size.
    floor = CAD_DOT_UM / best
    print(f"\n  CONSTRAINT ON 0a: sharpest cell is {best:.2f} px wide, and the imaged spot")
    print(f"    cannot be narrower than the {CAD_DOT_UM} um printed dot, so")
    print(f"    effective pixel size > {CAD_DOT_UM}/{best:.2f} = {floor:.3f} um/px")
    for nm, umpx in CALIBRATIONS.items():
        ok = umpx > floor
        print(f"      {nm:>10} {umpx:.3f} um/px  {'OK' if ok else 'VIOLATES THE FLOOR'}")

    verdict = []
    if spread > 0.25:
        verdict.append("spatially STRUCTURED blur -> not purely diffraction-limited")
    if abs(rr) > 0.4:
        verdict.append(f"radial trend ({rr:+.2f}) -> " + (
            "field curvature / spherical aberration (optics)" if rr > 0 else
            "domed or tilted sample / focus set at the rim (NOT an optics limit)"))
    if np.median(aniso) > 1.15:
        verdict.append("persistent anisotropy -> astigmatism")
    if per and per["strength"] > 0.45:
        verdict.append("repeating structure -> per-tile focus error in the stitch")
    if halo and halo["wing_excess"] > 0.10:
        verdict.append("wing excess -> scatter through the gel")
    if not verdict:
        verdict.append("uniform, isotropic, clean core -> consistent with NA/diffraction limit")
    print("\n  VERDICT")
    for v in verdict:
        print(f"    - {v}")

    res = dict(label=label, file=os.path.basename(path), n_dots=int(len(dots)),
               n_fits=int(len(arr)), fwhm_median_px=float(med),
               fwhm_best_cell_px=float(best), fwhm_worst_cell_px=float(worst),
               spread_frac=float(spread), radial_r=float(rr),
               aniso_median=float(np.median(aniso)), periodicity=per, halo=halo,
               flatten_density_gain=float(gain), verdict=verdict,
               pixel_size_floor_um_per_px=float(CAD_DOT_UM / best),
               cell_map=np.where(good, m, None).tolist())
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f"psf_origin_{label}x.json"), "w") as f:
        json.dump(res, f, indent=1)

    # a quick visual: the FWHM field map
    vis = np.where(good, m, med)
    vis = ((vis - best) / max(worst - best, 1e-9) * 255).astype(np.uint8)
    vis = cv2.applyColorMap(cv2.resize(vis, (480, 480), interpolation=cv2.INTER_NEAREST),
                            cv2.COLORMAP_VIRIDIS)
    cv2.imwrite(os.path.join(out_dir, f"psf_fieldmap_{label}x.png"), vis)
    return res


# -------------------------------------------------------------------- z-stack
def analyse_zstack(path, zstep, out_dir):
    import tifffile
    stack = tifffile.imread(path)
    if stack.ndim != 3:
        raise SystemExit(f"expected a 3-D z-stack, got shape {stack.shape}")
    print(f"\n{'='*78}\nZ-STACK  {os.path.basename(path)}  {stack.shape[0]} planes\n{'='*78}")
    print(f"{'plane':>6}{'z um':>8}{'dots':>7}{'median FWHM px':>17}")
    rows = []
    for k, pl in enumerate(stack):
        u8 = pl if pl.dtype == np.uint8 else io.to_uint8(pl.astype(np.float32))
        try:
            dots = lt.detect_dots(u8, tophat=TOPHAT, dot_area=DOT_AREA)
            arr = fit_dots(u8, dots, max_n=600)
            fw = float(np.median(2.3548 * np.sqrt(arr[:, 2] * arr[:, 3])))
        except Exception:
            dots, fw = [], float("nan")
        z = (k - (stack.shape[0] - 1) / 2) * zstep
        print(f"{k:>6}{z:>8.1f}{len(dots):>7}{fw:>17.2f}")
        rows.append(dict(plane=k, z_um=z, n_dots=len(dots), fwhm_px=fw))

    ok = [r for r in rows if np.isfinite(r["fwhm_px"])]
    if not ok:
        raise SystemExit("no plane yielded a usable fit")
    bestr = min(ok, key=lambda r: r["fwhm_px"])
    print(f"\n  best focus at z = {bestr['z_um']:+.1f} um, FWHM {bestr['fwhm_px']:.2f} px")
    print(f"  stitched-series reference FWHM was 7.5 px")
    if bestr["fwhm_px"] < 7.5 * 0.85:
        g = (7.5 / bestr["fwhm_px"]) ** 2
        print(f"  => the single-plane blur is FOCUS, not NA. Flattening focus is worth "
              f"~{g:.2f}x density. RE-OPEN plan section 3.1 at the optimistic end.")
    else:
        print("  => no sharper plane exists: the blur is NA/diffraction-limited. "
              "'Locked optics' in the plan stands.")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "psf_origin_zstack.json"), "w") as f:
        json.dump(dict(file=os.path.basename(path), zstep=zstep, rows=rows,
                       best=bestr), f, indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default="1.5,2.0")
    ap.add_argument("--cells", type=int, default=12)
    ap.add_argument("--zstack", default=None)
    ap.add_argument("--zstep", type=float, default=0.5)
    ap.add_argument("--out", default=os.path.join(HERE, "..", "docs", "phase0"))
    a = ap.parse_args()
    out = os.path.normpath(a.out)

    if a.zstack:
        return analyse_zstack(a.zstack, a.zstep, out)

    proj = P.Project.load(os.path.join(RWT, "Stitched Images", "project.rwproj.json"))
    want = {float(x) for x in a.frames.split(",")}
    res = [analyse_field(e.label, e.path, a.cells, out)
           for e in sorted(proj.images, key=lambda z: z.label) if e.label in want]

    print(f"\n{'='*78}\nSUMMARY — is the blur fixable?\n{'='*78}")
    print(f"{'frame':>7}{'median FWHM':>14}{'best cell':>12}{'spread':>9}"
          f"{'flatten gain':>14}")
    for r in res:
        print(f"{r['label']:>6}x{r['fwhm_median_px']:>13.2f}px{r['fwhm_best_cell_px']:>11.2f}"
              f"{r['spread_frac']*100:>8.0f}%{r['flatten_density_gain']:>13.2f}x")
    print(f"\nwrote {out}/psf_origin_*.json + psf_fieldmap_*.png")
    print("Direct confirmation still needs a z-stack: see PROTOCOL in this file's docstring,")
    print("then rerun with --zstack.")


if __name__ == "__main__":
    main()
