# Rev D — ArUco Tracker V2: the recipe

*Phase 5 of `WORKSHOP_PLAN.md`. Written in the format of Rev C §10 (`hydrogel_marker_analysis/docs/
hydrogel_marker_system_design.md`), but every number here was **measured** — on the real six-frame
V1 series, the real V1 STL, or synthetic frames through a camera model calibrated to them — in
W0–W11 (`FINDINGS.md`). Where Rev C said "adjust per §4", Rev D says which measurement moves which
number, and `tools/aruco_grid.py` re-derives the CAD from those measurements.*

*Status 2026-09-22: the design is complete and gated for all three candidates. The **choice** between
them waits on one lab measurement (the PSF after focus is flattened, Phase 1b), and is made by the
rule in §3 — no judgement call remains.*

---

## 1. The recipe, in one screen

- **Pattern:** 750 × 750 µm, 5 × 5 boxes, an ArUco tag (`DICT_4X4_50`, 6 modules incl. border,
  rounded, id ≙ node) at each of the 36 nodes; dashes (8.125 × 2.125 µm, 10 per box edge) on the
  box boundaries; a square lattice of **2.125 µm dots** filling every box at pitch
  **`1.75 × √(2.125² + PSF²)`** with a **`pitch − dot`** clearance from tags and dashes.
  Three gated sizes of the same pattern: **OPT** (tag 23 µm, pitch 5.00, 17,825 dots) ·
  **HEDGE** (27 µm, 5.74, 12,825) · **SAFE** (34 µm, 6.69, 8,625).
- **Realisation:** discrete rigid islands (every feature prints as its own solid, 2 µm tall, in the
  V1 resin and process); tags carry 0.20 µm necks across diagonal pinches and 0.30 µm fillets so
  no tag can come apart as the gel swells; ids chosen leaf-free first.
- **Imaging:** the existing microscope, unchanged optics; reference frame at the lowest λ holding
  the whole 750 µm pattern; **exposure `t(λ) = t_ref · max(1, (λ/1.5)²)`** — mandatory, not
  optional; **1365 µm stitch** kept for OPT/HEDGE to λ = 6 (SAFE needs ≥ 1,700 µm); z-stack /
  focus flattening first, because the PSF is the only lever that changes the dot count.
- **Pipeline:** ArUco decode on the plain-inverted frame (**no CLAHE**, `errorCorrectionRate = 1.0`,
  un-distortion edge band |k1|·FOV/2·1.4 excluded) → tag id gives node → dots addressed as
  `(node, di, dj)` from `reference_tags.json` → Gaussian-fit dot centres → per-window affine →
  Green strain; rigid-translation and uniform-swell controls.
- **Cross-checks:** the 0d/W4 stacked-residual stiffening test on the coupon; W8's synthetic
  known-warp field as the pipeline's regression test; V1's series re-run through the same code.
- **Coupon first** (`cad/coupon_phase6.stl`): all three candidates as mini-patterns, a pitch
  ladder 3.5–9.0 µm, a dot-size ladder 2.125/2.5/3.0, and two stiffening fields — one print
  answers decode, threshold, anchoring and pinning on the real gel (§6).

---

## 2. Pattern — the three tiers and their derivations

All three candidates are the **same design at three PSF settings**. Every dimension below is a
function of two inputs — `tag_um` and `psf_fwhm_um` — and `tools/aruco_grid.py` holds the
formulas, so a different Phase-1 PSF is a one-line rebuild, not a redesign.

