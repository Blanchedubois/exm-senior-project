# Phase 6 — Cross-image views: pair, overlay, vector field, distortion map

*Goal: the operator can compare any expanded image with the initial image and with the design:
see which features paired, the rigid overlay, the displacement vector field and a distortion
map, with uncertainty visible. These are visual checks on the data before export, not the
analysis. The V1 Summary tab is not ported.*

## 1. What to port

| V1 source | target | action |
|---|---|---|
| `rwtag/pairing.py` | `rwtag/pairing.py` | port; `pair_tags` and `pairs_xy` also carry covariances; `rigid_align` and a new `similarity_align` return parameter covariances (Phase 5 bootstrap); `displacement_field` returns the local deformation gradient per dot (§3); the `expansion_rows`, `expansion_distributions`, `write_summary_csv`, `write_distributions_csv` functions are **dropped** |
| `rwtag/refwarp/strain.py::_local_F` | `rwtag/deformation.py` | port and extend (§3) |
| `gui/pair_panel.py` | same | port; table gains sigma columns; the wide pairing export moves to Phase 7 |
| `gui/overlay_panel.py` | same | port unchanged in behaviour; box choice stays; add a "similarity (scale removed)" mode beside the rigid one |
| `gui/field_panel.py` | same | port; heat-map quantities extended (§4); vectors can be drawn in `init` or `expected` frame |
| `gui/summary_panel.py` | gone | analysis is elsewhere |
| `tests/test_pairing.py` | `tests/test_phase6_views.py` | port the synthetic cases; real-frame case replaced by dummy runs |

## 2. Pairing

Unchanged in principle: join two `TagResult.tags` dicts on identity. Each pair row now carries
`(x0, y0, C0)` in the initial's `corr` and `(x1, y1, C1)` in the expanded's `corr`. Counts per
category and per box as V1.

Because every image is tagged against the design independently, pairing is also possible
between any two expanded images, not only initial ↔ expanded. The combo offers "A ↔ B" for any
two accepted images; the default is initial ↔ selected.

## 3. Local deformation per feature

`deformation.local_gradient(P0, P1, k=8, radius_px=None)` fits, for each paired dot, the affine
`Δp1 ≈ F Δp0` over its `k` nearest paired neighbours in the initial frame (or all within a
radius). Returns per dot:

