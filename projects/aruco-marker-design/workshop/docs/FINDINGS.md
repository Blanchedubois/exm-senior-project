# Consolidated Findings — Rev D Workshop

*One entry per script, in the format of `hydrogel_marker_analysis/docs/FINDINGS.md`. Numbers are
from the scripts named; figures are in `../figures/`.*

---

## W0 — Candidate matrix (`w0_candidate_matrix.py`)

Nine candidates over PSF ∈ {3.18, 2.50, 1.91} × box grid {5×5, 4×4, 3×3} × dot {2.125, 3.0},
all built with the real generator so dot counts are exact. **PSF is the only lever that
matters**: 3.18 → 1.91 µm doubles the dots (8.6k → 17.8k); box grid moves it ±12%; 3 µm dots
double SNR at 6× but cost 40% of the dots and are only needed if exposure cannot scale with λ²
(uncompensated SNR at 6× = 2.1, under the Rose limit). `DICT_4X4_50` is the right dictionary
(43 strut-free IDs for 36 nodes; AprilTag 16h5 has only 27). Three candidates carried forward:
**SAFE** (A), **HEDGE** (D), **OPT** (F).

## W1 — Tag size vs blur, in-scene (`w1_tag_size_sweep.py`, `tag_size_sweep.png`)

**The decoder, not the scene, was the "2× in-scene penalty" seen in Phase B.** Isolating the
scene effects one at a time showed *centre* tags failing more than *edge* tags (4% vs 40% at
PSF 3.18) — the opposite of what vignette or lens distortion can do. The cause was the CLAHE
step inherited from the V1 simulator: over a dense dot field it re-maps the local histogram
until ArUco's dark modules are no longer dark. Replacing it with plain inversion took a 36 µm
tag at PSF 3.18 from 28% to **100%**. ArUco's own adaptive threshold needs no help.
*`simulate_v2.decode()` no longer uses CLAHE, and the Phase-C detector must not either.*

With the decoder fixed, all 36 IDs decoded in the worst-case placement (pattern corners in the
frame corners, vignette, barrel distortion + un-distortion, 2° rotation, real dot crowding,
L2 noise, 2 seeds), `DICT_4X4_50`:

| PSF (µm) | 1.5 | 1.91 | 2.5 | 3.18 | 3.5 |
|---|---|---|---|---|---|
| smallest tag ≥ 95% | ≤ 18 | ≤ 18 | 21 | 27 | 30 |
| module / PSF | (≤ 2.0) | (≤ 1.57) | 1.40 | 1.42 | 1.43 |

**Practical rule: module ≥ ~1.45 × PSF FWHM** (the 18 µm floor of the sweep censors the two
lowest PSFs). Phase B's 1.8× was CLAHE-inflated. **This corrects Phase B's headline** — "tags
were half the size they needed" — which over-corrected: the original 20.3 µm conservative tag
was *marginal* at PSF 3.18 (74% at 21 µm), not unusable, and 36 µm was ~30% larger than
necessary. The right SAFE size is 27–30 µm.

**Margin check** (geometry built for the design PSF, imaged at design and at 1.2× design):
every candidate passes at the Phase-B sizes — OPT 21 µm: 99% at 1.91, 94% / 33 tags at 2.29;
23 µm: 100% / 36; HEDGE 27 µm: 100% / 36; SAFE 35 µm: 100% / 36. **Adopted: tag = 6 × 1.75 ×
PSF** (the 1.45 minimum sized for a PSF 20% worse than design) → **OPT 21 (23 for a full
1.2× margin), HEDGE 27, SAFE 34 µm.**

**Dictionary:** `DICT_4X4_100` is identical to `_50` (same module geometry). `DICT_5X5_100`
(7 modules) lands within noise of 4×4 — its stronger error correction offsets its smaller
modules — but offers no advantage and has fewer strut-free IDs per dictionary size.
**Keep `DICT_4X4_50`.**

**Tag size does not buy dots.** SAFE at 35 vs 28 µm: 8,625 vs 8,625; OPT at 21 vs 17 µm:
+300. The keep-out removes only a handful of dots per node. Tag size is a robustness and
rigid-material question, not a density one — which means the decision between candidates is
entirely about PSF (W0), and W1 only sets the margin.

**Test-accounting note:** an 89% ceiling (32/36) at every size turned out to be the four
corner tags pushed past the frame edge by barrel distortion; giving the frame 40 µm more room
cleared it. Second time this workshop that a "physics" result was an accounting bug — check
the in-frame set before believing a plateau.

## W2 — Quiet zone (`w2_quiet_zone_sweep.py`, `quiet_zone_sweep.png`)

**The quiet zone is not an ArUco constraint on this pattern.** Sweeping clearance from 0.25 to
2.5 modules around the W1-sized tags of all three candidates, in the W1 worst-case placement
with real dot and dash crowding, every configuration decoded **100%** of 36 tags at the design
PSF and ≥ 99% at 1.2× the design PSF — including a quarter-module (1.0–1.4 µm) of clearance,
where the nearest dot's edge sits inside the blur radius of the tag border. The two-channel
variants (dots, or dots and dashes, in a second fluorophore) were also 100% everywhere.

