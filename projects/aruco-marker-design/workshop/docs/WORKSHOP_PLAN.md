# Final ArUco Nanoscribe Design — Workshop Plan (Rev D)
### Re-running the `hydrogel_marker_analysis` design workshop against the *measured* microscope

**Project:** `aruco-marker-design/workshop/` · **Redoes:** `hydrogel_marker_analysis` (Rev C, 2026-07-15) with real inputs
**Builds on:** Phase 0 measurements, Phase A generator, Phase B simulator (all in `aruco-marker-design/`)
**Written:** 2026-09-22 · **Status: PLAN — Phase 1 is at the microscope, Phases 2–5 are simulation and can start now**
**Direction set by the user: optimistic-leaning.** The workshop's job is to find the *most* optimistic design the measured optics can actually support, and to say plainly what it depends on.

> **Delivery model** (unchanged): one phase at a time, each verified before the next begins.
> Same shape as the July workshop — one script per question, one figure per script, findings
> consolidated at the end into `FINDINGS.md` and a `DESIGN_REV_D.md` recipe.

---

## 0. Why Rev C has to be redone, not extended

Rev C sized everything for **~100 nm/px and a confocal PSF (0.2–0.3 µm)**. The instrument
actually in use is **~510 nm/px with a 2.7–3.2 µm PSF** — 5× coarser sampling and ~10× more
blur. Rev C's own sizing table (§4) stops at 325 nm/px and says "tags large → bigger boxes or
AprilTag"; the real system is past the end of that table.

So every number in Rev C §4 and §10 (3.5 µm tags, 30 µm boxes, 3 µm checkerboard) is wrong for
this microscope by roughly an order of magnitude. The *method* — one simulation per design
question, robustness sweeps, a consolidated findings doc — is exactly right and is reused here.
Only the inputs change. That is what "the same exact analysis with the greater analysis of the
microscope" means in practice.

---

## 1. The microscope requirements — measured, not assumed

Every input below was measured on the real six-frame series or the real STL. Each enters the
design as a specific formula, so changing a measurement re-derives the design automatically
(`tools/aruco_grid.py` already works this way).

