#!/usr/bin/env python3
"""
w7_dot_vs_cross.py — Workshop W7 (Rev D, Phase 3).

QUESTION
    Rev C recommended a checkerboard / corner-cross fine tier over dots, on the
    grounds that saddle points and crosses localise better than blobs under
    blur. Is that true at THIS microscope (0.51 um/px, PSF 1.9-3.2 um), and
    what does each feature cost in anchoring area and in density?

FEATURES (all 2 um tall, as printed)
    dot      2.125 um square (the V1-proven feature)          -> 2-D Gaussian fit
    cross-4  two 1.0 um bars, 4 um tip-to-tip                  -> intensity centroid
    cross-6  two 1.0 um bars, 6 um tip-to-tip                  -> intensity centroid
    saddle   2x2 checkerboard of 2.125 um squares (two printed,
             on one diagonal) -> cv2.cornerSubPix at the saddle
    Every feature is also localised with the production estimator (threshold +
    connected-component centroid) as a common baseline.

    NOTE on the saddle: its two printed squares touch only at a point. As
    rigid islands they are TWO islands, so the saddle is not a material point
    of one piece and would drift apart under expansion unless bridged by a neck
    (extra material, and a stress concentrator -- W3). It is included to test
    Rev C's localisation claim, not as a serious candidate.

METHOD
    Render each feature at 20 px/um, place at a random sub-pixel offset,
    area-downsample to 0.51 um/px, blur by the PSF, add L2 noise (Poisson on
    240 e- full well + 6 counts read noise + 14 background), localise, compare
    to truth. 300 trials per (feature, PSF). Anchoring area = footprint +
    sidewall (perimeter x 2 um) from the hi-res raster. Implied pitch = 1.75 x
    the imaged extent (W5 rule applied to the feature's own size), and
    field precision = RMS / sqrt(features per unit area), i.e. the localisation
    precision available to a fixed-size strain window.

PASS (WORKSHOP_PLAN.md section 4)
    Pick the feature with the best field precision among those whose anchoring
    area is at least the proven dot's (R8). Expected: dots win at this blur.

Run:  python w7_dot_vs_cross.py
"""
from __future__ import annotations
import json
import math
import os
import time

import numpy as np
import cv2
from scipy.optimize import curve_fit

HERE = os.path.dirname(os.path.abspath(__file__))
FIG_DIR = os.path.normpath(os.path.join(HERE, "..", "figures"))
OUT_JSON = os.path.join(FIG_DIR, "w7_dot_vs_cross.json")

UMPX, HI = 0.510, 20.0                 # camera um/px, hi-res render px/um
HEIGHT = 2.0
PSFS = [1.91, 2.5, 3.18]
NOISE = dict(read_noise=6.0, full_well=240.0, background=14.0)
TRIALS = 300
CANVAS_UM = 24.0                       # per-feature canvas


def raster(kind):
    """Hi-res binary footprint of one feature, centred; returns (img, extent_um)."""
    S = int(CANVAS_UM * HI); c = S // 2
    img = np.zeros((S, S), np.uint8)
    def rect(x0, y0, x1, y1):
        cv2.rectangle(img, (int(round(c + x0 * HI)), int(round(c - y1 * HI))),
                      (int(round(c + x1 * HI)) - 1, int(round(c - y0 * HI)) - 1), 1, -1)
    if kind == "dot":
        h = 2.125 / 2; rect(-h, -h, h, h); ext = 2.125
    elif kind.startswith("cross"):
        L = float(kind.split("-")[1]); w = 1.0
        rect(-L / 2, -w / 2, L / 2, w / 2); rect(-w / 2, -L / 2, w / 2, L / 2); ext = L
    elif kind == "saddle":
        s = 2.125; rect(0, 0, s, s); rect(-s, -s, 0, 0); ext = 2 * s
    return img, ext


