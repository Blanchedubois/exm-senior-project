# Hydrogel Warpage Marker System — Analysis Package

A marker system for measuring the **local distortion (warpage) of an expanding hydrogel**
as a displacement/strain vector field, imaged under a microscope, with markers written by
**Nanoscribe two-photon polymerization (2PP)**.

**Architecture:** the field is tiled into *boxes*. A **6×6 ArUco tag** sits at every box
corner (its ID encodes the box address). Each box interior is filled with a **fine dot grid**
(the dense local-distortion measurement). ArUco IDs solve correspondence globally, so the
pattern is trackable through 2–5× expansion from a single before/after image.

Generated 2026-07-15/16.

---

## How to run

```bash
pip install opencv-contrib-python numpy matplotlib
python3 scripts/generate_pattern.py        # build the pattern + ground-truth JSON
python3 scripts/simulate_expansion.py       # expansion + rotation + warp robustness
python3 scripts/simulate_rigid_spread.py    # rigid islands spread -> field recovered
python3 scripts/simulate_module_spread.py   # naive "every module separate" (fails)
python3 scripts/simulate_conjoined_spread.py # conjoined model + connected-ID scan
python3 scripts/conjoined_markers.py        # curate IDs, struts, conjoined distortion map
python3 scripts/strut_prominence.py         # smooth strut + how prominent it may be
python3 scripts/blur_resolution.py          # optical-blur / low-resolution test
python3 scripts/multi_marker_test.py        # many different curated tags under blur
```

All geometry is in microns; scripts are parameterized at the top (box size, tag size,
dot pitch, resolution). Every script prints a summary and writes its figures.

---

## Key findings (see FINDINGS.md for detail)

- **Correspondence is free.** Uniform expansion + whole-grid rotation is a similarity
  transform; ArUco is invariant to it — tags decode however far they spread, at any angle,
  to 5×+ (`simulate_expansion.py`).
- **A rigid tag must stay ONE connected piece.** If its black fragments into separate
  drifting squares it fails almost immediately (`simulate_module_spread.py`,
  `simulate_conjoined_spread.py`).
- **Fix 1 — choose connected IDs.** 954/1000 IDs of DICT_6X6_1000 have single-8-connected
  black (`conjoined_ids.json`); these behave as rigid islands and decode at any expansion.
- **Fix 2 — smooth diagonal struts.** A thin elliptical neck (~0.2 µm) at each corner pinch
  ties everything into one piece; it lives in ArUco's ignored sampling margin so the code is
  unchanged. Usable width window ~0.2–0.68 µm, limited by printability, not recognition
  (`strut_prominence.py`).
- **Optical blur.** Tags decode until the PSF σ reaches ~0.3–0.5 of a module. Rule: keep one
  module ≥ ~2.5× the PSF σ (tag ≥ ~8× FWHM). A 6 µm tag tolerates FWHM up to ~0.5 µm —
  confocal easily, most widefield. Uniform across 250 tested tags, no weak IDs
  (`blur_resolution.py`, `multi_marker_test.py`).
- **Measurement works end-to-end.** From a warped conjoined grid, all markers decode and the
  displacement/warpage field + per-box areal expansion J are recovered
  (`rigid_spread_field.png`, `conjoined_distortion_map.png`).

---

## Contents

```
docs/    hydrogel_marker_system_design.md   full design document (Rev C)
         marker_grid_schematic.svg          architecture schematic
         FINDINGS.md                        consolidated simulation findings
scripts/ *.py                               all generators and simulations
data/    pattern_metadata.json              ground-truth undeformed feature coords
         conjoined_ids.json                 curated connected ID lists
figures/ *.png                              all result figures
```