| # | Quantity | Value | Source | Status | Enters the design as |
|---|---|---|---|---|---|
| R1 | Effective pixel size | **0.510 µm/px** (metadata) — or 0.381 if the filename labels are true | Phase 0a | ⛔ **GATE** — 2.4× swing | everything in px; 0b leans to 0.510 (pixel-size floor 0.383) |
| R2 | System PSF | **2.7 µm** (edge method) / 3.2 µm (dot method); **~1.9 µm if focus is flattened** | 0b, edge-spread | ◐ field done, z-stack pending | tag size, quiet zone, dot pitch |
| R3 | Blur is fixable | not diffraction-limited: 36–38% spread, worse in the *centre* → domed/tilted sample | 0b | ◐ | decides OPT vs SAFE |
| R4 | Dot separation | 1.60 × imaged FWHM measured (0c); **1.64–1.86 × at PSF 1.9–3.2 on synthetic frames (W5)**; **1.75 × adopted** — OPT sits at the edge under the production detector, use the tile detector or 1.85× | 0c, W5 | ✅ | `pitch = 1.75·√(dot² + PSF²)` |
| R5 | Tag decodability | **module ≥ 1.45 × PSF FWHM measured in-scene (W1); 1.75× adopted** = the minimum sized for a PSF 20% worse than design. Phase B's 1.8× was inflated by CLAHE in the decoder | W1 | ✅ | `tag = 6 · 1.75 · PSF` → OPT 21, HEDGE 27, SAFE 34 µm |
| R6 | Quiet zone | **not an ArUco constraint** (W2: 100% at ¼ module). Set by the *dot detector*: **quiet = pitch − dot** (≈ 0.8 module) so a dot never merges with a tag | W2 | ✅ | dot/dash keep-out |
| R7 | Signal vs expansion | **∝ λ⁻¹·⁸⁴** — 15% left at 4.2×; **empirically (W6): fixed exposure loses every dot at 3×, ∝ λ at 4×, ∝ λ² holds 98–100% to 6×, regardless of dot size** | Phase B, W6 | ✅ | **exposure ≥ (λ/1.5)² × reference** (mandatory) |
| R8 | Dot anchoring | 2.125 µm is the only size *proven* to track to 4.2×; 1 µm halves gel contact | V1 data + user | ✅ | dot ≥ 2.125 µm |
| R9 | Fiducial stiffening | < 8% of full pinning at 12–20 µm; **test sensitivity at 23–34 µm ≈ 0.7% (W4)** | 0d, W4 | ✅ test calibrated; real value from the coupon | coupon check |
| R10 | Rigid islands | features keep printed size; only spacing grows | Phase 0 | ✅ | simulator physics |
| R11 | Field of view | 1365 µm stitch (2676 px); wider is possible | user | ✅ | dots-in-view law |
| R12 | Expansion range | true λ 1.97–5.83 (if R1 = 0.510) | 0a-dependent | ◐ | λ sweep 1–6 |
| R13 | Footprint | **750 × 750 × 2 µm**, same as V1 | user | ✅ | `--fit inside` |
| R14 | Tiers | ArUco + grid markers + dots | user | ✅ | three tiers, dashes 8.125 × 2.125 |
| R15 | Tag integrity | rounded: necks at diagonal pinches + fillets; **decode flat in λ 1–6 with exposure ∝ λ²; any payload module loss survivable; border ring must stay intact** | user + W3 | ✅ | leaf-free IDs assigned first |
| R16 | Detector settings (Phase C) | **no CLAHE** (W1) · **`errorCorrectionRate = 1.0`** (W3; default = zero correction for 4×4) · exclude the **un-distortion band** \|k1\|·FOV/2·1.4 at the frame edge (**48 µm** at k1 = −0.05, not the ~25 quoted from W3) · **Gaussian-mask dot refinement** (W7; within 4% of the LSQ fit at 1/15 the cost) · per-PSF top-hat ≥ 2× imaged FWHM (W5/W9) · **noise-floored threshold max(Otsu, median + 5σ) — needed at PSF 3.18 already, once frames are flat-fielded** (Phase C) | W1, W3, W5, W7, W9, **Phase C** | ✅ **built** `rwtag/aruco` | `rwtag.aruco.ArucoParams` |

**R1 and R2 are the whole game.** Everything else is settled. R1 sets the scale; R2 sets which
candidate is printable. Phase 1 exists to close them and is the only lab time this plan needs
before fabrication.

---

## 2. The design space — and what is already eliminated

