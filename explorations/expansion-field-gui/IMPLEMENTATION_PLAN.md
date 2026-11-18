# Implementation Plan — Expansion-Field GUI (multi-image pairing)

**Goal.** A GUI that loads an **initial** image (the baseline expansion state) plus a **series of
expansion images** of the same printed pattern, runs the **same five tracking stages** on every
image (reusing the `gridtrack` core), and then — the important part — **pairs the markers of the
initial image to the markers of each expansion image by their tags** to produce the **expansion
displacement vector field** for each expansion state. Every stage writes **CSV** per image, and
each pairing writes a **CSV** linking the initial markers to that expansion's markers.

This document plans the code and is meant to be built **in phases** (§10). It is not the
implementation.

### Decisions locked in (from review)
| Decision | Choice |
|---|---|
| Vector field | **Both** full displacement **and** residual warpage |
| Markers paired | **Dots + ArUco tags** (dense dots + sparse tag frame) |
| Units | **Both µm and pixels** |
| Scope now | **Displacement vectors + pairing CSV** (strain/`J` left for later) |

---

## 1. Relationship to the existing code (reuse, don't duplicate)

The per-image processing is *exactly* the five stages already built and validated in
`../point-tracking-gui/gridtrack/`. This project **does not reimplement them** — it imports
`gridtrack` and adds only (a) multi-image orchestration and (b) the pairing stage.

```
gridtrack   (../point-tracking-gui/gridtrack)     # HEADLESS CORE, unchanged
  io, correct, address, reference, measure, correspond, filters, types

expansion_field_gui/
  fieldkit/          # NEW headless layer on top of gridtrack (no GUI imports)
    project.py       # ExpansionProject: the image set, shared config, output dirs
    pipeline.py      # process_image(): run stages 1-5 on one image -> ImageResult (+ CSVs)
    markers.py       # unify each image's tags + dots into one tagged "markers" table
    pairing.py       # pair_to_initial(): join by tag, fit registration, full+residual field
    io_csv.py        # standardised per-stage + pairing CSV writers; output-folder layout
  app/               # NEW GUI (PySide6 + pyqtgraph)
    main.py          # project window
    image_list.py    # sidebar: initial + expansions, per-stage status
    setup_panel.py   # shared Stage-1 correction + detection params; batch "Run all"
    review_panel.py  # open one image in the single-image stage views to tune (optional)
    pairing_panel.py # run pairing per expansion; expansion-factor / RMS readout
    field_view.py    # quiver / vector-field visualisation (full vs residual toggle)
  tests/
    test_pairing.py  # validate against the simulator's expansion series
```

> **Packaging note.** For a clean import, either (a) add `../point-tracking-gui` to `sys.path`
> in `fieldkit/__init__.py`, or (b) promote `gridtrack` to a small installed package
> (`pip install -e`). Recommend (b) eventually; (a) is fine to start. This is the only coupling.

**Key reuse insight (why pairing is easy).** Every feature already carries an *absolute* tag —
ArUco tags by `aruco_id`, dots by `(box_i, box_j, local_i, local_j)`. So pairing initial↔expanded
is a **table join on the tag**, not a fragile motion-tracking problem. Correspondence is free;
the work is the *registration + displacement maths* (§6).

---

## 2. Data model

```python
@dataclass
class ExpansionProject:
    initial_path: str
    expansion_paths: list[str]          # ordered series
    correction: CorrectionParams        # SHARED optics (same microscope) -- set once
    measure: MeasureParams
    filters: FilterParams
    out_dir: str
    results: dict[str, ImageResult]     # path -> result
    pairings: dict[str, PairingResult]  # expansion path -> pairing vs initial

@dataclass
class ImageResult:                      # one processed image (stages 1-5)
    path: str
    detection: MarkerDetection          # Stage 2 (upright image + tags)
    grid: GridModel                     # Stage 3 (nodes, ref->img transform, px_per_um)
    features: "pd.DataFrame"            # Stage 4/5 (dots+dashes, filtered)
    markers: "pd.DataFrame"             # unified tags+dots table (markers.py)

@dataclass
class PairingResult:                    # initial <-> one expansion
    expansion_path: str
    field: "pd.DataFrame"               # one row per shared marker (the pairing CSV)
    lambda_rel: float                   # recovered relative expansion factor
    rotation_deg: float                 # inter-frame rigid rotation
    rms_px: float                       # registration residual
    n_tags: int; n_dots: int            # shared-marker counts
```

