#!/usr/bin/env python3
"""
analyse_spectrum.py — read ONE image of the spectrum print and say, box by box,
what the microscope recognised.

    python analyse_spectrum.py IMAGE [--um-per-px 0.51] [--out DIR]

IMAGE is a stitched frame of the spectrum print at any expansion (.tif / .png). If
a Stage-1 sidecar (<image>.rwsession.json, written by the Reference-Warp Tagger) sits
beside it, its vignette / lens / rotation correction is applied first.

PER BOX (25 rows in <image>_spectrum.csv, heat-maps in <image>_spectrum.png)
    in_view       dots of that box inside the usable field
    recognised    dots found AND identified / in_view
    merged        dots estimated to sit inside blobs too large or too long to be one
                  dot -- the signature of a spacing too tight for the blur
    contrast      median (dot peak - darkest tenth of the box), image grey levels
    scatter_px    RMS of recognised dots about their box's fitted lattice
    blur_um       PSF FWHM, from Gaussian fits to the dots, printed size removed. The
                  frame's blur is taken from the REFERENCE-size boxes only: a small dot
                  is the nearest thing to a point; the estimate reads high for the
                  larger dots (up to +40 % at 4 um), whose flat top is not Gaussian.
    fully_in_view at least 90 % of the box's dots are inside the usable field. Boxes
                  cut by the edge of the field are reported but NOT judged: the field
                  edge loses dots for reasons that have nothing to do with spacing.
                  Image the print at the lowest expansion that shows all of it.
AND ONE LINE
    the tightest spacing that is >= 95 % recognised at the reference dot size, with
    every wider spacing also recognised -> which of the three designs to print.

HOW
    1. decode the ArUco tags (plain inversion, no CLAHE, error correction on)
    2. design -> image affine through the tag CENTRES (tags are rigid: their corners
       do not follow the expansion); handedness must be -1 (design y-up, image y-down)
    3. detect dots once per printed dot size (the top-hat and the area window follow
       the size), threshold floored at the noise level
    4. per box: start from the box's own four corner tags when all four decoded, refine
       an affine against the detections, match one-to-one within 0.45 of the spacing
"""
from __future__ import annotations
import argparse
import csv
import json
import math
import os
import sys

import numpy as np
import cv2
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "..", "Reference_Warp_Tagger")))
from rwtag.aruco import ArucoParams, Design, decode_tags, fit_affine          # noqa: E402
from rwtag.aruco.detect import refine_gauss                                   # noqa: E402

DESIGNS = [(5.0, "OPTIMISTIC"), (6.0, "MEDIUM"), (7.0, "CONSERVATIVE")]
PASS = 0.95
MIN_IN_VIEW = 30