**This corrects Phase B's second finding** ("the ArUco quiet zone was too small: decoding at
λ = 1 fell to 50%"). That was the third CLAHE artefact: CLAHE amplified the crowding, plain
inversion is indifferent to it. ArUco's contour detection needs light background *between* the
dots, which the lattice always leaves.

**Two-channel imaging buys nothing** — gain 0 dots for every candidate — because the quiet
zone barely costs dots anyway: the keep-out only removes a lattice row when it crosses one
(OPT 17,825 → 17,325 at ≥ 1.5 modules; SAFE 8,625 → 8,125 at ≥ 1.25). WORKSHOP_PLAN §7 Q1 is
therefore closed: **a second channel is not needed for the fiducial tier.**

**What actually sets the quiet zone is the dot detector, not the tag.** A dot printed 1 µm from
a 34 µm bright tag merges into the tag's connected component under the top-hat/Otsu detector
and is lost or mis-centred — the same failure Phase B caught between dots and dashes at 0.3 µm
clearance. So the clearance should equal the edge-to-edge gap dots already get from each other:
**quiet = pitch − dot** (OPT 2.9 µm, HEDGE 3.6, SAFE 4.6 ≈ 0.8 module), which is inside the
100% plateau and costs no dots relative to the Phase-B rule. *The generator now derives it this
way.* W5 (dot separation vs PSF) will confirm the dot-side of this on synthetic frames.

**Running tally of Phase-B conclusions overturned by fixing the decoder: two of four** (tag size
2× too small; quiet zone too small). The other two — dots merging with dashes, circular
keep-out on a square tag — were geometric and stand.

## W3 — Tag integrity through expansion (`w3_tag_integrity.py`, `tag_integrity.png`)

**A — expansion.** With exposure ∝ λ², every candidate decodes **100% of in-frame tags at every
λ from 1 to 6**: a rigid rounded tag keeps its pixel size, so decode is flat in λ once photons
are supplied. With fixed exposure it collapses on the measured λ⁻¹·⁸⁴ law — OPT 62% at 5×,
HEDGE 25%, SAFE 0%; all 0% at 6× — which is the Phase-B photon cliff re-confirmed at the W1
tag sizes. Smaller tags run out of photons per module first, so OPT's 23 µm tags are *more*
exposure-sensitive than the 36 µm ones Phase B tested. Exposure compensation stays mandatory.

**A usable-frame band.** A λ = 3 dip (6/8) that survived the lens-forward accounting fix
turned out to be the two tags 63 and 76 px from the frame border; every tag ≥ 91 px in decoded.
Lens *un-distortion* pulls content inward, so the outer ~|k1| × half-frame ≈ **50 px (25 µm) of
the corrected frame is smeared and unusable**. Real, not a bug: the stitched field is
effectively 25 µm narrower on each side than its pixel count suggests. Both in-frame tests now
exclude the band.

**B — fault injection** (36 IDs × each candidate, real pixel scale, design PSF, L2 noise):

| fault | OPT | HEDGE | SAFE | misdecodes |
|---|---|---|---|---|
| baseline | 100% | 100% | 100% | 0 |
| any one **payload** module lost | **100%** | **100%** | **100%** | 0 |
| any one **border** module lost | 0% | 0% | 2% | **2 / 1440 (SAFE)** |
| leaf module detached, λ = 1.5 | 100% | 100% | 100% | 0 |
| leaf detached, λ = 2 | 95% | 100% | 100% | 0 |
| leaf detached, λ = 3 | 68% | 68% | 68% | 0 |

Three things fall out:

1. **OpenCV's default error correction is zero for this dictionary.** `DICT_4X4_50` has
   `maxCorrectionBits = 1`, and the default `errorCorrectionRate = 0.6` rounds that to 0 — out
   of the box, a single flipped module loses the tag (0% payload survival in the first run).
   Setting `errorCorrectionRate = 1.0` restores the one bit the dictionary has: **100% payload
   survival.** *Phase-C requirement, alongside no-CLAHE.*
2. **A missing border module is fatal, regardless of error settings** — the notch breaks
   quad-fitting before any bit is read, so `maxErroneousBitsInBorderRate` never gets a vote.
   The border ring must stay one intact piece. That is exactly what the 4-connected IDs and the
   necks/fillets protect, so it is a design *confirmation*, not a gap — but it makes the ring
   the single most important printed feature in the pattern, and the coupon should look at it.
3. **The price of error correction is small but non-zero.** On border-damaged SAFE tags,
   `errorCorrectionRate = 1.0` produced **2 wrong IDs in 1,440 trials (0.14%)** where 0.6
   produced none. A wrong node ID is the one failure nothing downstream can see directly; the
   mitigation is `rwtag/project.py`'s cross-frame shared-tag validation and a node-lattice
   consistency check in Phase C. **Gate result: OPT and HEDGE pass strictly; SAFE passes with
   this documented 0.14% risk on already-damaged tags.**

