#!/usr/bin/env python3
"""
simulate_module_spread.py
=========================
Answer the specific question: what if the individual black SQUARES (modules)
inside an ArUco marker are each rigid, and the gel BETWEEN them stretches, so
the modules keep their size but the GAPS between them open up as the pattern
expands?

This is DIFFERENT from:
  * a marker that is one solid rigid island (whole tag rigid -> only
    translates -> always decodes), and
  * a marker that co-swells uniformly (modules AND gaps scale together ->
    stays a valid marker, just bigger).

If the modules are rigid and only the gaps grow, then for an expansion factor
lambda the module fill fraction is  f = 1 / lambda  (modules start touching at
f = 1). We render that and re-run the detector.

Prediction: it FAILS quickly, because (a) ArUco locates a marker by its SOLID
connected black border, which fragments into separate squares once gaps open,
and (b) the sampled cell regions start falling into white gaps. So a rigid
module system does NOT survive expansion -- you want each tag to be a single
solid rigid island instead.

Outputs
-------
  module_spread_examples.png   marker rendered at several expansion factors
  module_spread_sweep.png      decode success vs expansion factor
  prints the decode table

Requires: opencv-contrib-python, numpy, matplotlib, generate_pattern.py
"""

from __future__ import annotations
import numpy as np
import cv2
import cv2.aruco as aruco
from generate_pattern import get_dictionary, draw_marker, make_detector

DICT = "DICT_6X6_1000"
MARKER_ID = 42
MODULE_PX = 40


def module_map(dict_name, marker_id):
    """N x N grid (1 = black module) including the 1-module border."""
    d = get_dictionary(dict_name)
    # side in modules = data bits + 2 border; for 6x6 -> 8
    n_modules = 6 + 2
    img = draw_marker(d, marker_id, n_modules, 1)   # one pixel per module
    return (img < 128).astype(np.uint8), n_modules


def render_module_spread(mmap, n, module_px, fill):
    """Rigid modules of fixed size `module_px`, pitch = module_px / fill.
    fill = 1 -> solid marker; fill < 1 -> gaps open between rigid modules."""
    pitch = module_px / fill
    quiet = pitch                      # one pitch of white quiet border
    size = int(round(n * pitch + 2 * quiet))
    canvas = np.full((size, size), 255, np.uint8)
    for r in range(n):
        for c in range(n):
            if mmap[r, c]:
                cx = quiet + (c + 0.5) * pitch
                cy = quiet + (r + 0.5) * pitch
                x0, y0 = int(round(cx - module_px / 2)), int(round(cy - module_px / 2))
                canvas[y0:y0 + module_px, x0:x0 + module_px] = 0
    return canvas


def decodes(canvas, dict_name, marker_id):
    detect = make_detector(get_dictionary(dict_name))
    corners, ids = detect(canvas)
    if ids is None:
        return False
    return marker_id in [int(x) for x in ids.flatten()]


def main():
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    mmap, n = module_map(DICT, MARKER_ID)

    lambdas = [1.0, 1.15, 1.3, 1.5, 1.75, 2.0, 2.5, 3.0]
    results = []
    for lam in lambdas:
        f = 1.0 / lam                         # rigid modules, gaps grow by lambda
        img = render_module_spread(mmap, n, MODULE_PX, f)
        ok = decodes(img, DICT, MARKER_ID)
        results.append(ok)

    # find last surviving lambda
    surv = [lam for lam, ok in zip(lambdas, results) if ok]
    lam_fail = None
    for lam, ok in zip(lambdas, results):
        if not ok:
            lam_fail = lam
            break

    # ---- example panels ----
    show = [1.0, 1.3, 1.75, 2.5]
    fig, axes = plt.subplots(1, len(show), figsize=(17, 4.6), dpi=120)
    for ax, lam in zip(axes, show):
        img = render_module_spread(mmap, n, MODULE_PX, 1.0 / lam)
        ok = decodes(img, DICT, MARKER_ID)
        ax.imshow(img, cmap="gray", vmin=0, vmax=255)
        ax.set_title(f"lambda = {lam}   (fill {1/lam:.2f})\n"
                     f"{'DECODES' if ok else 'FAILS — border fragmented'}",
                     color=("#1f9d55" if ok else "#e0342b"), fontsize=11)
        ax.axis("off")
    fig.suptitle("Rigid MODULES with gaps opening up: the solid ArUco border breaks apart",
                 fontsize=13)
    fig.tight_layout(); fig.savefig("module_spread_examples.png"); plt.close(fig)

    # ---- sweep ----
    fig, ax = plt.subplots(figsize=(8, 4.6), dpi=120)
    ax.plot(lambdas, [1 if r else 0 for r in results], "o-", color="#e0342b")
    ax.set(xlabel="expansion factor lambda (rigid modules, gaps grow)",
           ylabel="decodes? (1 = yes)", ylim=(-0.1, 1.1),
           title="Rigid-module ArUco fails once gaps open (fill = 1/lambda)")
    ax.grid(alpha=0.3)
    ax.axhline(0.5, ls=":", color="gray")
    fig.tight_layout(); fig.savefig("module_spread_sweep.png"); plt.close(fig)

    print("Rigid-module ArUco (modules fixed size, gaps grow with expansion):")
    for lam, ok in zip(lambdas, results):
        print(f"   lambda={lam:<5} fill={1/lam:.2f}  ->  {'decodes' if ok else 'FAILS'}")
    print(f"\nLast surviving expansion: lambda = {max(surv) if surv else 'none'}")
    if lam_fail:
        print(f"First failure at        : lambda = {lam_fail}")
    print("\nConclusion: rigid modules that separate destroy the marker's solid border.")
    print("Fix: print each tag as ONE solid rigid island (whole tag rigid), OR fully")
    print("co-swelling (modules AND gaps scale together). Not rigid-modules-on-gel.")
    print("\nOutputs: module_spread_examples.png, module_spread_sweep.png")


if __name__ == "__main__":
    main()
