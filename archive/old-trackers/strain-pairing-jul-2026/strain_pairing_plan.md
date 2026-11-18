# Implementation Plan — Multi-image Pairing & Strain (glyph markers)

**Goal.** On top of the copied single-image glyph app (4 stages → filtered, box-tagged points), build a
**multi-image** tool that: processes an **initial** expansion image and a **series** of more-expanded
images through the same 4 stages, **pairs** every point (dot / dash / number / letter) across
expansions, writes **one big pairing CSV**, and maps the **strain / expansion** (heatmap, vector field,
distribution, measured-vs-expected table).

This mirrors the main project's `point_tracking_gui` + `expansion_field_gui` split, but for the glyph
system.

---

## 0. Architecture
```
Old_Tracker_StraiN_Pairing/
  point_tracking_gui/          COPIED — single-image glyph app (glyphtrack, stageui, model)  ✅ done
  strain_pairing_gui/          NEW — the multi-image app
    pairkit/                   headless core (no Qt): project, process, pair, strain, io_csv
    app/                       Qt GUI: image list + labels, embedded 4-stage view, pairing, strain
```
`strain_pairing_gui` reuses `../point_tracking_gui/{glyphtrack, stageui}` on `sys.path` (same mechanism
`expansion_field_gui` used). No duplication of the glyph pipeline.

**Per-image "point table" (the unit everything joins on).** Processing one image (the 4 stages) yields a
unified list of points, each already **box-tagged** by the pipeline:

| field | dots | dashes | glyphs (numbers/letters) |
|---|---|---|---|
| `type` | `dot` | `dash` | `digit` / `letter` |
| `box_number` | N | N | N |
| `sub_id` | local dot index within the box | `edge` + index along edge | `slot` (corner00/…/center/A/B/C/D) |
| `char` | — | — | the digit/letter |
| `x_px, y_px` | ✓ | ✓ | ✓ |
| `fx, fy` | ✓ (box-local) | ✓ | ✓ |

`box_number` comes from the registered grid; `fx, fy` are the point's position **as a fraction of its
box** — approximately invariant under uniform expansion, which is exactly what makes cross-expansion
pairing tractable.

---

## 1. Aspect 1 & 2 — process the initial image + the series
- **Image list** (left) with, per row, a **label = expansion factor** (e.g. `1.2`, `2.0`, `3.2`) and a
  role (**initial** vs **expansion**). Add-initial and add-expansions buttons; the label is editable.
- **Embedded 4-stage view** (the existing `stageui.StageWorkspace`): select an image → tune / run
  Stage 1–4 → the app stores that image's **filtered point table** (dots/dashes kept by Stage 4,
  glyphs from Stage 3). "Auto-run all 4" per image for speed; per-image params like the main project.
- Output: `project.results[path] = PointTable` for the initial and each expansion.