**Leaf modules.** A 4-connected ID can only shed a module attached by one edge (a "leaf"). A
shed leaf carried away by the gel is harmless to λ ≈ 2 and loses the ID a third of the time by
λ = 3 (never misreads it). 16 of the 43 strut-free IDs have **no leaf at all**; the generator
now assigns leaf-free IDs first (16 of the 36 nodes), then fewest-leaf.

**Rev C comparison.** The July "conjoined spread" failure — IDs lost by λ ≈ 1.2 as modules
separate — does not occur here at any λ, because every printed ID is a single 4-connected
island. The strut/neck analysis of Rev C is confirmed as the right idea and, for this
dictionary, largely unnecessary: the necks exist for stress relief, not connectivity.

## W4 — Stiffening-test sensitivity at the V2 tag scale (`w4_stiffening_sensitivity.py`, `stiffening_sensitivity.png`)

**The 0d test can see well below what it needs to.** With known pinning injected around the
V2 tags (23 / 27 / 34 µm, each with its keep-out, dots from the real generator, ground-truth
positions + the measured 0.25 px localisation noise, pooled over λ 2–4 exactly as 0d pooled the
real frames):

| injected | OPT | HEDGE | SAFE |
|---|---|---|---|
| 0% | z −0.7, recovered 0.2% | z −0.9, 0.2% | z −0.5, 0.1% |
| 2% | z −6.2, 1.6% | z −7.0, 1.8% | z −7.2, 1.7% |
| **5%** | **z −14.5, 3.8%** | **z −14.5, 4.1%** | **z −18.7, 4.2%** |
| 10% | z −29, 7.6% | z −26, 8.0% | z −33, 8.4% |
| 20% | z −49, 15.0% | z −76, 15.8% | z −70, 16.5% |

**Minimum detectable pinning ≈ 0.7–0.8% of full**, all three candidates; the null (0%) reads
within 1σ of zero; 5% is detected at 14–19σ and recovered at 3.8–4.2% — a mild, consistent
under-recovery because the 12 µm inner ring straddles the decaying kernel, so the bound reads
~20% low, which is the conservative direction. **PASS on all three.** The Phase-6 coupon is
worth printing: the test is not blind at this tag size, despite the larger keep-out removing
the dots nearest each tag.

**A method correction, worth recording.** The first run failed OPT at *zero* injected pinning
(z −2.6) — and the table showed why: the shifted-lattice *control* itself sat at +2.6σ. Every
seed had reused the **same warp field**, so the systematic from that one smooth realisation
never averaged out, and a per-dot SEM could not see it. That is precisely the spatial-
correlation caveat 0d flagged, now observed in the calibration. The fix — a fresh warp
realisation per seed, with significance taken from the scatter *between* realisations rather
than from per-dot SEM — brought the null to |z| < 1 and is the estimator the real-data test
should use too. **`tools/fiducial_stiffening.py` should be updated to bootstrap over frames
(or spatial blocks) rather than trusting per-dot SEM; its 0d bound stands but its quoted
error bars are optimistic.**

**Phase 2 complete.** W1–W4 settle the fiducial tier: `DICT_4X4_50`, tag = 6 × 1.75 × PSF
(OPT 23 / HEDGE 27 / SAFE 34 µm), quiet = pitch − dot, rounded and leaf-free-first IDs,
detector with no CLAHE and `errorCorrectionRate = 1.0`, a ~25 µm unusable frame edge, exposure
∝ λ² mandatory. Two of Phase B's four CAD findings were overturned along the way; the fiducial
tier is now sized to the measured microscope with margin, not to a decoder artefact.

## W5 — Dot separation vs PSF (`w5_dot_separation_vs_psf.py`, `separation_vs_psf.png`)

0c's spliced-pair method on synthetic frames at each candidate PSF, dense (λ = 1) and sparse
(λ = 4), with the production global-Otsu detector and a tile-wise Otsu candidate (C-1).
Threshold = 95% of the pair plateau, in units of the *imaged* dot FWHM:

| PSF (µm) | imaged FWHM | dense / global | sparse / global | dense / tile | sparse / tile |
|---|---|---|---|---|---|
| 1.91 | 5.4 px | **1.86** | 1.67 | 1.67 | 1.67 |
| 2.50 | 6.2 px | 1.79 | 1.79 | 1.79 | 1.79 |
| 3.18 | 7.3 px | 1.64 | 1.64 | 1.78 | 1.78 |

**The 1.75× rule holds at every PSF, within measurement quantization.** All twelve curves
overlay; the transition is a step about one pixel wide, and one pixel is 0.14–0.19 FWHM here —
wider than the 1.6–1.8 band the plan asked for, so the single 1.86 reading is one pixel step
(10 px vs 9 px) and the strict gate reads FAIL on quantization alone. Every threshold lies in
9–13 px.

