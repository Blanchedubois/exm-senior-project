# ArUco Warp Tracker (V2) — Implementation Plan
### Replacing glyph fiducials with ArUco tags, and densifying the dot matrix for deformation mapping

**Project:** `aruco-marker-design/` · **Supersedes the fiducial scheme in:** `base_design_for_nanoscribe_2026_01_14.stl`
**Builds on:** `hydrogel_marker_analysis` (design + ArUco robustness), `reference-warp-tagger` (Stages 1–8 pipeline), `expansion_camera_sim` (synthetic truth)
**Written:** 2026-09-22 · **Status: WORKSHOP DRAFT — nothing locked below §3 until Phase 0a (pixel size) lands.**
Phase 0: **0c ✅ · 0d ✅ · 0b ◐ partial · 0a ⛔ still the gate.** · **Phase A ✅ · Phase B ✅**
**Tag size doubled in Phase B** (20.3→36 µm conservative, 12.2→24 µm optimistic): simulation
showed the old blur rule was ~1.7× too optimistic once noise and pixel sampling are included.

> **Delivery model** (same as Phase 5): one phase at a time, each verified before the next begins.

---

## 0. Why a new design

Three things drove this, all measured from the existing six-frame series rather than assumed:

1. **Glyph addressing is the weak link.** The current README calls glyph recognition on real
   prints "*beta*", and notes letters and corner dots "print faint and rarely match". Frames at
   3×–4.2× only registered via `coreg` auto-rescue from a lower frame. ArUco decodes rotated,
   blurred and partially-occluded tags natively and gives a hard ID rather than a vote.
2. **Only 39% of printed material does measurement work.** Of the current 74,061 µm² footprint,
   dashes (20,341) and glyphs (24,781) are addressing overhead; only 28,939 µm² is dots.
3. **The dot matrix is under-exploited** — but *not* for the reason it first appears. See §2.

---

## 1. Measured baseline

Everything in this section is measured, not quoted. Reproduce with `tools/`.

### 1.1 The existing print (from the STL)

| Property | Value |
|---|---|
| Field | 750 × 750 µm, **5 × 5 boxes of 150 µm** |
| Feature height | **2.00 µm** (flat extrusion — exactly 2 Z levels) |
| Components | **7,341** total |
| Dots | **6,420** · 2.125 µm square · 4.52 µm² each · **8 µm pitch**, 5 µm phase |
| Boundary dashes | 681 · 20,341 µm² total |
| Glyphs (digits + A/B/C/D) | 240 · ~12.1 × 18.1 µm · 24,781 µm² total |
| Total footprint | 74,061 µm² = **13.2% areal fill** |
| Solid volume | 148,122 µm³ |

Per box: an 8 µm dot grid, dashed boundary, the box number repeated at 5 slots, and A/B/C/D at
the edge midpoints (see `reference_current_box.png`). The redundancy is what makes glyph
addressing work at all — and it is exactly what a single ArUco tag replaces.

### 1.2 The imaging system

| Property | Value | How |
|---|---|---|
| Printed features are **rigid islands** | **confirmed** | dot pitch triples 30.9→91.5 px across the series while glyph height stays 28–31 px and dot FWHM stays ~7.5 px |
| Imaged dot FWHM | 7.5 px | subpixel 2-D Gaussian fit, median over the 3 highest-λ frames |
| Effective pixel size | **disputed — see §1.3** | |
| System PSF FWHM | **1.9 or 3.2 µm** | deconvolving the known 2.125 µm CAD dot |

**Rigidity is the load-bearing result.** It confirms the premise the whole ArUco approach rests
on, and it is now verified on real prints rather than in simulation only.

It does **not**, however, remove the need for connected IDs. Rigidity means each *connected
printed piece* holds its shape; a tag whose modules form three disconnected blobs is three
independent islands that drift apart as the gel swells, and the code corrupts. Connectivity is
still what keeps a tag intact. (§3.2 resolves this more cleanly than struts do.)

### 1.3 ⚠️ GATE — the pixel-size ambiguity

Two irreconcilable values:

| Source | µm/px | ⇒ PSF FWHM | ⇒ true expansion of the six frames |
|---|---|---|---|
| OME-TIFF `PhysicalSizeX` | **0.510** | 3.18 µm | 1.97, 2.60, 3.24, 4.05, 4.86, **5.83×** |
| Dot lattice, assuming the `1.5X…` labels are true | **0.381** | 1.91 µm | 1.47, 1.94, 2.42, 3.02, 3.63, 4.36× |