| field | meaning |
|---|---|
| `F` (2×2) | local deformation gradient initial → expanded |
| `J = det F` | areal expansion |
| `lin = √J` | linear expansion (V1's quantity) |
| `U`, `R` | polar decomposition `F = R U`: stretch tensor and rotation |
| `λ1, λ2, φ` | principal stretches and the angle of the first principal axis in the initial frame |
| `anisotropy = λ1/λ2 − 1` | direction dependence of stretch |
| `rot_deg` | local rotation |
| `resid_rms` | fit residual over the neighbours, px |
| `n_nb` | neighbours used |
| `F_cov` | covariance of the four entries of `F` from the neighbours' position covariances (weighted least squares) |

These are the per-feature quantities the proposal names (anisotropy, inhomogeneity, local
warping) in their rawest form. The tool exports them; the downstream script aggregates them.

Also computed per pair set, for the alignment and for the `expected` frame: the global
similarity initial ← expanded (`s, θ, t`) with bootstrap covariance, and the global affine.

## 4. The views

**Pair tab**: as V1. Paired dots green, unpaired grey, tags as squares with ids; the table has
`tag, x0 ± s, y0 ± s, x1 ± s, y1 ± s`.

**Overlay tab**: as V1 (cyan initial, red expanded, rigid about a common box centre, scale
untouched) plus a similarity mode where the expanded image is also scaled down by the fitted
`s`, so only the non-uniform part remains visible. Layer opacities, centre marker, PNG export.

**Field tab**, per expanded image, drawn over the initial image:

- vector field `u = p1_aligned − p0` (rigid alignment: shows growth; similarity alignment: shows
  distortion only), decimated, scaled, with an optional error ellipse per arrow at 1σ;
- heat map, quantity selectable: `lin`, `|u|`, `J`, `anisotropy`, `rot_deg`, `resid_rms`,
  principal-axis orientation `φ` (cyclic colour map), and **deviation from design** `|p_corr −
  p_expected|` of the expanded image alone;
- a "significance" overlay masking cells whose value is within 1σ of zero;
- colour bar, range readout, the V1 `heat_grid` interpolation with the unpaired-void mask.

A fourth small panel, **Series strip**: thumbnails of every accepted image's deviation-from-
design map side by side, same colour scale, so the progression with λ is visible at a glance.
This is the one place the tool compares the various images for a given series.

## 5. Tests (`tests/test_phase6_views.py`)

- V1 synthetic cases: pair join, Kabsch ignores scale, rigid align centres, overlay geometry,
  heat grid masks voids.
- `test_local_gradient_recovers_affine`: points under a known affine plus noise; `F` within 1e-3
  of truth per entry; `F_cov` brackets the error over 100 trials.
- `test_polar_decomposition`: `F = R U` with `U` symmetric positive definite; principal
  stretches equal `svd(F)` singular values.
- `test_opt_warp_field_vs_truth`: on `opt_warp` λ = 2, the recovered displacement field after
  similarity alignment correlates with the simulator's `warp_disp` truth at > 0.9 and has RMS
  error < 0.35 µm (the Phase-D gate).
- `test_clean_series_is_flat`: on `opt_clean`, `anisotropy` median < 0.002 and `|u|` after
  similarity alignment is below 2σ for 95 % of dots.
- Offscreen GUI smoke: open each tab on a dummy project; switch quantities; export an overlay
  PNG.

## 6. Acceptance

- On `opt_warp` the field tab shows the injected lobes in the distortion map and the series
  strip shows them growing with λ.
- On `opt_clean` the distortion map is flat within noise.
- Tests pass. The user has stepped through the three tabs on a dummy project.

## 7. How this serves the end goal

The per-feature `F`, its decomposition and covariance are the `local_deformation.csv` export;
the similarity and rigid fits with covariances are the `alignment_<exp>.json` export. The views
exist so that what is exported has been looked at.

## 8. As built (2026-10-14)

**Files.** New: `rwtag/deformation.py`, `gui/compare_common.py`, `gui/series_panel.py`,
`tests/test_phase6_views.py` (10), `tests/test_phase6_gui.py`. Ported and rewritten: `rwtag/pairing.py`,
`gui/pair_panel.py`, `gui/overlay_panel.py`, `gui/field_panel.py`. Changed: `gui/app.py` (tabs 5–8),
`rwtag/types.py` + `rwtag/project.py` + `gui/state.py` (Stage-1 fingerprint, below). 88 tests pass.

**Any two accepted images**, not only Initial ↔ expanded: every tab has a reference and a compared
selector (reference defaults to the Initial). Rejected images are not offered.

**Local deformation with uncertainties.** `deformation.local_gradient` fits F over the 8 nearest
paired neighbours and propagates both frames' position covariances to F's 4×4 covariance (the
shared centre point correlates the rows), then to √J, J, λ1, λ2, anisotropy, φ and rotation by
finite differences. Synthetic check: F's 95 % interval covers the truth 94.9 % of the time; λ1
z-scores have a spread of 1.00. The polar factors are named `R_rot`, `U_stretch` (a first draft's
`U` silently overwrote the displacement `U`).

**Measured on the dummy series**

| comparison | truth | recovered |
|---|---|---|
| warped λ 2 vs λ 1, distortion field | 0.93 µm RMS | error 0.046 µm, correlation 0.999, 96 % inside 95 % |
| warped λ 4 vs λ 1 | 0.54 µm RMS | error 0.043 µm, correlation 0.997, 97 % inside 95 % |
| clean λ 2, 4 vs λ 1 | none | 96 % of displacements inside their 95 % ellipses; expansion within 0.05 % |
| rigid rotation, warped λ 2 vs 1 | −3.0656° (truth, about B7) | −3.0657° ± 0.0011 |
| λ 2 ↔ λ 4 (two expanded images) | 2.0 | 2.000 within 0.5 % |

The Phase-D gate (< 0.35 µm, correlation > 0.9) is met with an eightfold margin.

**Anisotropy has a positive noise floor.** λ1/λ2 − 1 ≥ 0 by construction, so noise biases it upward:
on the undistorted series its median is 0.0046 against a per-dot σ of 0.0040 (k = 8 neighbours). Each
value is exported with its σ; the downstream analysis must treat the floor as noise, not distortion.

**Views.** Pair: shared tags with ± σ, tags as squares. Overlay: rigid (scale kept) or similarity
(scale removed), with the rotation's bootstrap σ and the removed expansion's σ. Field: similarity or
rigid alignment; vectors with optional 1 σ error ellipses; eight heat quantities (|u|, √J, J,
anisotropy, φ on a cyclic map, local rotation, warping residual, the compared image's deviation from
its design) each with its own null so cells within 1 σ of uniform expansion can be hidden (φ is hidden
where anisotropy is not significant). Series (new, replaces V1's Summary): one map per image against
the reference on one colour scale, with a table of paired dots, uniform λ ratio, median and p90.

**A bug the screenshots found: stale corrected frames.** The selected image's corrected frame had been
made before its Stage-1 parameters changed, and the batch runner reused it: the 1× frame went in with
its lens uncorrected, and every expansion ratio was off by the 1.8 % lens bias (2× read 1.953). Every
corrected frame now carries a fingerprint of the parameters that produced it
(`PipelineState.corrected_key`) and is recomputed when they differ; regression test
`test_stale_corrected_frame_is_recomputed`.
