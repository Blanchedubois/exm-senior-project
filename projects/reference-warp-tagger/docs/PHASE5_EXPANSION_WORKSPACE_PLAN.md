# Reference-Warp Tagger — Expansion-Analysis Workspace Plan
### Multi-image project: per-image 4-stage tagging → pairing → aligned overlay → displacement field → expansion summary

**Project:** `reference-warp-tagger/` · **Builds on:** the completed Stages 1–4
**Written:** 2026-07-17 · delivered **incrementally, one phase at a time, each verified by
the user before the next begins.**

> **Decisions locked (2026-07-17):** (1) **evolve the existing app** into the project
> workspace (one app, sidebar + 8 tabs); (2) Initial = **lowest label automatically**, with
> a "Set as initial" override; (3) alignment = **Kabsch rotation + translation, scale
> locked to 1**, about the common box centres; (4) heat map = **both quantities,
> selectable** (local linear expansion / displacement magnitude).

---

## 0. What is being added

Today the app is single-image (one frame through Correct → Detect → Filter → Tag, plus a
headless series batch inside the Tag tab). The new workspace makes **multiple images
first-class**:

- **Image roles:** one **Initial** image (the reference state) + N **Expanded** images.
  Every image carries its **expected expansion** factor (parsed from `1.5X…` filenames,
  editable) — recorded in the project.
- **Per-image tagging:** each image individually runs the existing 4-stage pipeline (the
  four tabs operate on whichever image is selected; per-image tuning is preserved).
- **Cross-image analysis phases** (new tabs), all downstream of tagging:
  - **Pair** — match dots initial ↔ each expanded image by shared tag; positions of every
    paired dot in both frames → CSV.
  - **Overlay** — find a box common to both frames, align the expanded image to the initial
    by **rotation + translation about that box's centre (NO scaling)**; show initial in
    cyan / expanded in red, overlaid, with layer toggles + opacity.
  - **Field** — per-pair displacement (and local strain) in the aligned frame → CSV; render
    the **vector field** and a **heat map**, toggleable per expanded image.
  - **Summary** — **average measured expansion per expanded image vs its expected
    expansion** (table + plot), exported.

Everything reuses the proven `rwtag` cores (`correct`, `glyph`, `refwarp`): pairing = tag
join (already what `series.pair_table` does), strain = `strain.py`, per-image processing =
the Stage-1..4 machinery unchanged.

---

## 1. Phase A — Project workspace (multi-image management)

**Goal:** manage N images, each individually taken through Stages 1–4, with state kept per
image.

### Design
- **Project sidebar** (left of the existing tab area): the image list. Each row:
  `role · label × · filename · stage status (S1…S4 ticks)`. Actions: *Add images…*
  (auto-parse labels, confirm/edit in a dialog), *Set as initial*, *Remove*, label edit.
- **Selection model:** the four existing stage tabs always operate on the **selected**
  image. Switching selection swaps the active `PipelineState` (image + params + results) —
  the current single-image `AppState` grows into a `Project` holding one `PipelineState`
  per image, with the selected one live. Heavy arrays (raw/corrected images) are loaded
  lazily / dropped for unselected images to bound memory (~7 MP float32 each; results
  `DetectResult/FilterResult/TagResult` stay).
- **Persistence:** a `project.rwproj.json` next to the images: image list, roles, labels,
  per-image stage status + Stage-2 manual anchors. Stage-1 params stay in the existing
  per-image sidecars. Re-opening the project restores the list; recomputable results are
  re-run on demand (cheap, seconds per image).
- **Convenience batch:** a *Run stages 2–4* button per image (and *Run all pending*) that
  executes the pipeline with each image's saved tuning — the user can then inspect any
  stage manually. (This reuses the Stage-4 series machinery, now writing results back into
  the project instead of a throwaway batch.)

### Verify (user)
Add the six stitched frames; tune/tag two of them via different routes (one fully manual,
one via *Run stages 2–4*); switch between images and confirm each tab shows that image's
own state; reopen the project and confirm restoration.

---

## 2. Phase B — Pairing (initial ↔ each expanded)

**Goal:** for every expanded image, the list of dots present in **both** frames, with both
positions.

### Design
- Pairing is a **tag join** on `TagResult.tags` (dots only by default): for expanded image
  E, `pairs(E) = {tag: (x_init, y_init, x_exp, y_exp)}`.
- **Pair tab:** table per expanded image (selector): tag, initial x/y, expanded x/y;
  counts summary (n dots initial, n dots expanded, n paired, pairing fraction).
- **CSV export:** one per expanded image — `pairs_<label>x.csv`:
  `tag, category, x_init_px, y_init_px, x_exp_px, y_exp_px` — plus the existing wide
  pairing CSV across all images.
- Guards: an image without a TagResult shows "tag it first"; pairing recomputes
  automatically when a TagResult changes.

### Verify (user)
Pair 1.5× ↔ 2.0×; spot-check a few tags in the table against the two tagged views; export
and open the CSV.

---

## 3. Phase C — Common-box alignment & cyan/red overlay (NOT scaled)

**Goal:** overlay expanded on initial, aligned by a common box centre + orientation, with
**scale untouched** so the physical growth stays visible.

### Design
- **Common box:** boxes whose dot tags appear in both frames, ranked by paired-dot count;
  auto-pick the best, user-overridable (combo). Box centre in each frame from that frame's
  TPS warp (`warped_box_centers`) — *decision point Q3*.
