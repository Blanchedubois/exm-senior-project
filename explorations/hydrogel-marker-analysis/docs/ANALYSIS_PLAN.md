# Implementation Plan — Distortion-Field Analysis Pipeline

**Goal.** Given a *reference* image of the printed pattern (or its CAD ground truth) and one
or more *deformed* images of the same pattern after the hydrogel expands, recognize and map
every trackable feature, establish correspondence, and output the **local distortion as a
vector field** `u(x)` plus derived strain, areal/volumetric expansion `J`, and out-of-plane
warpage `w`.

This document plans the script(s); it is not the implementation. It is written to be handed
to an implementer and executed stage by stage.

---

## 1. Inputs & outputs

**Inputs**
- `reference image` — the as-printed pattern (pre-expansion). Optionally skip and use CAD.
- `grid_metadata.json` — ground truth from `generate_grid.py`: for every node the ArUco ID
  and (x,y) in µm; for every box the corner ArUco IDs and every dot's (i,j) local index and
  (x,y) in µm. **This file is the backbone**: it turns detection into absolute coordinates.
- `deformed image(s)` — one endpoint, or a time-lapse stack, or a confocal z-stack (3D).
- `calibration` — effective pixel size (µm/px); for 3D, z-step (µm/slice).

**Outputs**
- `features.parquet/json` — one row per tracked feature: `{type, aruco_box, local_i, local_j,
  ref_x, ref_y, def_x, def_y, (def_z), u_x, u_y, (w), sigma}`.
- `field.npz` — interpolated displacement field on a regular grid; `J`, principal strains,
  `w`, curvature maps.
- Figures — quiver of `u`, heatmaps of `J`/strain/`w`, 3D warped surface, uncertainty overlay.
- `report.json` — global expansion factor λ, RMS residual, per-box J, validation metrics.

---

## 2. All trackable features (enumerate, then prioritize)

The pattern offers several feature classes; use them in this priority order (most precise /
most robust first). The pipeline should detect *all available* and fuse them.

1. **ArUco tag corners** (4 per tag) — highest-value: each is subpixel-localizable *and*
   carries absolute identity via the decoded ID. These pin the global frame and every box.
2. **Fine dot centroids** — the dense measurement tier (currently ~312 dots/box; the dots
   fill each box out to the thick dashed boundary, with a clear keep-out disk around each
   corner tag). Subpixel centroid per dot; identity from `(box, local_i, local_j)`. **The
   per-box dot lattice is NOT a full regular grid** — positions inside the corner keep-outs
   are absent — so predictions must come from the metadata's *actual dot list* for that box,
   never an assumed full N×N lattice. This is the bulk of the field.
3. **Checkerboard/saddle corners** — if a box is filled with a checkerboard instead of dots
   (generator supports both), saddle points localize even better than blobs under blur.
4. **ArUco tag centroid** — one robust point per tag; coarse but very reliable fallback.
5. **Dashed box-boundary dashes** — the thick dashed grid lines between tags. Low precision;
   use only as coarse anchors / a visual registration guide separating boxes, not as a
   primary measurement. Their dash centroids can seed the per-box homography if a tag is
   missing.
6. **DIC speckle sub-fields** *(optional, if added to box interiors)* — continuous field
   inside a box via subset DIC; use where a dense continuous field is needed between dots.

Design note: dots and tag-corners are the workhorses. Treat 4–6 as optional/augmenting.

---

## 3. Pipeline stages

### Stage A — Load & preprocess
- Read image(s); if two-channel (ArUco in one fluorophore, dots in another) split channels.
- Flat-field / background subtract; mild denoise (median or NLM) *without* blurring corners.
- For 3D: load z-stack; keep per-slice and a max-intensity projection.
- Functions: `load_inputs()`, `preprocess(img)`, `split_channels(img)`.

### Stage B — Address (ArUco) → per-box frames
- `cv2.aruco.detectMarkers` on the ArUco channel → `{aruco_id: 4 corners}` (subpixel via
  `cornerSubPix`). Decode gives absolute node coordinates from `grid_metadata`.
