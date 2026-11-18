# Implementation Plan — Grid Inference & Auto-Complete (next stage)

> **Status: IMPLEMENTED.** `glyphtrack/gridmodel.py` (club_digits → vote_boxes → register →
> build_grid_model) + a **"Solve grid (auto-complete)"** button in the Glyph-grid stage with a tunable
> digit-club distance. On the 2.0X frame: **registered from 7 anchors, 14 boxes solved** with a
> coherent numbering (box 13 centre, 18 = +col, 14 = +row, …); 52 confirmed / 3 corrected / 88
> predicted / 2 conflicts. Per-glyph labels are colour-coded by state. All four decisions below are
> honoured (distance clubbing, flag-conflict, fill-predicted, per-glyph labels).
>
> **Clubbing by dots + single labels.** Two digits club into one number when they are close AND have
> **no fill dot between them** (`gridmodel._dot_between`) — so a box's own two digits join but adjacent
> boxes' numbers (always dot-separated) don't. Each clubbed number is drawn as **one label** ("13", not
> "1" + "3"). A lone digit that is a subset of the box's number (e.g. "1" of "13", the "3" undetected)
> is treated as a **partial → corrected to the full number**, not a conflict.
>
> **Slot-only OCR (`reader.read_slots`).** Recognition now runs *only where glyphs can be*: a detected
> blob is classified only if it sits within `slot_tol` (0.14 box) of a fiducial slot centre, restricted
> to that slot's role — so **dots and boundary dashes are never read as characters**. Same registration
> quality, with the non-glyph contamination removed. Both *Read glyphs* and *Solve grid* use it.
>
> **Ordering-driven registration + manual anchors (`register`).** Registration now **enumerates the 8
> orientations and picks the one most consistent with the numbering rule** (N = col·5 + row + 1 — up
> = +1, down = −1, right column = +5) across confident boxes, with letters as extra evidence — so the
> vertical/horizontal ordering drives the result instead of relying on the letters alone. When it still
> can't lock (too few confident boxes), the Glyph-grid stage says so and lets you **identify a box**:
> *Set box number* → click a box → type its number (and/or *Set letter* → click a letter → pick A–D).
> One or two manual anchors (weighted heavily) register the whole grid; anchors live in AppState so
> Stage 3 uses them too. `build_grid_model(..., manual=...)`.

**Goal.** Turn the per-glyph reads into a **coherent 5×5 grid model**, then use that model's
**redundancy and rigidity** to (1) club digits into box numbers and (2) **auto-fill / correct** the
weak or missing reads from what the grid *must* say. Design to workshop first — **Open questions** at
the end.

This is the analogue of the ArUco "map grid" stage: a few confident reads anchor the whole lattice,
and everything else is then determined by geometry.

---

## 0. What we already have (inputs)
- **Deskew** (Stage 1) makes glyphs upright → recognition is now reliable.
- **`lattice.fit_fiducial_lattice`** gives the box lattice `(O, U, V)` and assigns every detected glyph
  a **box node `(box_i, box_j)`** and a **slot** (`corner00/02/20/22`, `center`, or `A/B/C/D`).
- **`reader.read_glyphs`** gives each glyph a **character + confidence**, slot-role-restricted
  (digits at number slots, letters at edge slots).

The design is fixed and known: **5×5 boxes, N = col·5 + row + 1** (column-major, bottom→top then
left→right; box 13 = centre). Each box prints **N at 4 corners + centre** and **A(left) B(bottom)
C(right) D(top)**.

---

## 1. Part A — Digit clubbing → number tokens  (request #1)
Each **number slot** (4 corners + centre) holds the box number as **1–2 adjacent digit glyphs**. Club
them into one token:

