# Phase C — the ArUco detection path in `rwtag`

*2026-09-22. Gate: `tools/phase_c_verify.py` → `docs/phase_c_verify.{png,json}`, log in
`docs/phase_c_run.log`. Tests: `Reference_Warp_Tagger/tests/test_aruco.py` (8) — whole suite 57/57.*

**Result: PASS for all three candidates.** Every synthetic frame of the Phase-B camera model, λ 1–6,
two seeds, registers from its decoded tags with the correct handedness; **100.0% of the dots the
pipeline tags carry the right tag on every one of the 36 frames**; the tagged centres sit
0.20–0.28 px RMS from truth (0.10–0.14 µm); the series driver accepts every frame; and a frame
with only two, or only one, known tag still tags 100% correctly.

---

## 1. What was built

```
Reference_Warp_Tagger/rwtag/aruco/
  detect.py   Design (the V2 reference map) · ArucoParams (R16 settings) · decode_tags ·
              tag_handedness · fit_affine · detect_dots (noise-floored) · refine_gauss /
              refine_fit · detect() -> DetectResult
  series.py   process_frames / process_series: baseline, handedness gate, residual gate,
              shared-tag gate, loud rejection — the V1 driver's contract without coreg
tests/test_aruco.py, tests/run_all.py (the venv has no pytest; this runs every suite)
ArUco_Tracker_V2/tools/phase_c_verify.py   the gate
```

Three additive changes in `refwarp`, all V1-neutral (49 V1 tests unchanged):
`warp.coarse_map` reads the box size from `fit["box_um"]` (default 150 → V1 behaviour);
`tagmatch.tag_image` gains an **`aruco` category matched by id**, never by position;
`tagframe.detection_view` carries the decoded tags and the two overlay helpers take a lattice
`origin`. `dotfilter`, `pairing`, `strain`, `project` and the GUI are untouched.

**The contract.** `detect()` returns the same `DetectResult` the glyph path does, with
`model = {registered, kind:"aruco", reg: identity, affine, sign, tags, aruco_xy, …}` and
`fit = {O, U, V, box_um}` built so that `warp.coarse_map` *equals the tag-fitted affine* —
O = A(0,0), U = A_lin(box,0), V = A_lin(0,box). `tagframe.tag_frame` then runs unchanged: ICP
homography + TPS against the dots, seeded by that affine; `tagmatch` assigns every dot its
`dot|B{N}|{di}_{dj}` tag by nearest warped reference within 0.45 pitch. No box numbering, no
voting, no lattice registration, no coreg.