**The unified markers table** (`markers.py`) per image — one row per trackable point, with a
canonical `tag_key`:

| col | tags | dots |
|---|---|---|
| `type` | "tag" | "dot" |
| `tag_key` | `"T{aruco_id}"` | `"D{box_i}.{box_j}.{i}.{j}"` |
| `aruco_id` / `box_*` / `local_*` | id | box + local indices |
| `img_x_px, img_y_px` | tag centre (Stage 3, detected) | dot centre (Stage 5 survivor) |
| `px_per_um` | grid scale | grid scale |

Tags come from `grid.nodes` (status "detected"); dots from `features` (status "matched" i.e.
survived Stage 5). This is the table both sides of a pairing are joined on.

---

## 3. Output layout — CSV per stage, CSV per pairing

```
<out_dir>/
  project.json                              # image list, shared params, provenance
  <image_name>/                             # one folder per image (initial + each expansion)
    stage1_correction.csv                   # 1 row: the correction params applied
    stage2_tags.csv                         # aruco_id, corner_x/y (x4), cx, cy, theta_deg
    stage3_nodes.csv                        # aruco_id, node_i/j, ref_x/y_um, img_x/y_px, status, residual_px
    stage4_features.csv                     # full feature table (dots+dashes, tagged)
    stage5_features_filtered.csv            # filtered feature table (+ filter_reason)
    markers.csv                             # unified tags+dots used for pairing
  pairing/
    pairing_<expansion_name>_vs_initial.csv # the displacement field (see §6)
    pairing_summary.csv                     # one row per expansion: lambda_rel, rotation, rms, counts
```

`io_csv.py` owns these paths and writers so the layout is consistent and every stage is
inspectable as a CSV, exactly as required.

---

## 4. Per-image processing (stages 1-5, reused)

`fieldkit.pipeline.process_image(path, project) -> ImageResult` is a thin, headless wrapper over
the calls already validated in the single-image tool:

```python
img   = io.load_tiff(path)
corr  = correct.apply(img, project.correction)                 # Stage 1 (SHARED optics)
det   = address.detect_and_orient(corr, "DICT_6X6_1000", project.correction)   # Stage 2
grid  = reference.map_grid(det, project.reference)             # Stage 3
feats = measure.detect_features(det.image, grid, project.reference, project.measure)  # Stage 4
feats = filters.apply_filters(feats, grid, project.reference, project.filters, det.image.shape)  # Stage 5
mk    = markers.build(det, grid, feats)                        # unified tags+dots
io_csv.write_stages(out_dir/name, corr_params, det, grid, feats, mk)
```

**Shared vs per-image parameters.** Vignetting and lens distortion are properties of the
*microscope*, identical for every image, so **Stage-1 correction is set once and shared** (a big
simplification and physically correct — the acquisition optics don't change between expansion
shots). Rotation, drift and expansion differ per image and are handled automatically by stages
2-5. Per-image overrides are allowed (a rarely-needed escape hatch) via the review panel.

**Batch.** "Run all" loops `process_image` over `[initial] + expansions` with a progress bar; it
is fully headless underneath, so it also runs as a script for reproducibility.

---

## 5. The reference

All images are the **same printed pattern** at different expansion states, so they share **one
`grid_metadata.json`** (`project.reference`), auto-loaded once. Tag IDs and dot indices therefore
mean the same physical point in every image — the basis for pairing.

---

## 6. Stage 6 — Pairing → expansion vector field (the crux)

For the initial image **I** and one expansion image **E** (both processed), `pairing.pair_to_initial`:

**Step 1 — Join by tag.** Inner-join `markers_I` and `markers_E` on `tag_key` → shared markers,
each with `X_I` (px, initial) and `X_E` (px, expanded). Split into shared *tags* and shared *dots*.
(With fixed zoom, fewer markers overlap at higher expansion — that's expected; the field is built
on whatever is shared.)

**Step 2 — Register E to I on the shared TAGS** (robust, sparse, unambiguous). Fit a global
**similarity** `G` (expanded→initial) by RANSAC on the shared tag centres:
`G(x) = c·R(θ)·x + t`, giving scale `c`, rotation `θ`, translation `t`, and inliers. Fall back to
shared dots if too few tags overlap. Report:
- **relative expansion factor** `λ_rel = 1/c` (E is larger than I by ~`λ_rel`),
- inter-frame **rotation** `θ`, and the fit **RMS**.

