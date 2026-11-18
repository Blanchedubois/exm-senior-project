#!/usr/bin/env python3
"""
multi_marker_test.py
====================
Test MANY different ArUco IDs from the curated connected list (single
8-connected -> strut-able to one piece), not just one demo marker:

  1. verify every sampled tag decodes at full resolution (curated list is valid);
  2. measure each tag's optical-blur failure threshold (the sigma at which it
     stops decoding) -> shows how CONSISTENT the robustness is across markers,
     and flags any unusually blur-sensitive IDs to avoid;
  3. montage of many different tags (sharp and blurred) with decode status.

Outputs
-------
  multi_marker_montage.png     24 different strutted tags, sharp vs blurred
  multi_marker_threshold.png   histogram of per-tag blur failure thresholds
  prints reference decode count, threshold stats, and any weak IDs

Requires: opencv-contrib-python, numpy, matplotlib, conjoined_markers.py, strut_prominence.py
"""
from __future__ import annotations
import numpy as np
import cv2
from conjoined_markers import mmap, n_components, N
from strut_prominence import draw_smooth, decodes

MODULE_PX = 20
STRUT_W = 0.3
MODULE_UM = 6.0 / N            # 0.75 um for a 6 um tag


def gblur(img, sigma_px):
    return img if sigma_px <= 0 else cv2.GaussianBlur(img, (0, 0), sigma_px)


def main():
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    curated = [i for i in range(1000) if n_components(mmap(i), 8) == 1]
    sample = curated[:250]
    print(f"Curated single-8-connected IDs: {len(curated)}; testing {len(sample)}.\n")

    # 1. reference decode check (all should pass)
    ref_ok = [decodes(draw_smooth(i, strut_w=STRUT_W, module_px=MODULE_PX), i) for i in sample]
    n_ref = int(np.sum(ref_ok))
    bad_ref = [i for i, ok in zip(sample, ref_ok) if not ok]
    print(f"Reference (sharp) decode: {n_ref}/{len(sample)} "
          f"{'-> all curated tags valid' if n_ref == len(sample) else '-> some failed: ' + str(bad_ref)}\n")

    # 2. per-tag blur failure threshold (last sigma-fraction that still decodes)
    steps = np.round(np.arange(0.0, 0.75, 0.05), 2)
    thr = []
    for i in sample:
        last = 0.0
        for fr in steps:
            if decodes(gblur(draw_smooth(i, strut_w=STRUT_W, module_px=MODULE_PX), fr * MODULE_PX), i):
                last = fr
            else:
                break
        thr.append(last)
    thr = np.array(thr)

    weak = sorted((i for i, t in zip(sample, thr) if t <= 0.20), key=lambda i: dict(zip(sample, thr))[i])
    print("Per-tag blur failure threshold (sigma as fraction of a module):")
    print(f"   min={thr.min():.2f}  median={np.median(thr):.2f}  max={thr.max():.2f}  "
          f"(x{MODULE_UM:.2f} um)")
    print(f"   fraction robust to sigma>=0.30 module (~0.22 um): "
          f"{np.mean(thr >= 0.30)*100:.0f}%")
    print(f"   weak IDs (fail by sigma<=0.20 module): {len(weak)}"
          + (f" -> avoid e.g. {weak[:10]}" if weak else " (none)"))

    # histogram
    fig, ax = plt.subplots(figsize=(9, 5), dpi=120)
    ax.hist(thr, bins=np.arange(-0.025, 0.75, 0.05), color="#1166cc", edgecolor="white")
    ax.axvline(np.median(thr), color="#e0342b", ls="--",
               label=f"median {np.median(thr):.2f} module (~{np.median(thr)*MODULE_UM:.2f} um)")
    ax.set(xlabel="blur failure threshold, sigma (fraction of a module)",
           ylabel=f"number of tags (n={len(sample)})",
           title="Blur robustness across many different ArUco tags (curated list)")
    sec = ax.secondary_xaxis("top", functions=(lambda x: x * MODULE_UM, lambda x: x / MODULE_UM))
    sec.set_xlabel("sigma (um, 6 um tag)")
    ax.grid(alpha=0.3); ax.legend()
    fig.tight_layout(); fig.savefig("multi_marker_threshold.png"); plt.close(fig)

    # 3. montage: 24 different tags, sharp rows vs blurred rows
    ids24 = sample[::max(1, len(sample) // 24)][:24]
    sig = 0.35 * MODULE_PX
    fig, axes = plt.subplots(4, 12, figsize=(20, 7.2), dpi=115)
    for k, mid in enumerate(ids24):
        sharp = draw_smooth(mid, strut_w=STRUT_W, module_px=MODULE_PX)
        blurred = gblur(sharp, sig)
        row = (k // 12) * 2
        col = k % 12
        a1, a2 = axes[row, col], axes[row + 1, col]
        ok_s, ok_b = decodes(sharp, mid), decodes(blurred, mid)
        a1.imshow(sharp, cmap="gray", vmin=0, vmax=255)
        a1.set_title(f"{mid}", fontsize=7, color=("#1f9d55" if ok_s else "#e0342b")); a1.axis("off")
        a2.imshow(blurred, cmap="gray", vmin=0, vmax=255)
        a2.set_title("ok" if ok_b else "x", fontsize=7,
                     color=("#1f9d55" if ok_b else "#e0342b")); a2.axis("off")
    fig.suptitle(f"24 different curated tags — rows 1,3 sharp; rows 2,4 blurred (sigma 0.35 module ~0.26 um)",
                 fontsize=12)
    fig.tight_layout(); fig.savefig("multi_marker_montage.png"); plt.close(fig)

    print("\nOutputs: multi_marker_montage.png, multi_marker_threshold.png")


if __name__ == "__main__":
    main()