## 2. Aspect 3 — pairing
**Identity across expansions** (matched to the INITIAL image's points):
- **Glyphs**: exact key `(box_number, slot)` — the printed number/letter at that slot is unique per box.
- **Dots / dashes**: `(box_number, nearest fractional position within that box)` — for each point in an
  expansion, find the initial point of the same `type` in the same `box_number` whose `(fx, fy)` is
  nearest; accept if within a **tolerance** (else it's "disappeared" for that expansion). This tolerates
  the small strain-induced shift while rejecting wrong matches.
- A point **present in the initial but missing in an expansion** is kept (blank cell for that
  expansion); points that only appear later are ignored (identity is defined by the initial set).

**The big CSV** — one row per initial point, columns grouped by expansion:
```
point_id, type, box_number, sub_id, char, init_x, init_y,
  exp1_x, exp1_y, exp1_present, exp2_x, exp2_y, exp2_present, …
```
(one `<label>_x, <label>_y, <label>_present` triple per expansion; blank when disappeared).

## 3. Aspect 4 — strain / expansion
**Common-box alignment.** For an (initial, expansion) pair, pick a **box present in both with the same
number** (default: the one nearest the overlap centre; user-selectable) and use it to **centre** both
fields on that box's centre. A similarity transform (from the shared box grids / paired points, RANSAC)
maps the expansion into the initial's frame so displacements are comparable.

**Per-point expansion + strain.** For each paired point, in the common frame:
- **local expansion** = how much the point has moved apart from the reference relative to the initial
  (candidate metrics in Q4);
- **displacement vector** = paired position (expanded, aligned) − initial position → the strain field.

**Four outputs (per expansion image):**
1. **Heatmap** of per-point local expansion over the field.
2. **Vector field** of the displacements.
3. **Distribution** — histogram of per-point expansion; **mean = measured expansion**, **σ = spread**.
4. **Table** — measured expansion ± σ vs **expected = label ratio** (`label_exp / label_init`), per
   expansion, with the error from the histogram σ.

---

## 4. Phases (build order, each with a verification check)
- **P1 — Skeleton + processing. ✅ DONE & VERIFIED.** `strain_pairing_gui/pairkit/{types,process,
  project}.py` reuse the copied glyph core via sys.path; `pairkit.process.process_image` runs Stages 1-4
  headlessly (auto-deskew → geometry → grid model → filter) into a `PointTable` of box-tagged dots /
  dashes / numbers / letters. GUI shell `app/{main,image_list}.py` (+ run.py + launcher): image list with
  editable expansion labels, embedded 4-stage `StageWorkspace`, "Process all", and a point-tables
  summary. *Verified:* 1.5× → 2453 dots/174 dashes/115 glyphs, 2.0× → 1468/128/73, both registered;
  box pitch 598→764 px; GUI constructs + processes offscreen.
- **P2 — Pairing + big CSV. ✅ DONE & VERIFIED.** Points are now tagged with **design-frame** fractions
  (converted via the registration orientation) so identity is comparable across images despite each
  fit's arbitrary U/V axes. `pairkit.pair` matches by same box + type + nearest design fraction (tight
  for dots/dashes, looser for glyphs), greedy one-to-one; `io_csv.write_pairing` writes the wide CSV
  (`…, <label>x_x, <label>x_y, <label>x_present`). GUI: **Pair to initial** (rates tab) + **Export
  pairing CSV**. *Verified:* self-pairing **100%** (2742/2742, all types); cross 1.5×→2.0× pairs the
  co-visible points (dots 1444, dashes 95, numbers 58) — the rest is FOV / partial-box loss.
  *Known limitation:* letters pair ~0 here because letter **recognition** is sparse (STL-trained
  classifier) and lands on different edges per image — a recognition gap, not a pairing bug; improves
  with real-crop training.
- **P3 — Strain core. ✅ DONE & VERIFIED.** `pairkit.strain.compute_strain`: per-point deformation
  gradient F from k-NN paired displacements → areal **J = det F** and linear = √J (rotation-invariant,
  no alignment needed); global-similarity scale as a cross-check; **displacement field** via rigid
  de-rotation into the initial frame centred on a common reference box; distribution stats (mean, σ,
  median). *Verified:* synthetic (initial ×1.40 + rotation + translation) → **global_scale 1.400,
  per-point linear 1.400 ± 0.000** (exact); real 1.5×→2.0× → **1.304 ± 0.015** (1597 pts, ref box 18)
  vs expected **1.333** (~2% off, tight σ).
- **P4 — Analysis views + export. ✅ DONE & VERIFIED.** `app/strain_view.py` — a **Strain** tab with
  an expansion selector and Heatmap / Vectors / Both modes over the deskewed initial image (per-point
  linear expansion coloured; displacement quiver), a **distribution histogram** with mean (amber) +
  expected (red dashed) lines, and a **measured-vs-expected table** across all expansions (measured ± σ,
  expected label ratio, |Δ|, n). Exports `expansion_summary.csv` + per-expansion per-point
  `strain_<label>x.csv`. *Verified offscreen:* 1.5×→2.0× renders all three views + table row
  **1.304 ± 0.015 vs expected 1.333** (1597 pts); export writes the CSVs.
  *Known consideration:* pairing needs **consistent box numbering across frames**; at high expansion
  only a few boxes are in view (e.g. 3.0× shows boxes 1,2,6,7), so auto-registration can lock a
  different orientation/offset and pair 0 — use the embedded Stage-2 **manual box anchor** to pin the
  numbering on such frames, then re-pair.

## Status: all four phases complete. The multi-image pairing + strain app is functional end-to-end
(process → pair → strain → export), verified on the real 1.5×/2.0× frames and an exact synthetic check.

## Follow-ups (implemented)
- **Choose the centre box** — Strain tab has a `centre box` selector (auto or a specific box number);
  the displacement field re-centres on it (`compute_strain(..., ref_box=N)`).
- **Measured-vs-expected trend graph** — `measured vs expected` plot with the **expected y=x line**
  (dashed) and each expansion as a point with ±σ error bars.
- **Box-by-box pairing** — `pair.pair` now pairs **per box number**, with a small per-box translational
  ICP (`_translate_align`) that absorbs registration drift; reports per-box dot stats (`box_stats`).
  *Verified:* 1.5×→2.0× **1.304 ± 0.015** (exp 1.333, n=1597) and 1.5×→2.5× **1.646 ± 0.028**
  (exp 1.667, n=836) — both on the expected line; central boxes pair ~95%, edge boxes less (partial FOV).
  *Studied:* 1.5×→3.0× pairs ~0 because those two frames capture **different regions** (1.5× boxes 3–24
  vs 3.0× boxes 1,2,6,7) with non-overlapping dots even in shared boxes — a data-overlap limit, not an
  algorithm bug; use overlapping frames or the Stage-2 manual anchor to align numbering.

---

## 5. Assumptions (please confirm — see questions)
- All frames are at the **same microscope magnification / pixel size**, so greater expansion shows as
  **wider pixel spacing** (and fewer boxes in view). This lets pixel positions be compared after the
  common-box alignment, and makes the box-pitch ratio a direct expansion estimate.
- The printed pattern is **rigid** (features keep identity; the gel between them expands), so a point's
  box + fractional position is a stable identity.
- Expansion labels are multiplicative (`1.2×`, `2.0×`); expected relative expansion = `label / init_label`.

---

## Decisions (locked in)
1. **Separate `strain_pairing_gui`** reusing the copied glyph core via `sys.path`.
2. **Pair dots/dashes by same `box_number` + nearest box-fractional position** (tolerance ≈ 0.3× dot
   spacing); glyphs by exact `(box_number, slot)`. Identity fixed by the **initial** image.
3. **Big CSV cell = pixel `x, y` + present flag** per expansion; strain quantities live in the strain
   outputs.
4. **Primary expansion metric = deformation gradient areal J = det F** from the paired displacement
   field (the main project's strain measure); the distance-from-centre ratio shown as a secondary,
   intuitive read-out.

## Open questions (resolved above)
1. **Architecture** — new separate `strain_pairing_gui` reusing the copied glyph core (recommended,
   mirrors `expansion_field_gui`), or fold the multi-image workflow into the copied app itself?
2. **Pairing dots/dashes** — match by **same box_number + nearest box-fractional position within a
   tolerance** (recommended; glyphs matched exactly by slot). Good default tolerance ≈ **0.3 × dot
   spacing** (in box-fraction units)? And confirm: identity is fixed by the **initial** image's points.
3. **Big-CSV cell content** — per expansion, store the paired point's **pixel `x, y` (+ present flag)**
   (recommended). Also add per-cell **local expansion** and/or **displacement**, or keep those only in
   the strain outputs?
4. **Expansion metric** (how "measured expansion" per point is computed) —
   (a) **distance-from-common-box-centre ratio** (expanded/initial) per point;
   (b) **local deformation gradient** J = det F from the paired displacement field (areal expansion,
   like the main project's strain);
   (c) **nearest-neighbour dot-spacing ratio** per point.
   Which should be the primary measure (I can show more than one)?