| | formula | **OPT** | **HEDGE** | **SAFE** | source |
|---|---|---|---|---|---|
| design PSF FWHM | input | 1.91 µm | 2.50 µm | 3.18 µm | 0b (edge / dot methods), §3 |
| field | fixed | 750 × 750 × 2 µm | — | — | R13 (user) |
| boxes / nodes | fixed | 5 × 5 / 36 | — | — | R14; 4 × 4 changes dots by ~−12% (W0) |
| **tag** | `6 · 1.75 · PSF`, rounded up | **23 µm** | **27 µm** | **34 µm** | W1: module ≥ 1.45 × PSF measured; 1.75 = 20% margin |
| module | `tag / 6` | 3.83 | 4.50 | 5.67 | |
| node pitch | `(750 − tag) / 5` | 145.4 | 144.6 | 143.2 | `fit = inside`: extent is exactly 750 |
| **dot** | fixed | **2.125 µm square** | — | — | R8 anchoring floor (V1-proven; W6/W7: size buys nothing optically) |
| **dot pitch** | `1.75 · √(dot² + PSF²)` | **5.000** | **5.742** | **6.693** | 0c 1.60× measured, W5 1.64–1.86× at every PSF |
| quiet zone | `pitch − dot` | 2.88 | 3.62 | 4.57 | W2: not an ArUco constraint; set by the dot detector |
| tag keep-out (half-width, Chebyshev) | `tag/2 + quiet + dot/2` | 15.4 | 18.2 | 22.6 | square, because the tag is square |
| dash keep-out (dot centre to line) | `dash_w/2 + (pitch − dot) + dot/2` | 5.00 | 5.74 | 6.69 | Phase B: dots merged with dashes at 0.3 µm |
| dashes | 8.125 × 2.125 µm, 10 / box edge | 480 | 360 | 360 | V1 dimensions; count drops where the keep-out swallows an end dash |
| **dots** | exact, from the build | **17,825** | **12,825** | **8,625** | `cad/*.verify.json` |
| ids | leaf-free first, row-major | identical for all three (`cad/aruco_grid_*.ids.json`) | | | W3: shed leaf loses the id 20% by λ 3 |
| pinches bridged | | 21 | 21 | 21 | necks 0.20 µm × 0.72 module, fillets 0.30 µm |
| footprint / fill | | 103,887 µm² / 18.5% | 84,930 / 15.1% | 78,149 / 13.9% | V1: 74,140 / 13.2% |
| write time vs V1 | scan-length proxy | 1.40× | 1.15× | 1.05× | W11 |

**Why these and not Rev C's.** Rev C (§10) asked for 30 µm boxes, 3.5 µm tags and a 3 µm
checkerboard, for a ~100 nm/px confocal. At this microscope (0.51 µm/px, PSF 1.9–3.2 µm) a 3.5 µm
tag is smaller than one PSF and a checkerboard corner between 2 µm squares is not resolved
(`cornerSubPix` converges 0.5 µm off, W7). Dots at the anchoring-proven size, spaced by the
measured separation rule, are the densest fine tier that this microscope can actually resolve
(W7: 2–3× the field precision of crosses); and the dot count is then set **only by the PSF** — the
tag size, box count and dictionary move it by a few percent (W0, W1).

