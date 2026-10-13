# Phase 7 — Data export

*Goal: one action writes a self-describing bundle holding everything a later script needs to
analyse local distortion and spatial correlation: the raw inputs, every feature's position and
uncertainty in every frame of reference, every tag's pose, pairs, local deformation, and the
parameters each image was taken and processed with. The bundle is versioned and round-trips
through a reader shipped with the tool.*

## 1. Principles

- **Long format.** One row per (image, feature). Pivoting is the consumer's job. Every table
  has `image`, `tag`, `category`, `box` as its first columns so tables join trivially.
- **Every position has its frame in the column name** and a covariance beside it:
  `x_<frame>, y_<frame>, sxx_<frame>, syy_<frame>, sxy_<frame>`. Units px unless the frame is
  `design` (µm).
- **Nothing is dropped silently.** Rejected frames are listed with reasons; ambiguous tags are
  exported with their class; filtered-out dots are exported in a separate table with the reason.
- **Parameters travel with the data.** The manifest holds every setting of every image, the
  design file hashes, the tool version and the git commit.
- **CSV plus JSON.** CSV for tables, JSON for records. A Parquet copy of each table is written
  when `pyarrow` is importable, otherwise skipped with a note in the manifest.

## 2. The bundle

```
export_<project>_<YYYYMMDD-HHMMSS>/
  manifest.json
  README.md                      the column dictionary (generated from the schema below)
  images/
    <name>.meta.json             ImageMeta record (Phase 2)
    <name>.stage1.json           CorrectionParams + LevelsParams + shared flags
    <name>.detect.json           ArucoParams, design sha, decode report, FramePose, affine, lam_tags, lam_dots, per-box recognised counts
    <name>.filter.json           DotFilterParams, DashFilterParams, counts by reason
    <name>.tag.json              warp report (kind, per_det_median, matched_frac, n_pairs), similarity (s, θ, t, cov), per-category and per-box residuals
    <name>.raw.tif               copy of the input TIFF (opt-in: "include raw images")
  features_raw.csv
  features_corr.csv
  features_in_initial_rigid.csv
  features_in_initial_sim.csv
  deviation_from_design.csv
  tags_pose.csv
  dropped_features.csv
  pairs_<init>_<exp>.csv         one file per expanded image (and per A↔B pair the user adds)
  local_deformation_<init>_<exp>.csv
  alignment_<exp>.json
  rejected.json
```

## 3. Tables

Common leading columns on every feature table: `image` (file stem), `label` (λ expected),
`lam_derived`, `tag`, `category` (`aruco | dash | dot`), `box` (N or empty), `node_i, node_j`
(tags only), `di, dj` (dots only), `line, m` (dashes only).

### 3.1 `features_raw.csv` — positions in the acquired image

`x_raw, y_raw, sxx_raw, syy_raw, sxy_raw, relative_err (bool), signal_adu, bg_adu, sigma_px
(dots), decode_class (tags)`.

Positions are detected in `corr` and mapped through `inverse_geometric`; the covariance through
its Jacobian.

### 3.2 `features_corr.csv` — positions in the corrected image

Same columns with `_corr`, plus `resid_tps_px` (distance to the warped reference) and `kept
(bool)` always true here (dropped ones are in §3.7).

### 3.3 `features_in_initial_rigid.csv` and `features_in_initial_sim.csv`

For every image including the initial itself (identity map): the feature mapped into the
initial image's `corr` frame by the rigid map (rotation + translation about the common box
centre, scale kept) or by the similarity (scale removed).

`x_init, y_init, sxx_feat, syy_feat, sxy_feat, sxx_align, syy_align, sxy_align, x0_init, y0_init
(the initial image's own position of the same tag, blank if not present there), dx, dy
(= x_init − x0_init), sxx_d, syy_d, sxy_d (covariance of the difference)`.

The rigid table shows growth plus distortion; the similarity table shows distortion only. Both
are what the user described as "relative to the initial reference grid spacing image".

### 3.4 `deviation_from_design.csv`

