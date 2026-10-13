# Phase 5 — The error model: uncertainty on every position and rotation

*Goal: every detected feature carries a position covariance; every tag carries a rotation
uncertainty and a decode confidence; both are propagated through the optics correction, the
alignment to the initial image and the mapping to the design frame, so every exported position
has an error beside it. The model is validated against repeat-noise dummy frames.*

## 1. Sources of error, and which are modelled

| source | affects | modelled how |
|---|---|---|
| photon shot noise and read noise in the dot's pixels | dot centre | closed-form localisation bound (§2.1) |
| pixelation and PSF mismatch of the Gaussian model | dot centre | empirical scale factor from the repeat-frame test (§2.3) |
| corner refinement noise | tag corners, centre, rotation | `cornerSubPix` residual covariance (§2.2) |
| decode ambiguity | tag identity | `(n_bits_corrected, margin_bits)` from Phase 1, carried as a confidence class |
| lens un-distortion resampling, rotation resampling | all positions in `corr` | Jacobian propagation only; the resampling error is below the localisation floor (W8: 0.22 µm end-to-end vs 0.04 isolated) and is absorbed by the empirical factor |
| warp fit (TPS) | residuals, not positions | the TPS residual is reported as a QC number, not folded into the position error |
| alignment initial ← expanded | positions in `init` | covariance of the fitted rigid or similarity parameters by bootstrap over pairs (§3.2) |
| un-modelled gel physics | everything | **not** an error; it is the signal. Nothing here subtracts it |

## 2. Per-feature uncertainty

### 2.1 Dots

For a Gaussian spot of width `s` (px, from the fitted or design-predicted sigma), pixel size
`a = 1`, integrated signal `N` photons and background `b` photons per pixel, the localisation
variance per axis (Thompson, Larson & Webb 2002, with Mortensen's correction factor for
least-squares fitting) is

```
σ² = (s² + 1/12) / N  +  8π s⁴ b² / N²       (per axis, px²)
```

`N = dot_signal_adu × gain_e_per_adu`, `b = dot_bg_adu × gain_e_per_adu` where `dot_signal`
and `dot_bg` are the per-dot values Phase 3 records. If `gain_e_per_adu` is unset in the
metadata, `gain = 1` is used and the covariance is flagged `relative = true` in the export: the
*ratios* between dots are right, the absolute scale is not.

Covariance in `corr`: `diag(σ², σ²)`, then scaled by the empirical factor `κ²` from §2.3 (one
number per image, default 1.0 until calibrated). Off-diagonal is zero for an isotropic PSF.

### 2.2 Tags

`cv2.cornerSubPix` converges each corner to the saddle of the local gradient structure. Its
covariance is estimated from the inverse of the structure tensor `Σ ∇I ∇Iᵀ` over the refinement
window times the local noise variance, the standard Förstner estimate. With four corners each
carrying a 2×2 covariance `C_k`:

- centre covariance `C_c = (1/16) Σ C_k`;
- side vectors `e₁ = TR − TL`, `e₂ = BR − TR`; rotation `θ = atan2(e₁)` averaged with the
  perpendicular of `e₂`; `σ_θ²` by linear propagation of `C_TL, C_TR, C_BR, C_BL` through
  `atan2`, in degrees;
- `side_px` sigma likewise, giving the print-scale uncertainty per tag.

Decode confidence class: `clean` (0 bits corrected, margin ≥ 2), `corrected` (1 bit, margin
≥ 2), `ambiguous` (margin ≤ 1, excluded from registration and pairing but still exported with
the class).

### 2.3 Calibration against repeat frames

The `opt_noise` dummy run has ten noise realisations of the same geometry at λ = 1, 2, 4. For
each feature present in all ten, the empirical covariance of its ten positions is the ground
truth for the model:

- fit `κ` per λ so that the median over dots of `trace(C_model) / trace(C_empirical)` equals 1;
- report the spread of that ratio (should be within ×2 for 90 % of dots);
- check the tag rotation sigma the same way.

