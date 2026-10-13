# Phase D — the whole V2 pipeline against injected truth

*2026-09-22. Gate: `tools/phase_d_end_to_end.py` → `docs/phase_d_end_to_end.{png,json}`, log in
`docs/phase_d_run.log`.*

**Result: PASS for all three candidates.** From a reference frame and five expanded frames
(λ 1.5–6) the production path — `rwtag.aruco.series` → tags by identity → pairing — recovers the
expansion factor to **−0.019%** at every λ, the injected non-uniform deformation field to
**0.01–0.06 µm RMS** (correlation 0.999 against a 0.4–1.0 µm field), and the Green-strain field at
R = 25 µm to **≤ 0.0005** against a true field of 0.004–0.006. **Pipeline bias and gel physics
separate cleanly**: the pipeline's error is a constant −0.02%; the −0.18% … +0.13% swing that a
naive "recovered λ / nominal λ" would report is the gel — the mean dilation of the injected warp
inside the shrinking field of view.

---

## 1. Set-up

Phase C scored *positions* (every dot's tag and centre). Phase D scores what the app *reports*:
λ and the deformation field, derived from paired frames the way the pairing / strain stages
derive them.

- **Reference:** λ = 1, **no warp** (W8: the simulator's warp is a print distortion applied in
  every frame, so it must be off in the reference for a between-frame test), rotation 2°, drift.
- **Expanded:** λ ∈ {1.5, 2, 3, 4, 6}, warp `w(X)` (14 Gaussian lobes, 2 µm, σ 90 µm) so that
  `x′ = R[λ(X + w(X))] + t`; rotation +3° per step, fresh drift per frame; exposure fully
  compensated (W6); L2 noise; lens + vignette; Stage-1 un-distortion + flat-field.
- **Pipeline:** `process_frames` (6 frames, 1.5–2.3 s) → `pair_tags(ref, exp, kinds=("dot",))`;
  per frame a similarity design→expanded through all paired dots (allowing the reflection —
  see §3), its residual = recovered `w`, local affine over R = 25 µm → Green strain on the
  de-expanded field (Rev C/D: affine de-expansion first, then `F`, `E`), plus
  `rwtag.refwarp.strain.strain` — the number the app's summary tab shows.
- **Truth through the same estimator.** A random lobe field has a non-zero mean gradient, so the
  similarity that best fits the *true* positions is not exactly λ: `λ_eff = λ·(1 + mean dilation
  in view)`. Pipeline error is `λ_rec/λ_eff − 1`; the gel's contribution is `λ_eff/λ − 1`. The
  same holds for the field: recovered and true non-similarity parts are compared on the same dots.

## 2. Numbers

`paired` = dots paired by identity / in-frame truth · `pipe err` = λ_rec/λ_eff − 1 ·
`gel` = λ_eff/λ − 1 · `app λ` = `strain.strain()` mean (local, k = 8) · `w true / w err` = RMS of
the true non-uniform field over the paired dots / RMS of (recovered − true), design µm ·
`E true / E err` = RMS Green strain (de-expanded, R = 25 µm) / RMS error · `N@25` = dots per window.

| print | λ | paired | λ rec | λ eff | pipe err | gel | app λ | w true | w err | corr | E true | E err | N@25 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **OPT** | 1.5 | 17,823 / 17,825 | 1.4974 | 1.4977 | −0.019% | −0.15% | 1.499 | 0.959 | 0.047 | 0.999 | 0.0057 | 0.0004 | 68 |
| | 2 | 13,267 / 13,828 | 1.9960 | 1.9964 | −0.019% | −0.18% | 1.998 | 0.939 | 0.036 | 0.999 | 0.0059 | 0.0003 | 64 |
| | 3 | 5,874 / 6,114 | 2.9970 | 2.9976 | −0.019% | −0.08% | 2.997 | 0.662 | 0.024 | 0.999 | 0.0053 | 0.0002 | 64 |
| | 4 | 3,300 / 3,445 | 4.0003 | 4.0010 | −0.019% | +0.03% | 4.000 | 0.569 | 0.018 | 1.000 | 0.0048 | 0.0002 | 57 |
| | 6 | 1,360 / 1,399 | 6.0057 | 6.0067 | −0.018% | +0.11% | 6.009 | 0.430 | 0.012 | 1.000 | 0.0043 | 0.0001 | 53 |
| **HEDGE** | 1.5 | 12,812 / 12,825 | 1.4974 | 1.4977 | −0.019% | −0.16% | 1.500 | 0.959 | 0.051 | 0.999 | 0.0057 | 0.0004 | 58 |
| | 6 | 968 / 997 | 6.0059 | 6.0070 | −0.019% | +0.12% | 6.011 | 0.429 | 0.013 | 1.000 | 0.0042 | 0.0001 | 47 |
| **SAFE** | 1.5 | 8,361 / 8,625 | 1.4974 | 1.4976 | −0.019% | −0.16% | 1.500 | 0.959 | 0.058 | 0.998 | 0.0057 | 0.0005 | 43 |
| | 6 | 602 / 664 | 6.0068 | 6.0079 | −0.019% | +0.13% | 6.014 | 0.430 | 0.015 | 0.999 | 0.0039 | 0.0001 | 37 |

(Full table for HEDGE and SAFE in `phase_d_run.log`; every row lies between the ones shown.)

Reading it:

- **λ.** The pipeline recovers λ_eff to −0.019% on every frame of every print — a constant, i.e.
  a scale offset of 2 × 10⁻⁴ somewhere between render and un-distortion, far below anything
  that matters (the V1 question was a +6.5% drift). What *does* move with λ is `gel`: −0.18% at
  2× to +0.13% at 6×, the mean dilation of the injected field over whatever part of the pattern
  is in view. A pipeline that compared recovered λ with nominal λ would call that a bias; it is
  the measurement. **The app's `strain.strain()` mean agrees with λ_rec to 0.1%** (it is a local,
  k = 8 estimator on a warped field, so it carries a little of the field's own variance).
- **Warp field.** Recovered to 0.012–0.058 µm RMS in design units, 1–6% of the field's own RMS,
  correlation 0.998–1.000, and *improving* with λ — the same 0.25 px centre noise (Phase C) is
  0.13 µm at 1× and 0.02 µm at 6× once divided by λ. Density buys nothing here because the field
  (σ = 90 µm) is smooth on the dot-pitch scale; it buys resolution in the strain windows below.
- **Strain.** With de-expansion first, the Green-strain error at R = 25 µm is 0.0001–0.0005
  against a true field of 0.004–0.006: the field is recovered at 10–40× signal-to-error. OPT
  holds 53–68 dots per window, SAFE 37–43; both are well conditioned at this radius — W8's
  density argument bites below R ≈ 20 µm, which this test does not probe.
- **Pairing.** Identity pairing reaches W9's detection efficiency exactly (100% of *detected*
  dots pair; 91–100% of in-frame truth, the shortfall being crowding losses at the 1.75× rule).
  SAFE's 91% at 6× is inside W9's PASS floor of 90%.