**What the tiers are for.** Tier 1 (tags) gives every box an identity and a local frame, so pairing
across λ is by id and never by lattice registration (V1's 0.33 derate disappears, W10). Tier 2
(dashes) is the human-readable grid and the coarse strain field. Tier 3 (dots) is the measurement.

---

## 3. Choosing the candidate — the decision rule

Written before the Phase-1 numbers exist (plan §5). `P` is the PSF FWHM after the best available
focus (Phase 1b, `tools/psf_origin.py --zstack`).

| measured `P` | print | W9 basis |
|---|---|---|
| **≤ 1.9 µm** | **OPT** | PASS at 1.91 and at 2.5 (1.3× margin); 36% worst-frame dots at 3.18 |
| **2.0 – 2.5 µm** | **HEDGE** | PASS at 2.5, MARGINAL at 3.18, FAIL at 3.8 |
| **~3.2 µm** | **SAFE** | PASS at 3.18; the only candidate that does |
| **≥ 3.8 µm** | none — retune the detector first | every print collapses at λ = 6 (sparse-frame Otsu), W9 |

Rules that apply regardless: exposure ∝ λ² is mandatory (W6) — if the acquisition cannot support
it there is **no** print that survives λ ≥ 3, and no dot size rescues it; a candidate that fails
the DeScribe dry run (W11) or the coupon's decode test (§6) is out whatever its density.

**The optimistic lean.** HEDGE exists so that a *partial* focus fix still yields 50% more dots than
SAFE. 0b's field map says the blur is a tilted/domed sample (36–38% spread, worst in the *centre*),
not diffraction — fixable by ≈ 2.2×, which would put `P` in OPT's range. That is the expected
outcome, not a hope: it is what the measured field structure predicts.

---

## 4. Realisation

- **Process:** as V1 — same resin, 2 µm feature height, same substrate treatment; nothing in the
  design needs a new process. Hatch 0.2 / slice 0.3 µm assumed for the W11 time estimate.
- **Rigid islands:** every feature is a separate solid. Verified physics, not an assumption: on the
  V1 series the dot pitch triples (30.9 → 91.5 px) while glyph height and dot FWHM stay constant.
- **Tag rounding:** every diagonal (corner-only) contact between two black modules is bridged by
  an elliptical neck 0.20 µm wide and 0.72 module long, and every concave corner is filleted at
  0.30 µm; the neck lives inside ArUco's ignored corner margin so the id is unchanged (re-decoded
  by the gate). A 4-connected id is topologically one piece; W3 showed any payload-module loss is
  survivable and only the border ring is fatal — hence leaf-free ids first.
- **Dots:** 2.125 µm square, 2 µm tall — 21.5 µm² of gel contact per dot, the only size with
  *proven* anchoring (V1 to 4.2×). Do not shrink them: 1 µm buys 24% more dots and halves the
  contact. If the coupon shows detachment, the fallback is a 4 µm cross (1.8× the anchoring, 2.3×
  worse field precision, W7), **not** a larger dot.
- **STL:** `cad/aruco_grid_<variant>.stl` (box-style, ~1,400 coincident internal faces in the
  tags) or `cad/aruco_grid_<variant>_merged.stl` (outline side walls, none). Both are gated
  identical in geometry; **which one DeScribe slices cleanly is the pending dry run**
  (`cad/test_tag_<variant>_boxes.stl` vs `_merged.stl`). Zero overlapping rectangles in any file.
- **Gate (every emitted file passed it):** exact floating-point geometry (each dot record at its
  rectangle centre, configured size and pitch) · render round-trip at 6 px/µm recovers every dot
  within one pixel and decodes all 36 tags · outer extent exactly 750.00 × 750.00 µm.

---

## 5. Imaging

- **Microscope:** the existing one, optics unchanged (user constraint). Nominal 0.510 µm/px from the
  OME metadata; **Phase 1a calibrates this** (the filename labels imply 0.381; 0b's floor of 0.383
  leans to 0.510; if 0.510 is right the V1 series actually spans λ 1.97–5.83). Every pixel-domain
  number in this document assumes 0.510.
- **Focus first.** The PSF field map (0b) is structured — worse in the centre than the edges —
  which is a sample tilt or dome, not the objective. Take the z-stack at the centre and a corner
  (`tools/psf_origin.py --zstack`, protocol in `docs/phase0/PHASE0B.md`), flatten, and re-measure
  `P`. This single step decides between 8.6k and 17.8k dots.
- **Reference frame:** the lowest-λ state in which the full 750 µm pattern is in one stitched
  field (λ ≈ 1–1.5). The reference **is** the design: pairing is tag-addressed, so the reference
  need not be a lattice-registered image, only a decoded one.
- **Exposure policy (mandatory):** `t(λ) = t_ref · max(1, (λ / λ_ref)²)` with `λ_ref` the reference
  expansion — about 16× the reference exposure at 6×. Measured basis: signal ∝ λ⁻¹·⁸⁴ (Phase B);
  W6: fixed exposure loses every dot at λ = 3, ∝ λ at 4, ∝ λ² keeps 98–100% to 6 for every dot
  size. Never shorter than the reference. **Open (user, plan §7 Q3): does bleaching over the
  series permit this?** If not, no design change helps; the fix is on the acquisition side
  (fewer states, or a matched-filter detector for one more λ step at most).