This is not only a design input. **If the metadata is right, the expansion factors currently
being reported are ~30% low** — the "4.2×" frame is really ~5.8×. (This is separate from, and
survives, the +6.5%-at-4.2× drift already noted in `expansion_summary.csv`, which is a ratio and
therefore pixel-size independent.)

It also decides whether a new print run is worth doing at all: the achievable dot density
differs by **2.4×** between the two readings. **Phase 0 resolves this before anything is
fabricated.**

**Phase 0b leans toward the metadata value.** An imaged spot cannot be narrower than the
2.125 µm printed dot inside it, and the sharpest cell measured in the 1.5× frame is 5.54 px —
putting a floor of **0.383 µm/px** under the pixel size, which 0.381 marginally violates (it
would imply a PSF of exactly zero). Suggestive, *not* decisive: the margin is 0.5%, it rests on
one cell, and the 2.0× frame's floor (0.353) does not violate. See 0b §4.

---

## 2. The governing relationship

Everything reduces to one scaling law. Dots visible at expansion λ:

```
dots_in_view  ≈  ( stitched_pixels / dot_pitch_in_pixels )²
```

Both terms are pixel counts, so this holds under either calibration. It reproduces the observed
data: at 4.2× the pitch is 91.5 px, so geometry predicts ~856 dots in frame; 299 are actually
paired — a ~3× derate from the initial∩expanded overlap plus Stage-3 filtering.

**Consequence 1 — a physically larger pattern does not help.** Once the pattern overfills the
field you see a window of it, and the count in that window is independent of how much pattern
exists outside. Enlarging the printed field only helps at low λ, where dots are already
plentiful. *Do not spend print time on a bigger field.*

**Consequence 2 — with optics locked, there are exactly two levers:** more stitched pixels, and
finer pitch in pixels.

### 2.1 What each lever is worth (at 4.2×, from 299 paired dots today)

All pitch figures below use the **measured 1.75 × rule** (§2.3), not the original assumption.

| Lever | Gain | Cost | Confidence |
|---|---|---|---|
| **Stitch 2× wider (linear)** | **×4** | acquisition time only | high — pure geometry |
| Pitch 8 → 5.83 µm (1 µm dots), *if 0.510 µm/px* | ×1.9 | new print run | gated on Phase 0a |
| Pitch 8 → 3.77 µm (1 µm dots), *if 0.381 µm/px* | ×4.5 | new print run | gated on Phase 0a |
| Drop boundary dashes | ~×1.05 | free | high |
| Adaptive dot threshold (Phase C-1) | up to ×2 at the sparse end | software only | measured (0c §2.2) |
| **Flatten the focus across the field** | **×2.2** | level + refocus the sample | **indirect (0b); z-stack pending** |
| **Scale exposure with λ²** | **required above ~3×** | acquisition time only | **measured (Phase B): signal ∝ λ^-1.84** |

Stacked (stitch × pitch, excluding C-1): **299 → ~2,250** (conservative) or **~5,400**
(optimistic). At 2.0×: 1,996 → ~15,000 / ~36,000.

### 2.2 What ArUco is and is not for

Swapping glyphs → ArUco is roughly **neutral on dot count** (the freed glyph area is offset by
tag keep-out). Its value is **addressing reliability**, not density. Density comes from stitch
width and pitch. This plan should not be sold internally as a densification measure on the
strength of the tag swap alone.

### 2.3 The separation rule — **MEASURED, Phase 0c complete**

This was an assumed **2.0 × imaged-spot FWHM**. It has now been measured against the real
detector on real frames — see [`phase0/PHASE0C_SEPARATION_THRESHOLD.md`](phase0/PHASE0C_SEPARATION_THRESHOLD.md).

| | Threshold (95% of detection ceiling) |
|---|---|
| 1.5× frame (dense — the binding case) | **1.60 × FWHM** |
| 4.2× frame (sparse) | 2.27 × FWHM |
| **Adopted design rule** | **1.75 ×** (margin over 1.60; see 0c §4) |

Localisation at the working point is **RMS 0.25 px**, identical to the isolated-dot control —
resolving a close pair costs yield, not precision.

**Two findings carried forward:**

- **Sub-threshold failure is silent corruption, not lost yield.** Below ~1.4 × FWHM a pair fuses
  into a round blob that passes every filter and returns **one confident, mis-placed point**
  (2–3 px error). Only in the narrow 1.4–1.6 × band does the aspect filter reject it cleanly.
  This is why §4 R5 keeps a margin rather than running at the measured edge.
