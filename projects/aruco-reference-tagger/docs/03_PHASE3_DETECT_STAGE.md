# Phase 3 — Stage 2 in the GUI: ArUco decode replaces OCR, design-driven grid

*Goal: the "2 · Detect" tab runs on the Stage-1 corrected image, decodes the tags (Phase 1),
fits the design → image transform from them, detects dots and dashes with per-box parameters
from the loaded design, derives the expansion factor and rotation, and publishes a
`DetectResult` the later stages consume. The three V1 buttons (Detect grid / Read glyphs /
Solve grid) become one.*

## 1. What to port

| V1 source | target | action |
|---|---|---|
| `rwtag/aruco/detect.py` | `rwtag/aruco/detect.py` | port; `Design` gains the per-box table (§2); dot detection takes per-box parameters (§3); `detect()` fills the derived metadata (§4) |
| `rwtag/glyph/lattice.py` | `rwtag/lattice.py` | port **only** `detect_dots`, `estimate_basis`, `refine_basis`, `detect_dashes`, `dashes_on_grid`, `_phase_mode`. Drop every fiducial-slot constant and function (`FIDUCIALS`, `SLOT_FRACS`, `fit_fiducial_lattice`, `fslot_point`, `slot_point`, `draw_*`). `BOX_PER_DOT` and `BOX_UM` go: the design supplies them |
| `rwtag/glyph/types.py` | `rwtag/types.py` (merge) | keep `DetectResult` and `FilterResult`; drop `GlyphDetection`, `NumberToken`, `OrientationResult`, `GlyphDetectParams`, `CLASSES` |
| `rwtag/glyph/detect.py` | gone | `to_u8` moves to `io`; the three-step orchestration is replaced by `aruco.detect` |
| `rwtag/glyph/reader.py`, `classifier.py`, `gridmodel.py`, `stl_glyphs.py` | gone | OCR |
| `gui/detect_panel.py` | `gui/detect_panel.py` | rewrite around one step (§5); keep the view toggles and the canvas overlay helpers |
| `gui/canvas.py::draw_glyph_grid` | `draw_detect_overlay` | same drawing primitives; slots and glyph labels removed; tag quads, ids and rotation arrows added |
| `tests/test_glyph.py` | gone | replaced by `test_phase3_detect.py` |
| `tests/test_aruco.py` (end-to-end parts) | `tests/test_phase3_detect.py` | port |

## 2. The design loader, extended

`Design.from_dict` already reads `box_um`, `grid_n`, `dot_pitch`, `dot_side_um`, `tag_um`,
`dict_name`, and derives `origin_um = tag/2` for `fit = inside`. Add:

- `boxes`: a list of `BoxSpec(N, col, row, x0_um, y0_um, side_um, dot_um, pitch_um, phase_um,
  count, corner_tag_ids)`. For the spectrum print this comes from the `boxes` list in its
  `reference_tags.json` (present, 25 rows) and `spec_sheet.json` (adds `corner_tag_ids` and
  `tophat_px`). For designs 1–3 it is synthesised: 25 identical rows from the top-level values.
- `box_of_design_xy(x_um, y_um) -> N`, `box_of_node(i, j) -> N`, `node_ids` (the 36 `(i, j,
  id)` triples from `config.ids`), `expected_dot_pitch_px(N, um_per_px, lam)`,
  `expected_dot_fwhm_px(N, um_per_px, psf_um)`.
- `Design.load_folder(path)` reads `reference_tags.json` and, if present, `spec_sheet.json`,
  `ids.json`, and records `sha256` of each for the export manifest.
- A design registry: `designs/` in this repo holds a copy of each design folder's
  `reference_tags.json`, `spec_sheet.json`, `ids.json` (small files, ~3 MB total) so the app
  does not depend on `aruco-marker-design` being present. A "Load design…" action also accepts any
  folder.

## 3. Dots and dashes, per box

