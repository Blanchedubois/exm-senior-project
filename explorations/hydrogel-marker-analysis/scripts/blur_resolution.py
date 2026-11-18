#!/usr/bin/env python3
"""
blur_resolution.py
==================
Add a Gaussian blur to model limited optical resolution (the microscope PSF /
low pixel resolution) and re-test ArUco recognition of the conjoined (smooth-
strutted) tags -- per marker and on the full grid.

Blur is parameterized by sigma as a fraction of a MODULE, because that is the
scale that matters: once the PSF sigma approaches a module, neighbouring
modules smear together and the code can no longer be read. For a 6 um tag
(8 modules) one module ~ 0.75 um; optical resolution FWHM = 2.355 * sigma.

Outputs
-------
  blur_examples.png        one strutted tag at rising blur (sharp -> washed out)
  blur_marker_sweep.png    decode rate vs blur across many strutted IDs
  blur_grid_examples.png   the full pattern grid at rising blur
  blur_grid_sweep.png      markers decoded on the grid vs blur
  prints the blur tolerance and the equivalent optical resolution

Requires: opencv-contrib-python, numpy, matplotlib, generate_pattern.py,
          conjoined_markers.py, strut_prominence.py
"""
from __future__ import annotations
import numpy as np
import cv2

from generate_pattern import PatternConfig, generate, get_dictionary, make_detector
from conjoined_markers import mmap, n_components, N, DICT
from strut_prominence import draw_smooth, decodes

TAG_UM = 6.0
MODULE_UM = TAG_UM / N          # ~0.75 um


def gblur(img, sigma_px):
    if sigma_px <= 0:
        return img
    return cv2.GaussianBlur(img, (0, 0), sigma_px)


