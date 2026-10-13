#!/usr/bin/env python3
"""
w0_candidate_matrix.py — Workshop step 0 (Rev D).

The candidate design matrix, computed against the MEASURED microscope
requirements rather than Rev C's assumed ~100 nm/px confocal. Every candidate is
built with the real Phase-A generator, so dot counts are exact (keep-outs,
quiet zone, dash clearance, centred lattice), not area estimates.

Laws used (all measured on the real series; see WORKSHOP_PLAN.md section 1):
    pixel size      0.510 um/px                       (R1, gated)
    tag             6 modules x 1.8 x PSF FWHM        (R5)
    quiet zone      max(module, 1.5 x PSF)            (R6)
    dot pitch       1.75 x sqrt(dot^2 + PSF^2)        (R4)
    signal          ~ lambda^-1.84, SNR 27.4 per 2.125 um dot at 1.5x  (R7)
    dots in view    0.33 x (stitch_px / pitch_px)^2   (scaling law x measured derate)

Run:  python w0_candidate_matrix.py
"""
from __future__ import annotations
import contextlib
import io
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "tools")))
from aruco_grid import GridConfig, build, solid_ids                      # noqa: E402

UMPX, STITCH_PX, SEP, MODRULE = 0.510, 2676, 1.75, 1.8
SNR15, SIGEXP = 27.4, -1.84          # SNR/dot at 1.5x for a 2.125 um dot, fixed exposure
ROSE = 5.0                           # detection needs roughly SNR >= 5

CANDIDATES = [
    # id   PSF    grid  dot     note
    ("A", 3.18, 5, 2.125, "SAFE  - works at the blur measured today"),
    ("B", 3.18, 4, 2.125, "safe, 4x4 boxes"),
    ("C", 3.18, 3, 2.125, "safe, 3x3 boxes"),
    ("D", 2.50, 5, 2.125, "HEDGE - half the focus fix"),
    ("E", 2.50, 4, 2.125, "hedge, 4x4 boxes"),
    ("F", 1.91, 5, 2.125, "OPT   - full focus fix (user preference)"),
    ("G", 1.91, 4, 2.125, "opt, 4x4 boxes"),
    ("H", 1.91, 5, 3.000, "opt, 3 um dots (photon insurance)"),
    ("I", 2.50, 4, 3.000, "hedge, 4x4, 3 um dots"),
]


def snr(dot_um, lam, exposure=1.0):
    return SNR15 * (dot_um / 2.125) ** 2 * (lam / 1.5) ** SIGEXP * exposure


def dots_in_view(pitch_um, lam):
    return 0.33 * (STITCH_PX / (pitch_um * lam / UMPX)) ** 2


def candidate(cid, psf, grid_n, dot, note):
    tag = math.ceil(6 * MODRULE * psf)
    cfg = GridConfig(grid_n=grid_n, tag_um=float(tag), psf_fwhm_um=psf, dot_side_um=dot,
                     dashes=True, round_tags=True, fit="inside", field_um=750.0)
    with contextlib.redirect_stdout(io.StringIO()):
        rects, recs, _info = build(cfg)
    n_dots = sum(1 for r in recs if r["category"] == "dot")
    area = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in rects)
    p = cfg.dot_pitch_um
    return dict(id=cid, psf=psf, grid=f"{grid_n}x{grid_n}", tag_um=tag,
                quiet_um=cfg.quiet_zone_um, pitch_um=p, dots=n_dots,
                fill_pct=100 * area / 750.0 ** 2,
                at4x=dots_in_view(p, 4.0), at6x=dots_in_view(p, 6.0),
                snr6x_comp=snr(dot, 6.0, (6.0 / 1.5) ** 2), note=note)


def main():
    print("strut-free (single-4-connected) ids per dictionary:")
    for name, mods, n in (("DICT_4X4_50", 6, 50), ("DICT_4X4_100", 6, 100),
                          ("DICT_APRILTAG_16h5", 6, 30), ("DICT_5X5_50", 7, 50),
                          ("DICT_APRILTAG_36h11", 8, 587)):
        print(f"  {name:<22} {mods} modules  {len(solid_ids(name, mods, n)):>4}/{n}")

    print("\nCANDIDATES  (750 um field, 3 tiers, exposure ~ lambda^2)")
    print(f"{'id':<3}{'PSF':>5}{'grid':>6}{'tag':>5}{'quiet':>7}{'pitch':>7}{'dots':>8}"
          f"{'fill%':>7}{'@4x':>7}{'@6x':>7}{'SNR6x':>7}")
    for c in (candidate(*row) for row in CANDIDATES):
        print(f"{c['id']:<3}{c['psf']:>5.2f}{c['grid']:>6}{c['tag_um']:>5}{c['quiet_um']:>7.1f}"
              f"{c['pitch_um']:>7.2f}{c['dots']:>8,}{c['fill_pct']:>7.1f}{c['at4x']:>7.0f}"
              f"{c['at6x']:>7.0f}{c['snr6x_comp']:>7.1f}   {c['note']}")
    print("\n@4x/@6x = paired dots expected in a 2676 px stitch")
    print(f"SNR at 6x for a 2.125 um dot WITHOUT exposure compensation = "
          f"{snr(2.125, 6.0):.1f}  (Rose limit ~{ROSE:.0f}) -> compensation is mandatory")


if __name__ == "__main__":
    main()