# ------------------------------------------------------------------ detection
def blobs(u8, tophat, noise_k=5.0):
    """All bright components after top-hat + noise-floored Otsu: (centroid, area, w, h)."""
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (tophat | 1, tophat | 1))
    th = cv2.morphologyEx(u8, cv2.MORPH_TOPHAT, se)
    otsu, _ = cv2.threshold(th, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    med = float(np.median(th)); mad = float(np.median(np.abs(th.astype(np.int16) - med))) * 1.4826
    b = (th > max(float(otsu), med + noise_k * mad)).astype(np.uint8)
    n, _l, st, cen = cv2.connectedComponentsWithStats(b, 8)
    return cen[1:], st[1:, cv2.CC_STAT_AREA], st[1:, cv2.CC_STAT_WIDTH], st[1:, cv2.CC_STAT_HEIGHT]


def affine_lstsq(X, Y):
    M = np.column_stack([X, np.ones(len(X))])
    sol, *_ = np.linalg.lstsq(M, Y, rcond=None)
    return np.column_stack([sol[:2].T, sol[2]])                 # 2x3


def apply(A, X):
    return X @ A[:, :2].T + A[:, 2]


def fit_sigma(u8, pts, R):
    """Median Gaussian sigma (px) of up to 40 dots, window radius R."""
    from scipy.optimize import curve_fit
    xg, yg = np.meshgrid(np.arange(-R, R + 1), np.arange(-R, R + 1))
    f = lambda xy, a, x0, y0, s, b: (a * np.exp(-((xy[0] - x0) ** 2 + (xy[1] - y0) ** 2) / (2 * s * s)) + b).ravel()
    out = []
    sel = pts if len(pts) <= 40 else pts[np.linspace(0, len(pts) - 1, 40).astype(int)]
    for x, y in sel:
        xi, yi = int(round(x)), int(round(y))
        if xi - R < 0 or yi - R < 0 or xi + R + 1 > u8.shape[1] or yi + R + 1 > u8.shape[0]:
            continue
        pa = u8[yi - R:yi + R + 1, xi - R:xi + R + 1].astype(float)
        try:
            p, _ = curve_fit(f, (xg, yg), pa.ravel(), p0=[pa.max() - pa.min(), x - xi, y - yi, 2.5, pa.min()], maxfev=1500)
            if 0.5 < abs(p[3]) < 3 * R and abs(p[1]) < 3 and abs(p[2]) < 3:
                out.append(abs(p[3]))
        except Exception:
            pass
    return float(np.median(out)) if len(out) >= 5 else float("nan")


# ------------------------------------------------------------------ analysis
def analyse(u8, spec, design: Design, um_per_px=None, psf_guess_um=2.5, edge_band_um=25.0):
    u8 = np.asarray(u8, np.uint8)
    H, W = u8.shape
    umpp = float(um_per_px or spec["optics_assumed"]["um_per_px"])
    band = edge_band_um / umpp
    prm = ArucoParams(um_per_px=umpp, psf_fwhm_um=psf_guess_um, edge_band_um=edge_band_um)
    tags, tinfo = decode_tags(u8, prm, spec["tags"]["dictionary"])
    cen0, a0, w0, h0 = blobs(u8, 15)
    ok0 = (a0 >= 12) & (a0 <= 400) & (np.maximum(w0, h0) / np.maximum(np.minimum(w0, h0), 1) <= 1.7)
    A, ainfo = fit_affine(design, tags, prm, dots=cen0[ok0])
    res = dict(um_per_px=umpp, image=[int(W), int(H)], tags_decoded=len(tags), tags_used=ainfo.get("n_matched", 0),
               registered=A is not None, registration=ainfo.get("method"), handedness=ainfo.get("sign"))
    if A is None:
        res.update(boxes=[], verdict="not registered: no ArUco tag decoded", recommended=None)
        return res
    scale = float(np.sqrt(abs(np.linalg.det(A[:, :2]))))
    res["expansion"] = scale * umpp
    res["handedness_ok"] = bool(np.sign(np.linalg.det(A[:, :2])) == -1)

    by_box = {}
    for r in design.records:
        if r["category"] == "dot":
            by_box.setdefault(int(r["meta"]["box"]), []).append(r)
    tag_xy = {int(r["meta"]["aruco_id"]): np.array([r["x_um"], r["y_um"]]) for r in design.tag_records()}

    def run(psf_um):
        cache, out, matched_all = {}, [], {}
        for b in sorted(spec["boxes"], key=lambda b: (-b["row"], b["col"])):
            d, p = float(b["dot"]), float(b["pitch"])
            recs = by_box[b["box"]]
            X = np.array([[r["x_um"], r["y_um"]] for r in recs], float)
            fw = math.hypot(d, psf_um) / umpp                       # imaged dot width, px (rigid: no lambda)
            if d not in cache:
                th = max(11, int(math.ceil(2.0 * fw)) | 1)
                cen, ar, ww, hh = blobs(u8, th)
                cap = max(220.0, 3.2 * fw * fw)
                single = (ar >= 12) & (ar <= cap) & (np.maximum(ww, hh) / np.maximum(np.minimum(ww, hh), 1) <= 1.7) \
                         & (ar / np.maximum(ww * hh, 1) >= 0.55)
                pts = refine_gauss(u8, cen[single].astype(float), fw / 2.35482) if single.any() else np.zeros((0, 2))
                cache[d] = (pts, cen[~single & (ar >= 12)], ar[~single & (ar >= 12)],
                            float(np.median(ar[single])) if single.any() else float("nan"))
            pts, big_c, big_a, a_med = cache[d]
            ids = b["corner_tag_ids"]
            Ab = A
            if all(i in tags for i in ids):
                Ab = affine_lstsq(np.array([tag_xy[i] for i in ids]), np.array([tags[i]["centre"] for i in ids]))
            P = apply(Ab, X)
            pitch_px = p * scale
            gate = 0.45 * pitch_px
            m = np.zeros(len(X), bool); j = np.zeros(len(X), int)
            if len(pts):
                tree = cKDTree(pts)
                for _ in range(3):
                    dist, j = tree.query(P)
                    m = dist < gate
                    if m.sum() < 12:
                        break
                    Ab = affine_lstsq(X[m], pts[j[m]]); P = apply(Ab, X)
                dist, j = tree.query(P)
                order = np.argsort(dist); used = set(); m = np.zeros(len(X), bool)
                for k in order:
                    if dist[k] < gate and int(j[k]) not in used:
                        used.add(int(j[k])); m[k] = True
            view = (P[:, 0] > band) & (P[:, 0] < W - 1 - band) & (P[:, 1] > band) & (P[:, 1] < H - 1 - band)
            n_view = int(view.sum())
            row = dict(box=b["box"], col=b["col"], row=b["row"], position=b["position"], label=b["label"],
                       dot_um=d, pitch_um=p, gap_um=float(b["gap"]), printed=len(X), in_view=n_view,
                       fully_in_view=bool(n_view >= 0.9 * len(X)),
                       corner_tags_decoded=int(sum(i in tags for i in ids)))
            if n_view < MIN_IN_VIEW:
                row.update(recognised=float("nan"), merged=float("nan"), contrast=float("nan"),
                           scatter_px=float("nan"), blur_um=float("nan"), note="not in view")
                out.append(row); continue
            mv = m & view
            row["recognised"] = float(mv.sum() / n_view)
            # merged: over-size / elongated blobs inside the box
            lo, hi = P[view].min(0) - pitch_px, P[view].max(0) + pitch_px
            # only blobs INSIDE the dot lattice: within half a spacing of its outer dots.
            # (Dashes and tag modules are long or large blobs too, but they sit further
            # out than that -- counting them read as 15-40 % "merged" in boxes that
            # were 100 % recognised.)
            mlo, mhi = P[view].min(0) - 0.5 * pitch_px, P[view].max(0) + 0.5 * pitch_px
            inb = (big_c[:, 0] > mlo[0]) & (big_c[:, 0] < mhi[0]) & (big_c[:, 1] > mlo[1]) & (big_c[:, 1] < mhi[1]) \
                if len(big_c) else np.zeros(0, bool)
            if inb.any():                          # and not on a tag: nearest predicted dot within one spacing
                dd, _ = cKDTree(P[view]).query(big_c[inb])
                keep = np.nonzero(inb)[0][dd < pitch_px]
                inb = np.zeros(len(big_c), bool); inb[keep] = True
            est = float(np.sum(np.maximum(2.0, np.round(big_a[inb] / a_med)))) if inb.any() and a_med == a_med else 0.0
            if inb.any() and a_med != a_med:
                est = float(n_view - mv.sum())
            row["merged"] = float(min(1.0, est / n_view))
            Q = pts[j[mv]]
            x0, y0, x1, y1 = [int(v) for v in (max(lo[0], 0), max(lo[1], 0), min(hi[0], W - 1), min(hi[1], H - 1))]
            roi = u8[y0:y1, x0:x1]
            floor = float(np.percentile(roi, 10)) if roi.size else float("nan")
            if len(Q):
                qi = np.clip(np.round(Q).astype(int), 1, [W - 2, H - 2])
                peak = np.array([u8[y - 1:y + 2, x - 1:x + 2].max() for x, y in qi], float)
                row["contrast"] = float(np.median(peak) - floor)
                row["scatter_px"] = float(np.sqrt(np.mean(np.sum((Q - P[mv]) ** 2, 1))))
                sg = fit_sigma(u8, Q, max(3, min(8, int(pitch_px / 2))))
                v = (sg * umpp) ** 2 - d * d / 12.0
                row["blur_um"] = float(2.35482 * math.sqrt(v)) if sg == sg and v > 0 else float("nan")
            else:
                row.update(contrast=float("nan"), scatter_px=float("nan"), blur_um=float("nan"))
            row["note"] = ""
            out.append(row)
            for k in np.nonzero(mv)[0]:
                matched_all[recs[k]["tag"]] = (float(pts[j[k]][0]), float(pts[j[k]][1]))
        return out, matched_all

    def frame_blur(rows):
        """Median over the smallest dot size that has usable boxes (see the docstring)."""
        for d in sorted({r["dot_um"] for r in rows}):
            v = [r["blur_um"] for r in rows if r["dot_um"] == d and r["blur_um"] == r["blur_um"]
                 and r["recognised"] == r["recognised"] and r["recognised"] >= 0.5]
            if v:
                return float(np.median(v)), d
        return float("nan"), None

    boxes, matched = run(psf_guess_um)
    res["blur_um"], res["blur_from_dot_um"] = frame_blur(boxes)
    if res["blur_um"] == res["blur_um"]:                        # second pass with the measured blur
        boxes, matched = run(res["blur_um"])
        b2, d2 = frame_blur(boxes)
        if b2 == b2:
            res["blur_um"], res["blur_from_dot_um"] = b2, d2
    res["boxes"] = boxes
    res["matched"] = matched
    res.update(recommend(boxes))
    return res


def recommend(boxes):
    """Tightest reference-size spacing that is recognised, with every wider one too."""
    ref = min(b["dot_um"] for b in boxes)
    top = sorted([b for b in boxes if b["dot_um"] == ref], key=lambda b: b["pitch_um"])
    seen = [b for b in top if b["recognised"] == b["recognised"] and b.get("fully_in_view", True)]
    if not seen:
        return dict(tightest_pitch_um=None, recommended=None,
                    verdict="no reference-size box is fully in view: image the top row of the print, "
                            "at an expansion low enough to show whole boxes")
    best = None
    for b in reversed(seen):                                    # from the widest inwards
        if b["recognised"] >= PASS:
            best = b
        else:
            break
    wider_unjudged = [b["pitch_um"] for b in top if b not in seen and b["pitch_um"] > seen[-1]["pitch_um"]]
    if best is None and wider_unjudged:
        return dict(tightest_pitch_um=None, recommended=None,
                    verdict=f"inconclusive: {seen[-1]['pitch_um']:g} um is {seen[-1]['recognised']:.0%} recognised, and the "
                            f"wider spacings that would decide ({wider_unjudged} um) are cut by the field edge. "
                            "Image the print at a lower expansion, with all of it in view")
    if best is None:
        return dict(tightest_pitch_um=None, recommended=None,
                    verdict=f"no judged spacing up to {seen[-1]['pitch_um']:g} um is {PASS:.0%} recognised at this blur: "
                            "print nothing yet, flatten the focus first")
    name = next((n for p, n in DESIGNS if p >= best["pitch_um"] - 1e-9), None)
    missing = [b["pitch_um"] for b in top if b not in seen]
    return dict(tightest_pitch_um=best["pitch_um"], recommended=name,
                verdict=f"tightest spacing recognised at the {ref:g} um dot: {best['pitch_um']:g} um "
                        f"({best['recognised']:.0%}) -> print {name}"
                        + (f"   [not judged, cut by the field edge: {missing} um]" if missing else ""))


# ------------------------------------------------------------------ output
def table(res):
    L = [f"registered: {res['registered']} ({res.get('registration')}, {res['tags_decoded']} tags) · "
         f"expansion {res.get('expansion', float('nan')):.3f} x · blur {res.get('blur_um', float('nan')):.2f} um · "
         f"handedness {res.get('handedness')}"]
    if not res["boxes"]:
        return "\n".join(L + [res["verdict"]])
    L.append("\n  recognised (%) — columns: gap left -> right; rows: dot size top -> bottom\n")
    cols = sorted({b["gap_um"] for b in res["boxes"]}); rows = sorted({b["dot_um"] for b in res["boxes"]})
    L.append("    dot \\ gap " + "".join(f"{g:>9.3f}" for g in cols))
    for d in rows:
        line = f"    {d:>9.3f} "
        for g in cols:
            b = next(x for x in res["boxes"] if x["dot_um"] == d and x["gap_um"] == g)
            r = b["recognised"]
            line += "     --  " if r != r else f"{100 * r:>8.0f}" + (" " if b.get("fully_in_view", True) else "*")
        L.append(line)
    if any(not b.get("fully_in_view", True) for b in res["boxes"]):
        L.append("    (* cut by the edge of the field: reported, not judged)")
    L.append("\n  " + res["verdict"])
    return "\n".join(L)


def figure(res, path, title=""):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    cols = sorted({b["gap_um"] for b in res["boxes"]}); rows = sorted({b["dot_um"] for b in res["boxes"]})
    keys = [("recognised", "recognised", "RdYlGn", 0, 1, 100, "%"), ("merged", "merged", "RdYlGn_r", 0, 1, 100, "%"),
            ("contrast", "contrast (grey levels)", "viridis", None, None, 1, ""),
            ("scatter_px", "scatter about the lattice (px)", "viridis_r", None, None, 1, ""),
            ("blur_um", "blur measured (µm)", "viridis_r", None, None, 1, "")]
    fig, ax = plt.subplots(1, 5, figsize=(21, 4.6), dpi=110)
    for a, (k, ttl, cmap, lo, hi, mul, unit) in zip(ax, keys):
        M = np.array([[next(x for x in res["boxes"] if x["dot_um"] == d and x["gap_um"] == g)[k] for g in cols]
                      for d in rows], float)
        im = a.imshow(M, cmap=cmap, vmin=lo, vmax=hi, aspect="auto")
        a.set_xticks(range(len(cols))); a.set_xticklabels([f"{g:g}" for g in cols], fontsize=8)
        a.set_yticks(range(len(rows))); a.set_yticklabels([f"{d:g}" for d in rows], fontsize=8)
        a.set_xlabel("gap between dots (µm)"); a.set_ylabel("dot size (µm)"); a.set_title(ttl, fontsize=9)
        for i in range(M.shape[0]):
            for j in range(M.shape[1]):
                if M[i, j] == M[i, j]:
                    a.text(j, i, f"{M[i, j] * mul:.0f}{unit}" if mul == 100 else f"{M[i, j]:.2f}" if k != "contrast"
                           else f"{M[i, j]:.0f}", ha="center", va="center", fontsize=7.5,
                           bbox=dict(fc="white", ec="none", alpha=0.55, pad=0.8))
        fig.colorbar(im, ax=a, fraction=0.046, pad=0.02)
    fig.suptitle(f"{title}   expansion {res.get('expansion', float('nan')):.2f}× · blur {res.get('blur_um', float('nan')):.2f} µm · "
                 f"{res['tags_decoded']} tags\n{res['verdict']}", fontsize=10)
    fig.tight_layout(rect=[0, 0, 1, 0.88]); fig.savefig(path); plt.close(fig)


def save(res, stem, title=""):
    rows = res["boxes"]
    if rows:
        with open(stem + "_spectrum.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
        figure(res, stem + "_spectrum.png", title)
    with open(stem + "_spectrum.json", "w") as f:
        json.dump({k: v for k, v in res.items() if k != "matched"}, f, indent=1, default=float)


def load_image(path):
    from rwtag.aruco import series as AS
    return AS.prepare_frame(path, ArucoParams())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--um-per-px", type=float, default=None, help="default: the spec sheet's (0.510)")
    ap.add_argument("--edge-band-um", type=float, default=25.0, help="unusable band at the frame edge")
    ap.add_argument("--out", default=None, help="output folder (default: beside the image)")
    a = ap.parse_args()
    spec = json.load(open(os.path.join(HERE, "spec_sheet.json")))
    design = Design.load(os.path.join(HERE, "reference_tags.json"))
    res = analyse(load_image(a.image), spec, design, a.um_per_px, edge_band_um=a.edge_band_um)
    print(table(res))
    stem = os.path.join(a.out or os.path.dirname(os.path.abspath(a.image)),
                        os.path.splitext(os.path.basename(a.image))[0])
    save(res, stem, os.path.basename(a.image))
    print(f"\nwrote {stem}_spectrum.csv / .png / .json")


if __name__ == "__main__":
    main()
