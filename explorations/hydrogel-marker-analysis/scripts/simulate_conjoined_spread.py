#!/usr/bin/env python3
"""
simulate_conjoined_spread.py
============================
More faithful model of a rigid-black / expanding-gel ArUco marker:

  * Black modules that TOUCH edge-to-edge are one connected piece of rigid
    material -> they stay CONJOINED and move together (rigid).
  * Separate black regions (isolated modules, blobs not joined to others)
    DRIFT apart as the white gel between them expands.

So each connected black component is treated as a rigid body whose centroid
is carried by the uniform expansion (centroid -> center + lambda*(centroid-
center)), while the component keeps its own size/shape.

Consequence vs the naive "every module separate" sim:
  * The ArUco BORDER is a single connected ring -> it stays intact, so the
    marker can still be LOCATED (not shattered).
  * But separate interior black regions drift outward relative to that border.
    Once they drift ~ half a module, the sampled bits corrupt and the ID no
    longer decodes -- even though a quad is still found.

Outputs
-------
  conjoined_spread_examples.png   marker at several expansion factors
  conjoined_spread_sweep.png      located vs correctly-decoded vs expansion
  prints the table + the number of connected components

Requires: opencv-contrib-python, numpy, matplotlib, generate_pattern.py
"""

from __future__ import annotations
import numpy as np
import cv2
import cv2.aruco as aruco
from generate_pattern import get_dictionary, draw_marker, make_detector

DICT = "DICT_6X6_1000"
MODULE_PX = 40
N = 8  # 6 data + 2 border modules


def module_map(marker_id):
    d = get_dictionary(DICT)
    img = draw_marker(d, marker_id, N, 1)
    return (img < 128).astype(np.uint8)      # 1 = black


def components(mmap):
    """4-connected black components; returns list of (member_rc array, centroid_rc)."""
    num, labels = cv2.connectedComponents(mmap, connectivity=4)
    comps = []
    for L in range(1, num):
        rc = np.argwhere(labels == L).astype(float)   # (k,2) as (row,col)
        comps.append((rc, rc.mean(0)))
    return comps


def render(comps, lam, module_px=MODULE_PX):
    center = np.array([(N - 1) / 2.0, (N - 1) / 2.0])
    # compute all expanded module positions (in module units)
    placed = []   # (row, col) centers in module units
    for rc, cen in comps:
        cen_exp = center + lam * (cen - center)        # rigid-body centroid moves
        for m in rc:
            placed.append(cen_exp + (m - cen))          # keep rigid offset
    placed = np.array(placed)
    # canvas
    minrc = placed.min(0) - 1.5
    span = (placed.max(0) - minrc) + 1.5
    Hpx, Wpx = int(span[0] * module_px), int(span[1] * module_px)
    canvas = np.full((Hpx, Wpx), 255, np.uint8)
    half = module_px / 2.0
    for (r, c) in placed:
        yc = (r - minrc[0]) * module_px + module_px / 2.0
        xc = (c - minrc[1]) * module_px + module_px / 2.0
        x0, y0 = int(round(xc - half)), int(round(yc - half))
        canvas[y0:y0 + module_px, x0:x0 + module_px] = 0
    return canvas


def detect_state(canvas, marker_id):
    """Return (located, decoded_correct)."""
    d = get_dictionary(DICT)
    detect = make_detector(d)
    corners, ids = detect(canvas)
    decoded = ids is not None and marker_id in [int(x) for x in ids.flatten()]
    try:
        det = aruco.ArucoDetector(d, aruco.DetectorParameters())
        c2, i2, rej = det.detectMarkers(canvas)
        located = (i2 is not None and len(i2) > 0) or (rej is not None and len(rej) > 0)
    except Exception:
        located = decoded
    return located, decoded