- **Stitch:** keep **1365 µm** (2676 px) for OPT and HEDGE — at λ = 6 it holds 4 tags and 1,350 /
  967 paired dots (W9, W10). SAFE needs **≥ 1,700 µm** for 1,000 dots at λ = 6. Cost scales as
  (width / 1365)². If the true λ_max is 4, everything relaxes (plan §7 Q2).
- **Un-distortion:** the frame edge band `|k1| · FOV/2 · 1.4` (48 µm at k1 = −0.05 on a 1365 µm
  field) is unreliable after lens correction; exclude it (W3). Corner tags of the pattern must
  sit inside it.

---

## 6. Pipeline (Phase C requirements, R16)

1. **Tag decode:** `cv2.aruco` on the plain-inverted frame (bright-on-dark → dark-on-light).
   **No CLAHE** — over a dense dot field it re-maps the local histogram until dark modules are
   not dark; it was the entire "in-scene penalty" of Phase B (36 µm tag at PSF 3.18: 28% → 100%
   without it). `errorCorrectionRate = 1.0` (the 0.6 default gives *zero* correctable bits for
   4×4; W3). `DICT_4X4_50`, default `DetectorParameters` otherwise. Expect all in-frame tags at
   every λ under the exposure policy; a frame with < 1 decoded tag is unregisterable and is the
   sign of an exposure failure, not a detector one.