**The dense/sparse gap 0c measured (1.60 vs 2.27) does not reproduce.** Dense and sparse agree
within one pixel at every PSF and with both detectors. So the 2.27 on the real 4.2× frame was
not the global Otsu's fault, as 0c supposed — that frame had **15% of the reference signal**
(the λ⁻¹·⁸⁴ law measured later in Phase B), and photon starvation, not thresholding, widened
its threshold. **Phase C-1 (adaptive threshold) is therefore not motivated by separation**; the
tile detector moves thresholds by ≤ 1 px. Whether it helps *efficiency* in dim frames is W6's
question. The plan's C-1 entry is downgraded from "worth up to 2×" to "test in W6".

**One cell matters for OPT.** Under the production detector in a dense frame at PSF 1.91, the
threshold is 10 px while OPT's designed pitch is 5.00 µm = 9.8 px — at the edge. Two ways out,
both cheap: (a) the tile detector reads 9 px there (5% margin), or (b) raise OPT's rule to
1.85× (pitch 5.29 µm, ~10% fewer dots). **Recommendation: (a), and make it a Phase-C
requirement if OPT is printed.** HEDGE and SAFE have 10–15% margin under either detector.

**A prediction retracted.** I expected the V1 area floor (30 px²) to drop the optimistic
variant's ~5.6 px dots. It does not: detections are identical with floors of 30 and 12 at every
PSF (1196/1198, 935/935, 594/594). The blobs are larger after Otsu than my estimate.

**Two detector notes for Phase C.** Single-dot efficiency at L2 noise is 89–92% (PSF 1.91),
96–98% (2.5) and 83–87% (3.18) — the V1-tuned filter constants are not optimal at either end
and should be tuned per PSF. And resolved *pairs* plateau ~5–10% below the single-dot
efficiency squared (a pair is slightly less detectable than two lone dots — the extra bright
pixels nudge the global threshold); 0c's real frames happened to have plateau ≈ eff², which is
why its ceiling-relative criterion worked there and had to be made plateau-relative here.

## W6 — Dot size vs photons vs exposure (`w6_dot_size_photons.py`, `dot_photons.png`)

**Exposure policy decides everything; dot size decides nothing.** Empirical detection
efficiency through the simulator camera (HEDGE geometry, PSF 2.5, L2 noise, measured
λ⁻¹·⁸⁴ signal law), production detector:

| exposure | λ = 2 | λ = 3 | λ = 4 | λ = 5 | λ = 6 | (all three dot sizes) |
|---|---|---|---|---|---|---|
| fixed | 94–100% | **1–3%** | 0% | 0% | 0% | cliff at 3× |
| ∝ λ | 99–100% | 91–100% | **2–6%** | 0% | 0% | cliff at 4× |
| **∝ λ²** | 100% | 100% | 100% | 99–100% | **98–100%** | flat |

Analytic SNR at λ = 6 (shot-limited bound / read-limited): fixed 2.1 / 2.1, ∝ λ 4.3 / 8.6,
∝ λ² 8.6 / 34 for the 2.125 µm dot. **PASS for every dot size under ∝ λ².**

Three conclusions:

1. **3 µm dots are not insurance.** W0 supposed larger dots could rescue a fixed-exposure
   acquisition. They cannot: 3.0 µm dots detect 3% at λ = 3 with fixed exposure — the same
   cliff as 2.125 µm, one step later at best. The extra photons per dot (2×) are nothing against
   the λ⁻¹·⁸⁴ loss (0.28 at 3×, 0.08 at 6×). Dot size stays at the anchoring-proven 2.125 µm;
   the 3 µm option (candidates H, I) is retired.
2. **The detector fails before the photons do.** At λ = 3 with fixed exposure the analytic SNR
   is still 7.6 — above the Rose limit — yet detection is 1%. Top-hat + Otsu on a frame whose
   brightest feature is 28% of full scale simply does not threshold; it is a *contrast*
   failure, not a statistics one. A matched-filter detector would extend the fixed-exposure
   range somewhat, but with exposure ∝ λ² the point is moot, and that is the cheaper fix.
3. **The tile-Otsu detector (C-1) does not help efficiency either** — within a few percent of
   global at every cell, worse as often as better. With W5 showing it does not help separation,
   **Phase C-1 is dropped from the plan.** The one thing it would have bought — OPT's 1 px of
   separation margin (W5) — is better taken by setting OPT's rule to 1.85× (see W5).

**Acquisition rule for Rev D:** exposure at expansion λ ≥ (λ / 1.5)² × the 1.5× reference
exposure, never shorter than the reference — about 16× at 6×. The user's question of whether
bleaching permits this (plan §7 Q3) is now the *only* open question on the fine tier, because
nothing in the print can substitute for it.

**Method note.** The truth-to-pixel mapping had the same lens-normalisation slip as the
in-frame tests (half-canvas instead of half-FOV), which read as 38% "missed" dots at full
brightness; fixed in the simulator, W3 and W6. And an exposure policy defined relative to the
1.5× reference must be floored at 1× — "∝ λ²" at λ = 1 otherwise means *under*-exposing.

## W7 — Dots vs crosses vs saddles (`w7_dot_vs_cross.py`, `dot_vs_cross.png`)

Rev C recommended a checkerboard / corner-cross fine tier because "saddle points localise even
better than blobs under blur". At this microscope they do not.

