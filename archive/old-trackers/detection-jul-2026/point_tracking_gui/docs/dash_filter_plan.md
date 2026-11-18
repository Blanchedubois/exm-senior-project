# Implementation Plan — Filter dashes in Stage 4

> **Status: IMPLEMENTED.** `dotfilter.DashFilterParams` + `filter_dashes`; Stage 4 now has a **Dashes**
> group (3 rules, sliders) beside the **Dots** group, draws dots as circles / dashes as triangles by
> reason (with Show-dots / Show-dashes / Show-dropped toggles), and exports **dashes_filtered.csv** +
> dots_filtered.csv with box tags. 2.0× frame: 166 dashes → kept 129, off-grid 13, intersection 24,
> too-close 0; kept dashes run along the edges, corners/off-grid strays rejected.

**Goal.** Extend Stage 4 (Filter dots) to also filter the **boundary dashes**, with three
dash-specific rules that mirror how the dots are filtered.

## The three dash filters
1. **Too far from a grid line → reject.** The dashes sit on the box boundaries, so a dash whose
   perpendicular distance to the nearest box grid line exceeds `max_offgrid_frac × box_pitch` is
   spurious. (Same distance used by `dashes_on_grid`, now an adjustable filter.)
2. **Too close to each other → reject.** Along an edge the dashes are evenly spaced —
   **`dashes_per_edge ≈ 10`** per box edge (from the design), so the dash pitch =
   `box_pitch / dashes_per_edge`. Drop a dash whose nearest neighbour is closer than
   `min_sep_frac × dash_pitch` (duplicate/merged detections). The threshold is set by the
   **box-to-dash-spacing ratio**, as requested.
3. **At a grid intersection → reject.** Dashes are never at the box corners (line crossings). The
   distance to the nearest intersection is `hypot(du, dv)` (du, dv = perpendicular distances to the
   nearest u- and v-lines); drop a dash within `corner_radius_frac × box_pitch` of a corner.

## Phase 1 — Headless (`glyphtrack/dotfilter.py`)
`DashFilterParams(offgrid_enable, max_offgrid_frac=0.12, minsep_enable, min_sep_frac=0.5,
corner_enable, corner_radius_frac=0.10, dashes_per_edge=10)` and
`filter_dashes(dashes, grid, params) -> (records, counts)` where each record is
`{x, y, keep, reason}` with reason `'off_grid' | 'too_close' | 'intersection' | ''`
(priority: off_grid → intersection → too_close). Uses the box grid `{u, v, phase_u, phase_v,
box_pitch}` already computed in Stage 4.

## Phase 2 — Stage-4 GUI (`stageui/stage_filter.py`)
- A second group **"Filter dashes"** with an enable checkbox + slider for each of the three rules.
- `run()` also detects the raw dashes and filters them; `_refilter()` recomputes on any slider move.
- Overlay: dots as circles (as today) and **dashes as triangles** so the two never confuse — kept dash
  pink ▲, off-grid red ▲, intersection blue ▲, too-close orange ▲. Add **"Show dots" / "Show dashes"**
  toggles to declutter. Summary reports both dot and dash counts by reason.

## Phase 3 — Export
`dots_filtered.csv` stays; add **`dashes_filtered.csv`**
(`dash_id, x_px, y_px, keep, reason, box_i, box_j, edge, box_number`) — box tags from the solved grid
when available (via `results.tag_dashes`).

## Validation
2.0× frame: confirm kept dashes lie evenly along the boundaries, none at corners, no duplicates;
report counts per reason; export both CSVs; offscreen GUI runs + re-filters live.