def anchoring(img):
    area = img.sum() / HI ** 2
    cs, _ = cv2.findContours(img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    per = sum(cv2.arcLength(cnt, True) for cnt in cs) / HI
    return float(area), float(per), float(area + per * HEIGHT)


def image(hi, psf, dx_um, dy_um, rng):
    """Shift by (dx, dy) um, downsample to camera px, blur, noise, bright-on-dark uint8."""
    M = np.float32([[1, 0, dx_um * HI], [0, 1, -dy_um * HI]])
    sh = cv2.warpAffine(hi * 255, M, hi.shape[::-1], flags=cv2.INTER_LINEAR, borderValue=0)
    n = int(round(CANVAS_UM / UMPX))
    img = cv2.resize(sh, (n, n), interpolation=cv2.INTER_AREA).astype(np.float32)
    sigma = (psf / 2.35482) / UMPX
    img = cv2.GaussianBlur(img, (0, 0), sigma)
    img = rng.poisson(np.clip(img, 0, 255) / 255.0 * NOISE["full_well"]) / NOISE["full_well"] * 255.0
    img = img + NOISE["background"] + rng.normal(0, NOISE["read_noise"], img.shape)
    return np.clip(img, 0, 255).astype(np.float32), n / 2.0


# --------------------------------------------------------------- estimators
def est_centroid(img, guess):
    """Production-like: top-hat, Otsu, largest component near the guess, centroid."""
    u8 = img.astype(np.uint8)
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    th = cv2.morphologyEx(u8, cv2.MORPH_TOPHAT, se)
    _t, b = cv2.threshold(th, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    n, lab, st, cen = cv2.connectedComponentsWithStats(b, 8)
    if n < 2:
        return None
    d = np.hypot(cen[1:, 0] - guess[0], cen[1:, 1] - guess[1])
    k = int(np.argmin(d)) + 1
    m = lab == k
    yy, xx = np.nonzero(m); w = th[m].astype(float)
    return np.array([(xx * w).sum() / w.sum(), (yy * w).sum() / w.sum()])


def est_gauss(img, guess):
    R = 6; xi, yi = int(round(guess[0])), int(round(guess[1]))
    pa = img[yi - R:yi + R + 1, xi - R:xi + R + 1]
    xg, yg = np.meshgrid(np.arange(-R, R + 1), np.arange(-R, R + 1))
    f = lambda xy, a, x0, y0, s, b: (a * np.exp(-((xy[0] - x0) ** 2 + (xy[1] - y0) ** 2) / (2 * s * s)) + b).ravel()
    try:
        p, _ = curve_fit(f, (xg, yg), pa.ravel(), p0=[pa.max() - pa.min(), 0, 0, 2.0, pa.min()], maxfev=3000)
        return np.array([xi + p[1], yi + p[2]])
    except Exception:
        return None


def est_saddle(img, guess, win):
    inv = (255 - img).astype(np.uint8)           # dark squares on light, as a checkerboard
    pts = np.array([[[guess[0], guess[1]]]], np.float32)
    cv2.cornerSubPix(inv, pts, (win, win), (-1, -1),
                     (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.001))
    return pts[0, 0].astype(float)


def main():
    os.makedirs(FIG_DIR, exist_ok=True)
    t0 = time.time()
    rng = np.random.default_rng(0)
    kinds = ["dot", "cross-4", "cross-6", "saddle"]
    results = {}
    print(f"{'feature':<9}{'foot um2':>9}{'anchor um2':>11}{'extent':>8}" +
          "".join(f"{'PSF ' + str(p):>18}" for p in PSFS) + "   (natural | centroid RMS, um)")
    for kind in kinds:
        hi, ext = raster(kind)
        foot, per, anch = anchoring(hi)
        results[kind] = dict(footprint_um2=foot, anchoring_um2=anch, extent_um=ext, per_psf={})
        cells = []
        for psf in PSFS:
            en, ec = [], []
            for _ in range(TRIALS):
                dx, dy = rng.uniform(-0.5, 0.5, 2) * UMPX
                img, c = image(hi, psf, dx, dy, rng)
                truth = np.array([c + dx / UMPX - 0.5, c - dy / UMPX - 0.5])   # centroid convention
                guess = truth + rng.normal(0, 0.7, 2)
                if kind == "dot":
                    p = est_gauss(img, guess)
                elif kind == "saddle":
                    p = est_saddle(img, guess, win=max(3, int(round(2.125 / UMPX))))
                else:
                    p = est_centroid(img, guess)
                q = est_centroid(img, guess)
                if p is not None and np.all(np.isfinite(p)) and np.hypot(*(p - truth)) < 4:
                    en.append(np.hypot(*(p - truth)))
                if q is not None and np.hypot(*(q - truth)) < 4:
                    ec.append(np.hypot(*(q - truth)))
            rn = math.sqrt(np.mean(np.square(en))) * UMPX if en else float("nan")
            rc = math.sqrt(np.mean(np.square(ec))) * UMPX if ec else float("nan")
            imaged = math.hypot(ext, psf)
            pitch = 1.75 * imaged
            dens = (750.0 / pitch) ** 2
            fp = rn / math.sqrt(dens) * 1000          # nm per (feature/field)^0.5 -- relative only
            results[kind]["per_psf"][str(psf)] = dict(rms_natural_um=rn, rms_centroid_um=rc,
                                                      n_ok=len(en), imaged_um=imaged, pitch_um=pitch,
                                                      features=dens, field_precision=fp)
            cells.append(f"{rn:>7.3f} |{rc:>7.3f}")
        print(f"{kind:<9}{foot:>9.2f}{anch:>11.1f}{ext:>8.2f}" + "".join(f"{c:>18}" for c in cells))

    # ---- decision: best field precision among features with anchoring >= dot's
    print(f"\n{'PSF':>5}{'feature':>10}{'RMS um':>8}{'pitch um':>10}{'features':>10}{'field prec.':>13}{'anchor ok':>11}")
    ref = results["dot"]["anchoring_um2"]
    verdict = {}
    for psf in PSFS:
        best = None
        for kind in kinds:
            r = results[kind]["per_psf"][str(psf)]; ok = results[kind]["anchoring_um2"] >= ref - 1e-9
            print(f"{psf:>5.2f}{kind:>10}{r['rms_natural_um']:>8.3f}{r['pitch_um']:>10.2f}"
                  f"{r['features']:>10,.0f}{r['field_precision']:>13.2f}{('yes' if ok else 'NO'):>11}")
            if ok and np.isfinite(r["field_precision"]) and (best is None or r["field_precision"] < best[1]):
                best = (kind, r["field_precision"])
        verdict[str(psf)] = best[0] if best else None
        print(f"      -> best at PSF {psf}: {best[0] if best else 'none'}")
    print(f"\nW7: {'PASS — dots win at every PSF' if all(v == 'dot' for v in verdict.values()) else 'see table'}")

    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.4), dpi=110)
    for kind in kinds:
        ax1.plot(PSFS, [results[kind]["per_psf"][str(p)]["rms_natural_um"] for p in PSFS], "o-",
                 label=f"{kind} (anchor {results[kind]['anchoring_um2']:.0f} um²)")
        ax2.plot(PSFS, [results[kind]["per_psf"][str(p)]["field_precision"] for p in PSFS], "o-", label=kind)
    ax1.set_xlabel("PSF FWHM (um)"); ax1.set_ylabel("localisation RMS (um), natural estimator")
    ax1.grid(alpha=.3); ax1.legend(fontsize=8); ax1.set_title("per-feature precision", fontsize=10)
    ax2.set_xlabel("PSF FWHM (um)"); ax2.set_ylabel("RMS / sqrt(features per field)  [lower = better]")
    ax2.grid(alpha=.3); ax2.legend(fontsize=8); ax2.set_title("field precision (precision x density)", fontsize=10)
    fig.suptitle("W7 — dot vs cross vs saddle at 0.51 um/px", fontsize=10)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(os.path.join(FIG_DIR, "dot_vs_cross.png")); plt.close(fig)
    with open(OUT_JSON, "w") as f:
        json.dump(dict(psfs=PSFS, trials=TRIALS, results=results, verdict=verdict), f, indent=1, default=float)
    print(f"wrote figures/dot_vs_cross.png + w7_dot_vs_cross.json  ({(time.time()-t0)/60:.1f} min)")


if __name__ == "__main__":
    main()