| Axis | Options | Eliminated (with evidence) |
|---|---|---|
| Fiducial dictionary | `DICT_4X4_50` · `DICT_4X4_100` · `DICT_5X5_50` · AprilTag 16h5 · AprilTag 36h11 | **16h5**: only 27 strut-free IDs, 36 needed · **36h11**: 8 modules → tags 33% larger for no gain · **5X5_50**: 7 modules, 33 solid IDs |
| Tag size | derived from R5 | **≤ 21 µm** at the measured PSF: 74% in-scene (W1) — marginal; the earlier "47%" was a CLAHE artefact |
| Box grid | 3×3 · 4×4 · **5×5** · 6×6 over 750 µm | none — but §3 shows it barely matters (+12% dots from 5×5→3×3) |
| Fine feature | **dots** · crosses · saddle corners (Rev C's suggestion) | **W7: dots win 2–3× on field precision; saddles unresolved at this PSF (0.5 µm RMS) and structurally two islands. Cross-4 = mechanical fallback only** |
| Dot size | **2.125** · 3.0 µm | **1.0 µm**: halves anchoring, 4.5× fewer photons |
| Dot pitch | derived from R4 | — |
| Grid markers | **on** (V1 geometry) · sparse · off | off (user wants three tiers) |
| Quiet zone | derived from R6 · two-channel imaging | **two-channel**: buys 0 dots (W2) — dropped |
| Exposure | fixed · **∝ λ²** | **fixed**: SNR 2.1 at 6× (Rose limit ~5) |
| Tag rounding | **necks + fillets** · sharp | sharp (34 pinches = fracture initiators) |

---

## 3. Candidate matrix — computed today (`scripts/w0_candidate_matrix.py`)

750 µm field, three tiers, 2.125 µm dots unless noted, exposure ∝ λ². *@4×/@6×* = paired dots
expected in the current 2676 px stitch (scaling law × the measured 0.33 pairing derate).
*SNR6×* = per-dot SNR at 6× with compensation.

| id | PSF | grid | tag | quiet | pitch | **dots** | fill | @4× | @6× | SNR6× | |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **A** | 3.18 | 5×5 | 35 | 5.8 | 6.69 | **8,625** | 14.2% | 858 | 381 | 34 | **SAFE** — works today |
| B | 3.18 | 4×4 | 35 | 5.8 | 6.69 | 8,960 | 12.2% | 858 | 381 | 34 | |
| C | 3.18 | 3×3 | 35 | 5.8 | 6.69 | 9,657 | 11.1% | 858 | 381 | 34 | |
| **D** | 2.50 | 5×5 | 27 | 4.5 | 5.74 | **12,825** | 15.1% | 1,165 | 518 | 34 | **HEDGE** — half the focus fix |
| E | 2.50 | 4×4 | 27 | 4.5 | 5.74 | 13,200 | 14.1% | 1,165 | 518 | 34 | |
| **F** | 1.91 | 5×5 | 21 | 3.5 | 5.00 | **17,825** | 18.0% | 1,537 | 683 | 34 | **OPT** — the user's preference |
| G | 1.91 | 4×4 | 21 | 3.5 | 5.00 | 18,240 | 17.2% | 1,537 | 683 | 34 | |
| H | 1.91 | 5×5 | 21 | 3.5 | 6.22 | 10,925 | 21.2% | 992 | 441 | 68 | 3 µm dots |
| I | 2.50 | 4×4 | 27 | 4.5 | 6.83 | 8,960 | 17.9% | 823 | 366 | 68 | 3 µm dots |

What the matrix already settles:

- **PSF is the only lever that matters.** 3.18 → 1.91 µm *doubles* the dots (8.6k → 17.8k).
  Nothing else in the design space comes close. The optimistic layout is therefore not a
  geometry choice — it is a bet on R2/R3, and Phase 1 decides it.
- **Box count is nearly irrelevant** (+12% from 5×5 → 3×3). Keep 5×5 for addressing
  redundancy at high λ, where only 4 tags are in frame.
- ~~**3 µm dots are insurance, not an upgrade.**~~ **W6: they are not even insurance.** With
  fixed exposure, 3.0 µm dots fall off the same cliff at 3× as 2.125 µm dots (3% detection);
  the detector fails on contrast before photon statistics matter. Candidates H and I are
  retired. **Exposure ∝ λ² is mandatory in every candidate**, and dot size stays at the
  anchoring-proven 2.125 µm.
- **`DICT_4X4_50` is the right dictionary**: 43 strut-free IDs for 36 nodes, smallest module
  count, largest inter-ID Hamming distance.
- ~~Tag size differs slightly from the built V2 variants…~~ **Settled by W1:** the in-scene
  minimum is module ≥ 1.45 × PSF; adopted 1.75× → OPT 21 (23 with full 1.2× margin), HEDGE 27,
  SAFE 34 µm. Tag size barely changes the dot count (±300), so it does not affect the choice
  between candidates. Also from W1: **no CLAHE in the decoder** (Phase-C requirement).

**Three candidates go forward: OPT (F), HEDGE (D), SAFE (A).** The workshop's output is which
one to print, decided by the rule in §5.

---

## 4. The experiments

Same shape as `hydrogel_marker_analysis/scripts/`: one script per question, one figure per
script, a pass criterion stated before it runs. Scripts reuse `tools/aruco_grid.py` and
`tools/simulate_v2.py`; nothing is re-implemented.

### Phase 1 — Close the two open inputs *(lab, ~20 min at the scope; blocks fabrication only)*

| | Deliverable | Closes |
|---|---|---|
| **1a** | Calibration slide, or one known STL length measured in a frame | R1 — and re-issues all six expansion factors (likely ~30% higher than the labels) |
| **1b** | Z-stack, 0.5 µm steps over ±10 µm, once at pattern centre and once at a corner → `tools/psf_origin.py --zstack` | R2/R3 — whether the 3 µm blur is focus (OPT reachable) or the objective (SAFE) |
| **1c** | *Cheap pre-check:* level the sample, refocus on the pattern centre, one frame, `psf_origin.py --field` | if the 38% spread collapses, R3 is confirmed at zero cost |

Phases 2–4 do **not** wait on this: they run every candidate across PSF ∈ {1.9, 2.5, 3.2} so
the answer is ready the moment Phase 1 lands.

### Phase 2 — Fiducial tier

| Script | Question | Method | Figure | Pass |
|---|---|---|---|---|
| **W1** `tag_size_sweep.py` | How big must a tag be, with margin? | All 36 real IDs, real px size, real noise, **plus vignette and lens un-distortion** (the Phase-B sweep lacked both, and in-scene decode was ~2× worse than isolated); sweep tag 18–40 µm × PSF 1.5–3.5 × {4X4_50, 4X4_100, 5X5_50} | `tag_size_sweep.png` | ≥95% at design PSF **and** ≥1 decoded tag/frame at 1.2× design PSF; fixes the rounding margin |
| **W2** `quiet_zone_sweep.py` | How much clear space around a tag? | λ = 1 (dots at their closest), sweep quiet 0.5–2.5 modules, real dot crowding; also a two-channel variant (dots in a second colour → no crowding) | `quiet_zone_sweep.png` | smallest quiet with ≥95% at λ=1; two-channel gain quantified |
| **W3** `tag_integrity_expansion.py` | Does a rounded rigid tag survive λ 1–6? *(Rev C's `simulate_conjoined_spread` redone)* | Rigid-island model through λ 1–6 under the measured PSF; then **fault injection** — drop one module, break one neck — and check decode | `tag_integrity.png` | decode unchanged across λ; ID survives any single-module loss |
| **W4** `tag_stiffening_scale.py` | Does a 27–35 µm tag pinch the gel? | Re-run the 0d stacked-residual test on Phase-B synthetic frames with injected stiffening of 0 / 5 / 20% to calibrate sensitivity; the *real* answer needs the coupon (Phase 6) | `stiffening_sensitivity.png` | test proven able to detect ≥5% pinning at this tag size |

### Phase 3 — Fine tier

| Script | Question | Method | Figure | Pass |
|---|---|---|---|---|
| **W5** `dot_separation_vs_psf.py` | Does the 1.75× rule hold at each PSF? | 0c's spliced-pair method on synthetic frames at PSF 1.9 / 2.5 / 3.2, **with and without the adaptive threshold (Phase C-1)** | `separation_vs_psf.png` | threshold within 1.6–1.8× at every PSF; C-1 closes the dense/sparse gap |
| **W6** `dot_size_photons.py` | Which dot size survives λ_max? | SNR vs λ vs dot {2.125, 2.5, 3.0} vs exposure {fixed, ∝λ, ∝λ²}, using the measured λ⁻¹·⁸⁴ law and 27.4 SNR anchor | `dot_photons.png` | SNR ≥ 5 at λ = 6 for the chosen dot + exposure policy |
| **W7** `dot_vs_cross.py` | Are Rev C's crosses/saddles better than dots here? | Localisation RMS of dot vs cross vs saddle corner under PSF 1.9–3.2 with noise; anchoring area per feature | `dot_vs_cross.png` | pick the feature with best RMS *per µm² of anchoring*; expected: dots win at this blur |
| **W8** `lattice_density_field.py` | Does density buy strain precision? *(Rev C's `simulate_rigid_spread` redone)* | Inject a known warp field, run the full pipeline on OPT/HEDGE/SAFE, fit local affine over windows; strain noise vs density (the 1/√N argument) | `density_vs_strain_noise.png` | recovered field matches injected to localisation precision; noise scales as 1/√N |

> **Phase C (2026-09-22): built and gated** — `reference-warp-tagger/rwtag/aruco/`, all three candidates PASS against synthetic truth (`aruco-marker-design/docs/PHASE_C_DETECTOR.md`). Two corrections on the way: tag *corners* are rigid and cannot carry the expansion (affine through centres); flat-fielded sparse frames need a noise-floored threshold.
>
> **Phase D (2026-09-22): done, all three candidates PASS** (`aruco-marker-design/docs/PHASE_D_END_TO_END.md`): λ recovered to −0.019% at every level, warp field to 0.01–0.06 µm, strain to ≤ 0.0005. The note below was followed (reference rendered without warp).
>
> **Note for Phase D (from W8):** the simulator's warp is a *print distortion* (λ·warp in every
> frame, uniform between frames). To test non-uniform-expansion recovery, render the reference
> without warp (as W8 does) or add a λ-dependent warp term; and always un-distort before
> measuring, as Stage 1 does.

### Phase 4 — Whole pattern

| Script | Question | Method | Figure | Pass |
|---|---|---|---|---|
| **W9** `candidate_montage.py` | Which candidate works at which PSF? | `simulate_v2` on OPT / HEDGE / SAFE × PSF {1.9, 2.5, 3.2} × λ 1–6, exposure ∝ λ², ladder relative to design | `candidate_grid.png` + decode table | **the decision table for §5** |
| **W10** `fov_and_stitch.py` | How wide should the stitch be? | dots-in-view vs λ vs stitch width, per candidate | `stitch_width.png` | width at which ≥ 1,000 paired dots survive at λ_max |
| **W11** `print_budget.py` | What does each candidate cost to print? | footprint, volume, triangle count; **DeScribe dry-run of one tag** for the coincident-face question | `print_budget.png` | STL accepted by DeScribe; volume vs V1 stated |

> **From W11:** every candidate prints in roughly V1's time (OPT 1.40×, HEDGE 1.15×, SAFE 1.05×
> the scan length). Box-style STLs have ~1,400 coincident internal faces in the tags; merged-outline
> variants with none exist for all three. **User: open `cad/test_tag_optimistic_boxes.stl` and
> `_merged.stl` in DeScribe and report which slices cleanly.**

### Phase 5 — Decision and Rev D *(desk)* — **done 2026-09-22**

- `FINDINGS.md` — one paragraph per script, in the July format. ✅
- `DESIGN_REV_D.md` — the recipe, in Rev C's §10 format: pattern, realisation, imaging
  (exposure policy, stitch width), pipeline, cross-checks. ✅ All three candidates carried with
  the §5 mapping; the choice is a table look-up once Phase 1b gives the PSF.
- CAD emitted and gated (Phase A) for **all three** candidates — `cad/aruco_grid_{optimistic,
  hedge,conservative}` — so the print needs no rebuild after the choice. ✅
- Coupon designed, built and gated: `tools/coupon_phase6.py` → `cad/coupon_phase6.stl`. ✅

### Phase 6 — Coupon, then full print *(lab)*

`cad/coupon_phase6.stl` (750 × 750 µm, same envelope and stitch as the full print; Rev D §7):
**all three candidates as one-box mini-patterns** with distinct ids (so decode at the real PSF
is compared side by side), a **dot-pitch ladder** 3.5 → 9.0 µm in eight 70 µm patches straddling
the W5 threshold (4.6–6.6 µm), a **dot-size ladder** 2.125 / 2.5 / 3.0 µm at the HEDGE rule, and
**two stiffening fields** (260 µm of HEDGE-pitch dots around one 34 µm and one 23 µm tag) for the
0d/W4 test; every ladder patch has its own 27 µm tag, and an L datum fixes handedness. 24 of the
43 solid ids. Image through λ 1–λ_max with exposure ∝ λ²; pass criteria per region in Rev D §7.
Then the full field — the candidate the coupon's mini-patterns and §5 agree on (coupon wins).

---

## 5. Decision rule — how the final design gets chosen

Written down *before* the results exist, so the choice cannot drift toward the preferred answer.

1. Phase 1b gives the PSF, `P`, after the best available focus.
2. From W9, take the **most optimistic candidate** whose decode meets the Phase-B gate at
   PSF = `P`, **and** keeps ≥ 1 decoded tag per frame at 1.2 × `P`.
3. ~~Expected~~ **Measured mapping (W9): `P` ≤ 1.9 → OPT · 2.0 < `P` ≤ 2.5 → HEDGE · ~3.2 → SAFE ·
   `P` ≥ 3.8 → retune the detector first (sparse-frame Otsu collapse), no print chosen.**
4. Exposure ∝ λ² is mandatory regardless (W6). If the acquisition cannot support it, dot size
   rises to 3.0 µm (H/I) and the candidate drops one rung.
5. Any candidate that fails W3 (integrity) or W11 (DeScribe) is out regardless of density.

**What "optimistic-leaning" buys under this rule:** the plan deliberately carries HEDGE as a
named candidate so that a *partial* focus fix still yields a design 50% denser than SAFE,
rather than collapsing to SAFE the moment OPT's 1.9 µm target is missed.

---

## 6. Gates

| Phase | Deliverable | Gate | Status |
|---|---|---|---|
| **W0** | candidate matrix | computed, three candidates named | **✅ done 2026-09-22** |
| **1** | pixel size, PSF origin | R1 and R2 closed | ⛔ lab |
| **2** | W1–W4 | tag size with margin, quiet zone, integrity, stiffening sensitivity | **✅ complete 2026-09-22** (W3 SAFE: 0.14% misdecode risk documented) |
| **3** | W5–W8 | separation per PSF, dot size, feature type, density → strain | **✅ complete 2026-09-22** (density payoff confirmed end to end: N^−0.56; SAFE cannot resolve windows < 25 µm, OPT can to 12) |
| **4** | W9–W11 | decision table, stitch width, print budget | **✅ complete 2026-09-22** (DeScribe dry run of `cad/test_tag_*` left to the user) |
| **5** | FINDINGS, DESIGN_REV_D, CAD + gate, coupon plan | design chosen by §5 rule | **✅ complete 2026-09-22** — choice is a §5 table look-up on the Phase-1b PSF; all three CAD files and the coupon are gated |
| **6** | coupon, full print | real decode/anchoring/stiffening confirmed | lab |

---

## 7. Decisions still the user's

1. ~~**Two-channel imaging**~~ — **closed by W2: no gain**, the quiet zone was never a constraint
   once the decoder was fixed. No second channel needed.
2. **Maximum λ to design for.** 6× is assumed; if 4× is the real ceiling, SNR and stitch
   requirements relax considerably.
3. **Can exposure scale with λ²?** Photobleaching over the series is the risk; if not, H/I
   (3 µm dots) become the fallback and W6 needs a bleaching term.
4. **Box grid** — 5×5 kept by default; say if 4×4 is preferred (it changes little).

---

## 8. Layout

```
aruco-marker-design/workshop/
  docs/     WORKSHOP_PLAN.md (this) · FINDINGS.md · DESIGN_REV_D.md ✅
  figures/  … · coupon_phase6.png
  ../tools/coupon_phase6.py → ../cad/coupon_phase6.*   (Phase 6 coupon)
  scripts/  w0_candidate_matrix.py ✅ · w1…w11 as above
  figures/  one PNG per script
```

Tools stay in `aruco-marker-design/tools/`; the workshop scripts import them.