- **The threshold is frame-dependent (1.60 vs 2.27) because `detect_dots` uses a global Otsu.**
  Fixing that is worth up to **2×** more usable density at the sparse end for a software change
  and no fabrication — added as **Phase C-1**.

---

## 3. Target geometry

### 3.1 Two variants, pending Phase 0

| | Conservative (0.510 µm/px) | Optimistic (0.381 µm/px) |
|---|---|---|
| Field | 750 × 750 µm, 5 × 5 boxes of 150 µm | same |
| ArUco tag | **20.3 µm** | **12.2 µm** |
| Dot pitch (rule 1.75×, measured) | **5.83 µm** | **3.77 µm** |
| Printed dot | **2.125 µm (V1-proven anchoring)** | **2.125 µm** |
| ArUco tag | **36 µm** (Phase B) | **24 µm** (Phase B) |
| Dots (**exact, as generated**) | **8,125** | **17,825** |
| vs today (6,420) | **×1.27** | **×2.78** |
| Outer extent | **750 × 750 µm (= V1)** | **750 × 750 µm (= V1)** |

Going below a 1 µm printed dot is wasted effort — by then the imaged spot is PSF-dominated and
stops caring what was printed (0.5 µm buys only a further 4%).

### 3.2 Fiducials — **DICT_4X4_50, and no struts**

Scanning connectivity across dictionaries (`tools/scan_connected_ids.py`):

| Dictionary | Modules | IDs | 8-connected (strut-able) | **4-connected (already solid)** |
|---|---|---|---|---|
| **DICT_4X4_50** | **6** | 50 | 50 | **43** |
| DICT_4X4_100 | 6 | 100 | 99 | 87 |
| DICT_4X4_250 | 6 | 250 | 249 | 214 |
| DICT_6X6_1000 (current toolkit) | 8 | 1000 | 954 | 533 |

A 5 × 5 box grid needs **36 node IDs**. `DICT_4X4_50` offers **43 already-solid IDs** — enough
to build the entire pattern with **zero struts**. This removes the strut design, its
printability window, and its recognition-margin question from the project entirely.

Choosing the *smallest* sufficient dictionary also **maximises inter-ID Hamming distance**, which
is the main robustness objection to dropping from 6×6 to 4×4. Residual misdecode risk is caught
by the geometric cross-frame validation already in `rwtag/project.py:198`.

Headroom: `DICT_4X4_100` (87 solid) covers an 8×8 grid; `DICT_4X4_250` (214 solid) covers 10×10.

### 3.3 Boundary dashes — **removed**

They exist to lock the grid for the glyph pipeline. ArUco addresses globally, so they are
redundant. Removing them frees 20,341 µm² and their dot-exclusion zones.

*Open question:* keep a sparse subset purely as a human visual check? Costs little, aids manual
QC of a print. **Decide in workshop.**

### 3.4 Print budget — the new design is *cheaper*

| | Current | Conservative V2 | Optimistic V2 |
|---|---|---|---|
*Generator-exact figures (Phase A); these supersede the earlier estimates.*

| | Current | Conservative V2 | Optimistic V2 |
|---|---|---|---|
| Measurement dots | 6,420 | **8,125** (×1.27) | **17,825** (×2.78) |
| Dash material | 20,341 µm² | 0 | 0 |
| **Total footprint** | **74,140 µm²** | **64,696** | **100,013** |
| Volume (× 2 µm) | 148,122 µm³ | **129,392** | **200,026** |
| **vs current** | — | **87%** | **135%** |
| Areal fill | 13.2% | 11.5% | 17.8% |

**Dot size is capped by ANCHORING at the V1-proven 2.125 µm**, not by optics. Shrinking to 1 µm
would buy 24% more dots but halve each dot's gel contact area (21.5 → 9.0 µm²), risking dots that
no longer track their material point. See `PHASE_A_PATTERN_GENERATOR.md` §3.

**More measurement dots, less total material, shorter write time** — because the glyphs and
dashes were the expensive part.

This also resolves the mechanical-perturbation worry raised in workshop: total fiducial material
*drops* (24,781 → 7,400 µm²), and a 20 µm tag is comparable to the 12 × 18 µm glyphs already
being printed. Per-island size is not a regression. Areal fill falls 13.2% → 3.5%, so the
pattern should perturb the gel *less* than the current one.

---

## 4. Risks and open questions

