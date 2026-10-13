# Spacing Workshop — master plan

*Three Nanoscribe designs at three dot spacings, plus one "spectrum" test print. Written
2026-09-29. Companion documents: `01_DESIGN_PARAMETERS.md` (the numbers),
`02_SPEC_SHEET_FORMAT.md` (what the recognition code reads), `03_SPECTRUM_PRINT.md` (the 4th print).*

---

## 1. What is being built

| # | folder | what | dot | spacing (centre to centre) | status |
|---|---|---|---|---|---|
| 1 | `designs/1_optimistic/` | the existing optimistic print, unchanged | 2.125 µm | **5.0 µm** | STL exists, gated |
| 2 | `designs/2_medium/` | intermediate | 2.125 µm | **6.0 µm** | to build |
| 3 | `designs/3_conservative/` | close to the reference, not equal to it | 2.125 µm | **7.0 µm** | to build |
| 4 | `designs/4_spectrum/` | test print: every box a different spacing × size | 2.125 → 4.0 µm | 5.0 → 8.9 µm | to build |
| — | *(reference, for comparison)* | `base_design_for_nanoscribe_2026_01_14.stl` | 2.125 µm | 8.0 µm | the current print |

Every folder gets: the STL (+ merged-mesh twin), a **`DESIGN_SPEC.md`** (the human-readable
design specification), a **spec sheet** (`spec_sheet.json` + `features.csv`, the machine-readable
description the recognition code is written against), a render, and its gate record.

All four keep the current envelope — **750 × 750 × 2 µm**, 5 × 5 boxes, three tiers (ArUco tags at
the 36 nodes, dashes on the box edges, dots inside) — so they drop into the same Nanoscribe job
and the same stitched field as today's print.

## 2. Decisions taken (your answers, 2026-09-29)

| | decision | consequence |
|---|---|---|
| A | **Dot = 2.125 µm, exactly the reference**, in designs 1–3 | the existing optimistic STL is kept byte for byte; only the spacing differs between the three |
| B | **Spacing 5.0 / 6.0 / 7.0 µm** | conservative sits one step inside the reference's 8.0 µm; medium is the midpoint |
| D | **ArUco tags stay the same size (23 µm) in every design — only the dot spacing changes** (2026-09-29) | tags, ids, node positions and all 480 dashes are identical in the three designs and the spectrum print; the designs differ in the dot lattice and nothing else. Cost: a 23 µm tag decodes reliably only to a blur of ~2.6 µm, while conservative's dots tolerate 3.4 µm (`01` §3) |
| C | **Spectrum: spacing left → right, size top → bottom**, optimistic top-left, conservative bottom-right | the spectrum print is where dot sizes of 3 µm and above get tested on the real gel |

**A note on the dot size.** The reference STL was measured directly (6,424 dots): its grid dots are
**2.125 µm squares at 8.0 µm spacing**, not 3 µm. What looks like ~3 µm on the microscope is the
2.125 µm dot *after* the blur (2.125 µm convolved with a ~2.7 µm PSF is a ~3.4 µm spot). So "the
reference dot size" and "3+ µm" are two different things; decision A keeps the printed size, and
the spectrum print tests whether *printing* 3 µm and above is better.

**One thing I resolved on your behalf — please confirm.** Your dot-size answer said "2.125 µm
everywhere", your spectrum answer said "size top to bottom". I have read that as: designs 1–3 use
2.125 µm only; the spectrum print varies size, with 2.125 µm as its top row.

## 3. Open decisions (defaults chosen; say if you want otherwise)

| | question | default | why |
|---|---|---|---|
| D1 | In the spectrum, is "spacing" the centre-to-centre pitch or the **gap between dot edges**? | **gap** — built this way in S5 | With centre pitch, a 4 µm dot at 7 µm pitch leaves a 3 µm gap and is *harder* to resolve than the optimistic corner — the bottom-right would not be conservative. With gap, every row has about the same resolvability and bottom-right is the safest box on the print. Top row is identical either way (5.0 → 7.0 µm pitch). See `03_SPECTRUM_PRINT.md` §2. |
| ~~D2~~ | ~~Tag size in each design~~ | **closed by decision D: 23 µm in all** | — |
| ~~D3~~ | ~~Tag size on the spectrum print~~ | **closed by decision D: 23 µm** | — |
| D4 | Dot sizes on the spectrum rows | 2.125 / 2.5 / 3.0 / 3.5 / 4.0 µm | starts at the reference, brackets "3+" on both sides |
| D5 | Spec-sheet format | JSON (parameters) + CSV (every feature) | JSON loads in one line in Python/MATLAB; CSV opens in Excel |

## 4. Phases

Each phase ends at a gate and stops for your review, as before.