2. **Addressing:** design → image affine through the decoded tag **centres** (≥ 3 tags: affine;
   2: similarity; 1: rotation from the tag's corners + scale from the dot-lattice pitch) — never
   through tag corners, which keep their printed size and are not affine images of the design
   for λ ≠ 1 (Phase C). Handedness from the corner order must be −1 (y-up design, y-down image).
   Then ICP homography + TPS against the dots, and each dot ← `(box, di, dj)` by nearest warped
   reference within 0.45 pitch (`reference_tags.json` carries every design position); pair across
   λ by identity. No lattice registration, no cross-frame search.
3. **Dot detection:** top-hat (element ≥ 2× the *imaged* FWHM) → **threshold = max(Otsu,
   median + 5·σ_robust)** — flat-fielding amplifies corner noise and plain Otsu collapses into it in
   sparse frames (Phase C: SAFE at 6× went from 31% to 97% efficiency with the floor) → components →
   **Gaussian-mask refinement** (W7/Phase C: 0.20 px vs 0.23–0.30 for the plain centroid, within
   4% of a full Gaussian fit at 1/15 the cost). Area floor 12 px² is safe at every PSF (W5). Tune
   the top-hat per PSF (13 px at 1.9–2.5, 15 at 3.18). The tile-wise Otsu (former C-1) is **not**
   worth having: ≤ 1 px on separation, no gain in efficiency (W5, W6). **Built and gated:**
   `rwtag.aruco` (`docs/PHASE_C_DETECTOR.md`).
4. **Handedness:** design coordinates are y-up, images y-down; flip once, at the boundary, and
   test with the coupon's L datum. (This bit 0d, Phase B and W8.)
5. **Strain:** per-dot local affine over a window of radius R → Green strain; at R = 25 µm OPT
   holds 64 dots and recovers a known field to 0.0044 unbiased (HEDGE 52 / 0.0047, SAFE 37 /
   0.0059; W8). Error scales as N⁻⁰·⁵⁶ across candidates; below R ≈ 20 µm SAFE's windows are
   ill-conditioned (8–18 dots) and OPT is the only candidate that resolves 12 µm windows.
6. **Controls:** rigid translation and uniform swell of the reference (Rev C), plus W8's
   synthetic known-warp run as the regression test for the whole chain.

---

## 7. The Phase-6 coupon — `tools/coupon_phase6.py` → `cad/coupon_phase6.stl`

One 750 × 750 µm print in the same envelope (same DeScribe job, same stitch) that answers on the
real gel the four things synthetic frames cannot. Gated to the same standard as the full print
(24/24 tags decode, 7,393/7,393 dots recovered, exact geometry, zero overlaps, 750.00 × 750.00).
Layout, design y-up (`workshop/figures/coupon_phase6.png`):

```
 y 750 ┌ MINI_OPT ──────┐   ┌ MINI_HEDGE ────┐   ┌ MINI_SAFE ─────┐   one box + 4 tags each,
       │ 23 µm · 5.00   │   │ 27 µm · 5.74   │   │ 34 µm · 6.69   │   175 µm, production generator,
 y 575 └ 768 dots ──────┘   └ 513 ───────────┘   └ 345 ───────────┘   distinct ids (0–11)
 y 505  [tag] PITCH 3.50   [tag] 4.00   [tag] 4.50   [tag] 5.00   [tag] 5.74      row A, 70 µm patches
 y 400  [tag] PITCH 6.69   [tag] 7.50   [tag] 9.00   [tag] SIZE 2.50   [tag] SIZE 3.00   row B
 y 260 ┌ STIFF_34 ──────────────┐                    ┌ STIFF_23 ──────────────┐
       │ 260 µm of 5.74-pitch   │        L datum     │ same field, 23 µm tag  │
 y 0   └ dots, 34 µm tag centre ┘        (y = 0)     └────────────────────────┘
        x 0                            x 360                             x 750
```

| region | what it settles | pass / read-out |
|---|---|---|
| **MINI_OPT / HEDGE / SAFE** (ids 3,23,42,… per `coupon_phase6.ids.json`) | which candidate decodes at the real PSF, side by side in one frame at every λ | a candidate is printable if all 4 tags decode at every λ under the exposure policy **and** ≥ 90% of its dots are recovered in the reference frame — the W9 gate, now on real frames. Most optimistic passer wins (§3). |
| **PITCH 3.50 → 9.00** (2.125 µm dots; 400 → 64 dots per patch) | the real separation threshold — where the 1.75× rule sits on this microscope | resolved fraction per patch vs pitch; the first pitch ≥ 95% is the threshold. Spans 0.9–3.2 × imaged FWHM over PSF 1.9–3.2, so ≥ 2 patches land each side of the W5 prediction (4.6–6.6 µm) at any plausible PSF. If the threshold is above the printed candidate's pitch, drop one rung. |
| **SIZE 2.50 / 3.00** (at the HEDGE rule: 6.19 / 6.83 µm) with **PITCH 5.74** as the 2.125 control | anchoring and brightness vs dot size on the real gel | dots must track coherently (local affine residual ≤ 2× the reference frame's) through λ_max at all three sizes. W6/W7 predict no optical difference; **only detachment of the 2.125 patch would justify a change — and then to crosses, not larger dots.** |
| **STIFF_34 / STIFF_23** (1,976 / 2,000 dots, tag at centre) | does a tag pinch the gel (R9)? | 0d/W4 stacked-residual test (`tools/fiducial_stiffening.py`) against the shifted-lattice control; sensitivity ≈ 0.7% of full pinning at this tag size (W4). Pass: no radial residual above the test's noise out to 3 tag radii at λ_max. Two tag sizes so a positive result gives the slope. |
| **DATUM** (L, 30 µm arms on the bottom edge) | handedness of design ↔ image | long arm must point +y after the pipeline's single flip; if it points −y the flip is missing. |

Ladder patches each carry their own 27 µm tag (decodes ≥ 95% to PSF 3.18, W1) 8 µm away, so
every patch is addressed by id at every λ. Ids are drawn from the same leaf-free-first pool as the
full print (mini-patterns at pool offsets 0/4/8, lone tags from 12) — 24 of the 43 solid ids.

**Protocol:** image the coupon exactly as the full print will be — reference at the lowest λ,
then each state through λ_max, exposure ∝ λ², 1365 µm stitch — and run the decode, the pitch
ladder read-out, the anchoring residuals and the stiffening test on the same frames. Print the
full field only when the coupon's mini-pattern verdict and §3's PSF verdict agree; if they
disagree the coupon wins (it is the real gel).

---

## 8. What changed from Rev C, and why

| Rev C (§10) | Rev D | measured reason |
|---|---|---|
| box 30 µm, tag 3.5 µm, `DICT_4X4_1000` | box ~145 µm, tag 23–34 µm, `DICT_4X4_50` | 0.51 µm/px and PSF 1.9–3.2 µm: module ≥ 1.45 × PSF (W1); 43 leaf-free ids suffice for 36 nodes (W0) |
| 3 µm checkerboard, corners by `cornerSubPix` | 2.125 µm dots at 5.0–6.7 µm, Gaussian-fit | saddle not resolved at this PSF: 0.5 µm RMS vs 0.04–0.06 for dots (W7); dots 2–3× better field precision |
| ~4 µm quiet border **or** two-channel | quiet = pitch − dot (2.9–4.6 µm); one channel | quiet zone was never an ArUco constraint (W2); two-channel closed — no gain |
| tile volume-fraction ≲ 1–2% | 14–18.5% areal fill (2 µm tall) | matches V1 (13.2%), which the gel accepted; write time 1.05–1.40× V1 (W11) |
| exposure unspecified | exposure ∝ λ², floored at reference | signal ∝ λ⁻¹·⁸⁴; fixed exposure loses every dot at 3× (W6) |
| pixel-starved → AprilTag + bigger boxes | not needed | AprilTag 16h5 has fewer strut-free ids (27) and no benefit at 4×4 (W0, W1) |
| "finer field → drop `p_fine` toward the fab floor" | **fab floor is irrelevant**; the PSF is the floor | dot density is PSF-limited; 1.91 vs 3.18 µm doubles the dots (W0); fixing focus is the only lever |
| `simulate_rigid_spread` (Rev C analysis) | W8 end-to-end with the production detector | error ∝ N⁻⁰·⁵⁶, unbiased; 0.003 floor is the warp model, not the measurement |
| (no rounding) | necks + fillets; leaf-free ids | rigid tag in a swelling matrix; border-ring loss fatal, payload loss survivable (W3) |

Rev C's structure — coded rigid islands, tag-addressed fine features, affine de-expansion — is
kept whole. Its numbers were for a different microscope.

---

## 9. Still the user's (plan §7)

1. **Effective pixel size** (R1) — Phase 1a, calibration slide. Scales every pixel figure here.
2. **Maximum λ** — 6 assumed; at 4 the stitch and SNR margins roughly double.
3. **Exposure ∝ λ² vs photobleaching** — the only open question on the fine tier; nothing in the
   print substitutes for it.
4. **4×4 vs 5×5 boxes** — 5×5 kept; 4×4 costs ~12% of the dots and changes nothing else.
5. **DeScribe dry run** — box vs merged STL style (`cad/test_tag_*`).

## 10. Files

```
ArUco_Tracker_V2/
  tools/aruco_grid.py          generator + Phase-A gate (VARIANTS: conservative=SAFE, hedge, optimistic=OPT)
  tools/coupon_phase6.py       coupon generator + gate
  cad/aruco_grid_<v>.stl, _merged.stl, .reference_tags.json, .ids.json, .verify.json   (v = optimistic | hedge | conservative)
  cad/coupon_phase6.stl, _merged.stl, .reference_tags.json, .ids.json, .verify.json
  cad/test_tag_<v>_boxes.stl, _merged.stl                                              (DeScribe dry run)
  workshop/docs/FINDINGS.md    W0–W11, the evidence for every number above
  workshop/figures/            one figure per W-script; coupon_phase6.png; trackers_gallery.png
```

To rebuild for a measured PSF `P` other than the three carried: edit `VARIANTS` in
`tools/aruco_grid.py` (`tag_um = ceil(6 · 1.75 · P)`, `psf_fwhm_um = P`) and run
`python tools/aruco_grid.py --variant <name>`; the gate must print `PHASE-A GATE: PASS`.
