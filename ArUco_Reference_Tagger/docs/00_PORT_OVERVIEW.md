# ArUco Reference Tagger — port overview

*Written 2026-10-13. Plans the port of `Reference_Warp_Tagger/` (the V1 glyph tagger) into
`ArUco_Reference_Tagger/` for the V2 ArUco print. One document per phase; each phase is built,
verified on dummy frames, and signed off before the next begins.*

## 1. What the finished tool does

One sentence: **take a series of microscope images of one printed V2 marker field at different
expansion states, find every feature (ArUco tag, dash, dot) with its position, rotation and
uncertainty, give each feature its design identity, and export tables another script can use to
measure local distortion and its spatial correlation.**

The tool is a data producer. It does not decide what the distortion means. The one piece of
analysis it keeps is a visual comparison between images (overlay, vector field, distortion map)
so the operator can see that a series is sane before exporting it.

## 2. What changes from the V1 tagger, in one table

| V1 (Reference_Warp_Tagger) | V2 (ArUco_Reference_Tagger) | Why |
|---|---|---|
| Stage 2 reads printed digits and letters with a HOG + kNN classifier, clubs digits, votes box numbers, registers orientation by the numbering rule | Stage 2 decodes ArUco tags; the id **is** the node, so registration is read, not inferred | the whole point of the V2 print; removes the glyph classifier, `gridmodel`, `reader`, `stl_glyphs`, `coreg` |
| One fixed design: 150 µm boxes, 8 µm dots, hard-coded constants in `lattice.py`, `reftags.py`, `warp.py` | Design loaded from the print's own `reference_tags.json`; box pitch, node origin, dot pitch and dot size come from the file, **per box** for the spectrum print | three candidate designs plus the spectrum test print must all work |
| Auto-deskew from glyph confidence | Rotation from the decoded tags (corner order gives the frame's rotation and handedness) | no classifier |
| No per-image acquisition metadata | A metadata record per image (objective, laser, pixel size, exposure, date, time, gel, expected and derived expansion, notes), auto-filled from OME-XML where present, editable in the GUI, exported with every dataset | the analysis downstream needs the conditions each image was taken under |
| No uncertainty on positions | Every feature carries a 2×2 position covariance, every tag a rotation uncertainty and decode confidence, and both are propagated through the optics correction and the alignment to the reference image | the distortion analysis has to know what is noise |
| Exports: tagged CSV, pairing CSV, field CSV, summary CSV | A versioned export bundle: raw inputs, raw and corrected feature tables with errors, the same relative to the initial image, deviations from the design, per-feature local deformation, and the parameter record of every image | the downstream script consumes this and nothing else |
| Tab 8 Summary (measured vs expected trend, histograms, box plots) | Dropped. Tabs for pair, overlay, field stay as visual checks | analysis is done elsewhere |
| Cross-frame validation by shared-tag count and coreg rescue from a lower frame | Simple gates: handedness, warp residual, shared tags. No rescue, because ids register each frame alone | `rwtag/aruco/series.py` already does this |

Dropped outright: `rwtag/glyph/reader.py`, `classifier.py`, `gridmodel.py`, `stl_glyphs.py`,
`rwtag/refwarp/coreg.py`, `rwtag/refwarp/reftags.py` (the STL builder), `reference/glyph_knn.yml`,
`Markers CAD/`, `gui/summary_panel.py`, the OCR steps of `gui/detect_panel.py`.

## 3. The phases

| Phase | Document | Delivers | Verified on |
|---|---|---|---|
| 1 | `01_PHASE1_ARUCO_RECOGNITION.md` | A headless package + CLI that finds every ArUco tag in an image with id, centre, corners, rotation, handedness and confidence; the dummy-frame generator | dummy frames at λ 1–6 with truth |
| 2 | `02_PHASE2_FOUNDATION_AND_METADATA.md` | Package scaffold, Stage 1 optics correction, image IO, the metadata record and its GUI form, the project sidebar | real-frame round trips + dummy OME-XML |
| 3 | `03_PHASE3_DETECT_STAGE.md` | Stage 2 in the GUI: tag decode replaces OCR, design-driven grid with per-box pitch and dot size, dot and dash detection | dummy frames of all four designs |
| 4 | `04_PHASE4_FILTER_AND_TAG.md` | Stage 3 filter with V2 gates, Stage 4 tagging against the loaded design, series driver, overlays | dummy series; identity recovery vs truth |
| 5 | `05_PHASE5_ERROR_MODEL.md` | Per-feature covariance, tag rotation sigma, decode confidence; propagation through correction and alignment; validation against repeat-noise frames | dummy frames with seeds |
| 6 | `06_PHASE6_CROSS_IMAGE_VIEWS.md` | Pair, overlay, vector field and distortion map tabs, with uncertainty shown | dummy series with injected warp |
| 7 | `07_PHASE7_DATA_EXPORT.md` | The export bundle and its manifest; a reader that round-trips it | dummy series; schema tests |

Phases 1 and 2 are independent and can be built in either order. 3 depends on 1 and 2. 4 on 3.
5 touches 3 and 4 but is its own deliverable. 6 and 7 depend on 4 and 5.

## 4. Fixed decisions (apply in every phase)

**Coordinate frames.** Every position is tagged with the frame it is in. Five frames exist:

| frame | unit | definition |
|---|---|---|
| `raw` | px | the TIFF as acquired, y down, pixel centre convention of OpenCV |
| `corr` | px | after the Stage-1 geometric correction (lens un-distortion, then deskew rotation). Photometric steps (vignette, low-pass, levels) do not move points |
| `design` | µm | the print, origin bottom-left, y **up**; design → image is a reflection (det < 0) |
| `init` | px | the `corr` frame of the project's initial image. Other images reach it through a fitted alignment (rigid, or similarity when scale is wanted) |
| `expected` | px | where a feature should be in `corr` if the gel expanded uniformly: the best-fit similarity of the design onto this image. Deviation from it is the distortion signal |

Points are detected in `corr` and mapped to `raw` through the exact inverse of the geometric
correction (rotation inverse; lens forward model). Detection is not rerun on the raw frame.
This is an assumption, flagged in §7.

**Feature identity.** Tags are strings exactly as the V2 design files write them:
`aruco|N{i}_{j}|{id}`, `dash|H{j}|{m}` / `dash|V{i}|{m}`, `dot|B{N}|{di}_{dj}` with
`N = col*5 + row + 1` counted from the bottom-left. These never change across the tool.

**Design file is the source of truth.** `reference_tags.json` from the design folder, plus
`spec_sheet.json` when present. Nothing about the print is hard-coded. The loader exposes a
`Design` object with field size, node pitch, node origin, dictionary, tag size, dashes per edge,
and a per-box table `(N, col, row, x0, y0, dot_um, pitch_um, phase_um, count)`. For designs 1–3
the per-box table has one row per box with identical values.

**Uncertainty is a 2×2 covariance per feature**, stored as `sxx, syy, sxy` in px² of the frame
the position is in, and transformed with the Jacobian of every map a position goes through.
Tags additionally carry `rot_deg, rot_sigma_deg` and a decode record. Phase 5 defines them.

**Headless core, thin GUI.** `rwtag/` has no Qt. Every GUI action calls a function that a test
can call. The V1 split is kept exactly.

**No silently wrong identity.** A frame that fails a gate is rejected with the reason and
excluded from pairing and export, as in V1.

## 5. Dummy frames

All verification uses synthetic frames rendered by the V2 simulator
(`ArUco_Tracker_V2/tools/simulate_v2.py`) through a new generator script
`ArUco_Tracker_V2/tools/make_dummy_series.py` (Phase 1). It writes, for any of the four designs:

- a series of 16-bit single-page TIFFs named `{λ}X_{design}_{run}.ome.tif` with an OME-XML
  header carrying pixel size and a fabricated acquisition date, exposure and objective, so the
  metadata reader can be tested;
- `truth.json` beside them: for every frame, the true position in `raw` px of every feature,
  the true rotation of every tag, the injected warp field, the applied lens, vignette and
  rotation, and the exposure used;
- `truth_meta.json`: the metadata values written into each header.

Options: expansion list, rotation per frame, drift, warp on or off, noise level, PSF, pixel
size, number of noise seeds per state (for the Phase-5 repeat-frame tests). Output goes to
`ArUco_Tracker_V2/dummy/<design>/<run>/`. TIFFs are gitignored; the script and the truth JSON
are committed.

## 6. Final output, the thing every phase must serve

Phase 7 writes an export bundle per project. Its contents are fixed now so every earlier phase
produces what it needs:

```
export_<project>_<timestamp>/
  manifest.json                  tool version, design file hash, every parameter of every image
  images/<name>.meta.json        the acquisition metadata record per image
  images/<name>.stage1.json      optics correction + levels used
  images/<name>.detect.json      detector settings, decode report, registration, warp report
  features_raw.csv               one row per (image, feature): raw px, covariance, tag fields
  features_corr.csv              the same in the corrected frame
  features_in_initial_rigid.csv  every image's features mapped into the initial image, no scale
  features_in_initial_sim.csv    the same with the fitted scale removed
  deviation_from_design.csv      per feature: expected px under uniform expansion, deviation, residual to the TPS warp
  tags_pose.csv                  per (image, tag): centre, four corners, rotation, handedness, decode margin, all with sigma
  pairs_<init>_<exp>.csv         identity join initial ↔ expanded, both positions, both covariances
  local_deformation.csv          per paired dot: displacement, local deformation gradient F (2×2), its rotation and stretches, Jacobian, fit residual, neighbour count
  alignment_<exp>.json           the rigid and similarity fits initial ← expanded with their covariances
  rejected.json                  frames that failed a gate and why
```

Phase 7 holds the column-level schema. Columns are long-format (one row per feature per image)
so any later script can pivot them.

## 7. Open questions and the assumptions made meanwhile

These are the points where a different answer changes the work. Each phase proceeds on the
assumption listed until told otherwise.

1. **Raw positions.** Assumed: detect once on the corrected frame and map back to raw through
   the inverse geometric correction. Alternative: run the detector a second time on the raw
   frame and report both independently. The second costs double detection time but measures
   what the correction does to the detector itself.
2. **"Relative to the initial reference grid spacing image".** Assumed to mean positions
   expressed in the initial (lowest expansion) image's frame. Both a rigid map (rotation +
   translation, scale kept, as V1's overlay) and a similarity map (scale removed) are exported.
   If instead this means relative to the **design** grid, that is the `deviation_from_design`
   table, which is also exported.
3. **Metadata fields.** The list in Phase 2 is a proposal. Fields can be added at any time;
   removing one later breaks old exports, so the list should be settled before Phase 7.
4. **Photon units for the error model.** The closed-form localisation error needs the photon
   count per dot, which needs the camera gain (electrons per ADU). Assumed: gain is a metadata
   field, defaulting to 1.0 with the error reported as "relative" when unset. The empirical
   repeat-frame estimate does not need it.
5. **Which designs.** Assumed: all four (Optimistic, Medium, Conservative, Spectrum) load from
   their folders, and the spectrum's per-box dot sizes are honoured everywhere.
6. **GUI framework.** Assumed: stay on PySide6 + pyqtgraph and keep the V1 window layout
   (sidebar + tabs) so the ported panels drop in.
7. **Rotation convention.** Assumed: a tag's rotation is the angle of its design +x axis in
   the image, degrees, counter-clockwise positive in the y-down image frame, reported both per
   tag and as the frame's median. Handedness is reported separately as ±1.

## 8. Verification standard for every phase

- Headless tests under `tests/` run with `python tests/run_all.py` (the V1 runner, copied).
- Every phase adds a test that reads a dummy series and checks against `truth.json` with
  numeric tolerances written in the phase document.
- The GUI is exercised offscreen (`QT_QPA_PLATFORM=offscreen`) for at least one smoke test per
  panel: construct, load a dummy image, run the stage, read the state.
- A phase is done when its acceptance list is met and the user has opened the app on the dummy
  series and agreed.
