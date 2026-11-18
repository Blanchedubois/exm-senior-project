# Reference-Warp Tagger — Stage 3 Implementation Plan
### Filter false-positive dots & dashes → the clean marked image

**Project:** `reference-warp-tagger/` · **Scope:** Stage 3 only (a third tab)
**Ported from:** `Old_Trackers_Detection/point_tracking_gui/glyphtrack/dotfilter.py`
**Consumes:** the Stage-2 `DetectResult` · **Feeds:** Stage 4 (tag)
**Written:** 2026-07-17

---

## 0. Where this fits

| Stage | Goal | Status |
|---|---|---|
| 1 | Correct optics. | done |
| 2 | Detect & identify (dots, dashes, numbers, letters); number & orient the boxes. | done |
| **3** | **Filter the false-positive dots & dashes; show the clean filtered marked image (dots/dashes/numbers/letters marked, grid following the dashes, boxes numbered).** | **this document** |
| 4 | Reference-warp tag the **filtered** points/grid. | planned |

Stage 3 is a **third tab**. It does **not re-detect** — it consumes the Stage-2 `DetectResult`
already in `PipelineState.detection` (dots, lattice basis, all dashes, box grid, glyph
positions, and the solved model), applies the toggleable quality filters with **live** slider
feedback, and renders the **filtered marked image**: the surviving dots/dashes plus the
Stage-2 grid, box numbers, and glyph labels. The filtered point sets are published to
`PipelineState.features` for Stage 4 to tag.

> **Decided (from Stage-4 spec):** tagging happens on the **processed + filtered** points. So
> Stage 3's output — the kept dots/dashes, with the grid/numbering carried from Stage 2 — is
> exactly the input Stage 4 warps the reference onto.

---

## 1. What to port

One headless module — the filtering is already written and validated:

| Module (old) | Role | Port |
|---|---|---|
| `glyphtrack/dotfilter.py` | `DotFilterParams` + `filter_dots`; `DashFilterParams` + `filter_dashes` | **verbatim** into `rwtag/glyph/dotfilter.py` |

No new dependencies (numpy + scipy KDTree, already required). `results.py`/`finalize`
(per-point box tags) is **Stage 4**, not ported here — Stage 3 filtering does not require
registration.

---

## 2. The filters (exactly as the old app, all toggleable + live sliders)

**Dots** — `filter_dots(dots, basis, glyph_pos, glyph_h, params)` → `(records, counts)`,
each record `{x, y, keep, reason}`, reason priority `too_close → on_glyph → off_lattice`:
1. **Too close to a neighbour** — nearest neighbour < `min_sep_frac × dot_pitch`
   (dot pitch = box pitch / 18.75, from the refined lattice). Default **0.55**.
2. **On a number/letter** — within `glyph_radius_frac × glyph_height` of a detected glyph.
   Default **0.80**. (No-op if Stage 2 only reached *Detect grid* — no glyph positions yet.)
3. **Off its ideal lattice node** — deviation from the nearest refined-lattice node >
   `max_dev_frac × dot_pitch`. Default **0.35** (the primary adjustable knob).

**Dashes** — `filter_dashes(dashes_all, grid, params)` → `(records, counts)`, reason priority
`off_grid → intersection → too_close`:
1. **Too far from a grid line** — perpendicular distance to the nearest box line >
   `max_offgrid_frac × box_pitch`. Default **0.12** (the same metric `dashes_on_grid` uses,
   now adjustable).
2. **At a grid intersection** — within `corner_radius_frac × box_pitch` of a line crossing
   (dashes never sit at box corners). Default **0.10**.
3. **Too close to each other** — nearest neighbour < `min_sep_frac × dash_pitch`, dash pitch =
   `box_pitch / dashes_per_edge` (`dashes_per_edge = 10` from the design). Default **0.50**.