V1 ran one top-hat and one Otsu over the whole frame with one `dot_area` range. On the spectrum
print the dot size and pitch change box to box, and even on designs 1–3 the expected dot size
in px changes with λ (the dot is rigid, so its imaged size is `√(dot² + PSF²) / (µm/px)`, but the
pitch grows as λ). So:

1. Decode tags and fit the design → image affine `A` as V1 does (`fit_affine`, centres only,
   handedness from corners). This gives λ and rotation before any dot is looked at.
2. For every box `N` in the design, push its four corners through `A` to get its image quad.
   Boxes with no corner in the frame are skipped. Each box gets its own detector settings from
   its `BoxSpec` and `ArucoParams`: top-hat element `≥ 2 × imaged FWHM` of **that box's** dot,
   `dot_area` from that box's dot side in px with a ×0.4–2.5 band, and the Gaussian-refinement
   sigma from that box's imaged FWHM.
3. Run `detect_dots` on the frame **masked to that box's quad** (dilated by one dot pitch so
   border dots are not cut), with the noise-floored threshold from V1 (`max(Otsu, median +
   5σ)`). Concatenate. Dots inside a decoded tag's grown quad are dropped as before.
4. Refine every dot with `refine_gauss` using its box's sigma. Record for each dot: box `N`,
   integrated signal above background (ADU), background level, fitted sigma. Phase 5 needs them.
5. Dashes: one pass with the V1 `detect_dashes` (aspect-gated), then `dashes_on_grid` against
   the node lattice from `A`.