**R16 settings, as implemented.** Plain inversion, no CLAHE. `errorCorrectionRate = 1.0`.
Tags with any corner inside the un-distortion band (`edge_band_um`, = |k1|·FOV/2·1.4 — **48 µm**
for the simulator's k1 = −0.05, not the 25 µm quoted earlier) are ignored; duplicated ids are
dropped rather than guessed. Top-hat element ≥ 2× the imaged dot FWHM (13 px at PSF 1.9–2.5,
15 at 3.18). Dot area floor 12 px². Dot detections inside a decoded tag (its white modules pass
the top-hat) are masked out. Centres refined by a Gaussian-mask centroid (§3).

## 2. Two things learned

**Rigid islands break the corner fit.** The first version fitted the affine through tag
*corners* (four correspondences per tag, robust from one tag). It was 3 pitches off at 2× and
60 pitches off at 4×, and ICP then snapped to the wrong lattice — 0% correct with a
0.16 px "residual". A tag keeps its printed size while the pattern expands, so its corners are
not affine images of the design for λ ≠ 1. Now the **centres** carry the expansion (full affine
from ≥ 3 tags, similarity from 2), the **corners** carry only rotation and handedness, and a
single-tag frame takes its scale from the **dot-lattice pitch** (the dots' spacing grows with
λ, the tag does not) — the "PRINT scale" fallback is flagged in `affine_info.method`.

**Flat-fielding collapses Otsu in sparse frames.** Stage 1 divides by the vignette, amplifying
corner noise up to 10×. On SAFE at λ = 6 (665 dots in 7 Mpx) the top-hat's Otsu threshold fell
to 12 with the noise at median 10 / σ 6: 59% of detections were noise, real dots merged, 31%
efficiency, and the TPS fitted through the junk mis-tagged 30% of what remained. The same frame
*without* flat-fielding — what W9 tested — detects 96%. The fix is a floor on the threshold,
**max(Otsu, median + 5·σ_robust)** of the top-hat image (`ArucoParams.noise_k`), which restores
96.7% / 3.4% false and leaves dense frames untouched (their Otsu is far above the floor). This is
the sparse-frame-robust threshold R16 anticipated for PSF ≥ 3.5 µm; it is needed at 3.18 as soon
as frames are flat-fielded, which real Stage-1 frames are. `rwtag.glyph.lattice.detect_dots`
(V1) is unchanged; the floored version lives in `rwtag.aruco.detect.detect_dots`.

Also found, in the simulator: `cv2.rectangle` is corner-inclusive, so every rendered feature
was one render-pixel too large and every centre biased by +0.25 camera px in x and y — a
constant (+0.23, +0.29) px that only a sub-pixel test could see (every W-script used a 3 px
tolerance). Fixed in `simulate_v2.render_scene`; no workshop conclusion moves.

## 3. Numbers (seed 0; seed 1 identical to the second decimal)

`tags` = decoded / in frame · `affine` = median |A·design − truth| over in-frame dots, before the
warp refinement · `det` = detections · `tagged` = dots given a tag · `correct` = tagged dots
whose tag is right (< 3 px from that dot's truth) · `recov` = correct / in-frame truth ·
`rms` = RMS of correct centres vs truth (px; 0.51 µm/px).

| print | λ | tags | affine px | dots in | det | tagged | correct | recov | rms px | warp med |
|---|---|---|---|---|---|---|---|---|---|---|
| **OPT** | 1 | 36/36 | 1.55 | 17,825 | 17,824 | 17,824 | **100.0%** | 100% | 0.201 | 0.18 |
| | 1.5 | 34/36 | 2.44 | 17,825 | 17,829 | 17,824 | 100.0% | 100% | 0.227 | 0.15 |
| | 2 | 16/16 | 3.02 | 13,824 | 13,276 | 13,276 | 100.0% | 96% | 0.250 | 0.16 |
| | 3 | 8/8 | 3.08 | 6,112 | 5,872 | 5,870 | 100.0% | 96% | 0.253 | 0.15 |
| | 4 | 4/4 | 2.84 | 3,444 | 3,300 | 3,298 | 100.0% | 96% | 0.264 | 0.14 |
| | 6 | 4/4 | 2.82 | 1,398 | 1,370 | 1,360 | 100.0% | 97% | 0.266 | 0.09 |
| **HEDGE** | 1 | 36/36 | 1.61 | 12,825 | 12,811 | 12,811 | 100.0% | 100% | 0.210 | 0.19 |
| | 2 | 16/16 | 3.00 | 10,096 | 9,694 | 9,693 | 100.0% | 96% | 0.254 | 0.16 |
| | 4 | 4/4 | 2.87 | 2,515 | 2,423 | 2,409 | 100.0% | 96% | 0.270 | 0.13 |
| | 6 | 4/4 | 2.92 | 998 | 983 | 972 | 100.0% | 97% | 0.278 | 0.01 |
| **SAFE** | 1 | 36/36 | 1.59 | 8,625 | 8,457 | 8,455 | 100.0% | 98% | 0.226 | 0.21 |
| | 2 | 16/16 | 3.02 | 6,961 | 6,641 | 6,635 | 100.0% | 95% | 0.266 | 0.18 |
| | 4 | 4/4 | 2.99 | 1,744 | 1,677 | 1,652 | 100.0% | 95% | 0.283 | 0.13 |
| | 6 | 4/4 | 2.89 | 665 | 664 | 647 | 100.0% | 97% | 0.281 | 0.01 |

Reading it:

- **Registration.** Handedness −1 on every frame (a y-up design in a y-down image *must* be a
  reflection; `tag_handedness` reads it from the corner order of each tag and every tag agreed).
  The tag affine alone predicts every in-frame dot to 1.5–3 px — the residual is the injected
  non-uniform warp (2 µm × λ), which the TPS then absorbs.
- **Tagging.** 100.0% on all 36 frames: not one dot mis-tagged. *Recovered* (96–97% beyond 1.5×)
  is W9's detection efficiency — the ~4% lost to crowding at the 1.75× rule — not a tagging loss.
- **Precision.** 0.20–0.28 px RMS ≈ 0.10–0.14 µm in the image, through vignette, lens
  un-distortion, rotation resampling and L2 noise. Gaussian-mask refinement vs the plain
  centroid: 0.233 → 0.201 px (OPT, λ 1), 0.300 → 0.226 (SAFE); W7's least-squares fit reaches
  0.193 / 0.217 at 15× the cost. **`refine="gauss"` is the default**; `"fit"` is kept for
  validation.
- **`warp.per_det_median` is not accuracy.** It falls to 0.01 px at λ = 6 because a TPS through
  a few hundred points interpolates them exactly; the truth RMS (0.28 px) is the real number.
  Downstream QC should read `matched_frac` and the tag counts, not the median.
- **Sparse registration.** The λ = 6 frame with the map cut to 2 known tags: similarity fit, 100%
  correct; to 1 known tag: single-tag + lattice scale, affine 12–27 px off (≈ 0.2–0.4 pitch at
  λ = 6) but ICP recovers it, 100% correct. A frame with one decodable tag is still usable.
- **λ = 1.5 shows 34/36**: two corner tags sit inside the 48 µm edge band with the 5° rotation
  and are deliberately ignored; the truth mask counts centres. Not a decode failure.

## 4. Using it

```python
from rwtag.aruco import Design, ArucoParams, series as AS
design = Design.load("ArUco_Tracker_V2/cad/aruco_grid_optimistic.reference_tags.json")
params = ArucoParams(um_per_px=0.510, psf_fwhm_um=P,            # Phase-1 numbers
                     edge_band_um=abs(k1) * FOV_um / 2 * 1.4)   # k1 from Stage 1
frames = AS.process_series(find_series(folder), design, params)  # ascending λ, sidecar Stage 1
table = AS.pair_table(frames)                                    # {tag: {λ: (x, y)}} -> pairing/strain
```

Per frame: `f.ok`, `f.reason`, `f.tags` (`dot|…`, `dash|…`, `aruco|…`), `f.warp`,
`f.det.model["summary"]` (tags used, px/µm, handedness). The coupon map
(`cad/coupon_phase6.reference_tags.json`) loads the same way; its regions are addressed by their
own tags.

**Not done here:** GUI wiring. `gui/detect_panel.py` drives the glyph steps; the ArUco path is
headless (`project.run_stages` still calls the glyph detector). A "V2" mode in the detect panel
that calls `rwtag.aruco.detect` and skips the read/solve steps is a small, separate change.

## 5. Gate

| check | OPT | HEDGE | SAFE |
|---|---|---|---|
| every frame registered · handedness −1 · ≥ 1 tag | ✅ | ✅ | ✅ |
| tag affine < 0.5 pitch from truth | ✅ | ✅ | ✅ |
| tag correctness ≥ 99% every frame | ✅ 100.0% | ✅ 100.0% | ✅ 100.0% |
| RMS of correct tags < 0.5 px | ✅ 0.20–0.27 | ✅ 0.21–0.28 | ✅ 0.23–0.28 |
| series driver accepts every frame | ✅ | ✅ | ✅ |
| 2-tag and 1-tag maps ≥ 99% correct | ✅ | ✅ | ✅ |
| **Phase C** | **PASS** | **PASS** | **PASS** |

Phase D (end-to-end vs known truth with the warp switched on *between* frames, λ and the warp
field recovered) is the next desk phase; its truth machinery is this script's.