- **Primary (slot-based, robust):** all digit glyphs the fit assigned to the *same* `(box_i, box_j,
  number-slot)` form one token. Order them **along +col (the box's left→right axis)** and concatenate
  → the slot's number string (e.g. "1","3" → `13`).
- **Fallback / tuning (proximity):** where the slot assignment is unavailable, club digit glyphs whose
  centres are within a **distance threshold** (default ≈ 0.6 × box-relative digit pitch, exposed as a
  slider per your request) and roughly collinear along +col.
- **Sanity:** a token is 1 or 2 digits; value must be in **1–25**. Reject/मflag otherwise.

Output: up to **5 number tokens per box** (4 corners + centre), each with a value + a combined
confidence (min/mean of its digits).

---

## 2. Part B — Per-box number by redundancy vote
Each box has up to 5 independent number reads (corners + centre). **Majority-vote** them (weighted by
confidence) → a single **box number** + an **agreement score** (how many of the 5 agree). A box whose
5 copies strongly agree is a **high-confidence anchor**; a box with split/weak copies is **tentative**.

---

## 3. Part C — Global registration  (the key step of request #2)
Fit the mapping **image box node `(box_i, box_j)` → design `(col, row)` → number N**. Because the grid
is rigid, this is just an **orientation + integer offset**:

1. **Orientation from letters.** Within any box, the vector centre→**C** is the **+col** direction and
   centre→**D** is **+row**; **A**/**B** confirm the opposite signs. A robust vote over all detected
   letters fixes which lattice axis (`±U`, `±V`) is +col and which is +row — resolving the 90°/flip
   ambiguity the geometry alone can't. *(Cross-check: the number sequence must increase by 1 along
   +row and by 5 along +col.)*
2. **Offset by RANSAC over anchors.** With axes fixed, each confident box gives
   `(col,row) = ((N-1)//5, (N-1)%5)` at its node `(box_i,box_j)`. Solve the integer shift
   `(col0,row0)` that most anchors agree on (RANSAC / mode vote); outliers (misreads) are rejected.
3. **Gate.** Require a minimum of confident anchors (e.g. ≥ 2 boxes agreeing **and** ≥ 1 letter for
   orientation). Below that, skip auto-complete and just show raw reads (never invent a grid).

Result: **every visible box node now has a known N** and a known upright orientation.

---

## 4. Part D — Auto-complete  (request #2)
With registration locked, every slot's **ideal** glyph is determined: box N ⇒ its 5 number slots are
N's digits, its 4 letter slots are A/B/C/D per the resolved orientation. For each slot compare the
detected read to the ideal and tag it:

| State | Condition | Shown as |
|---|---|---|
| **confirmed** | detected, high-conf, matches ideal | green/normal |
| **corrected** | detected but low-conf **or** mismatched → replaced by ideal | amber |
| **predicted** | no detection at that slot → filled from ideal | blue, hollow |
| **conflict** | detected **high-conf** but disagrees with ideal | red (see Q2) |

So low-confidence characters get "snapped" to the grid's ideal, and gaps are filled — exactly the
"awareness of the high-confidence detections completes the rest" behaviour requested.

---

## 5. Data structures (`glyphtrack/gridmodel.py`, headless)
```python
@dataclass
class NumberToken:      value:int; digits:list; x:float; y:float; slot:str; box:tuple; conf:float
@dataclass
class BoxRead:          box:tuple(i,j); number:int|None; agree:float; letters:dict; conf:float
@dataclass
class GridModel:
    axes: dict          # +col, +row in (U,V) terms; flip/rotation
    offset: tuple       # (col0,row0)
    boxes: dict         # (box_i,box_j) -> {N, col, row}
    slots: list         # per-slot: pos, ideal_char, read_char, conf, state
    registered: bool; n_anchors:int
```
`build_grid_model(reads, fit)` returns a `GridModel`; the GUI draws `slots` by `state`.

---

## 6. GUI (Stage “Grid” / extends the Glyph-grid stage)
- Button **"Solve grid"** after *Read glyphs*.
- Overlay: the **box number** drawn once at each box centre (large), plus per-slot marks coloured by
  state (confirmed/corrected/predicted/conflict). A legend + counts ("18 boxes solved, 92% slots
  confirmed, 3 conflicts").
- Controls: the **digit-club distance** slider (Part A), a **min-anchor** spin (Part C gate), and the
  **conflict policy** (Q2).

---

## 7. Validation
- **Self-consistency on the real frames:** % of boxes whose 5 number copies agree; after registration,
  % of slots matching the model; number of conflicts. Report per frame across 1.5×–4.2×.
- **Synthetic ground truth (STL):** render the design at a known rotation/crop, run end-to-end, assert
  the recovered box numbers + orientation are exactly right and auto-complete fills every slot.
- **Ablation:** show auto-complete recovers boxes that raw per-glyph reads got wrong (the whole point).

---

## 8. Risks / notes
- **Wrong orientation → whole grid mislabelled.** Mitigated by the letter vote + the number-sequence
  cross-check + the anchor gate.
- **Partial FOV.** Only ~3–4 boxes are visible per frame; registration must work from a **sub-block**
  of the 5×5 (it does — offset is solved, not assumed).
- **Over-trusting the model.** If a real high-confidence read disagrees, silently overwriting it hides
  genuine print defects → hence the **conflict** state and Q2.
- **Digit order after deskew.** +col is ~horizontal post-deskew, so left→right ordering is stable; the
  orientation solve makes it exact.

---

## Decisions (locked in)
1. **Digit clubbing — distance threshold only.** Club digit glyphs whose centres are within a tunable
   distance (default ≈ 0.12 × box pitch), ordered along +col. (The fit still assigns each token to a
   box/slot for the vote — that's registration, not clubbing.)
2. **Conflicts — flag, keep the read.** A high-confidence read that disagrees with the grid ideal is
   marked **conflict (red)** and the detected value is kept; never silently overwritten.
3. **Fill missing — yes, mark predicted.** Undetected slots are filled from the grid ideal and drawn
   distinctly (hollow blue).
4. **Display — per-glyph labels**, colour-coded by state (confirmed / corrected / predicted /
   conflict), a label on every slot.