6. The lattice `basis` is fitted per box (`estimate_basis` + `refine_basis` on that box's dots)
   and stored as `basis_by_box[N]`; the frame-level `basis` kept for V1-compatible callers is the
   median-pitch box's basis. The tag-match gate in Phase 4 uses the per-box pitch.

Expansion factor: `lam_tags = scale(A) / scale_print`, where `scale(A) = √|det A_lin|` in px/µm
from the tag **centres** and `scale_print` is the design's px/µm from the metadata `um_per_px`.
So λ is derived from the design geometry and the pixel size, without a reference image. A second
estimate `lam_dots` from the per-box dot pitch vs design pitch is recorded as a cross-check; the
two should agree within a percent on a clean frame.

## 3b. The second detection pass, on the raw frame

After the corrected-frame detection, `detect()` runs again on the **raw** image (the TIFF as
loaded, only percentile-stretched to 8 bit, no optics correction) with the same `ArucoParams`
and design. Its tags are matched to the corrected pass by id; its dots and dashes are matched
to the corrected pass by mapping the corrected positions into the raw frame with
`correct.inverse_geometric` and taking the nearest raw detection within `0.45 × pitch`. The
result is stored as `DetectResult.raw_pass` with, per feature of the corrected pass:
`x_raw_det, y_raw_det` (the independent raw detection, NaN if unmatched), `x_raw_map, y_raw_map`
(the mapped position) and `raw_found (bool)`. The summary reports the matched fraction and the
median `|det − map|`, which is the correction's effect on the detector. The raw pass is cached
on the entry and is skipped when the Stage-1 geometric parameters are all zero (raw equals
corr).

## 4. `DetectResult` and derived metadata

`DetectResult` keeps its V1 shape so Phase 4's `tagframe` works unchanged, with these
additions:

| field | content |
|---|---|
| `tags` | `{id: TagObservation}` from Phase 1 |
| `frame_pose` | `FramePose` from Phase 1 |
| `dot_box` | (N,) box number per dot |
| `dot_signal`, `dot_bg`, `dot_sigma_px` | per dot, for the error model |
| `basis_by_box` | per-box lattice |
| `lam_tags`, `lam_dots` | derived expansion factors |
| `design_sha` | hash of the design file used |

`detect()` writes `meta.expansion_derived = lam_tags`, `meta.rotation_derived_deg =
frame_pose.frame_rot_deg`, `meta.handedness`. The metadata dock refreshes.

`model` keeps the keys V1 code reads: `registered`, `kind = "aruco"`, `reg = IDENTITY_REG`,
`affine`, `sign`, `aruco_xy`, `summary`.

## 5. The Detect panel

Controls, top to bottom:

- **Design**: combo over the registry (Optimistic / Medium / Conservative / Spectrum / custom
  folder…) with the file hash shown. Persisted per project; the metadata `print_design` field
  is set from it.
- **Detector settings**: µm/px (read from metadata, editable here with the metadata source
  updated), PSF FWHM µm, edge band µm, refinement method (gauss / fit / none), noise floor k,
  mask tags on/off. These are `ArucoParams`.
- **Detect** (one button). Runs §3 and publishes the `DetectResult`.
- **Auto-deskew (write to Stage 1)**: sets `rotate_deg = −frame_rot_deg` so the grid is upright,
  re-renders Stage 1 synchronously (the V1 `deskewApplied` mechanism), and re-detects. Upright
  frames are not required by any later stage; this is a convenience for viewing.
- **View**: tags (quad + id + rotation arrow, coloured by decode status: clean / corrected /
  flagged), dots (coloured by box), dashes, box quads with `N`, expected-grid overlay from `A`.
- **Summary**: tags decoded / in design / unknown ids / flagged; λ from tags and from dots;
  rotation ± spread; handedness; dots per box vs design count (a table for the spectrum print,
  the per-box recognised fraction that `analyse_spectrum.py` reports).

The manual-anchor group ("Identify a box") is gone. If zero tags decode the frame is reported
as unregistered with the reason, and the summary suggests exposure or edge-band causes, as
Rev D §6 says.

## 6. Tests (`tests/test_phase3_detect.py`)

- Port of `test_aruco.py::test_synthetic_end_to_end` and the two sign-gate tests, now driven
  from the dummy runs instead of calling the simulator inline.
- `test_design_registry_loads_all_four`: every design loads; box tables have 25 rows; the
  spectrum's rows match its `boxes.csv`.
- `test_lam_from_tags`: on `opt_clean`, `lam_tags` within 0.5 % of each frame's λ; `lam_dots`
  within 1 %.
- `test_per_box_dots_spectrum`: on `spectrum_clean` λ = 1, recognised fraction per box ≥ 0.95
  in every box the design rule says is resolvable at the dummy PSF, and the bottom-left
  known-bad box is reported below that (the test is discriminating).
- `test_dots_per_box_matches_truth`: on `opt_warp` λ = 2, ≥ 97 % of truth dots within 0.5 px,
  by nearest neighbour; the dot's `dot_box` equals the truth box.
- `test_rejects_unregistered`: a frame with every tag masked out returns `registered = False`
  with a reason and no exception.
- Offscreen GUI smoke: load a dummy image, Detect, check state; switch design, Detect again.

## 7. Acceptance

- On every dummy run the Detect tab registers every frame that has ≥ 1 tag, and the summary
  numbers match `truth.json` within the test tolerances.
- On the spectrum run the per-box table reads like `analyse_spectrum.py`'s output.
- Tests pass. The user has stepped through a dummy series in the GUI.

## 8. How this serves the end goal

This phase produces the per-feature raw observations with the extra per-dot fields (signal,
background, box) that the error model needs, and the derived λ and rotation that go into each
image's metadata record. The per-box design handling is what lets one tool serve all four
prints without code changes.

## 9. As built (2026-10-14)

**Files.** New: `rwtag/aruco/detect.py` (the detector), `rwtag/lattice.py` (ported subset of V1's
`glyph/lattice.py`: blob detection with the noise-floored threshold, basis estimate and refine,
dashes on grid; every V1 constant and the glyph-slot code dropped), `rwtag/designs.py` (registry),
`designs/` (copies of the four design folders, byte-identical to `aruco-marker-design/designs/`),
`gui/detect_panel.py`. Changed: `rwtag/types.py` (+ `DetectResult`, `FilterResult`),
`rwtag/aruco/tags.py` (dot/dash settings on `ArucoParams`; rotation sign), `rwtag/correct.py`
(+ `raw_source_valid`), `rwtag/project.py` (+ `run_detect`), `gui/app.py` (tab 2, auto-deskew).
Tests: `test_phase3_detect.py` (10), `test_phase3_gui.py`, helper `tests/_dummy.py`. 53 pass in all.

**Dots per printed size, not per box mask.** Instead of masking the frame box by box, the
detector runs once per distinct dot size (one for designs 1–3, five for the spectrum print) with
the top-hat and area band of that size, then gives each blob to the box its design position falls
in (inverse tag affine) and keeps it only if that box prints that size. No mask edges, no
double-counting, five passes instead of 25.

**Edge flags are exact.** The fixed un-distortion band of the plan is replaced by a test of each
feature's real raw source (`correct.raw_source_valid`): a dot is flagged `edge` when its raw
position is outside the lens model's range or within one spot width of the raw border; a tag when
any corner is within one module of it. The `edge_band_um` setting remains as an optional extra
margin, default 0.

**Rotation convention changed to counter-clockwise on screen.** Phase 1 reported
`atan2(dy, dx)` in y-down pixels, which reads −2° for a frame rotated +2° counter-clockwise. All
rotations are now counter-clockwise-on-screen positive, the same sign as the Stage-1 rotation
slider and `cv2.getRotationMatrix2D`: an applied +2.0° reads +2.00°. The dummy truth uses the
same convention. Raw rotation = corrected rotation − Stage-1 `rotate_deg`; auto-deskew sets
`rotate_deg = −(raw rotation)`.

**Photometry for the error model.** Measured on the RAW frame at each dot's raw position: the
background is the 10th percentile of the patch (a ring median sat on the neighbouring dots at
λ = 1, where the pitch is about four spot widths, and read the width 30 % low), the signal is the
background-subtracted sum inside 2.5 σ divided by the Gaussian fraction inside it, and the width is
the second moment corrected for that truncation. Measured spot σ is 2.2 px against 2.0 px for the
printed 2.125 µm square convolved with the PSF; the rest is interpolation blur from the Stage-1
remap, which the Phase-5 calibration absorbs.

**The spectrum dummy is now rendered at PSF 2.0 µm** (`spectrum_clean`, every box resolvable) and
a new preset `spectrum_blur` at 3.4 µm checks that the per-box table discriminates.

**Measured, every frame through a real Stage-1 correction (lens + vignette + 6° deskew)**

| run | quantity | value |
|---|---|---|
| opt_warp, λ 1–6 | truth dots found within 0.5 px | 99.35–99.94 % |
| | assigned to the right box | 100 % |
| | position RMS vs truth | 0.21–0.24 px |
| | detections matching no truth dot | ≤ 0.02 % |
| | λ from tags / from dot pitch | within 0.2 % / 0.1 % (warp included) |
| cons_dim, λ 1, 3, 6 | dots found / λ | 98.5–99.0 % / within 0.2 % |
| spectrum_clean, λ 1 | each of 25 boxes found / its own λ | ≥ 98 % / within 0.5 % |
| spectrum_blur, PSF 3.4 | known-bad box 1 / widest box 21 | 2 % / 100 %; rank correlation with the design rule 0.85; top row names 7.0 µm (Conservative) |
| raw second pass, opt_warp | dots re-found / raw det vs mapped | 99.9 % / median 0.02 px |
| tag rotation, 311 tags | error vs truth | mean 0.00°, sd 0.15° per tag |

**Rotation precision sets the gate.** Per-tag rotation is unbiased with a 0.15° spread, so a frame
with only four tags in view can miss by 0.25° by chance; the frame-rotation test gate is
0.6°/√(tags), i.e. 0.30° with four tags and 0.10° with 36.

**Known limit: the raw pass is weaker in vignetted corners.** The raw frame is not flat-fielded,
so at high blur the dimmest corner dots fall below the threshold: on `spectrum_blur` the raw pass
re-finds 67 % of the dots against 99.9 % on the sharp runs. Unmatched dots keep their mapped raw
position and are exported with `raw_found = false`, never dropped.