**Step 3 — Two displacement fields** (both requested), per shared marker `m`:
- **Full displacement** (rigid-aligned — removes only the inter-frame rotation+drift, KEEPS the
  expansion, so the field shows the gel spreading):
  `R_rigid(x) = R(θ)·(x − μ_E) + μ_I`  (centroids of shared tags), then
  `u_full = R_rigid(X_E) − X_I`.
- **Residual warpage** (similarity-aligned — removes the mean expansion+rotation+drift, leaving
  the local non-uniform part):
  `u_resid = G(X_E) − X_I`.

**Step 4 — Units.** Convert both to µm with the recovered scale (`px_per_um`, ~equal for I and E
under fixed zoom): `u_*_um = u_*_px / px_per_um`. Store **both px and µm**.

**Step 5 — Pairing CSV** (`pairing_<E>_vs_initial.csv`), one row per shared marker:
```
tag_key, type, aruco_id, box_i, box_j, local_i, local_j,
x_init_px, y_init_px, x_exp_px, y_exp_px,
u_full_x_px, u_full_y_px, u_full_x_um, u_full_y_um, u_full_mag_um,
u_resid_x_px, u_resid_y_px, u_resid_x_um, u_resid_y_um, u_resid_mag_um,
inlier, status
```
plus a row in `pairing_summary.csv`: `expansion_name, lambda_rel, rotation_deg, rms_px,
n_tags, n_dots, n_inliers`.

**Robustness.** RANSAC rejects mis-registered tags; markers present on only one side are recorded
with `status = "unpaired_initial"` / `"unpaired_expansion"` (never dropped). A per-marker outlier
gate (residual vs local neighbours, reusing the Stage-5 idea) can flag suspect vectors.

> This is exactly the field the later strain step needs: `F` from `∂u/∂X`, `J = det F`, principal
> strains, and interpolation are a thin layer on `u_full` — deferred per the scope decision, but
> the CSV already carries everything required.

---