Filtering runs on **all** detected dashes (`DetectResult.dashes_all`), so `off_grid` is a
first-class filter reason (Stage 2's `dashes_on_grid` was only a preview cull).

---

## 3. Data contracts

- **`DetectResult` gains `glyph_h: float`** (median glyph-blob height ÷ 1.4, computed in the
  Stage-2 `read` step; default 30.0). Needed by the on-glyph dot filter. Wire it through
  `detect.read` and both `DetectResult` constructions (headless `detect()` and the panel's
  `_store_detection`).
- **New `FilterResult`** (in `rwtag/glyph/types.py`), stored on `PipelineState.features`:

```python
@dataclass
class FilterResult:
    dot_recs: list        # [{x,y,keep,reason}, ...]  (all dots, keep flag)
    dash_recs: list       # [{x,y,keep,reason}, ...]  (all dashes)
    dot_counts: dict      # {kept, too_close, on_glyph, off_lattice}
    dash_counts: dict     # {kept, off_grid, intersection, too_close}
    kept_dots: np.ndarray    # (n,2) surviving dot centres  -> Stage 4 input
    kept_dashes: np.ndarray  # (m,2) surviving dash centres -> Stage 4 input
    dot_params: dict
    dash_params: dict
```

- `AppState.set_features(fr)` + a `featuresChanged` signal (mirrors `set_detection`).

---

## 4. GUI — the third tab

### 4.1 Tab wiring (small)
Add a third tab to the existing `QTabWidget`: `"3 · Filter"` → `_stage_page(canvas3,
FilterPanel)`, its own `ImageCanvas`. On entering the tab, pull `PipelineState.detection`;
if absent, show "Run Stage 2 (Detect grid) first".

### 4.2 `FilterPanel` (modelled on `stageui/stage_filter.py`)
- **Dots** group — three `enable + SliderSpin` rows (min-sep 0.1–1.0, glyph radius 0.3–1.6,
  max deviation 0.05–1.0).
- **Dashes** group — three `enable + SliderSpin` rows (max off-grid 0.03–0.4, min-sep 0.1–1.0,
  corner radius 0.02–0.3).
- **Filter** button; sliders/checkboxes **re-filter live** (`_refilter`).
- View toggles: Show dots ● / Show dashes ▲ / Show dropped / Show glyph labels / Show box
  numbers.
- **Export filtered…** — `dots_filtered.csv` + `dashes_filtered.csv`
  (`id, x_px, y_px, keep, reason`); box tags are added in Stage 4.
- Summary + Log: counts per reason and the dot/dash pitch.

### 4.3 The filtered marked image (canvas overlay)
Reuse `canvas.draw_glyph_grid` for the "marked" layer, then overlay the filtered points:
- **grid** — cyan box-boundary lines from `DetectResult.grid` (follows the dashes);
- **box numbers** — from `model.node_num` at box centres (if registered);
- **glyph labels** — the solved `model.labels` coloured by state (numbers/letters marked;
  toggle);
- **dots** — kept = green ● (small); dropped = red (too_close) / orange (on_glyph) / magenta
  (off_lattice), gated by *Show dropped*;
- **dashes** — kept = pink ▲; dropped = red (off_grid) / blue (intersection) / orange
  (too_close).

Colour maps ported verbatim from the old `stage_filter` (`_DOT_COLOR`, `_DASH_COLOR`).

**Export marked image…** (existing toolbar action) already grabs the active tab's canvas, so
on the Filter tab it writes the *filtered* marked PNG — the Stage-3 deliverable.

---

## 5. Forward hooks for Stage 4
- `FilterResult.kept_dots` / `kept_dashes` are the **only** points Stage 4 tags — the "tag the
  filtered points" requirement.
- The Stage-2 `reg` (orientation + offset + `node_num`) travels unchanged; Stage 4's
  reference-warp uses the kept dots + `reg` as its anchor.
- Keep the full `dot_recs`/`dash_recs` (kept **and** dropped, with reasons) so the record is
  auditable and Stage 4 never silently loses points.

---

## 6. Testing (headless, no Qt)
- **`filter_dots`** — synthetic lattice: a dot placed on top of a glyph position → `on_glyph`;
  a dot displaced far from its node → `off_lattice`; a duplicate next to a dot → `too_close`;
  a clean-lattice dot → kept.
- **`filter_dashes`** — dashes on a box line kept; one at a corner → `intersection`; one mid-box
  → `off_grid`; a duplicate → `too_close`.
- **Real-frame integration** — build a `DetectResult` via `detect.detect` on the 2.0× frame,
  run both filters, assert the kept fraction is high and the dropped dots cluster on glyphs /
  off-lattice (sanity: kept dots ≳ 90 %).
- **GUI smoke (offscreen)** — three tabs present; Filter consumes the Stage-2 detection,
  re-filters live, publishes `FilterResult`, and Export writes the two CSVs.

---

## 7. Milestones
1. **M1** — port `dotfilter.py`; add `glyph_h` + `FilterResult`; filter unit tests green.
2. **M2** — third tab + `FilterPanel`; live filtering over the Stage-2 detection; filtered
   marked overlay.
3. **M3** — export CSVs; publish `FilterResult` to state; offscreen GUI smoke test.

---

## 7a. Calibration & grid-alignment fixes (2026-07-17, from the real frames)
Measured on `Stitched Images/*`:
- **Dot deviation** from a single global lattice is median ~15–19 % of pitch, **p99 up to
  ~50 %** — because the gel is *warped* (that displacement is the signal). So the off-lattice
  gate at 0.35 was culling valid dots. **`max_dev_frac` default → 0.60**, `min_sep_frac → 0.50`,
  dash `max_offgrid_frac → 0.15`. Result on 2.0×: kept dots 1443 → **1506/1519** (off-lattice
  61 → 0).
- **Box grid alignment.** The box **pitch** is correct (dash-measured 773 ≈ glyph-fit 773 ≈
  18.75× dot), but the **dash-phase** grid is unreliable (only ~120 of ~400 dashes detected),
  so its lines drifted off the boundaries while the box *numbers* (drawn from the glyph fit)
  were right. Fix: **draw box lines/slots from the glyph-fit lattice** (`lattice.fit_box_corner`)
  whenever a fit exists, and filter dashes against `lattice.grid_from_fit(fit)`. The fit is
  registration-validated, so its boundaries track the dashes. Residual drift at the far
  corners is genuine warp a single affine fit can't capture (a per-box/TPS refinement is a
  Stage-4 concern).

## 8. Open items (non-blocking)
- Whether `dashes_per_edge` (10) matches this print's dash count per edge — verify on a frame;
  it only affects the dash min-sep threshold.
- Whether to persist the Stage-3 params/result into the session JSON (a `stage3` section),
  like Stage 2 — useful for reproducibility; can be added when Stage 4 lands.