| feature | anchoring | localisation RMS (natural estimator), PSF 1.91 / 2.5 / 3.18 | implied pitch | features / field | field precision |
|---|---|---|---|---|---|
| **dot 2.125 µm** (Gaussian fit) | 21 µm² | **0.038 / 0.048 / 0.063 µm** | 5.0–6.7 µm | **12.6–22.5 k** | **0.25–0.56** |
| cross, 4 µm arms (centroid) | 38 µm² | 0.055 / 0.063 / 0.078 | 7.8–8.9 | 7.0–9.3 k | 0.57–0.93 |
| cross, 6 µm arms (centroid) | 58 µm² | 0.054 / 0.065 / 0.071 | 11.0–11.9 | 4.0–4.6 k | 0.79–1.12 |
| saddle 2×2 (`cornerSubPix`) | 42 µm² | **0.46 / 0.51 / 0.53** | 8.2–9.3 | 6.5–8.5 k | 5.0–6.5 |

**Dots win at every PSF, on both counts.** Per feature, the Gaussian-fitted dot is the most
precise (0.04–0.06 µm ≈ 0.07–0.12 px); and because it is the smallest feature it packs 1.5–3×
denser, so the precision available to a fixed strain window ("field precision" = RMS/√density)
is **2–3× better than a cross**. Rev C's saddle is an order of magnitude worse: with a 1.9–3.2
µm PSF the checkerboard corner between 2.125 µm squares is not resolved, and `cornerSubPix`
converges half a micron away. Rev C's claim was made for a confocal PSF of 0.2–0.3 µm, where
it is presumably true; it does not survive a 10× coarser blur.

The saddle has a second, structural problem: its two printed squares touch only at a point, so
as rigid islands they are *two* islands — the saddle is not a material point of one piece and
would come apart under expansion unless bridged by a neck (extra material and a stress
concentrator, W3). Not a candidate.

**Two useful by-products.**
- **A Gaussian-fit refinement beats the production centroid by 25–35%** (0.038 vs 0.057 µm at
  PSF 1.91; 0.063 vs 0.082 at 3.18). Cheap to add in Phase C, and it feeds directly into the
  strain-noise budget (W8).
- **Crosses are the mechanical fallback.** A 4 µm cross carries 1.8× the dot's anchoring area
  at 2.3× worse field precision. If the Phase-6 coupon shows 2.125 µm dots detaching, that is
  the trade to make — not larger dots, which W6 showed buy nothing optically and cost density.

Fine-tier feature is settled: **2.125 µm dots.**

## W8 — Lattice density → strain precision, end to end (`w8_lattice_density_field.py`, `density_vs_strain_noise.png`)

Rev C's `simulate_rigid_spread` redone: a known warp injected, imaged through the real camera
model, dots **detected** with the production detector, identity by ground truth (Phase C's
tag-addressed assignment stands in), local affine → Green strain, compared with the analytic
truth. λ = 2, all three candidates at their design PSF.

**The field is recovered unbiased** (bias ≤ 0.001 at every window) with these errors:

| window R (µm) | OPT (N / err) | HEDGE | SAFE | cross-candidate slope |
|---|---|---|---|---|
| 12 | 19 / 0.0152 | 12 / 0.0162 | 8 / 0.0299 | −0.79 |
| 18 | 36 / 0.0075 | 26 / 0.0089 | 18 / 0.0138 | −0.92 |
| **25** | **64 / 0.0044** | **52 / 0.0047** | **37 / 0.0059** | **−0.56** |
| 35 | 123 / 0.0028 | 97 / 0.0036 | 69 / 0.0036 | −0.36 |
| 50 | 249 / 0.0029 | 186 / 0.0034 | 130 / 0.0032 | −0.13 |

**The density argument holds.** Where the affine fit is well conditioned (every candidate with
N ≥ 30, R = 25 µm) the error scales across candidates as N^−0.56 — the predicted −0.5 within
error. Above R ≈ 35 µm every candidate hits the same floor (~0.003), which is the *curvature*
of the injected warp (σ = 90 µm) inside the window — a model limit, not a measurement one.
Below R ≈ 20 µm the slope steepens to −0.8/−0.9 because SAFE's windows hold only 8–18 dots and
a six-parameter fit degrades faster than √N there. **Practical reading: SAFE cannot resolve
strain on windows below ~25 µm; OPT can go to ~12 µm at the same precision SAFE reaches at 18.**
That is what "optimistic-leaning" buys in the final map: a 2× finer spatial resolution of the
deformation field at equal noise, or √2 lower noise at equal resolution. **PASS.**

End-to-end localisation RMS is 0.22–0.24 µm (production) and 0.22 µm (Gaussian-refined) —
consistent with the 0.25 px measured on real frames in 0c, and coarser than W7's isolated-dot
0.04–0.06 µm because the real frames are dense, warped and un-distortion-resampled. The
Gaussian refinement buys 10–20% at the small windows that matter.