def main():
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # strutted IDs (corner pinches -> need struts); test the conjoined design
    strut_ids = [i for i in range(1000)
                 if n_components(mmap(i), 4) > 1 and n_components(mmap(i), 8) == 1]
    sample = strut_ids[:90]
    demo = max(strut_ids, key=lambda i: n_components(mmap(i), 4))
    module_px = 24
    strut_w = 0.3

    # ---------- Part 1: per-marker blur sweep ----------
    fracs = np.round(np.arange(0.0, 1.05, 0.1), 2)
    rate = []
    for fr in fracs:
        s = fr * module_px
        oks = [decodes(gblur(draw_smooth(i, strut_w=strut_w, module_px=module_px), s), i)
               for i in sample]
        rate.append(np.mean(oks))
    rate = np.array(rate)
    safe = fracs[rate >= 0.99]
    f_tag = safe.max() if len(safe) else 0.0

    # examples
    show = [0.1, 0.4, 0.7, 1.0]
    fig, axes = plt.subplots(1, len(show), figsize=(17, 4.7), dpi=120)
    for ax, fr in zip(axes, show):
        img = gblur(draw_smooth(demo, strut_w=strut_w, module_px=module_px), fr * module_px)
        ok = decodes(img, demo)
        ax.imshow(img, cmap="gray", vmin=0, vmax=255)
        ax.set_title(f"blur sigma = {fr:.1f} module ({fr*MODULE_UM:.2f} um)\n"
                     f"{'decodes' if ok else 'FAILS'}",
                     color=("#1f9d55" if ok else "#e0342b"), fontsize=11)
        ax.axis("off")
    fig.suptitle(f"Strutted tag ID {demo} under optical blur (low resolution)", fontsize=12)
    fig.tight_layout(); fig.savefig("blur_examples.png"); plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 5), dpi=120)
    ax.plot(fracs, rate * 100, "o-", color="#1166cc")
    ax.axvline(f_tag, ls="--", color="#e0342b",
               label=f"recognition limit ~{f_tag:.1f} module (sigma~{f_tag*MODULE_UM:.2f} um, "
                     f"FWHM~{2.355*f_tag*MODULE_UM:.2f} um)")
    ax.set(xlabel="blur sigma (fraction of a module)",
           ylabel=f"tags still decoded (%)  (n={len(sample)})",
           title="Recognition vs optical blur (single strutted tags)", ylim=(-3, 103))
    sec = ax.secondary_xaxis("top", functions=(lambda x: x * MODULE_UM, lambda x: x / MODULE_UM))
    sec.set_xlabel("blur sigma (um, 6 um tag)")
    ax.grid(alpha=0.3); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig("blur_marker_sweep.png"); plt.close(fig)

    # ---------- Part 2: full-grid blur sweep ----------
    cfg = PatternConfig(n_boxes_x=3, n_boxes_y=3, box_size_um=30.0, marker_um=TAG_UM,
                        dot_pitch_um=1.5, px_per_um=20.0, draw_box_boundary=True)
    grid, meta = generate(cfg)
    total = meta["n_nodes"]
    mod_px_grid = cfg.marker_um / N * cfg.px_per_um       # module size in grid px
    detect = make_detector(get_dictionary(DICT))

    def n_decoded(img):
        _, ids = detect(img)
        return 0 if ids is None else len(ids)

    gfracs = np.round(np.arange(0.0, 1.05, 0.1), 2)
    gdec = [n_decoded(gblur(grid, fr * mod_px_grid)) for fr in gfracs]

    show = [0.1, 0.4, 0.7, 1.0]
    fig, axes = plt.subplots(1, len(show), figsize=(17, 4.8), dpi=120)
    for ax, fr in zip(axes, show):
        img = gblur(grid, fr * mod_px_grid)
        nd = n_decoded(img)
        # crop to one box region for visibility
        s = int((cfg.margin_um + cfg.box_size_um + cfg.marker_um) * cfg.px_per_um)
        ax.imshow(img[:s, :s], cmap="gray", vmin=0, vmax=255)
        ax.set_title(f"blur sigma {fr:.1f} module ({fr*MODULE_UM:.2f} um)\n"
                     f"{nd}/{total} markers on full grid",
                     color=("#1f9d55" if nd == total else "#e0342b"), fontsize=10)
        ax.axis("off")
    fig.suptitle("Full pattern grid (markers + fine dots) under optical blur — top-left corner",
                 fontsize=12)
    fig.tight_layout(); fig.savefig("blur_grid_examples.png"); plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 5), dpi=120)
    ax.plot(gfracs, gdec, "o-", color="#1f9d55")
    ax.set(xlabel="blur sigma (fraction of a module)",
           ylabel=f"markers decoded / {total}",
           title="Recognition vs optical blur (full grid)", ylim=(-0.5, total + 1))
    sec = ax.secondary_xaxis("top", functions=(lambda x: x * MODULE_UM, lambda x: x / MODULE_UM))
    sec.set_xlabel("blur sigma (um, 6 um tag)")
    ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig("blur_grid_sweep.png"); plt.close(fig)

    # ---------- report ----------
    print(f"Module ~ {MODULE_UM:.2f} um (6 um tag, 8 modules). Optical FWHM = 2.355*sigma.\n")
    print("Per-marker (strutted) decode rate vs blur sigma:")
    for fr, rr in zip(fracs, rate):
        print(f"   sigma {fr:.1f} module ({fr*MODULE_UM:.2f} um): {rr*100:5.1f}%")
    print(f"\nFull grid ({total} markers) decoded vs blur sigma:")
    for fr, nd in zip(gfracs, gdec):
        print(f"   sigma {fr:.1f} module ({fr*MODULE_UM:.2f} um): {nd}/{total}")
    print(f"\nRecognition holds (>=99%) up to sigma ~{f_tag:.1f} module "
          f"(~{f_tag*MODULE_UM:.2f} um), i.e. optical FWHM ~{2.355*f_tag*MODULE_UM:.2f} um.")
    print("Typical confocal resolution ~0.2-0.3 um FWHM, widefield ~0.3-0.5 um -> comfortably fine")
    print("for a 6 um tag. If the tag is smaller / resolution worse, enlarge the tag so a module")
    print("stays >~2x the PSF sigma.")
    print("\nOutputs: blur_examples.png, blur_marker_sweep.png, blur_grid_examples.png, blur_grid_sweep.png")


if __name__ == "__main__":
    main()