| phase | deliverable | gate | where |
|---|---|---|---|
| **S0** | this plan + the three companion documents; parameters frozen | you confirm §2 and §3 | `designs/docs/` — **done** |
| **S1** | generator extensions: spacing given directly (not derived from a PSF); per-box dot size and spacing (for the spectrum); spec-sheet emitter | existing three CAD files rebuild **bit-identical**; unit checks on the new options | `tools/aruco_grid.py`, `tools/spec_sheet.py`, `tools/spectrum_layout.py`, gate `tools/s1_gate.py` — **done 2026-09-29, 14/14** (`docs/S1_gate.json`) |
| **S2** | designs 1–3 built into their folders: STL, merged STL, tag map, ids, spec sheet, render | Phase-A gate on each (exact geometry, render round-trip, all 36 tags decode, extent exactly 750); optimistic identical to the existing file | `designs/1_…`, `2_…`, `3_…`, builder `tools/build_designs.py` — **done 2026-09-29, all three PASS** (`docs/S2_gate.json`) |
| **S3** | **recognition test** — each design imaged through the camera model at a ladder of blur (PSF 1.5 → 4 µm) and expansion (1 → 6×), run through the production pipeline | per design: the worst blur at which ≥ 90 % of dots are still recognised and every frame registers — *measured*, to replace the predicted column in `01` §2 | `designs/docs/S3_RECOGNITION.md` + one figure per folder — **done 2026-09-29**: fully recognised to 2.7 / 3.1 / 3.4 µm blur; 23 µm tags decode ≥ 95 % to 3.4 µm; 432 / 432 frames register |
| **S4** | **printability check** — smallest gap and feature against the 2PP limits, write-time estimate, mesh checks, single-box test files for a DeScribe dry run | zero overlaps, zero sub-limit gaps; write time stated relative to the reference | `designs/docs/S4_PRINTABILITY.md` — **done 2026-09-29, all three PASS**: tightest gap 2.875 µm (reference 1.5), write time 1.40 / 1.03 / 0.80 × the reference, merged meshes rebuilt manifold; DeScribe dry run of `test_box*.stl` is yours |
| **S5** | the spectrum print: STL, tag map, **per-box spec sheet**, render with every box labelled, and the analysis script that reads a real image of it and reports, per box, how many dots were recognised | Phase-A gate; synthetic run of the analysis script recovers the known answer | `designs/4_spectrum/` — **done 2026-09-29** (`docs/S5_SPECTRUM.md`): 9,244 dots in 25 boxes, build gate PASS; the analysis script names the same design as the truth at every test blur |
| **S6** | `DESIGN_SPEC.md` for each folder, a top-level `README.md` comparing the four, final figures | every number in every document traceable to a file in its folder | all four folders — **done 2026-09-29**: `DESIGN_SPEC.md` × 4, `designs/README.md`, `designs/comparison.png`, written by `tools/write_design_specs.py` from the folders' own files (`docs/S6_gate.json`) |
| **L1** *(lab)* | print the spectrum, image it at each expansion | the per-box table from S5's script | yours |
| **L2** *(lab)* | print whichever of designs 1–3 the spectrum result selects | — | yours |

**Order and dependencies.** S1 → S2 → (S3, S4 in either order) → S5 → S6. S5 needs S1 but not
S2–S4, so it can be pulled forward if you want the test print in hand first.

## 5. What already exists and is reused

- `tools/aruco_grid.py` — the generator and its gate (Phase A). Designs 1–3 are three settings
  of it; the spectrum needs the per-box extension (S1).
- `tools/simulate_v2.py`, `tools/phase_c_verify.py`, `tools/phase_d_end_to_end.py` — the camera
  model and the truth-scored pipeline tests. S3 is these, swept over blur.
- `Reference_Warp_Tagger/rwtag/aruco/` — the recognition code. The spec sheets are written so
  that this code, or any new code, can be configured from them alone.
- `workshop/scripts/w11_print_budget.py` — overlap, mesh and write-time checks for S4.
- The earlier HEDGE (5.74 µm) and SAFE (6.69 µm) prints stay in `cad/` untouched; MEDIUM and
  CONSERVATIVE here are new builds at the round spacings you chose.

## 6. Risks carried into this workshop

| risk | where it is handled |
|---|---|
| Optimistic (5.0 µm) only resolves if the blur is brought down to ~1.9 µm | S3 measures it; the spectrum print (L1) settles it on the real microscope |
| Dots larger than the reference have never been printed in this gel | spectrum rows 2–5 |
| Signal falls as λ⁻¹·⁸⁴ — exposure must rise as λ² for *any* of these prints | unchanged from Rev D; stated in every `DESIGN_SPEC.md` |
| Effective pixel size still uncalibrated (0.510 assumed) | every pixel figure in the spec sheets is stored alongside the µm value and the assumed µm/px, so a recalibration is one number |