**Three findings about the simulator, needed for Phase D.**
1. **Its warp is a print distortion, not a non-uniform expansion.** `place()` applies
   λ·warp(X) in *every* frame, λ = 1 included, so between any two frames the deformation is
   exactly uniform and the warp merely scales up. On its own it therefore *cannot* test
   non-uniform-expansion recovery — it produced a 0.024 strain-error floor here until the
   reference was rendered without warp. Phase D must switch the warp on between frames (as W8
   does) or add a λ-dependent term.
2. **Measure on un-distorted frames.** Detecting on the distorted frames gave a +0.18 Green-
   strain bias: the λ = 2 dots sit at larger radius than the λ = 1 dots, where barrel
   magnification reaches ~7%. Stage 1 already un-distorts; any synthetic test must too.
3. **Fourth handedness slip of the workshop** — the recovered strain is in image (y-down)
   coordinates, truth in design (y-up); the shear component flips sign between them. Harmless
   here only because the injected shear was small. Design↔image code remains guilty until
   checked.

**Phase 3 complete.** The fine tier is settled by measurement: 2.125 µm dots at
pitch = 1.75 × √(dot² + PSF²) (1.85× for OPT under the production detector), exposure ∝ λ²,
Gaussian-fit refinement in Phase C, and the density payoff confirmed end to end.

## W9 — The decision table (`w9_candidate_montage.py`, `candidate_grid.png`)

Rows = the print (sized for its design PSF); columns = the PSF the microscope actually delivers.
λ 1–6, exposure ∝ λ², Phase-2 detector settings, two seeds with independent drift and noise. Dot
efficiency is scored **one-to-one** (merged pairs count as lost) and on the **worst frame** —
the reference frame is the densest and breaks first, and a mean over λ hid that (OPT at 3.18 µm
averaged 86% while keeping 36% at λ = 1).

| print \ actual PSF | 1.91 µm | 2.50 µm | 3.18 µm (measured) | 3.80 µm (stress) |
|---|---|---|---|---|
| **OPT** (tag 23, pitch 5.00) | **PASS** 96% · 1,351 @6× | PASS 95% · 1,350 | FAIL 36% | FAIL 18% |
| **HEDGE** (tag 27, pitch 5.74) | PASS 95% · 969 | **PASS** 95% · 968 | MARGINAL 90% · 966 | FAIL 36% |
| **SAFE** (tag 34, pitch 6.69) | PASS 95% · 645 | PASS 95% · 645 | **PASS** 95% · 645 | FAIL 16% · 120 |

(cell: worst-frame dot efficiency · usable dots at 6×; every cell keeps ≥ 4 decodable tags per
frame except OPT at 3.8 µm, which keeps 3)

**§5 rule, applied:** actual PSF **≤ 1.91 → OPT · 2.5 → HEDGE · 3.18 → SAFE** (the rule strictly
returns "none" at 3.18 because every print fails the +20% stress column, see below) · **≥ 3.8 →
no print passes**. This is the plan's *expected* mapping (≤ 2.0 OPT, 2.0–2.8 HEDGE, > 2.8 SAFE),
now measured instead of guessed.

**What decides the table is the fine tier, never the fiducials.** Tags decode ≥ 4 per frame in
eleven of twelve cells and 3 in the twelfth; the W1 sizing has margin everywhere. What fails is
dot separation in the reference frame at a blur the pitch was not designed for: OPT's 5.0 µm
pitch is 1.8× the imaged spot at 1.91 µm but 1.3× at 3.18 µm.

**Why OPT is chosen only at 1.91 although it passes at 2.5.** The rule demands the print still be
usable one column up (+20% PSF). OPT at 3.18 keeps 36% of its reference-frame dots — unusable —
so it has no margin at 2.5. **OPT is the right print only if Phase 1b shows the focus fix
reaching ~1.9–2.0 µm, and holding.** HEDGE is the right print for 2.0–2.5. That is the whole
optimistic-vs-hedge question, and it now has a number attached.

**The 3.8 µm column is a detector result, not a print result.** SAFE loses 84% of its dots at
λ = 6 there (120 usable, reproducible across both seeds) while HEDGE keeps 958 — same dot, same
blur, so not geometry. At 3.8 µm the imaged spot (8.5 px) approaches the production top-hat
element (15 px), and the global Otsu on SAFE's *sparser* high-λ frame collapses. This is the
sparse-frame fragility 0c suspected — W5 cleared it for *separation*; it is real for *detection
efficiency* in dim, sparse, badly-blurred frames. If Phase 1b lands anywhere near 3.8 µm, the
Phase-C detector needs a larger top-hat element and a threshold robust to sparse frames before
any print is chosen; that column should not be read as "no design works".

**Two scoring corrections made during W9**, both of which moved the answer: nearest-neighbour
dot matching (lets merged pairs count twice) → one-to-one; mean-over-λ dot efficiency (hides the
reference frame) → worst frame. The first turned out not to change the numbers — the production
detector *rejects* merged blobs rather than mis-centring them (0c) — the second did.

## W10 — Field of view / stitch width (`w10_fov_and_stitch.py`, `stitch_width.png`)