## 7. GUI layout

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Toolbar: [Add initial image] [Add expansion images…] [Set output dir] [Run all]│
├───────────────┬────────────────────────────────────────┬───────────────────────┤
│ IMAGE LIST    │             VIEW (tabbed)              │  CONTROLS (context)     │
│ ● initial  ✓✓✓✓✓│  • Image tab: selected image + its    │  Setup: shared Stage-1  │
│ ○ exp 2.0x ✓✓✓✓✓│    stage overlays (reuses canvas)     │   correction sliders,   │
│ ○ exp 3.0x ✓✓✓✓✓│  • Field tab: quiver of the pairing   │   detect/filter params  │
│ ○ exp 4.0x ····│    (full vs residual toggle)          │  Pairing: pick expansion│
│ [+][-]        │                                        │   → λ_rel, θ, RMS, run  │
├───────────────┴────────────────────────────────────────┴───────────────────────┤
│ Log / progress (batch stage completion, pairing summary)                        │
└──────────────────────────────────────────────────────────────────────────────┘
```
- **Image list** shows per-image stage status (5 ticks) and marks the initial image.
- **Image tab** reuses the single-image `ImageCanvas` + overlays to inspect any image's stages.
- **Field tab** is the new visualisation (§8).
- **Controls** are context-sensitive: *Setup* (shared params + Run all), *Pairing* (per expansion).

---

## 8. Field visualisation (`field_view.py`)

pyqtgraph, on the **initial** image (or a blank µm canvas):
- **Quiver**: each shared marker drawn as a segment `X_I → X_I + k·u` (arrowheads via a light
  `ArrowItem` or drawn triangles; for thousands of dots, line segments coloured by `|u|` are the
  performant default), with a length-scale slider `k`.
- **Toggle** full ↔ residual field; **colour** by magnitude (perceptually-uniform map); optional
  heatmap/interpolated background (deferred with strain).
- Readouts: `λ_rel`, rotation, RMS, shared-marker counts; hover shows a marker's tag + vector.
- Tags drawn distinctly (larger) from dots.

---

## 9. Validation — the simulator's expansion series is ground truth

`../expansion-camera-sim/tiffs/` is a labelled expansion series (`λ = 1 … 5`) of the same pattern
with known optics, rotation, drift and warp. Tests (`tests/test_pairing.py`):
1. **Recovered expansion factor.** Pair `l1p00` (initial) → `l2p00`/`l3p00`; assert `λ_rel` ≈ 2.0 /
   3.0 (the simulator's relative expansion) within a few %.
2. **Rotation.** `θ` matches the simulator's accumulating inter-frame rotation.
3. **Residual field ≈ warp.** With uniform expansion removed, `u_resid` is small and structured
   (the multi-lobe warp), not the full expansion.
4. **Tag join integrity.** Every shared `tag_key` refers to the same physical node; unpaired
   markers recorded, not dropped.
5. **CSV round-trip.** Every stage + pairing CSV writes and reloads with the documented columns.

(Note: under fixed zoom, high-λ frames share fewer markers with the initial — the tests assert on
the shared subset, which is the physically correct behaviour.)

---

## 10. Phases (build order)

1. **P0 — Scaffold + reuse. ✅ done.** `fieldkit` imports the shared `gridtrack` core;
   `ExpansionProject` (initial + expansions, shared params, output layout, `project.json`); GUI
   shell (toolbar add-images / set-output, image list with status, preview canvas, log).
2. **P1 — Per-image batch + CSVs. ✅ done.** `pipeline.process_image` runs stages 1-5 over
   `gridtrack`; `markers.build` unifies tags+dots; `io_csv` writes `stage1_correction.csv …
   stage5_features_filtered.csv` + `markers.csv` per image; shared Stage-1 correction panel +
   "Run all" with progress. Validated on the simulator series (`tests/test_pipeline.py`): all
   images processed, every stage CSV written, markers table has tags+dots with unique tag_keys.
3. **P2 — Unified markers + review.** `markers.build`; let the user open any image in the reused
   stage views to inspect/tune; per-image override.
4. **P3 — Pairing (core deliverable). ✅ done.** `pairing.pair` (tag-key join, RANSAC similarity
   fit on shared tags, **full + residual** displacement in **µm + px**), `project.pair_all` +
   `io_csv` pairing CSV + `pairing_summary.csv`; GUI pairing panel (per-expansion λ/rotation/RMS
   table). Validated on the sim series (`tests/test_pairing.py`): recovers λ = 2.000 / 3.000,
   sub-px RMS, full field shows the expansion while the residual is the minimal warp (~0.03 µm).
5. **P4 — Field visualisation. ✅ done.** `field_view` on the initial image: interpolated
   magnitude **heatmap** background (`analysis.interpolate_magnitude`), colour-by-magnitude
   **quiver with arrowheads** + density control + arrow-scale + full/residual toggle, a
   **magnitude legend**, and a field **summary** (`analysis.field_summary`: paired counts,
   median/max |u| full & residual). Analysis helpers validated in `tests/test_analysis.py`.
   (Optional extra: per-marker hover tooltip.)
6. **P5 — Polish. ✅ done.** Headless CLI batch runner (`fieldkit/cli.py` + `run_batch.py`),
   project session save/load (`project.json` + toolbar Save/Open), threaded "Run all"
   (`app/worker.py` — the UI stays responsive), per-marker hover in the field view. CLI +
   session round-trip validated (`tests/test_cli.py`).
7. **P6 — Strain. ✅ done.** `strain.py` — per-marker deformation gradient `F` (least squares on
   k nearest neighbours of `u_full`), `J = det F` (areal expansion), Green-Lagrange `E`, principal
   strains `E1,E2`, `max_shear`; `strain_<name>_vs_initial.csv`; a **J heatmap** mode in the field
   view + median-J readout. Validated on the simulator (`tests/test_strain.py`): J recovers
   λ² = 4.00 / 9.00, near-zero shear, roughly uniform with warp-driven local variation.

---

## 11. Open items / assumptions to confirm while building

1. **One image per expansion** (not a stack/time-series per level). If a level has multiple
   frames, average their marker positions or treat each as its own pairing. *(Assumed: one each.)*
2. **All images share one `grid_metadata.json`.** *(Assumed: same printed pattern.)*
3. **Registration source** = shared **tags** first, dots as fallback. *(Chosen; revisit if tag
   overlap is routinely tiny at high expansion.)*
4. **`px_per_um` equality** across images (fixed zoom). If acquisitions vary in magnification, take
   each image's own recovered scale and register with a full similarity (already handled by `G`).
5. **Datum/anchor.** The full-displacement field removes inter-frame *rigid* motion via shared-tag
   centroid + rotation. If a physical datum (fixed fiducial) is available, anchor on it instead for
   an absolute frame — easy to add.