| # | Item | Impact | Mitigation / owner |
|---|---|---|---|
| R1 | **Pixel-size ambiguity** (§1.3) | 2.4× swing in achievable density; ~30% error in reported λ | **Phase 0 blocks everything** |
| R2 | PSF may be defocus-limited, not NA-limited | If so, "optics locked" is false — worth **×2.2** | **Part-answered (0b): blur varies 38% across the field and is worse in the CENTRE — a sample/focus signature, not optics.** z-stack still needed to rule out printed-dot size variation |
| R3 | 1 µm dots at 2 µm height = aspect 2:1 posts | Possible collapse / poor adhesion on development | Phase 5 print test coupon before full field |
| R4 | 4×4 Hamming distance < 6×6 | Misdecode | Smallest dictionary + geometric validation (§3.2) |
| R5 | Pitch below threshold ⇒ **silent corruption**, not lost yield (0c §2.1) | Confident wrong points; no downstream filter recovers them | **Measured** (0c). Design rule 1.75× carries margin over the 1.60× edge |
| ~~R6~~ | ~~Rigid tags locally stiffen the gel~~ | — | **RETIRED (0d).** Stacked residual field around 205 fiducials: −0.030 ± 0.138 µm at 8–12 µm, i.e. **< 8% of full pinning**. No penalty at the 12–20 µm scale. Caveat: blind inside 8 µm |
| R7 | Stitch 2× wider ⇒ 4× tiles ⇒ photobleaching / drift over a longer acquisition | May cap the dominant lever | Measure bleaching across an existing stitch |

---

## 5. Phases

### Phase 0 — Calibration gate *(blocks all fabrication)*
Nothing is printed until these three numbers exist.

- **0a — Effective pixel size.** Calibration slide, or measure a known-length STL feature in a
  frame. Resolves §1.3, and re-issues the expansion factors for all six existing frames.
- **0b — PSF origin. ◐ PARTIAL 2026-09-22** — field analysis done on existing frames: the blur
  is **not** diffraction-limited (36–38% spread across the field in two frames, and blurrier in
  the **centre** than the edges — a domed/tilted sample or rim focus, not an objective fault).
  Flattening is worth **≈2.2×** more dots. *Not* per-tile stitch error and *not* gel scatter.
  **Still needs the z-stack** to exclude spatially varying printed-dot size, which would look
  identical in one plane. Protocol + tool ready: `phase0/PHASE0B_PSF_ORIGIN.md` §6.
- **0d — Fiducial stiffening (R6). ✅ DONE 2026-09-22** — no detectable effect: dots 8–12 µm
  from a fiducial follow uniform expansion to −0.030 ± 0.138 µm, bounding any stiffening below
  **~8% of full pinning**. Validated against a shifted-lattice null (+0.2σ). Blind inside 8 µm.
  See `phase0/PHASE0D_FIDUCIAL_STIFFENING.md`.
- **0c — Separation threshold. ✅ DONE 2026-09-22** — measured **1.60 × FWHM** (dense frame),
  design rule **1.75 ×** adopted; +31% dot yield over the assumption. Two findings carried
  forward: sub-threshold failure is silent corruption, and the global-Otsu threshold makes the
  limit frame-dependent (→ Phase C-1). See `phase0/PHASE0C_SEPARATION_THRESHOLD.md`.

**Gate:** conservative vs optimistic variant chosen; §3.1 locked.
**Deliverable:** `docs/CALIBRATION.md` + corrected λ table.

### Phase A — Pattern generator ✅ **DONE 2026-09-22**
Both variants generated and gated PASS. Exact geometry verified in floating point (0.00e+00 µm
error over 9,900 dots), 36/36 tags decode from the rendered CAD, tag map loads through
`reftags.load()` unchanged. See `PHASE_A_PATTERN_GENERATOR.md`.

*Note:* the plan's "< 0.05 µm" verify tolerance is not measurable against a raster render
(1 px = 0.167 µm at 6 px/µm); the gate now checks exact geometry in floating point and uses
raster-aware tolerances for the render round-trip. The exact check is far stronger.

Original scope:
`aruco_grid.py`: parameterised CAD generator → STL, in the idiom of `toolkit/generate_grid.py`
but targeting the real 150 µm box geometry.