Analytic, calibrated to W9: usable(λ, S) = D · eff · ((S − 2b)/(750 λ))², with the un-distortion
band b = 25 µm. Against W9's measured λ = 6 counts for the current 1365 µm stitch the pure-area
model over-predicts by a uniform **0.93** for all three prints (rotation and drift crop it omits)
— a clean check, applied as the calibration.

**Paired dots at λmax, and the stitch width each print needs for ≥ 1,000:**

| print | current 1365 µm @ λ=4 / 5 / 6 | width for 1,000 @ λ=4 / 5 / 6 | cost (area vs current) |
|---|---|---|---|
| **OPT** | 3,038 / 1,944 / **1,350** | 805 / 993 / **1,182 µm** | 0.3 / 0.5 / **0.7×** |
| **HEDGE** | 2,175 / 1,392 / **967** | 942 / 1,165 / **1,387 µm** | 0.5 / 0.7 / **1.0×** |
| **SAFE** | 1,454 / 931 / **646** | 1,140 / 1,413 / **1,686 µm** | 0.7 / 1.1 / **1.5×** |

**The "stitch wider" lever is largely unnecessary in V2.** It was the dominant lever in the plan
(§2.1, ×4 at 4.2×) because the V1 series paired only 299 dots at its top frame. That loss was not
the field of view: it was the 1.5× "initial" frame already overflowing the field and pairing by
lattice registration (the 0.33 derate). In V2 the reference frame holds the entire pattern and
pairing is by tag identity, so a detected dot is always pairable — and the *same* 1365 µm
stitch yields **1,350 paired dots at λ = 6 for OPT** (4.5× the V1 figure at a comparable
expansion) and 967 for HEDGE. Only SAFE needs a wider stitch to clear 1,000 at 6×.

**Recommendation: keep the current 1365 µm stitch for OPT and HEDGE up to λ = 6.** Do not go
narrower even where the dot count would allow it — at the 1,000-dot widths only ~2 tags are in
view at λ = 6, below the 4-per-frame redundancy the W3/W9 gate uses; the current width keeps 4.
Going to 2× linear (2730 µm, 4× the tiles) is optional and buys a further 4× dots (5,600 for OPT
at 6×); it is worth it only if the strain map needs finer windows at λmax (W8) and bleaching
permits the extra exposure. For SAFE at λ = 6, 1,700 µm (1.5× the tiles) is the minimum.

Plan §7 Q3 (stitch width target) is closed by this; §2.1's stitch row is re-weighted.

## W11 — Print budget and mesh checks (`w11_print_budget.py`, `print_budget.png`)

All three candidates rebuilt under the final Phase-2/3 rules (W1 tag sizes, W2 quiet zone,
leaf-first IDs) and re-gated PASS. Budget from the generator's exact geometry; write-time proxy
= laser scan length for a hatched solid (hatch 0.2 µm, slice 0.3 µm, IP-Dip 63×):

| | dots | tags | dashes | dots (µm²) | **footprint** | fill | **scan** | vs V1 | STL |
|---|---|---|---|---|---|---|---|---|---|
| V1 | 6,420 | 24,781 (glyphs) | 20,341 | 28,939 | 74,140 µm² | 13.2% | 2.5 m | — | 6.6 MB |
| **OPT** | 17,825 | 15,109 | 8,288 | 80,491 | **103,887** | 18.5% | **3.5 m** | **1.40×** | 11.4 MB |
| **HEDGE** | 12,825 | 20,802 | 6,216 | 57,913 | **84,930** | 15.1% | **2.8 m** | **1.15×** | 8.3 MB |
| **SAFE** | 8,625 | 32,986 | 6,216 | 38,947 | **78,149** | 13.9% | **2.6 m** | **1.05×** | 5.8 MB |