def main():
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # --- scan the dictionary: how connected is the black in each ID? ---
    scan_ids = list(range(200))
    ncomp = {mid: len(components(module_map(mid))) for mid in scan_ids}
    from collections import Counter
    dist = Counter(ncomp.values())
    n_single = sum(1 for v in ncomp.values() if v == 1)
    print(f"Scanned {len(scan_ids)} IDs of {DICT}.")
    print(f"Connected-black-components per marker (4-connectivity):")
    for k in sorted(dist):
        print(f"   {k} component(s): {dist[k]} markers")
    print(f"=> {n_single}/{len(scan_ids)} markers have SINGLE connected black "
          f"(-> intrinsically a rigid island, decode at any lambda)\n")

    best_id = next(mid for mid in scan_ids if ncomp[mid] == 1)
    worst_id = max(scan_ids, key=lambda m: ncomp[m])
    print(f"Best  (single component): ID {best_id}")
    print(f"Worst ({ncomp[worst_id]} components): ID {worst_id}\n")

    lambdas = [1.0, 1.1, 1.2, 1.35, 1.5, 1.75, 2.0, 2.5, 3.0]

    def sweep(mid):
        comps = components(module_map(mid))
        loc, dec = [], []
        for lam in lambdas:
            l, d = detect_state(render(comps, lam), mid)
            loc.append(l); dec.append(d)
        return loc, dec

    loc_w, dec_w = sweep(worst_id)
    loc_b, dec_b = sweep(best_id)

    # examples (worst-case marker drifting)
    comps_w = components(module_map(worst_id))
    show = [1.0, 1.2, 1.5, 2.5]
    fig, axes = plt.subplots(1, len(show), figsize=(17, 4.7), dpi=120)
    for ax, lam in zip(axes, show):
        img = render(comps_w, lam)
        l, dcd = detect_state(img, worst_id)
        ax.imshow(img, cmap="gray", vmin=0, vmax=255)
        state = "DECODES" if dcd else ("located, ID lost" if l else "not located")
        ax.set_title(f"lambda = {lam}\n{state}",
                     color=("#1f9d55" if dcd else ("#e08a00" if l else "#e0342b")), fontsize=11)
        ax.axis("off")
    fig.suptitle(f"Worst-case ID {worst_id} ({ncomp[worst_id]} black pieces): border ring stays, "
                 f"but separate modules drift and corrupt the code", fontsize=12)
    fig.tight_layout(); fig.savefig("conjoined_spread_examples.png"); plt.close(fig)

    # sweep figure
    fig, ax = plt.subplots(figsize=(9, 4.6), dpi=120)
    ax.plot(lambdas, [int(x) for x in dec_w], "o-", color="#e0342b",
            label=f"worst ID {worst_id} ({ncomp[worst_id]} pieces): decoded")
    ax.plot(lambdas, [int(x) for x in loc_w], "s--", color="#e08a00", alpha=0.7,
            label=f"worst ID {worst_id}: merely located")
    ax.plot(lambdas, [int(x) for x in dec_b], "^-", color="#1f9d55",
            label=f"single-piece ID {best_id}: decoded")
    ax.set(xlabel="expansion factor lambda", ylabel="success (1 = yes)", ylim=(-0.1, 1.2),
           title="Rigid-black / expanding-gel: single-piece IDs are robust; multi-piece IDs lose their code")
    ax.legend(fontsize=8); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig("conjoined_spread_sweep.png"); plt.close(fig)

    print("Worst-case sweep (rigid black, gel expands between separate pieces):")
    for lam, l, dcd in zip(lambdas, loc_w, dec_w):
        s = "DECODES" if dcd else ("located, ID lost" if l else "not located")
        print(f"   ID {worst_id}: lambda={lam:<5} -> {s}")
    last_w = max([l for l, d in zip(lambdas, dec_w) if d], default=None)
    last_b = max([l for l, d in zip(lambdas, dec_b) if d], default=None)
    print(f"\nWorst ID {worst_id} decodes up to lambda = {last_w}")
    print(f"Single-piece ID {best_id} decodes up to lambda = {last_b} (i.e. all tested)")
    print("\nActionable levers:")
    print(" * SELECT marker IDs whose black is a single 4-connected piece -> rigid-island by construction.")
    print(" * Or make the WHOLE tag one solid rigid island regardless of ID.")
    print(" * Or fully co-swelling (modules AND gaps scale together).")
    print("\nOutputs: conjoined_spread_examples.png, conjoined_spread_sweep.png")


if __name__ == "__main__":
    main()