- **Alignment transform (rigid, scale = 1):** translation aligns the two box centres;
  rotation is the least-squares rotation (Kabsch, det-guarded, **no scale**) of the paired
  dot vectors about those centres. Applied to the expanded image via `cv2.warpAffine`
  (`M = [R | c_init − R·c_exp]`) on a canvas sized to hold both.
- **Overlay view:** initial → **cyan** channel, aligned expanded → **red** channel,
  additive composite (grey where they coincide). Controls: per-layer visibility + opacity
  sliders, expanded-image selector, common-box combo, aligned-box-centre marker, optional
  paired-dot markers. Export composite PNG.
- The rigid transform per expanded image is stored (project JSON) — Phase D measures
  displacements **in this aligned frame**.

### Verify (user)
Overlay 2.0× on 1.5×: the common box centres coincide, orientations match, and the red
lattice visibly *grows outward* from the aligned centre (no scaling applied). Toggle
layers/opacity; try a different common box.

---

## 4. Phase D — Displacement / strain field (per expanded image)

**Goal:** quantify initial → expanded deformation from the paired dots, in the aligned
(unscaled) frame; visualise as vector field + heat map.

### Design
- For every paired dot: `u = p_exp_aligned − p_init` (displacement in the aligned frame).
  Local linear expansion per dot from `strain._local_F` over k-NN paired neighbours
  (rotation-invariant; unaffected by the rigid alignment).
- **CSV per expanded image** — `field_<label>x.csv`:
  `tag, x_init, y_init, x_exp, y_exp, x_exp_aligned, y_exp_aligned, u_x, u_y, u_mag,
  local_linear_expansion`.
- **Field tab:** over the initial image — **quiver** (arrows, decimated to stay readable,
  scale slider) and **heat map** (scattered values → `scipy.interpolate.griddata` on a
  regular grid → semi-transparent colormap). Heat quantity selectable: `|u|` or local
  linear expansion (*Q4*). Toggles: vectors / heat map / image; expanded-image selector
  (per-image, as requested); colorbar + stats line (median/p90).

### Verify (user)
Field for 2.0×: arrows radiate from the aligned box centre, heat map of local expansion is
≈ uniform ~1.33 with warp deviations visible; switch to 3.0× and confirm the selector
swaps everything.

---

## 5. Phase E — Expansion summary (measured vs expected)

**Goal:** one view answering "how much did each image actually expand?"

### Design
- Per expanded image: **measured expansion** = mean ± σ of the per-dot local linear
  expansion (Phase D values; identical maths to the validated `strain.py`), **expected** =
  `label_exp / label_init`. Table: image, expected, measured, σ, n pairs, pairing %.
- **Plot:** measured vs expected with error bars + identity line (the Stage-4 trend plot,
  now fed by the project pipeline).
- **Export:** `expansion_summary.csv` + plot PNG. Expected-expansion labels (from
  filenames, user-edited) are recorded per image in the project JSON and in every exported
  CSV header.

### Verify (user)
All five expanded frames summarised; measured tracks expected (per the validated series
numbers); exports open cleanly.

---

## 6. GUI restructure (Phase A, carried through)

```
MainWindow
  toolbar: Add images… · Save project · Open project · Export…
  ┌ sidebar (project) ┐ ┌ tabs (operate on SELECTED image / analysis) ─────────┐
  │ ● 1.5× initial ✓✓✓✓ │ │ 1 Correct · 2 Detect · 3 Filter · 4 Tag           │
  │ ○ 2.0× exp     ✓✓✓✓ │ │ 5 Pair · 6 Overlay · 7 Field · 8 Summary          │
  │ ○ 3.0× exp     ✓—— │ └────────────────────────────────────────────────────┘
  └────────────────────┘   (5–8 are cross-image; enabled once ≥1 pairing exists)
```

New headless module: `rwtag/pairing.py` (pair join, rigid Kabsch alignment, displacement +
field grids, CSVs) — GUI stays thin, everything testable without Qt.

---

## 7. Phase order & verification gates

| Phase | Deliverable | Gate | Status |
|---|---|---|---|
| **A** | project sidebar, per-image state, persistence, run-pending batch | user verifies multi-image workflow | **done 2026-07-17** |
| **B** | pair join + table + CSVs | user verifies pairs/CSV | **done 2026-07-17** |
| **C** | rigid alignment + cyan/red overlay | user verifies overlay visually | **done 2026-07-17** |
| **D** | displacement/strain CSV + quiver/heat map (+ cross-frame validation added to the project batch runner — the standalone-registration trap surfaced here) | user verifies fields | **done 2026-07-17** |
| **E** | summary table/plot + exports | user verifies numbers | **done 2026-07-17** |

Each phase lands with headless tests (`tests/test_pairing.py` grows per phase) + an
offscreen GUI smoke test, and stops for user verification before the next.

---

## 8. Resolved decisions (confirmed 2026-07-17)

1. **App structure** — evolve the existing window (single app, project sidebar + 8 tabs).
2. **Initial designation** — automatic (lowest label) with a manual override.
3. **Alignment rotation** — Kabsch rotation + translation about the common box centres,
   scale locked to 1.
4. **Heat map** — both quantities, selectable (local linear expansion / |u|).