For every feature in every image: `x_design_um, y_design_um` (the design position), `x_expected,
y_expected` (the design position pushed through the image's fitted similarity, in `corr` px),
`dev_x, dev_y` (= `corr − expected`, px), `dev_x_um, dev_y_um` (divided by the fitted px/µm so
the number is in design micrometres at that expansion), `sxx_dev, syy_dev, sxy_dev`,
`mahalanobis`, `significant (bool)`, `resid_tps_px`.

This is the per-feature deviation in x and y from the ideal grid, for dots, dashes and tags
alike, which the user asked for as item 6.6.

### 3.5 `tags_pose.csv`

One row per (image, tag): the Phase-1 record plus Phase-5 sigmas: `aruco_id, x_corr, y_corr,
sxx, syy, sxy, c0x, c0y, …, c3x, c3y` (corners TL, TR, BR, BL), `rot_deg, rot_sigma_deg,
side_px, side_sigma_px, handedness, n_bits_corrected, margin_bits, contrast, decode_class,
in_edge_band, rot_rel_frame_deg` (this tag's rotation minus the frame median), and the same
centre in `raw`, `init_rigid`, `init_sim`, `design` frames with covariances.

### 3.6 `pairs_<init>_<exp>.csv`

`tag, category, box, x0_corr, y0_corr, sxx0, syy0, sxy0, x1_corr, y1_corr, sxx1, syy1, sxy1,
x1_init_rigid, y1_init_rigid, x1_init_sim, y1_init_sim, ux_rigid, uy_rigid, ux_sim, uy_sim`.

### 3.7 `dropped_features.csv`

Every detection that did not reach tagging: `image, category, x_corr, y_corr, reason` (`too_close
| near_tag | off_lattice | off_grid | intersection | unmatched | ambiguous_id | duplicate_id |
edge_band`).

### 3.8 `local_deformation_<init>_<exp>.csv`

Per paired dot (Phase 6): `tag, box, x0_corr, y0_corr, F11, F12, F21, F22, J, lin, lam1, lam2,
phi_deg, anisotropy, rot_deg, resid_rms_px, n_nb, F_cov (10 upper-triangle entries), U11, U12,
U22`.

### 3.9 `alignment_<exp>.json`

`{"rigid": {"box": N, "c_init": [..], "c_exp": [..], "R": [[..]], "t": [..], "angle_deg": ..,
"n_pairs": .., "cov_theta_t": [[..]]}, "similarity": {"s": .., "angle_deg": .., "t": [..],
"cov": [[..]], "n_pairs": ..}, "affine": {"A": [[..]], "cov": ..}, "bootstrap_n": 200}`.

### 3.10 `rejected.json`

`[{"image": .., "label": .., "stage": "detect|filter|tag|series", "reason": ..}]`.

### 3.11 `manifest.json`

```
{
  "bundle_version": "1.0",
  "tool": {"name": "ArUco_Reference_Tagger", "version": .., "git_commit": ..},
  "created": ISO time,
  "project": {"path": .., "initial": .., "images": [..]},
  "design": {"name": .., "folder": .., "reference_tags_sha256": .., "spec_sheet_sha256": ..},
  "frames": {"raw": "...", "corr": "...", "init_rigid": "...", "init_sim": "...", "expected": "...", "design": "..."},
  "error_model": {"kappa": .., "kappa_source": "default|calibrated", "gain_default_used": [images]},
  "per_image": {"<name>": {"meta": .., "stage1": .., "detect": .., "filter": .., "tag": ..}},
  "tables": {"features_raw.csv": {"rows": .., "sha256": ..}, ...},
  "parquet": true|false
}
```

The per-image parameter blocks are duplicated here from `images/` so the manifest alone
describes the run.

## 4. Code

- `rwtag/export.py`: `build_bundle(project, design, options) -> ExportBundle` (pure data), and
  `write_bundle(bundle, folder)`. Each table is a function that returns a `pandas.DataFrame`
  from the project's `PipelineState`s, so tests can check columns without writing files.
- `rwtag/export_schema.py`: the column dictionary as data (name, dtype, unit, frame,
  description), used both to validate the DataFrames before writing and to generate the bundle's
  `README.md`.
- `rwtag/export_reader.py`: `read_bundle(folder)` returns the tables and manifest; a `check()`
  method validates hashes and schema. This is the first thing the downstream script imports.
- `scripts/export_project.py`: headless export of a saved project (`project.rwproj.json`) with
  the design and options on the command line, so a batch of projects can be exported without
  the GUI.

## 5. GUI

Toolbar "Export bundle…": a dialog with the output folder, the "include raw images" checkbox,
the extra A↔B pairs to include, and a preview of the row counts per table. The log records the
bundle path and the manifest hash.

## 6. Tests (`tests/test_phase7_export.py`)

- `test_schema_validates`: every table from a dummy project passes the schema; a table with a
  renamed column fails.
- `test_roundtrip`: write, read back, every table equal, hashes verify.
- `test_frames_are_consistent`: for every row, `features_raw` mapped through the stored Stage-1
  params equals `features_corr` within 1e-3 px; `features_in_initial_sim` for the initial image
  equals `features_corr`.
- `test_deviation_matches_truth`: on `opt_warp`, `dev_x_um, dev_y_um` correlate with the
  simulator's `warp_disp` at > 0.9 and the clean run's deviations are within 2σ for 95 % of
  rows.
- `test_pairs_match_local_deformation`: every tag in a pairs file appears in the matching
  deformation file with the same `x0_corr, y0_corr`.
- `test_rejected_listed`: a project with one deliberately mirrored frame exports with that frame
  in `rejected.json` and absent from every table.
- `test_headless_script`: `export_project.py` on a saved dummy project produces the same bundle
  as the GUI path (same hashes).

## 7. Acceptance

- A dummy project of six states exports in under a minute; the bundle's `README.md` reads
  correctly; `read_bundle().check()` passes.
- The user has opened the CSVs and agreed the columns are what the downstream analysis needs.
- Tests pass.

## 8. How this serves the end goal

This is the end goal. Everything upstream exists to fill these tables.