- Group nodes into boxes (each box = its 4 corner IDs). For each box compute a **homography**
  ref→deformed from the 4 corner tags — this predicts where interior features should be.
- Robustness: missing/undecoded tag → fall back to 3 corners (affine) or neighbor
  extrapolation; flag the box. RANSAC over all node correspondences to reject outliers and
  fit a global similarity as a coarse prior.
- Functions: `detect_aruco()`, `build_boxes()`, `box_homography(box)`.

### Stage C — Measure (fine features)
- For each box, restrict to its ROI (from the homography-mapped corners).
- **Dots:** blob detection (`cv2.SimpleBlobDetector` or `skimage.feature.blob_log`) → refine
  each centroid with a 2D Gaussian fit for subpixel + amplitude/σ (for uncertainty).
- **Checkerboard:** `cv2.findChessboardCornersSB` on the ROI (pattern size known from
  metadata) → `cornerSubPix`.
- 3D: detect per-slice then fit the axial profile (1D Gaussian along z) for `def_z`; or detect
  on the projection and refine z locally.
- Functions: `detect_dots(roi)`, `detect_checker(roi)`, `refine_subpixel()`, `fit_axial_z()`.

### Stage D — Correspondence (the crux, but localized)
- Because ArUco IDs partition the field, correspondence is a *per-box* problem:
  1. Use the box homography to map each ground-truth dot from that box's metadata dot list
     (which already omits the corner keep-out positions) into the deformed image (predicted
     position). Do not synthesize a full N×N lattice — iterate the actual listed dots.
  2. Assign detected dots to predictions with `scipy.optimize.linear_sum_assignment`
     (Hungarian) using distance cost, gated by a max radius.
  3. Unmatched detections / predictions → flag as dropped (record, don't silently discard).
- Optional time-lapse: `trackpy.link` frame-to-frame as an independent identity source; cross-
  check against the ID-based assignment.
- Output: every matched feature gets a global key `(box, local_i, local_j)` with `ref_xy`
  (from metadata) and `def_xy` (measured).
- Functions: `predict_positions(box)`, `assign_hungarian()`, `link_timelapse()` (optional).

### Stage E — Global registration → residual warpage
- Fit a global **similarity (or affine)** transform ref→deformed over all matched features
  (least squares, RANSAC-robust). Its linear part gives the **global expansion λ** (and
  rotation); subtract it to leave the **residual field** = the warpage of interest.
- Functions: `fit_global_transform()`, `residual_field()`.

### Stage F — Field & mechanics
- `u(X) = def_xy − ref_xy` per feature (`w = def_z − ref_z` in 3D).
- Interpolate to a regular grid: `scipy.interpolate.RBFInterpolator` or `griddata`.
- **Deformation gradient** `F` per feature: least-squares fit of `dx = F·dX` over k nearest
  neighbors (`scipy.spatial.cKDTree`). Then `E = ½(FᵀF − I)`, principal strains,
  `J = det F` (2D areal, 3D volumetric), curvature from `∇w`.
- Functions: `displacement_field()`, `interpolate_field()`, `deformation_gradient()`,
  `strain_and_J()`, `curvature()`.

### Stage G — Uncertainty
- Propagate per-feature localization σ (from the Gaussian-fit residual / SNR) into `u`, `F`,
  `J`. Bootstrap neighbor sets for `F`. Report per-feature and field-level error bars.
- Functions: `localization_sigma()`, `propagate_uncertainty()`, `bootstrap_F()`.

### Stage H — Visualization & report
- Quiver of `u` (and residual warpage), heatmaps of `J` / principal strain / `w`, 3D warped
  surface (`pyvista`), dropped-feature overlay. Write `report.json`.
- Functions: `plot_quiver()`, `plot_heatmaps()`, `plot_surface3d()`, `write_report()`.

---

## 4. Data structures
- `FeatureTable` (pandas DataFrame): columns `type, aruco_box, local_i, local_j, ref_x, ref_y,
  ref_z, def_x, def_y, def_z, u_x, u_y, w, sigma, status`.
- `BoxRecord`: `box_ij, corner_ids, homography, n_expected, n_matched, n_dropped`.
- `FieldResult`: grids of `u`, `J`, `E1/E2`, `w`, plus `lambda_global`, `rms_residual`.

---

## 5. 3D and time-lapse
- **3D (confocal):** run Stages B–D per slice or on the projection; add `fit_axial_z` for the
  z-coordinate; extend `F` to 3×3 for volumetric `J` and true out-of-plane warpage.
- **Time-lapse:** loop Stages B–F per frame with the reference fixed; optionally incremental
  (frame→frame) to watch warpage develop and to provide the trackpy cross-check.

---

## 6. Validation (build in from day one)
- **Synthetic ground truth (do this first):** reuse the simulators' `deform()` to warp the
  generated pattern by a *known* field, run the whole pipeline, and confirm recovered `u`/`J`
  match to within localization precision. This is the unit test for the analysis.
- **Rigid-translation:** known stage shift, no expansion → `u` uniform; scatter = noise floor.
- **Uniform-swell:** homogeneous region → `J ≈ λ^dim`; residuals clustered at markers reveal
  strain shielding.
- **CAD self-consistency:** compare reference detections to `grid_metadata` → separates print
  error from deformation.
- **Cross-method:** incremental µDIC/DICe and/or thin-plate-spline (SimpleITK/elastix) on the
  same features; agreement validates the field.

---

## 7. Libraries
`opencv-contrib-python` (aruco, findChessboardCornersSB, cornerSubPix), `numpy`, `scipy`
(optimize.linear_sum_assignment, interpolate, spatial.cKDTree, linalg), `pandas`,
`scikit-image` (blob detection), optional `trackpy` (time-lapse), `SimpleITK`/`pyelastix`
(TPS cross-check), `matplotlib` + `pyvista` (viz).

---

## 8. Suggested module layout
```
analysis/
  io.py            load_inputs, preprocess, split_channels, load_metadata
  address.py       detect_aruco, build_boxes, box_homography
  measure.py       detect_dots, detect_checker, refine_subpixel, fit_axial_z
  correspond.py    predict_positions, assign_hungarian, link_timelapse
  fielding.py      fit_global_transform, displacement_field, deformation_gradient,
                   strain_and_J, curvature, interpolate_field
  uncertainty.py   localization_sigma, propagate_uncertainty, bootstrap_F
  viz.py           plot_quiver, plot_heatmaps, plot_surface3d
  validate.py      synthetic_test, rigid_translation_test, uniform_swell_test
  run.py           orchestrates A->H; CLI: run.py --ref ref.png --def def.png --meta grid_metadata.json
```

---

## 9. Phased milestones
1. **M1 — Address only:** detect ArUco, build boxes, recover the coarse per-box λ and a node-
   level displacement field. (Validates on the synthetic pair.)
2. **M2 — Dense dots:** add dot detection + Hungarian correspondence → full-resolution `u`.
3. **M3 — Mechanics:** `F`, strain, `J`, warpage + interpolation + figures.
4. **M4 — Uncertainty + validation suite** (synthetic, rigid, uniform-swell, cross-method).
5. **M5 — 3D and/or time-lapse** extensions.

---

## 10. Edge cases & failure handling
- Missing/blurred tag → box still solvable from 3 corners or neighbors; flag it.
- Dropped/merged dots (blur, expansion collisions) → recorded as `status=dropped`, never
  silently ignored; report counts.
- Partial field of view / tiling → node IDs make stitching trivial (global coordinates);
  merge FeatureTables across tiles by ID.
- Outliers → RANSAC in global fit; robust (Huber) loss in `F` fits.
- Large expansion collisions between dots → rely on tag-anchored prediction to keep
  assignment unambiguous; drop rather than mis-assign.
```
