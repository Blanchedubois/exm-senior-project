# Phase 4 — Stage 3 filter and Stage 4 tagging on the V2 design

*Goal: the "3 · Filter" and "4 · Tag" tabs work on V2 detections. Every surviving feature gets
its design identity; the design → image warp is fitted; the series driver batch-tags a project
with the V2 gates. After this phase the per-image half of the pipeline is complete.*

## 1. What to port

| V1 source | target | action |
|---|---|---|
| `rwtag/glyph/dotfilter.py` | `rwtag/dotfilter.py` | port; `filter_dots` takes `basis_by_box` and tests deviation against each dot's **own box** lattice (§2); the glyph gate is removed; `DashFilterParams.dashes_per_edge` reads from the design |
| `rwtag/refwarp/warp.py` | `rwtag/refwarp/warp.py` | port; `BOX_UM`/`LINE_N` constants go, `coarse_map` reads `fit["box_um"]` (already does) and `predicted_nodes` takes the design |
| `rwtag/refwarp/tagmatch.py` | same | port; the `glyph` category and `_by_category`'s number/letter branch go; the dot gate becomes per-box (`0.45 × pitch_px[N]`) |
| `rwtag/refwarp/tagframe.py` | same | port; `load_records` takes the `Design`; `warped_grid_segments` and `warped_box_centers` take `box_um`, `origin`, `grid_n` from it (the signatures already exist, the defaults change) |
| `rwtag/refwarp/types.py` (`TagResult`) | same | port; add `per_box` statistics and `design_sha` |
| `rwtag/refwarp/strain.py` | same | port unchanged (Phase 6 uses `_local_F`) |
| `rwtag/refwarp/io_csv.py` | same | port; Phase 7 replaces its writers but `write_tagged` stays for the per-frame quick export |
| `rwtag/refwarp/series.py` | gone | the V1 glyph series driver |
| `rwtag/aruco/series.py` | `rwtag/series.py` | port; it becomes the only driver. `default_dot_params` already turns the glyph and off-lattice gates off; the off-lattice gate comes back **per box** (§2) |
| `rwtag/refwarp/coreg.py`, `reftags.py` | gone | rescue and STL build |
| `rwtag/project.py::run_stages` | `rwtag/project.py::run_stages` | rewrite: Stage 1 params → `aruco.detect` → `filter_frame` → `tag_frame`; the validated variant keeps only the handedness, residual and shared-tag gates from `aruco/series.py` |
| `gui/filter_panel.py` | same | port; remove the glyph-radius controls; add a per-box summary table; colour dots by box |
| `gui/tag_panel.py` | same | port; the series group drives `rwtag/series.py`; the strain table and trend plot are **removed** (analysis is elsewhere); kind combo becomes `all / aruco / dash / dot`; the "tilted frame" warning goes (tilt is fine) |
| `tests/test_dotfilter.py`, `test_refwarp.py` | `tests/test_phase4_tag.py` | port the synthetic cases; real-frame cases are replaced by dummy-run cases |

## 2. Filter changes

- **Off-lattice gate, per box.** V1 tested every dot against one global lattice; V2's
  `aruco/series.py` turned it off because the lattice phase steps box to box. With
  `basis_by_box` from Phase 3 the gate returns: a dot is off-lattice if it is more than
  `max_dev_frac × pitch_px[N]` from the nearest node of **its box's** lattice. Default stays
  0.60 (the gel warp is signal, not noise).
- **Min-separation gate** uses the box's pitch.
- **Tag keep-out** replaces the glyph gate: dots within `tag_keepout_um` (from the design's
  per-box table, else `tag/2 + pitch − dot`) of a decoded tag centre are dropped with reason
  `near_tag`. Phase 3 already masks the tag interior; this adds the quiet zone.
- **Dashes**: unchanged logic, `dashes_per_edge` from the design.
- `FilterResult` gains `dot_box` and the per-dot fields carried from `DetectResult` (filtered to
  the kept rows) so Phase 5 does not have to re-join.

## 3. Tagging changes

`tag_frame(det, filt, design)`:

1. Reference control points: all design dots (`ref_dots_um`) as V1.
2. Seed: `fit = {O, U, V, box_um}` built by Phase 3 from the tag affine, so `coarse_map` under
   the identity registration equals the affine. Unchanged from `aruco/detect.py`.
3. ICP homography then TPS (`warp.fit_warp`), with the gate `0.5 × pitch` evaluated with each
   detected dot's **box pitch**. `tps_max = 500` control points stays.
