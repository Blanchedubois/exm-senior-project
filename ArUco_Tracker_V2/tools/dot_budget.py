#!/usr/bin/env python3
"""
dot_budget.py — parametric dot-yield calculator for the V2 ArUco marker grid.

Source of every number in docs/IMPLEMENTATION_PLAN.md sections 2 and 3.

All constants are MEASURED from the existing six-frame series and the
2026-01-14 STL, not assumed:

  printed dot (STL)          2.125 um square
  imaged dot FWHM            7.5 px   (subpixel Gaussian fit, high-lambda frames)
  printed features           RIGID    (constant px size as the gel expands)
  stitched frame             2676 px
  design dot pitch           8.0 um

The effective pixel size is DISPUTED (plan section 1.3) -- OME metadata says
0.510 um/px, the dot lattice says 0.381 um/px if the filename labels are true.
Everything downstream swings by ~2.4x between them, so both are carried here
until the Phase-0 calibration settles it.

Run:  python dot_budget.py
"""
from __future__ import annotations
import math
from dataclasses import dataclass

# ----------------------------------------------------------------- measured
CAD_DOT_UM = 2.125        # printed dot side, from the STL
IMAGED_FWHM_PX = 7.5      # imaged dot FWHM, median over the 3 highest-lambda frames
STITCH_PX = 2676          # stitched frame width
DESIGN_PITCH_UM = 8.0     # current printed dot pitch
CURRENT_DOTS = 6420       # dot components in the current STL

# observed lattice pitch per frame (px), from rwtag detection
PITCH_PX = {1.5: 30.95, 2.0: 40.77, 2.5: 50.80, 3.0: 63.51, 3.5: 76.21, 4.2: 91.46}

CALIBRATIONS = {"metadata": 0.510, "lattice": 0.381}


@dataclass
class Optics:
    """Imaging constants implied by a choice of effective pixel size."""
    um_per_px: float
    sep_rule: float = 2.0          # pitch >= sep_rule x imaged spot FWHM (plan 2.3)

    @property
    def psf_fwhm(self) -> float:
        """System PSF, by deconvolving the known CAD dot from the imaged spot."""
        imaged = IMAGED_FWHM_PX * self.um_per_px
        return math.sqrt(max(imaged ** 2 - CAD_DOT_UM ** 2, 0.0))

    def imaged_spot(self, dot_um: float) -> float:
        return math.hypot(dot_um, self.psf_fwhm)

    def pitch_floor(self, dot_um: float) -> float:
        return self.sep_rule * self.imaged_spot(dot_um)

    def aruco_module(self) -> float:
        """Module floor = max(pixel sampling, blur). Blur rule from FINDINGS.md
        section 4: one module >= 2.5 x PSF sigma."""
        return max(5 * self.um_per_px, 2.5 * self.psf_fwhm / 2.3548)

    def tag_um(self, modules: int = 6) -> float:
        """6 modules = DICT_4X4 incl. its 1-module border; 8 = DICT_6X6."""
        return modules * self.aruco_module()

    def true_lambda(self, label: float) -> float:
        return PITCH_PX[label] * self.um_per_px / DESIGN_PITCH_UM


def budget(opt: Optics, field_um=750.0, n_boxes=5, pitch_um=None, dot_um=1.0,
           quiet_um=3.0, tag_modules=6):
    """Dot yield for one candidate geometry. Returns a dict."""
    pitch_um = pitch_um or opt.pitch_floor(dot_um)
    tag = opt.tag_um(tag_modules)
    keepout = tag / 2 + quiet_um
    nodes = (n_boxes + 1) ** 2
    gross = (field_um / pitch_um) ** 2
    # each node removes a disc of radius `keepout`; edge/corner nodes remove less,
    # so this is deliberately the pessimistic bound.
    lost = nodes * math.pi * keepout ** 2 / pitch_um ** 2
    total = max(0.0, gross - lost)
    dot_area = total * dot_um ** 2
    tag_area = nodes * 18 * (tag / tag_modules) ** 2      # ~half the modules printed
    return dict(pitch_um=pitch_um, dot_um=dot_um, tag_um=tag, keepout=keepout,
                nodes=nodes, total=total, vs_current=total / CURRENT_DOTS,
                footprint=dot_area + tag_area, fill=(dot_area + tag_area) / field_um ** 2)


