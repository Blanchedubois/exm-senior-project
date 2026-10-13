# Phase 2 — Foundation: package scaffold, Stage 1 optics, image metadata, project sidebar

*Goal: the app opens, a project of images can be built, each image can be corrected with the
V1 Stage-1 tools, and each image carries an editable acquisition-metadata record that is saved
beside it and travels into every export. Nothing about markers yet.*

## 1. What to port, file by file

| V1 source | target | action |
|---|---|---|
| `run.py` | `run.py` | copy; rename the window title |
| `requirements.txt` | `requirements.txt` | copy; drop `scikit-image` (HOG) and the unused `trackpy`, `pyarrow`; keep `pandas` for export |
| `Launch Reference-Warp Tagger.command` / `.bat` | `Launch ArUco Reference Tagger.command` / `.bat` | copy; change the venv folder name to `aruco_reference_tagger` so the two apps' environments do not collide; update the title text |
| `rwtag/__init__.py`, `rwtag/types.py` | same paths | copy; add `ImageMeta` to `PipelineState` (§2) |
| `rwtag/correct.py` | same | copy unchanged; add `inverse_geometric(points, params, shape)` (§3) |
| `rwtag/io.py` | same | copy; add `read_ome_metadata()` and the `.rwmeta.json` sidecar helpers (§2) |
| `rwtag/project.py` | same | copy `ImageEntry`, `Project`, persistence; **remove** `run_stages` / `run_stages_validated` (they return in Phase 4 on the ArUco path); `ImageEntry` gains `meta` and `glyph_manual` goes |
| `gui/app.py` | same | copy; remove the classifier, deskew signal, Stage 2–8 panel wiring for now; keep toolbar, log dock, sidebar, Stage-1 tab; add the metadata dock (§4) |
| `gui/state.py`, `gui/canvas.py`, `gui/widgets.py` | same | copy unchanged (`glyph_manual` removed from state) |
| `gui/correct_panel.py` | same | copy; the "Auto-deskew (from glyph grid)" button becomes "Auto-deskew (from ArUco tags)", enabled once Phase 3 lands |
| `gui/project_panel.py` | same | copy; the stage ticks stay four wide |
| `tests/run_all.py`, `test_correct.py`, `test_io.py`, `test_project.py` | same | copy; `test_project.py` loses the `run_stages` test until Phase 4 |
| `docs/STAGE1_IMPLEMENTATION_PLAN.md` | not ported | the design decisions in it still hold; this document supersedes it |

Everything in `rwtag/correct.py` is detector-agnostic and validated by round-trip tests; it is
ported byte for byte.

## 2. The image metadata record

### 2.1 Fields

`rwtag/meta.py` defines `ImageMeta`, a dataclass serialised to `<image>.rwmeta.json` beside the
TIFF (same pattern as the `.rwsession.json` sidecar). Every field has a `source` so the export
says whether a value came from the file header, the user, or the pipeline.

| group | field | type | from |
|---|---|---|---|
| identity | `sample_id`, `print_design` (optimistic / medium / conservative / spectrum), `print_batch`, `gel_type` (MAGNIFY / TExM / other), `operator` | str | user |
| state | `expansion_expected` (λ the operator set up), `expansion_control` (ionic strength in mM, or iris position, free text + value), `state_label` (the `1.5X` from the filename), `time_since_expansion_min` | float / str | filename + user |
| derived | `expansion_derived` (λ measured by the pipeline from tag centres, Phase 3), `expansion_derived_sigma`, `rotation_derived_deg`, `handedness` | float | pipeline, read-only in the GUI |
| optics | `objective_name`, `magnification` (e.g. 100), `numerical_aperture`, `immersion`, `um_per_px`, `um_per_px_source` (header / user / calibrated), `binning` | str / float | header then user |
| illumination | `laser_wavelength_nm`, `laser_power_mw` or `laser_power_pct`, `excitation_filter`, `emission_filter`, `exposure_ms`, `gain_e_per_adu`, `camera_offset_adu` | float / str | header then user |
| acquisition | `date` (ISO), `time` (ISO), `timezone`, `stitched` (bool), `n_tiles`, `stitch_software`, `z_slices`, `z_step_um` | | header then user |
| sample | `cells_present` (bool), `cells_description` (which cells, free text) | bool / str | user |
| free | `notes` | str | user |

