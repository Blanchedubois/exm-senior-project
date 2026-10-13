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