**Every candidate prints in about the same time as V1 — OPT 40% longer, SAFE 5% — while carrying
1.3–2.8× the measurement dots.** The earlier claim (Phase A, first draft) that V2 would print in
a third of V1's time was for 1 µm dots; at the anchoring-proven 2.125 µm the dot tier is now the
bulk of the material (77% of OPT's footprint) and the saving is gone, replaced by 2.8× the dots.
Dots per metre of scan: V1 2,600 · SAFE 3,300 · HEDGE 4,500 · **OPT 5,100** — OPT is the most
efficient print per unit of write time as well as the densest.

**Mesh checks.** Zero overlapping rectangles in any candidate (checked pairwise across the whole
field), so no self-intersections. The box-style STLs do contain **~1,400 coincident internal
faces** per candidate (abutting rectangles inside the tags — about 40 per tag; dots and dashes
are isolated boxes and contribute none). Whether DeScribe accepts those is the one question this
workshop cannot answer itself. So each candidate now also has a **merged-outline STL**
(`aruco_grid_<variant>_merged.stl`): identical top and bottom tiling, side walls emitted only
along the outline of each connected region (shared edges dropped, T-junction remainders kept),
so every island is one closed solid with no internal face. And `test_tag_<variant>_boxes.stl`
/ `_merged.stl` are single-tag files for the dry run — open both in DeScribe; whichever slices
cleanly is the style to print.

**Phase 4 complete.** W9 gives the decision, W10 the acquisition field, W11 the cost and the
printable files. What remains before fabrication is Phase 1 at the microscope (pixel size,
z-stack), the DeScribe dry run, and Phase 5's write-up of Rev D.

## Phase 5 — Rev D and the coupon (`DESIGN_REV_D.md`, `tools/coupon_phase6.py`, `coupon_phase6.png`)

The recipe is written in Rev C's §10 format with every number traced to a W-script, and all three
candidates are carried with the measured decision mapping (P ≤ 1.9 → OPT · 2.0–2.5 → HEDGE · ~3.2 →
SAFE · ≥ 3.8 → retune the detector). The three CAD files were re-gated after the generator gained an
id offset (`GridConfig.id_start`) — geometry and ids unchanged, `PHASE-A GATE: PASS` for all three.

The Phase-6 coupon goes beyond the plan's brief in one way: instead of "the tag set at the chosen
size" it carries **all three candidates as one-box mini-patterns with distinct ids** (768 / 513 /
345 dots), so the real-PSF decode comparison is made on one frame rather than inferred from the
z-stack alone. The rest is as planned — a pitch ladder 3.5 → 9.0 µm (0.9–3.2 × imaged FWHM over
PSF 1.9–3.2, ≥ 2 patches either side of the W5 prediction at any plausible PSF), a size ladder
2.125 / 2.5 / 3.0 at the HEDGE rule, and two 260 µm stiffening fields with a 34 and a 23 µm tag
(two sizes give the slope if pinning is detected). Each ladder patch is addressed by its own 27 µm
tag, and an L datum on the bottom edge tests the design↔image handedness that bit 0d, Phase B and
W8. 24 of 43 solid ids; 7,393 dots; 9.0% fill; gated to the full-print standard (24/24 decode,
every dot recovered per region, exact geometry, zero overlaps, 750.00 × 750.00). Box and merged
STLs both emitted (939 coincident faces removed in the merged file).

**Phase 5 complete.** Left for the lab: Phase 1 (pixel size, z-stack → P), the DeScribe dry run,
the coupon; then the full print by the §5 look-up.

## Phase C — the detector, against truth (`tools/phase_c_verify.py`, `docs/PHASE_C_DETECTOR.md`)

The R16 settings became code: `rwtag/aruco/` (detect + series driver) with three additive
changes in `refwarp`, the V1 path untouched (49 old tests + 8 new, 57/57). Gated on synthetic
frames of all three candidates through the Phase-B camera, λ 1–6, two seeds: **every frame
registers from its tags with the right handedness, 100.0% of tagged dots carry the correct tag on
all 36 frames, centres are 0.20–0.28 px RMS (0.10–0.14 µm) from truth, and a frame with a single
decodable tag still tags 100% correctly** (scale from the dot-lattice pitch). Two findings that
change the recipe: (1) **tag corners cannot carry the expansion** — rigid islands keep their
printed size, so the design→image affine goes through tag *centres*, corners give rotation and
handedness only (the corner fit was 3 pitches off at 2× and ICP then locked to the wrong
lattice with a perfect-looking residual); (2) **flat-fielding collapses Otsu in sparse frames** —
SAFE at 6× fell to 31% efficiency with 59% false detections once the vignette was divided out;
a threshold floor at median + 5σ of the top-hat restores 97%. Both are in Rev D §6. Also fixed:
a +0.25 px rendering bias in the simulator (corner-inclusive `cv2.rectangle`) invisible to every
3 px-tolerance test. The refinement choice is settled: Gaussian-mask centroid (0.20 px) within 4%
of W7's least-squares fit at 1/15 the cost. `warp.per_det_median` is shown not to be an accuracy
measure (a TPS through a few hundred dots interpolates them exactly) — read `matched_frac` and
the truth RMS instead.

## Phase D — the whole pipeline against injected truth (`tools/phase_d_end_to_end.py`, `docs/PHASE_D_END_TO_END.md`)

Reference at λ = 1 without warp, five expanded frames (λ 1.5–6) with a 14-lobe 2 µm field,
through the production path to paired tags, then λ, the deformation field and the Green strain
at R = 25 µm — each scored against the truth **passed through the same estimator on the same
dots**. All three candidates PASS: **λ to −0.019% at every level (a constant, i.e. no
λ-dependent pipeline bias — V1's +6.5% at 4.2×, if real, is gel or pixel size, not tagging);
the non-uniform field to 0.01–0.06 µm RMS (correlation ≥ 0.998); strain to ≤ 0.0005 against a
0.004–0.006 field.** What a naive comparison with nominal λ would have called a −0.18…+0.13%
bias is the mean dilation of the injected field inside the shrinking field of view — gel, and
correctly measured. Two scoring lessons for Phase F on real data: de-expand before computing
strain (else the error grows as λ²), and let any design↔image similarity carry a reflection —
the first run of this script forced a proper rotation and reported λ ≈ 0.001, the fifth
handedness bite in this workspace. Desk phases are now complete (0c, 0d, A, B, C, D, 2–5);
what remains is the microscope (Phase 1), the coupon (6/E), the full print (F), and a V2 mode in
the GUI.