## 3. The bug it caught — the same one, again

The first run reported λ_rec ≈ 0.001 at every level, a "−99.9% error", with the warp and strain
numbers absurd. The similarity estimator (Umeyama) was constraining `R` to a proper rotation, and
design (y-up) → image (y-down) *is a reflection*. This is the fifth time the handedness has bitten
in this workspace (0d Kabsch, Phase B rotation matrix, W8 shear, Phase C fit). The estimator now
allows det R = −1 and the gate checks that it *is* −1 on every frame. The rule for Phase E/F
code: **any design↔image fit must either flip y explicitly at the boundary or permit a reflection,
and must assert the sign it finds.** `rwtag.pairing.kabsch_rotation` (image↔image, where no
reflection should occur) is unaffected.

The second finding was in the scoring, not the pipeline: comparing the recovered field with the
raw injected `w` gave 0.6–0.9 µm "errors" and correlations of 0.45–0.87, because the similarity
absorbs the linear part of the field and the field of view shrinks with λ. Truth must go through
the same estimator on the same dots — then the numbers above appear. And Green strain must be
computed on the *de-expanded* field, or its error grows as λ² and no fixed gate makes sense.

## 4. Gate

| check | OPT | HEDGE | SAFE |
|---|---|---|---|
| \|λ pipeline error\| < 0.5% at every λ | ✅ 0.019% | ✅ 0.019% | ✅ 0.019% |
| warp RMS error < 0.35 µm and corr > 0.9 | ✅ ≤ 0.047 / 0.999 | ✅ ≤ 0.051 / 0.999 | ✅ ≤ 0.058 / 0.998 |
| strain RMS error (R = 25 µm, de-expanded) < 0.006 | ✅ ≤ 0.0004 | ✅ ≤ 0.0004 | ✅ ≤ 0.0005 |
| ≥ 90% of in-frame truth paired by identity (W9 floor) | ✅ 96–100% | ✅ 96–100% | ✅ 91–97% |
| design → image handedness −1 on every frame | ✅ | ✅ | ✅ |
| **Phase D** | **PASS** | **PASS** | **PASS** |

**What Phase D says about V1's +6.5% at 4.2×:** on this pipeline the expansion factor carries no
λ-dependent bias at all (−0.02%, flat). If the real series shows a drift, it is the gel (or the
pixel size, R1) — not the tagging. The remaining desk-side item is the GUI's V2 mode; everything
else now waits on the microscope (Phase 1) and the coupon (Phase 6).