- Config dataclass mirroring §3.1; both variants selectable.
- Node IDs drawn from the 43 solid `DICT_4X4_50` IDs; ID ↔ `(i, j)` map persisted.
- Dot lattice with tag keep-out; optional sparse dashes (§3.3).
- Emits the **reference tag map** in the existing `reference_tags.json` schema
  (`box_um`, `grid_n`, `dot_pitch`, `records[{tag, category, x_um, y_um}]`) so
  `rwtag/refwarp` consumes it unchanged. The 36 tags carry a new `category: "aruco"`,
  the one deliberate schema extension — **`tagmatch._by_category` must learn it in Phase C.**

**Verify:** round-trip the generated STL through `stl_glyphs.render_topdown`; recovered dot
count, pitch and tag positions match the config to < 0.05 µm. Every tag decodes from the
rendered CAD at the design pixel size.

### Phase B — Simulator retarget ✅ **DONE 2026-09-22**
Gate PASS on both variants. Caught **four real CAD bugs** (tag size 2× too small, quiet zone too
small, dots merging with dashes, circular keep-out on a square tag) plus a y-up/y-down rotation
bug in the simulator itself. See `PHASE_B_SIMULATOR.md`.

Original scope:
Point `expansion_camera_sim` at the V2 geometry.

- Replace the `toolkit` import with the Phase-A generator.
- **Fix the fixed-FOV starvation:** `fov_um` must be set so the pattern still yields dots at
  λ_max; today λ=4 and λ=5 keep **one tag** in frame and are unusable.
- **Re-tune the degradation ladder.** As shipped, L3/L4 decode ~zero and L1 is indistinguishable
  from L0 — only ~2.5 usable rungs. Re-space between L1 and L3.
- Fix `save_montage` (`tight_layout` + 2-line suptitle overlap); drop dead `render_camera_frame`.
- **Write outputs to a timestamped directory**, not in place.

**Verify:** decode ≥ 95% of in-frame tags at every λ at L0; a monotonic, gradual decode falloff
across the five levels.

### Phase C — Detection path
`rwtag/glyph` currently detects dots, dashes, lattice and glyphs. V2 replaces glyph reading with
ArUco decode; **everything downstream of registration is unchanged** — that is the point of the
existing architecture.

- New `rwtag/aruco/detect.py`: undistort → flat-field → ~~CLAHE~~ **plain inversion (no CLAHE, W1)**
  → `detectMarkers` (`errorCorrectionRate = 1.0`, edge band excluded) → node map.
- `DetectResult.model` populated directly from decoded IDs (no voting, no clubbing, no
  numbering-rule registration). Manual anchors become a fallback, not a routine necessity.
- `refwarp`, `dotfilter`, `pairing`, `project` untouched.

> **Built 2026-09-22** — `reference-warp-tagger/rwtag/aruco/` (`detect.py`, `series.py`), three
> small additive changes in `refwarp` (`warp.coarse_map` reads the box size from the fit;
> `tagmatch` gains an `aruco` category matched **by id**; `tagframe` carries decoded tags and an
> overlay `origin`), `tests/test_aruco.py` (8 tests) and the gate script
> `tools/phase_c_verify.py` → `docs/PHASE_C_DETECTOR.md`. Two things learned on the way:
> (1) **rigid islands break the corner fit** — a tag keeps its printed size while the pattern
> expands, so tag *corners* are not affine images of the design for λ ≠ 1 (three pitches off at
> 2×); the affine is fitted through tag **centres**, corners give only rotation and handedness,
> and a single-tag frame takes its scale from the dot-lattice pitch. (2) The simulator painted
> every rectangle one render-pixel too large (`cv2.rectangle` is corner-inclusive), a constant
> +0.25 px centre bias no earlier script could see through its 3 px tolerance; fixed.

**Verify:** on Phase-B synthetic frames with known truth — registration correct at every λ, tag
recovery ≥ 99%, warp residual below the Phase-B noise floor. Then the existing seven headless
suites stay green.

> **Audit note from 0d §4.** Design coords are y-up, image coords are y-down, so design → image
> is a REFLECTION, and `kabsch_rotation` forces det = +1. Fitting the wrong handedness gave a
> 638 px residual instead of 11 px — confidently wrong, not obviously broken. Check every
> design↔image fit in `refwarp`/`pairing` for this during Phase C.

### Phase C-1 — Adaptive dot threshold *(new, from 0c §2.2)* — **DROPPED (W5, W6)**
~~`lattice.detect_dots` uses a global Otsu, which makes the separation threshold depend on how
many features a frame happens to contain (1.60 × dense vs 2.27 × sparse). Replace it with a
local/adaptive threshold.~~ W5 showed the dense/sparse gap 0c measured was photon starvation
on the real 4.2× frame, not the threshold (tile-wise Otsu moves the threshold ≤ 1 px), and W6
showed it does not help efficiency either. The production global Otsu stays; the sparse-frame
weakness that remains (PSF ≥ 3.5 µm at λ = 6, W9) needs a different threshold, not a local one.

