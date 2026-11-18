# Implementation Plan — Stage 3: Final Grid / Results

> **Status: IMPLEMENTED.** `glyphtrack/results.py` (`tag_dots`, `finalize`, `GridResult.write_csv`) +
> `stageui/stage_results.py` (Stage **3 Results**). On the 2.0× frame: 14 boxes solved (coherent
> numbering), **1567 dots each tagged** to a box + local (fx,fy), big box numbers + letters drawn, and
> **boxes.csv / glyphs.csv / dots.csv** exported. Dots are recorded (faint, toggle) rather than
> emphasised, as requested.
>
> **Tagged dashes (added).** Stage 3 also tags the on-grid boundary dashes — each with its box (i,j),
> which edge (u0/u1/v0/v1), and box number — shows them as **pink ▲** (toggle), and exports
> **dashes.csv**. 2.0× frame: 159 dashes tagged.

**Goal.** A clean output stage that presents the **final solved grid**: one definitive **box number**
per box, the **A/B/C/D letters**, and every **fill dot tagged** to its box + local position (recorded
for downstream tracking, shown only faintly/optionally). Export it all to CSV.

This is the payoff stage — Stage 1 (correct + deskew) and Stage 2 (detect + read + solve) feed it; it
just consolidates and presents.

---

## 1. What it shows / records
- **Final grid** — box boundaries + each box's **number drawn large at its centre** (the authoritative
  value from the vote + registration + auto-complete), and the four edge **letters**.
- **Dots (recorded, not emphasised)** — every detected dot **tagged** with the box it belongs to
  `(box_i, box_j)`, its **box number N**, and its **local position** `(fx, fy) ∈ [0,1]²` inside the box.
  Shown only as a faint overlay behind a toggle (default off), because the point of recording them is
  export / tracking, not display.
- **Summary + export** — counts, and CSVs written on demand.

## 2. Pipeline (reuses everything built)
`Stage-1 corrected image (incl. deskew)` → `detect_dots` → `fit_box_grid` → `read_glyphs` (geometry
→ `fit`) → `read_slots` (slot-only OCR) → `build_grid_model` (club + vote + register + auto-complete)
→ **`results.finalize`** (below). No new maths — a consolidation layer.

## 3. New headless module `glyphtrack/results.py`
```python
@dataclass
class DotTag:    x; y; box_i; box_j; box_number; fx; fy      # a tagged fill dot
@dataclass
class BoxResult: box_i; box_j; col; row; number; letters:dict; cx; cy   # a solved box
@dataclass
class GridResult:
    registered:bool; boxes:list[BoxResult]; dots:list[DotTag]
    labels:list          # the per-slot state labels (for the completed overlay)
    summary:str
    def write_csv(out_dir)   # boxes.csv, dots.csv, glyphs.csv

def tag_dots(dots, fit, reg) -> list[DotTag]      # box + local coords + N per dot
def finalize(model, fit, dots) -> GridResult      # from the solved model
```
- `tag_dots`: for each dot, `bc = inv([U|V])·(dot − O)`; `box=(⌊bc⌋)`, `local=(bc − box)`,
  `N = box_number(box, reg)` (may be None outside the 5×5).
- `finalize`: from `model` (registered), build one `BoxResult` per in-grid node (number from
  `node_num`, letters from the orientation), tag all dots, keep the completed per-slot `labels`.

`gridmodel` gains a small helper `box_colrow(node, reg) -> (col, row, N)` used by both.

## 4. GUI — `stageui/stage_results.py` (Stage 3 "Results")
- **"Compute final grid"** runs the pipeline on the current (Stage-1-corrected) image.
- Canvas overlay: box boundaries (subtle) + **big box numbers** at centres + letters; optional faint
  dots (checkbox, default off).
- A compact **table**: box (i,j) → number, and total dots tagged / boxes solved.
- **"Export CSV…"** → pick a folder → writes `boxes.csv`, `glyphs.csv`, `dots.csv`.
- If the grid isn't registered, say so (and show the raw reads), never invent numbers.

`canvas.add_labels` gains a `size` argument so box numbers render large; a thin `draw_final_grid`
helper draws quads + big numbers + letters + optional dots.

## 5. Workspace
`STAGE_NAMES = ["1 Correct optics", "2 Glyph grid", "3 Results"]`; append `ResultsPanel`. Stage 3
re-runs the pipeline itself (fast) so it's independent of whether Stage 2 was clicked.

## 6. CSV schema
- `boxes.csv`: `box_i, box_j, col, row, number, A, B, C, D`
- `glyphs.csv`: `box_i, box_j, slot, char, state` (confirmed/corrected/predicted/conflict)
- `dots.csv`: `dot_id, x_px, y_px, box_i, box_j, box_number, local_fx, local_fy`

## 7. Validation
- Headless: on the 2.0× frame, `finalize` returns registered=True, ~14 boxes with coherent numbers,
  and ~1500 dots each tagged with a box (interior dots get a box number). CSVs write + reload.
- Offscreen GUI: stage constructs, "Compute final grid" runs without error, export writes files.

## 8. Notes
- Dots outside the solved 5×5 (or off-grid) get `box_number = None` — kept in the CSV, flagged.
- This stage is display/export only; all recognition/registration lives in Stages 1–2.