`κ` is stored in `ArucoParams.loc_error_scale` and in the manifest. On real data the same
procedure runs on any set of repeat exposures of a static sample (the proposal's "control images
of static gels"), through a "Calibrate error model from repeat images…" action in the Detect
tab that takes a folder of frames, detects them, and sets `κ`.

## 3. Propagation

### 3.1 Between the image frames

A position with covariance `C` under a differentiable map `f` becomes `J C Jᵀ`.

- `corr → raw`: `J` from `correct.geometric_jacobian` (Phase 2).
- `corr → init` by a rigid map `p' = R p + t`: `J = R`.
- `corr → init` by a similarity `p' = s R p + t`: `J = s R`, plus the term from the parameter
  uncertainty (§3.2).
- `corr → design` (µm, y-up) by the inverse of the fitted similarity: `J = (1/s) Rᵀ F` with `F`
  the reflection.

### 3.2 Alignment uncertainty

The rigid and similarity fits initial ← expanded are least-squares over the paired dots. Their
parameter covariance `C_θ` (over `θ, t_x, t_y[, s]`) is estimated by bootstrap: 200 resamples
of the pair set, refit, sample covariance. For each mapped point the alignment contribution is
`J_θ C_θ J_θᵀ` with `J_θ = ∂p'/∂θ` evaluated at that point; it is added to `J C Jᵀ`. Both terms
are exported separately (`sxx_feat`, `sxx_align`) so the downstream script can choose.

### 3.3 Deviation from design

`deviation = p_corr − p_expected` where `p_expected = similarity(design)`. Its covariance is
`C_feat + J_θ C_θ J_θᵀ`. A deviation is "significant" when its Mahalanobis distance exceeds 3;
that flag is exported as a convenience, not a decision.

## 4. Data structures

Phase 3's `DetectResult` and Phase 4's `FilterResult` / `TagResult` gain parallel arrays:
`dot_cov (N,3)` as `(sxx, syy, sxy)`, `tag_cov {id: {centre (2,2), corners (4,2,2), rot_sigma_deg,
side_sigma_px, decode_class}}`. `TagResult.cov = {tag: (sxx, syy, sxy)}` in `corr`.

`rwtag/errors.py` holds: `dot_localisation_cov`, `corner_cov`, `tag_pose_cov`, `propagate`,
`bootstrap_alignment_cov`, `calibrate_kappa`.

## 5. GUI

- Tag tab: "Colour by sigma" view (point size or colour by `√trace(C)`), and the readout shows
  `tag · x ± sx · y ± sy · (rot ± sr for tags)`.
- Detect tab: the calibration action from §2.3 and a display of the current `κ` and gain.
- Metadata dock: `gain_e_per_adu` highlighted when unset, with the "relative errors" warning.

## 6. Tests (`tests/test_phase5_errors.py`)

- `test_thompson_formula`: a rendered Gaussian spot with Poisson noise at known `N, b, s`;
  10,000 realisations; empirical variance within 15 % of the formula.
- `test_corner_cov_matches_repeat`: on `opt_noise`, per-tag centre and rotation empirical
  covariance within ×2 of the model for 90 % of tags.
- `test_kappa_calibration`: `calibrate_kappa` on `opt_noise` returns `κ` in [0.7, 2.0] and after
  scaling the median ratio is 1 ± 0.1.
- `test_propagation_is_consistent`: push a cloud of points with covariances `corr → raw → corr`;
  recovered covariances equal the originals to 1e-6.
- `test_alignment_bootstrap`: two dummy frames related by a known rigid motion plus noise; the
  bootstrap covariance of `θ` brackets the true error over 50 trials.
- `test_mahalanobis_flag_rate`: on `opt_clean` (no warp), fewer than 1 % of deviations are
  flagged significant; on `opt_warp`, the flagged set correlates with `|w_true| > 3σ`.

## 7. Acceptance

- Every exported position in Phases 6 and 7 has a covariance; tags have rotation sigma and a
  decode class.
- The repeat-frame calibration runs on `opt_noise` and the tests pass.
- The user has seen the sigma view on a dummy frame and the calibration action.

## 8. How this serves the end goal

The downstream distortion analysis needs to separate gel deformation from measurement noise.
This phase supplies the noise half, per feature, in every frame the positions are reported in,
and keeps the alignment's own uncertainty separate so it can be included or not.