def dots_in_view(pitch_px: float, stitch_px: float = STITCH_PX) -> float:
    """The governing scaling law (plan section 2). Pixel counts only, so this is
    independent of the pixel-size ambiguity. Observed pairing runs ~3x below it
    (initial-intersect-expanded overlap + Stage-3 filtering)."""
    return (stitch_px / pitch_px) ** 2


def main():
    print(f"measured: CAD dot {CAD_DOT_UM} um | imaged {IMAGED_FWHM_PX} px | "
          f"stitch {STITCH_PX} px | current pitch {DESIGN_PITCH_UM} um\n")

    print("=" * 74)
    print("GOVERNING LAW  dots_in_view = (stitch_px / pitch_px)^2   [plan section 2]")
    print("=" * 74)
    print(f"{'label':>7}{'pitch px':>10}{'predicted':>12}{'actually paired':>18}")
    observed = {2.0: 1996, 2.5: 1207, 3.0: 583, 3.5: 443, 4.2: 299}
    for lab, ppx in PITCH_PX.items():
        obs = observed.get(lab)
        print(f"{lab:>6}x{ppx:>10.2f}{dots_in_view(ppx):>12,.0f}"
              f"{(f'{obs:,}' if obs else '-- initial --'):>18}")

    for name, umpx in CALIBRATIONS.items():
        opt = Optics(umpx)
        print("\n" + "=" * 74)
        print(f"CALIBRATION '{name}'  =  {umpx:.3f} um/px")
        print("=" * 74)
        print(f"  system PSF FWHM        {opt.psf_fwhm:.2f} um")
        print(f"  ArUco module floor     {opt.aruco_module():.2f} um  "
              f"-> 4x4 tag {opt.tag_um(6):.1f} um, 6x6 tag {opt.tag_um(8):.1f} um")
        print(f"  stitched field         {STITCH_PX * umpx:.0f} um")
        print("  true expansion of the six frames: "
              + "  ".join(f"{k}x->{opt.true_lambda(k):.2f}" for k in PITCH_PX))

        print("\n  pitch floor vs printed dot size:")
        for d in (CAD_DOT_UM, 1.5, 1.0, 0.5):
            print(f"     dot {d:5.3f} um -> imaged {opt.imaged_spot(d):.2f} um"
                  f" -> pitch floor {opt.pitch_floor(d):5.2f} um"
                  f"   (density vs today {(DESIGN_PITCH_UM / opt.pitch_floor(d)) ** 2:.2f}x)")

        b = budget(opt, dot_um=1.0)
        print(f"\n  RECOMMENDED V2 GEOMETRY (1.0 um dots, 5x5 boxes, DICT_4X4_50):")
        print(f"     pitch {b['pitch_um']:.2f} um | tag {b['tag_um']:.1f} um "
              f"(keep-out r={b['keepout']:.1f} um) | {b['nodes']} nodes")
        print(f"     dots {b['total']:,.0f}  ({b['vs_current']:.1f}x the current "
              f"{CURRENT_DOTS:,})")
        print(f"     footprint {b['footprint']:,.0f} um^2 = {b['fill']*100:.1f}% areal fill"
              f"   (current: 74,140 um^2 = 13.2%)")

    print("\nSensitivity: the separation rule above is 2.0x imaged FWHM (conservative).")
    print("At 1.5x -- if Phase 0c shows detection tolerates it -- every density figure")
    print("improves by 1.78x.")


if __name__ == "__main__":
    main()