### Phase D — End-to-end on synthetic truth
> **Done 2026-09-22:** `tools/phase_d_end_to_end.py` → `docs/PHASE_D_END_TO_END.md`. The +6.5%-at-4.2× question is answered for the pipeline side: no λ-dependent bias (−0.02%, constant). The truth must go through the same estimator as the data (mean dilation of the warp in view is gel, not bias), strain must be computed after de-expansion, and design→image fits must permit the reflection — caught here for the fifth time.

Run the full 8-tab pipeline on the Phase-B set and score against ground truth.

**This is the deliverable the current workspace cannot produce**, and it is what settles the
+6.5%-at-4.2× drift: with known truth, pipeline bias and gel physics separate.

**Verify:** recovered λ within tolerance of injected λ at every level; recovered warp field
matches the injected lobes.

### Phase E — Print test coupon
> **Built (workshop Phase 5, 2026-09-22):** `tools/coupon_phase6.py` → `cad/coupon_phase6.stl`, gated; layout and pass criteria in `workshop/docs/DESIGN_REV_D.md` §7. It carries all three candidates as mini-patterns, not just one tag set.

Before the full field: a small coupon carrying the tag set, a dot-pitch ladder (spanning the
§2.3 threshold), and an aspect-ratio ladder for R3.

**Verify:** dots survive development at 1 µm; tags decode on the real microscope; the measured
separation threshold matches Phase 0c.

### Phase F — Full print + real-data validation
Print the V2 field, acquire at the same λ series **plus the wider stitch**, and run Phase D's
comparison on real frames.

**Verify:** dot pairing at λ_max beats today's 299 by the §2.1 prediction.

---

## 6. Phase gates

| Phase | Deliverable | Gate | Status |
|---|---|---|---|
| **0a** | effective pixel size | §3.1 variant chosen | **todo — blocks all** |
| **0b** | PSF origin | z-stack confirms focus vs NA | **◐ partial — field done, z-stack pending** |
| **0c** | separation threshold | rule measured, plan updated | **✅ done 2026-09-22** |
| **0d** | fiducial stiffening (R6) | bounded, risk retired | **✅ done 2026-09-22** |
| **A** | `aruco_grid.py` → STL + `reference_tags.json` | CAD round-trip clean | **✅ done 2026-09-22** |
| **B** | retargeted simulator, fixed FOV + ladder | graded decode falloff | **✅ done 2026-09-22** |
| **C** | `rwtag/aruco` detection, existing suites green | registration at every λ | **✅ done 2026-09-22** — all three candidates PASS (`docs/PHASE_C_DETECTOR.md`): 100.0% correct tags on 36/36 frames, 0.20–0.28 px RMS; suite 57/57 |
| **D** | end-to-end vs known truth | λ and warp recovered | **✅ done 2026-09-22** — all three PASS (`docs/PHASE_D_END_TO_END.md`): λ to −0.019% (flat in λ), warp field 0.01–0.06 µm RMS, strain error ≤ 0.0005 |
| **E** | print coupon | dots survive, tags decode | CAD built + gated; lab pending |
| **F** | full print + wide stitch | beats 299 dots at λ_max | todo |

---

## 7. Decisions to take in workshop

1. **Sparse dashes — keep or drop?** (§3.3) Cheap, aids human QC, costs a little dot area.
2. **Box count.** 5×5 is inherited. 8×8 (81 nodes, `DICT_4X4_100`) gives finer addressing and
   more fallback anchors at high λ, at the cost of more keep-out. Worth modelling in
   `tools/dot_budget.py`.
3. **Stitch width target.** The dominant lever (§2.1) — what is actually achievable against R7?
4. **Do we keep a glyph tier at all** as a human-readable backup, or go ArUco-only?
5. **Scope of Phase D.** Minimum viable truth test, or a full fidelity sweep across the ladder?

---

## 8. Tools in this folder

| File | Purpose |
|---|---|
| `tools/dot_budget.py` | parametric dot-yield calculator; the source of every §2/§3 number |
| `tools/scan_connected_ids.py` | connectivity scan across ArUco dictionaries (§3.2 table) |
| `docs/reference_current_box.png` | one box of the existing print, rendered from the STL |
