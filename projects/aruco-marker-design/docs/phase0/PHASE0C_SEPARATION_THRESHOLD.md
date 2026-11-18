# Phase 0c — Dot separation threshold

**Status: DONE (2026-09-22)** · Tool: `tools/separation_threshold.py` · Raw: `sep_threshold_*.json`, `sep_threshold_run.txt`

**Question.** `IMPLEMENTATION_PLAN.md` §2.3 assumed a dot pitch of **≥ 2.0 × the imaged-spot
FWHM**. That multiplier was a guess, and every density figure in the plan scales with it.
Measure it against the real detector instead.

**Answer.** **1.60 × FWHM** in the binding (dense reference) frame, degrading to **2.27 ×** in a
sparse frame. **Adopt 1.75 ×** as the design rule — see §4.

---

## 1. Method

Empirical, no Gaussian assumption anywhere:

1. Detect dots in a real Stage-1-corrected frame.
2. **Build a dot template** by subpixel-aligning and averaging 400 *isolated* real dots. This
   carries the true PSF, amplitude and profile shape.
3. **Harvest genuine empty-background tiles** from the same frame.
4. For each trial separation, **splice a synthetic patch into the real frame**: pairs of
   templates at random orientation, added in intensity over a real background bed. Splicing
   rather than testing a standalone patch matters — `lattice.detect_dots` thresholds with a
   **global Otsu**, so the surrounding frame must be authentic.
5. Run `lattice.detect_dots` with the exact pipeline parameters (`tophat=15`,
   `dot_area=(30,220)`) and score each site: 2 detections, 1, or 0.

**Control.** Sites with a *single* dot measure the detector's per-dot efficiency. Pair
resolution can never exceed efficiency², so this is the ceiling every rate is normalised
against. Without it the first version of this test appeared to plateau at 88% and looked like a
resolution limit; it was simply detection efficiency. The plateau now sits at ~100% of ceiling,
which is what validates the method.

361 sites per separation, 21 separations, two frames.

---

## 2. Results

| Frame | Real dots | Per-dot efficiency | Ceiling | **95%-of-ceiling threshold** |
|---|---|---|---|---|
| **1.5×** (dense) | 2,902 | 93.4% | 87.1% | **12 px = 1.60 × FWHM** |
| **4.2×** (sparse) | 321 | 95.3% | 90.8% | **17 px = 2.27 × FWHM** |

Localisation at the working point: **RMS ≈ 0.25 px** (clean matches), equal to the isolated
single-dot control — so resolving a close pair costs *yield*, not *precision*.

### 2.1 Three regimes, not two

The transition is sharp and has more structure than expected (1.5× frame):

| Separation | both | one | none | What happens |
|---|---|---|---|---|
| 4–10 px (0.5–1.3 ×) | ~1% | ~85% | ~14% | **fused into one blob that passes the filters** — a single detection, mis-placed by 2–3 px |
| 11 px (1.47 ×) | 27% | 12% | **60%** | elongated blob fails aspect/extent → **both dots rejected** |
| ≥ 12 px (1.60 ×) | ~90% | ~6% | ~4% | two clean centroids, RMS 0.20–0.44 px |

**This corrects what I wrote when scoping the test.** I predicted the `max_aspect=1.7` filter
would reject merging pairs before they could produce a biased centroid, so over-dense dots would
only cost yield. That is true only in the narrow 1.4–1.6 × band. Below ~1.4 × the fused blob is
round enough to pass every filter and yields **one confident, wrong point** — which no
downstream filter can recover, and which would silently corrupt a deformation field.

Packing dots below the threshold is therefore worse than merely wasteful. It is actively unsafe.

### 2.2 The threshold is frame-dependent — and that is a software defect

1.60 × vs 2.27 × is a 40% spread between two frames of the *same sample on the same
microscope*. The cause is `detect_dots` using a **global Otsu threshold**: the 4.2× frame
contains 9× fewer features, so Otsu lands differently and marginal blobs fall out.

This is worth fixing independently of the V2 print. A local/adaptive threshold (or an
Otsu computed over a feature-rich window) should collapse the spread toward the 1.60 × figure
in every frame — which would be worth a further **(2.27/1.60)² = 2.0×** in usable dot density at
the sparse end, for a software change and no fabrication.

**→ Recommend adding this as Phase C-1.**

---

## 3. Why 1.60 × is the binding number

V2 dots are most tightly packed in the **reference frame** — the lowest-λ, densest, brightest
image. As the gel expands, spacing grows and the constraint relaxes monotonically. The dense
1.5× frame is therefore the correct binding case, and the sparse 4.2× result is a caution about
detector behaviour rather than a constraint on pitch.

---

## 4. Recommendation: adopt **1.75 ×**

Not the measured 1.60 ×, for three reasons:
- ~10% margin over a single measurement on one sample;
- the 4.2× frame shows the detector can behave worse than 1.60 × under conditions we do not yet
  fully control (§2.2);
- the sub-threshold failure mode is *silent corruption* (§2.1), so the asymmetry of risk
  strongly favours margin.

Revisit 1.60 × once the adaptive-threshold fix lands.

## 5. Impact on the plan

| | Pitch | Dots | vs today |
|---|---|---|---|
| **Conservative calibration (0.510 µm/px)** | | | |
| assumed 2.00 × | 6.67 µm | 12,213 | ×1.9 |
| **measured 1.75 ×** | **5.83 µm** | **15,952** | **×2.5** |
| **Optimistic calibration (0.381 µm/px)** | | | |
| assumed 2.00 × | 4.31 µm | 29,742 | ×4.6 |
| **measured 1.75 ×** | **3.77 µm** | **38,847** | **×6.1** |

A **+31% dot yield** over the plan's assumption, at zero cost — the assumption was simply
conservative.

**Strain-noise check.** Localisation 0.25 px = 0.129 µm (conservative) or 0.096 µm (optimistic).
Across a nearest-neighbour baseline that is ~3.1–3.6% per pair — high, but per *pair*. Fitting a
local affine over a window of N dots scales the noise as 1/√N, so the denser lattice buys back
precision or spatial resolution, chosen in software. This is the argument for density; it does
**not** work if pitch drops below threshold, because §2.1 corruption is not zero-mean.

---

## 6. Reproduce

```bash
cd aruco-marker-design/tools
python separation_threshold.py --frames 1.5,4.2
```

~4 min. Needs the `reference-warp-tagger` venv (it imports `rwtag`) and the six stitched frames.

## 7. Still open in Phase 0

- **0a — effective pixel size.** Still the gating 2.4× ambiguity. Unaffected by this result:
  everything above is in FWHM units and converts cleanly once 0a lands.
- **0b — PSF origin** (NA-limited vs defocus). If defocus, the imaged FWHM shrinks and *every*
  pitch above shrinks with it.
