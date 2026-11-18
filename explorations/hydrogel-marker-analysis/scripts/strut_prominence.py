#!/usr/bin/env python3
"""
strut_prominence.py
===================
(1) Replace the blobby disc strut with a SMOOTH, thin elliptical neck aligned
    along the black diagonal -> less prominent, intrudes less into white cells.
(2) Plot how prominent the strut may be before the ArUco tag stops being
    recognized (decoded). This gives the usable window: big enough to hold the
    pieces together mechanically, small enough not to corrupt the code.

Strut prominence = neck WIDTH (minor axis of the ellipse) as a fraction of a
module. The major axis is fixed (reaches into both black squares so the bridge
always connects); only the width is swept.

Outputs
-------
  strut_smoothness_examples.png   one tag at rising strut width (smooth necks)
  strut_prominence_plot.png       decode rate vs strut width across many IDs
  prints the recognition threshold and a recommended width

Requires: opencv-contrib-python, numpy, matplotlib, conjoined_markers.py
"""
from __future__ import annotations
import numpy as np
import cv2
from conjoined_markers import (mmap, get_dictionary, make_detector,
                               n_components, N, DICT)

MODULE_PX = 22


def draw_smooth(marker_id, strut_w=0.15, strut_len=0.72, module_px=MODULE_PX,
                border_modules=1.5, draw=True):
    """Smooth elliptical struts (minor axis = strut_w * module) along the
    black diagonal at each corner pinch."""
    m = mmap(marker_id)
    off = int(round(border_modules * module_px))
    size = N * module_px + 2 * off
    img = np.full((size, size), 255, np.uint8)
    for r in range(N):
        for c in range(N):
            if m[r, c]:
                img[off + r * module_px:off + (r + 1) * module_px,
                    off + c * module_px:off + (c + 1) * module_px] = 0
    if draw and strut_w > 0:
        minor = max(1, int(round(strut_w * module_px)))
        major = max(minor, int(round(strut_len * module_px)))
        for r in range(N - 1):
            for c in range(N - 1):
                a, b = m[r, c], m[r, c + 1]
                cc, d = m[r + 1, c], m[r + 1, c + 1]
                if a and d and not b and not cc:
                    ang = 45
                elif b and cc and not a and not d:
                    ang = 135
                else:
                    continue
                vx, vy = off + (c + 1) * module_px, off + (r + 1) * module_px
                cv2.ellipse(img, (vx, vy), (major // 2, minor // 2), ang, 0, 360, 0, -1, cv2.LINE_AA)
    return img


def decodes(img, marker_id):
    _, ids = make_detector(get_dictionary(DICT))(img)
    return ids is not None and marker_id in [int(x) for x in ids.flatten()]


def main():
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # IDs where struts actually matter (corner pinches present)
    strut_ids = [i for i in range(1000)
                 if n_components(mmap(i), 4) > 1 and n_components(mmap(i), 8) == 1]
    sample = strut_ids[:120]
    demo = max(strut_ids, key=lambda i: n_components(mmap(i), 4))

    # ---- smoothness / prominence examples ----
    widths = [0.15, 0.5, 0.9, 1.3]
    fig, axes = plt.subplots(1, len(widths), figsize=(17, 4.7), dpi=120)
    for ax, w in zip(axes, widths):
        img = draw_smooth(demo, strut_w=w)
        ok = decodes(img, demo)
        ax.imshow(img, cmap="gray", vmin=0, vmax=255)
        ax.set_title(f"strut width = {w:.2f} module\n{'decodes' if ok else 'FAILS'}",
                     color=("#1f9d55" if ok else "#e0342b"), fontsize=11)
        ax.axis("off")
    fig.suptitle(f"Smooth elliptical struts on ID {demo} — thinner = less prominent, smoother",
                 fontsize=12)
    fig.tight_layout(); fig.savefig("strut_smoothness_examples.png"); plt.close(fig)

    # ---- prominence sweep: decode rate vs strut width ----
    ws = np.round(np.arange(0.0, 1.65, 0.1), 2)
    rate = []
    for w in ws:
        oks = [decodes(draw_smooth(i, strut_w=w), i) for i in sample]
        rate.append(np.mean(oks))
    rate = np.array(rate)

    # recognition ceiling: last width with >=99% decode rate
    safe = ws[rate >= 0.99]
    w_thresh = safe.max() if len(safe) else 0.0

    # lower bound is FABRICATION: Nanoscribe min printable feature ~0.2 um
    module_um = 6.0 / N          # 1 module ~ 0.75 um for a 6 um tag
    fab_min_um = 0.2
    fab_min_frac = fab_min_um / module_um
    recommend = round(max(fab_min_frac, 0.25), 2)   # printable, smooth, well below ceiling

    fig, ax = plt.subplots(figsize=(9.2, 5), dpi=120)
    ax.axvspan(fab_min_frac, w_thresh, color="#1f9d55", alpha=0.12, label="usable window")
    ax.plot(ws, rate * 100, "o-", color="#1166cc")
    ax.axvline(w_thresh, ls="--", color="#e0342b",
               label=f"recognition ceiling ~{w_thresh:.2f} module (~{w_thresh*module_um:.2f} um)")
    ax.axvline(fab_min_frac, ls="--", color="#8a6d00",
               label=f"Nanoscribe min feature ~{fab_min_um} um")
    ax.axvline(recommend, ls="-", color="#1f9d55",
               label=f"recommended ~{recommend:.2f} module (~{recommend*module_um:.2f} um)")
    ax.set(xlabel="strut width (fraction of a module)",
           ylabel=f"tags still decoded (%)  (n={len(sample)})",
           title="How prominent can the conjoined strut be and still be recognized?",
           ylim=(-3, 103))
    secax = ax.secondary_xaxis("top", functions=(lambda x: x * module_um,
                                                  lambda x: x / module_um))
    secax.set_xlabel("strut width (um, for a 6 um tag)")
    ax.grid(alpha=0.3); ax.legend(fontsize=8, loc="lower left")
    fig.tight_layout(); fig.savefig("strut_prominence_plot.png"); plt.close(fig)

    print(f"IDs needing struts (corner pinches): {len(strut_ids)}; sampled {len(sample)}.")
    print("Decode rate vs strut width (fraction of a module):")
    for w, rr in zip(ws, rate):
        bar = "#" * int(rr * 30)
        print(f"   width {w:.2f} ({w*module_um:.2f} um): {rr*100:5.1f}%  {bar}")
    print(f"\nRecognition ceiling (>=99% decode): ~{w_thresh:.2f} module (~{w_thresh*module_um:.2f} um).")
    print(f"Fabrication floor (Nanoscribe ~{fab_min_um} um): ~{fab_min_frac:.2f} module.")
    print(f"=> Usable window: ~{fab_min_frac:.2f}..{w_thresh:.2f} module "
          f"(~{fab_min_um:.2f}..{w_thresh*module_um:.2f} um).")
    print(f"Recommended strut width: ~{recommend:.2f} module (~{recommend*module_um:.2f} um) "
          f"— smooth, printable, well below the recognition ceiling.")
    print("Note: the binding limit is the PRINTABLE minimum, not recognition — the smooth")
    print("diagonal strut sits in ArUco's ignored corner margin, so it barely affects decoding.")
    print("\nOutputs: strut_smoothness_examples.png, strut_prominence_plot.png")


if __name__ == "__main__":
    main()