4. `tagmatch.tag_image`: dots ← design dots by nearest warped reference within `0.45 ×
   pitch_px[N]`; dashes ← design dashes within `0.9 × pitch`; ArUco ← by id (position never
   used). One-to-one as V1.
5. `TagResult.tags = {tag: (x, y)}` in `corr` px; `residuals` per tag; `per_category` and
   `per_box` counts and median residuals; `warp` model; `source`, `confidence`.
6. Record the **similarity** fit of design → image through the tag centres and matched dots
   (`scale, rot, t`) alongside the TPS. This is the "uniform expansion" model that defines the
   `expected` frame in Phase 7; the TPS residual on top of it is the non-uniform part.

Box helpers (`warped_box_centers`, `tag_box` in pairing) keep working because V2 dot tags are
still `dot|B{N}|…`.

## 4. Series driver and project runner

`rwtag/series.py::process_frames` is the V2 driver from `aruco/series.py` with:

- `filter_frame` using the per-box gates;
- gates: handedness equal to the baseline's; warp `per_det_median < max_resid` (default 10 px,
  scaled by λ: `max_resid × max(1, λ/2)`, since high-λ frames hold fewer, sparser dots); shared
  tags with accepted frames `≥ min_share` (default 40, or 10 ArUco ids whichever is met first,
  since at λ = 6 only four tags are in frame);
- rejection reasons as strings, kept on the frame and in the project.

`project.run_stages(entry, design, params, log)` runs Stage 1 (sidecar params, no auto-deskew)
→ `aruco.detect` → `filter_frame` → `tag_frame` and stores results on the entry's
`PipelineState`. `run_stages_validated` applies the three gates against already-accepted
entries. The sidebar's "Run stages 2–4" and "Run all pending" call these.

## 5. GUI

- **Filter tab**: sliders for min separation, max deviation, tag keep-out, the three dash
  gates; "Show dropped" colours by reason (`too_close`, `near_tag`, `off_lattice`, dash reasons);
  box quads and ids carried from Stage 2; per-box table (kept / dropped by reason).
- **Tag tab**: Tag current frame; hover readout of any feature's tag; kind and box filters;
  warped reference grid overlay (TPS) and the **expected** grid (similarity) in a second colour
  so the operator can see the non-uniform part; colour by residual (QC). Series group: process
  the project's images in λ order and list accepted / rejected with reasons. Exports: the
  per-frame tagged CSV (quick look); the full bundle is Phase 7.

## 6. Tests (`tests/test_phase4_tag.py`)

- Synthetic cases from V1 `test_dotfilter.py` and `test_refwarp.py` (`design_to_fit`
  semantics, warp round trip, strain) adapted to a V2 `Design`.
- `test_filter_per_box_lattice`: on `spectrum_clean`, no dot in a resolvable box is dropped as
  off-lattice; injected stray dots are.
- `test_identity_recovery_clean`: on `opt_clean` every λ, ≥ 99 % of truth dots in frame receive
  their true tag; zero wrong tags; all 36 (or in-frame) ArUco tags by id.
- `test_identity_recovery_warp`: on `opt_warp`, ≥ 97 % correct, ≤ 0.1 % wrong (a wrong tag is a
  dot assigned a neighbour's identity; the per-box gate at 0.45 pitch prevents it unless the
  warp exceeds half a pitch locally).
- `test_series_gates`: `cons_dim` is accepted at λ = 1, 3, 6 with the λ-scaled residual gate;
  a mirrored frame is rejected with a handedness reason; a frame with every tag masked is
  rejected as unregistered.
- `test_similarity_vs_truth`: the recorded similarity's scale equals the frame's λ × print
  scale within 0.2 % on `opt_clean`.
- Offscreen GUI smoke: filter and tag one dummy frame; run the series from the sidebar.

## 7. Acceptance

- Every frame of every dummy run is tagged, with identity recovery at the levels above.
- The project runner batch-processes a dummy project from the sidebar with per-image sidecar
  tuning, and rejections are loud.
- Tests pass. The user has tagged a dummy series in the GUI and hovered features.

## 8. How this serves the end goal

After this phase every feature in every accepted image has a design identity, a position in
`corr`, and a residual to the TPS warp. The similarity recorded in §3.6 is what the
`deviation_from_design` export is measured against. The pairing in Phase 6 is a pure join on
these identities.