`gain_e_per_adu` and `camera_offset_adu` feed the Phase-5 photon-count estimate. Fields the user
asked for by name (lens, laser, date, time, derived expansion) are all present; the rest are the
ones the downstream analysis will want when comparing conditions.

### 2.2 Auto-fill from OME-XML

`io.read_ome_metadata(path)` uses `tifffile`'s `ome_metadata` and maps:
`Pixels/@PhysicalSizeX` → `um_per_px` (source header); `Image/AcquisitionDate` → date, time;
`Objective/@NominalMagnification`, `@LensNA`, `@Immersion`; `Channel/@ExcitationWavelength`,
`@EmissionWavelength`; `Plane/@ExposureTime`; `Detector/@Gain` if present. Missing elements
leave the field empty, never guessed. Plain TIFFs without OME-XML yield an empty record except
`state_label` from the filename.

The filename parser `refwarp.series.parse_label` ("1.5X…" → 1.5) is kept and moved to
`rwtag/io.py`.

### 2.3 Where it lives

`PipelineState.meta: ImageMeta`. `ImageEntry.ensure_loaded()` reads the sidecar if present,
else runs the OME auto-fill once and writes the sidecar. `Project.save()` also embeds every
image's record in `project.rwproj.json` so the project file alone is a complete description.

## 3. Mapping corrected positions back to raw

`correct.inverse_geometric(points_corr, params, shape)` returns the same points in the raw
frame: undo the rotation exactly (rotate by `−rotate_deg` about the same centre), then apply the
**forward** Brown–Conrady model `r_d = r (1 + k1 r² + k2 r⁴)` about the distortion centre. The
forward model is closed-form, so this is exact to floating point; the un-distortion used on the
image is its numeric inverse, and the round trip `raw → corr → raw` is tested to 1e-3 px.

Also provided: `geometric_jacobian(points_corr, params, shape)`, the 2×2 Jacobian of `corr →
raw` at each point, used by Phase 5 to carry covariances between frames.

## 4. GUI additions

- **Metadata dock** (right-hand dock, collapsible): a form over `ImageMeta` grouped as in §2.1.
  `cells_present` is a checkbox that enables the `cells_description` text box beside it.
  Header-sourced values show a small "from file" badge; editing one changes its source to
  "user". Derived fields are read-only and grey until Phase 3 fills them. "Apply to all images"
  copies the optics and illumination groups to every image in the project (sample and state
  fields stay per image). Changes autosave to the sidecar on selection change and on project
  save, as the Stage-1 params do.
- **Add images…** parses the label from the filename as V1 did and opens the metadata form on
  the first image added with the header-derived values filled in.
- **Project sidebar** row: `● 1.5× initial  ·  100×/488nm  ·  ✓···` so the optics are visible at
  a glance.

## 5. Tests (`tests/test_phase2_foundation.py`)

- All V1 `test_correct.py` and `test_io.py` cases.
- `test_inverse_geometric_roundtrip`: random points, random `k1, k2, rotate_deg`; `raw → corr →
  raw` within 1e-3 px; Jacobian matches finite differences within 1e-4.
- `test_ome_metadata_from_dummy`: the Phase-1 dummy TIFFs' headers are read back and equal
  `truth_meta.json`.
- `test_meta_sidecar_roundtrip`: `ImageMeta` → JSON → `ImageMeta`, sources preserved.
- `test_project_embeds_meta`: save and load a project; every image's metadata survives.
- `test_dummy_truth_after_correction`: on `opt_warp` λ = 1, applying the dummy's known lens
  coefficients in Stage 1 puts the truth tag centres (undistorted truth from `truth.json`)
  within 0.3 px of `inverse_geometric`'s prediction.
- Offscreen GUI smoke: build `MainWindow`, add a dummy image, edit a metadata field, select
  another image, select back, check the sidecar on disk.

## 6. Acceptance

- The app launches from the launcher into its own venv, opens the six real V1 frames and the
  dummy runs, and the Stage-1 tab behaves exactly as the V1 app's does.
- Metadata for a dummy frame auto-fills from its header; a user edit survives a restart.
- Tests pass.

## 7. How this serves the end goal

Every export row carries the image's metadata record (Phase 7 joins on image name). The
`gain_e_per_adu` field is what makes the Phase-5 photon-count error absolute rather than
relative. `inverse_geometric` is what makes the `features_raw.csv` table possible without a
second detection pass.
