# Reference-Warp Tagger — Stage 2 Implementation Plan
### Detect & identify: dots, dashes, numbers, letters → box grid, numbered & oriented

**Project:** `reference-warp-tagger/` · **Scope:** Stage 2 only (a second tab)
**Ported from:** `Old_Trackers_Detection/point_tracking_gui/` — the `glyphtrack` package
**Consumes:** the Stage-1 corrected image · **Feeds:** Stage 3 (filter) → Stage 4 (tag)
**Written:** 2026-07-17 · handed to an implementer

> **Decisions locked (2026-07-17):** (1) numbering = **read-and-register / predict** — the
> glyphtrack approach, not warp-driven, for Stage 2; (2) **reuse** the existing beta
> `glyph_knn.yml` with the **manual-anchor** fallback for high-expansion frames — no retrain
> now; (3) the printed design is **unchanged** — 5×5 boxes, 150 µm, numbers 1–25 via
> `N=col*5+row+1`, letters A–D at the edge slots — so the ported `lattice` constants hold;
> (4) Stage 2 runs on the **Stage-1 corrected image**.

---

## 0. Where this fits

| Stage | Goal | Status |
|---|---|---|
| 1 | Correct optics (rotation, gamma, vignette, lens, denoise, levels). | **done** |
| **2** | **Detect & identify every feature (dots, dashes, numbers, letters); fit the box grid to the dashes; infer each box's number & the grid orientation by *predicting* numbers; render the marked image.** | **this document** |
| 3 | Filter false-positive dots/dashes; re-render the filtered marked image. | planned |
| 4 | Reference-warp tag every point on the **processed + filtered** image/grid. | planned |

Stage 2 is a **second tab** in the GUI. It runs on the Stage-1 **corrected image**
(`PipelineState.corrected_image`) — so all identification happens on the processed frame,
exactly as Stage 4 will require. It produces: the fine-dot lattice, the boundary dashes on
the grid, the glyph reads (digits + letters), the fitted 5×5 box grid, and the **registered
box numbering + orientation** — drawn as one marked image and stored in state for Stages 3–4.

> The app is the **Reference-Warp** Tagger: warping the STL reference onto the frame is the
> **Stage-4 tagging** mechanism. Stage 2's job is the *self-contained* detection + numbering
> that (a) gives the user a fully marked, numbered grid to verify, and (b) supplies the
> anchors/geometry the Stage-4 warp needs. The two are complementary, not competing — see
> the decision box in §3.

---

## 1. What to port (the `glyphtrack` package)

The old app already solved Stage 2 as its "glyph grid" stage. Port these **headless** modules
verbatim into a new `rwtag/glyph/` (or keep the `glyphtrack` name) sub-package — they are
numpy/OpenCV/scipy only, no Qt:

| Module (old) | Role | Port |
|---|---|---|
| `glyphtrack/lattice.py` | dot & dash detection; lattice basis; **dash-locked box grid**; fiducial-lattice fit; box/slot geometry; design constants | **verbatim** |
| `glyphtrack/reader.py` | glyph-blob detection; classify at slots; `read_glyphs` (fit) + `read_slots` (OCR at slots); `estimate_deskew` | **verbatim** |
| `glyphtrack/classifier.py` | HOG + `cv2.ml.KNearest` glyph classifier (`predict_batch`, `predict_restricted`) | **verbatim** |
| `glyphtrack/gridmodel.py` | digit **clubbing → per-box vote → register (orientation+offset) → auto-complete** | **verbatim** |
| `glyphtrack/types.py` | `CLASSES`, glyph dataclasses | **verbatim** |
| `reference/glyph_knn.yml` | the trained k-NN model (7.3 MB) | **copy** into `reference-warp-tagger/reference/` |

Do **not** port yet (later stages / retraining only): `glyphtrack/stl_glyphs.py` +
`classifier.build_glyph_model` (STL mining — needed only to *retrain*), `glyphtrack/dotfilter.py`
and `glyphtrack/results.py` (Stage 3/results), and the whole `refwarp/` package (Stage 4).

**New dependency for Stage 2:** `scikit-image` (the classifier's HOG). Already listed under
"Stages 2–4 (planned)" in `requirements.txt`; move it to the active set.

**Design constants (from the STL — expansion-invariant ratios), in `lattice.py`:**
`DOT_UM = 8.0`, `BOX_UM = 150.0`, so `BOX_PER_DOT = 18.75`; a **5×5 grid of boxes** numbered
`N = col*5 + row + 1` (1…25); five **number slots** (four corners + centre) and four **letter
slots** `A/B/C/D` at the box edges; `FIDUCIALS` gives each slot's local-µm position. These
encode the actual printed design, **confirmed unchanged for this dataset** — port as-is.

---

## 2. The pipeline (headless, exactly as `refwarp.detect.detect` orchestrates it)

Input: the Stage-1 corrected image → `u8 = io.to_uint8(corrected)`.

1. **Dots** — `lattice.detect_dots(u8)`: white top-hat → Otsu → connected components kept by
   size + roundness. Returns the fine-fill dot centroids (the thousands of dots that vote the
   geometry robustly). *These are the measurement tier.*
2. **Lattice basis** — `estimate_basis(dots)` (NN-vector histogram → pitch + angle) then
   `refine_basis(dots, basis)` (iterated closest-node least squares → global pitch/angle,
   removing the smear that would misplace far boxes).
3. **Dashes** — `detect_dashes(u8)`: mid-size solid bars on the box boundaries.
4. **Box grid** — `fit_box_grid(basis, dashes)`: box axes = dot axes; `box_pitch =
   pitch·18.75`; the **box-corner phase along each axis is locked from the dash centres**
   (`_phase_mode`). → *this is the grid that "follows the lines of the dashes."*
   `dashes_on_grid(dashes, grid)` keeps only dashes lying on a boundary line (drops strays).
5. **Glyph blobs** — `reader.detect_glyph_blobs(u8)`: CLAHE + top-hat + Otsu, kept by
   glyph size/height → candidate digit/letter crops + positions.
6. **Fiducial lattice fit** — `reader.read_glyphs(u8, clf, grid)`: classify blobs
   (unrestricted pass) to get confident glyphs, `fit_fiducial_lattice` snaps them to their
   nearest slot and least-squares refines `(O, U, V)` — the precise box lattice used for all
   box-coordinate math.
7. **Slot reads** — `reader.read_slots(u8, clf, fit)`: OCR **only** blobs sitting at a
   fiducial slot, restricted to that slot's role (digits at number slots, `ABCD` at letter
   slots). Returns per-glyph `{x,y,char,conf,kind,box,slot}`.
8. **Grid model** — `gridmodel.build_grid_model(reads, fit, dots=dots, manual=…)`:
   - **club_digits** — join adjacent digits into a number token *unless a fill-dot lies
     between them* (so "13" clubs, but two different boxes' numbers never merge);
   - **vote_boxes** — each box's number from its (redundant, 5-copy) tokens, conf-weighted;
   - **register** — pick the **orientation (1 of 8) + integer offset** that best satisfies the
     **numbering rule** `N = col*5+row+1` across confident boxes, using letters (and any
     manual anchors) as extra evidence. This is the "**predict the numbering & orientation**"
     step — it needs only a couple of solid boxes, then the *rule* fixes the rest;
   - **auto-complete** — for every in-view box, emit each slot's label with a **state**:
     `confirmed` / `corrected` / `predicted` (missing → filled from the rule) / `conflict`.
   Returns `labels` (x,y,text,state,kind), `reg`, `node_num` (box node → N), `summary`.

**Deskew wiring (closes a Stage-1 stub).** `reader.estimate_deskew(u8, clf)` returns the
rotation that makes glyphs upright (dot lattice gives tilt mod 90°; the four quadrants are
scored by glyph-recognition confidence). Stage 1 shipped a disabled **Auto-deskew** button —
now enable it: it calls this and writes `CorrectionParams.rotate_deg`. Stage 2 can also
auto-deskew on first run if `rotate_deg == 0`, mirroring `refwarp.detect`.

---

## 3. Numbering source — the one real design decision

Two ways to establish box numbers/orientation; they share steps 1–7 above:

- **(A) Read-and-register (glyphtrack, this plan's baseline).** Read what glyphs you can,
  then `register` uses the numbering rule + a few anchors to **predict** every box number.
  Matches the user's wording ("predicting the numbers as outlined in the app previously") and
  degrades gracefully to **manual anchors** when the classifier can't read (high expansion).
- **(B) Warp-reference-driven.** Warp the STL `reference_tags.json` onto the detected dots and
  read box numbers off the warped reference by position (the `refwarp` mechanism).

> **Decided: (A).** Stage 2's numbering + marked image use read-and-register, because it is
> self-contained and is what "predict the numbers" means. **(B)** is the Stage-4 tagging
> engine and reuses (A)'s dots + registration (`reg`) as its anchor — the seam is kept clean
> so (B) drops in at Stage 4 without touching the Stage-2 panel.

**Known limitation (carried from the old app + your notes):** the classifier is trained on
STL-synthetic glyphs, so OCR on real prints is *beta*, and at **≥3× expansion digits often
can't be read at all** → auto-register can fail. The mitigation is built in and must be
ported: **manual box anchors** (click a box, type its number; click a letter) feed `register`
with high weight, and one or two anchors lock the whole grid via the numbering rule.

---

## 4. GUI — the second tab

### 4.1 Workspace refactor (small)
Stage 1 today is `MainWindow` → `[canvas | CorrectPanel]`. Introduce a **tabbed workspace**
so Stage 2 is a second tab sharing the one `AppState`:

```
MainWindow
  toolbar: Open · Save session · Load session · Copy to all · [Export marked image…]
  QTabWidget
    Tab "1 · Correct"   -> StagePage(canvas1, CorrectPanel)      # existing
    Tab "2 · Detect"    -> StagePage(canvas2, DetectPanel)       # new
  status bar (cursor readout) · Log dock
```

- Each tab owns its **own canvas** (Stage 1 is a live editor; Stage 2 an analysis view with
  different overlays) — simplest, no shared-view coupling. Both read/write the shared
  `AppState`. (The old app shared one canvas via `StageWorkspace`; separate canvases are
  cleaner here and avoid overlay bleed.)
- Switching to Tab 2 pulls `state.corrected_image`. If Stage 1 hasn't produced one, show
  "Run Stage 1 first" and offer to use the raw image.

### 4.2 `DetectPanel` (modelled on `stageui/stage_glyphgrid.py`)
Controls, top→bottom:

- **Detection params** — dot area min/max, dot top-hat px (spin boxes; defaults 30 / 220 / 15).
- Buttons (progressive disclosure, mirroring the old panel's proven flow):
  1. **Detect grid** — steps 1–4 → overlay dots + box grid + on-grid dashes; report dot
     count, pitch, angle, box pitch, dashes-on-grid.
  2. **Read glyphs** — steps 5–7 → overlay classified digits/letters (green=letter,
     cyan=digit; faint = low-confidence, gated by a "show weak" checkbox).
  3. **Solve grid (auto-complete)** — step 8 → per-slot labels coloured by state and **box
     numbers at box centres**; summary line (`registered: k anchors · n boxes solved · …`).
  - **Auto-deskew** — runs `estimate_deskew`, writes it back to Stage-1 rotation.
- **Identify a box (if solve fails)** — the manual-anchor group: **Set box number** (click a
  box → type 1–25), **Set letter** (click a letter → pick A–D), **Clear anchors**; re-solves
  on each anchor. This is the high-expansion fallback.
- View toggles: dots / dashes / fiducial slots / weak reads / box numbers.
- Summary label + everything also mirrored to the Log dock.

### 4.3 Canvas overlay (add to `gui/canvas.py`)
The generic helpers (`add_points/add_polylines/add_labels/clear_overlays`) are already ported.
Add one composite method, `draw_glyph_grid(dots, box_quads, num_pts, letter_pts, dash_pts,
labels_by_state, box_numbers)` — a straight port of the old canvas `draw_glyph_grid` plus a
`box_numbers` pass (text N at each box centre). Colour map (port from old panel):
`confirmed`=green, `corrected`=amber, `predicted`=blue, `conflict`=red, `raw`=grey.

---

## 5. State & data contracts

Add a headless result dataclass and hang it on the existing forward slots (no reshaping):

```python
# rwtag/glyph/types.py  (or extend rwtag/types.py)
@dataclass
class DetectResult:
    u8: np.ndarray                 # the 8-bit image detection ran on (Stage-1 corrected)
    dots:   np.ndarray             # (N,2) fine-dot centroids
    basis:  dict                   # v1,v2,pitch,angle_deg,origin  (refined lattice)
    dashes: np.ndarray             # (M,2) dash centres kept ON the grid
    glyphs: np.ndarray             # (K,2) all glyph-blob positions
    grid:   dict                   # dash-locked box grid: u,v,box_pitch,phase_u,phase_v,*_vec
    fit:    dict                   # fiducial lattice: O,U,V,box_pitch (box-coordinate frame)
    reads:  list                   # per-glyph slot reads {x,y,char,conf,kind,box,slot}
    model:  dict                   # build_grid_model output: labels, reg, node_num, summary
    deskew: float
```

- Store it in `PipelineState.detection`; keep `PipelineState.grid = model` (or a thin view)
  so Stage 3/4 read numbering without knowing detection internals.
- `AppState` gains `glyph_manual = {"numbers": [(node,N)], "letters": [{box,x,y,char}]}`
  (ported) and a `detectionChanged` signal.
- **Session JSON (extend):** add a `stage2` section — detection params + the manual anchors +
  the solved `reg` (orientation, offset) — so a verified numbering reloads without re-solving.
  Bump `SESSION_VERSION` to 2; the loader already ignores unknown sections (forward-compatible).

---

## 6. The marked image (the Stage-2 deliverable)

"Produces a final image of the dots/dashes/numbers/letters marked, the grid following the
dashes, the boxes numbered accordingly." Concretely, after **Solve**:

- **dots** — small amber points (the measurement lattice);
- **dashes** — pink triangles, only those **on the grid** (`dashes_on_grid`);
- **grid** — cyan box-boundary lines from the **dash-locked** `grid` (so lines run through the
  dashes); fiducial-slot markers optional;
- **numbers & letters** — the `build_grid_model` labels, coloured by state, with **box numbers
  at box centres**;
- **Export marked image…** (toolbar) — render the overlay onto `u8` and write a PNG (+ a
  sidecar `*.stage2.json` with `reads`, `model`, `reg` for the record). This PNG is the
  "final marked image" the user asked for; Stage 3 will produce the filtered version.

---

## 7. Forward hooks for Stages 3–4

- **Stage 3 (filter)** consumes `detection.dots` / `detection.dashes` + `grid`/`fit`; it flags
  false-positive dots (proximity/quality/residual/border — the old `FilterParams` +
  `glyphtrack.dotfilter`) and off-line dashes (already partly done by `dashes_on_grid`).
  Stage 2 must therefore keep **all** detected dots/dashes (not just on-grid) available, with
  the on-grid subset marked — Stage 3 does the culling.
- **Stage 4 (tag)** consumes the **filtered** points + `fit`/`reg`: warp the STL
  `reference_tags.json` onto the surviving dots and tag each point by proximity (the `refwarp`
  package). Registration (`reg`: orientation + offset + box numbers) from Stage 2 is the
  anchor that makes the warp's box numbering unambiguous — the fix for the periodic-lattice
  ambiguity noted in your memory.
- Keep detection **per-image** (each expansion frame is tilted/shifted independently) — never
  assume a shared global grid across frames.

---

## 8. Testing

Headless (no Qt), reusing the real frames + a synthetic case:

- **Geometry on a clean synthetic grid** — render a small dot lattice + dashes at a known
  pitch/angle; assert `estimate_basis`/`refine_basis` recover them, and `fit_box_grid` locks
  the dash phase.
- **Registration rule** — unit-test `gridmodel.register` / `box_number`: given a handful of
  `boxes` votes consistent with an orientation+offset, the solved `node_num` obeys
  `N = col*5+row+1`; a single manual anchor + letters locks it; conflicting votes flag.
- **club_digits** — "1","3" adjacent with no dot between → token 13; with a dot between →
  two tokens.
- **Classifier smoke** — `GlyphClassifier.load(reference/glyph_knn.yml)` then
  `predict_restricted(crop, DIGITS)` returns a label+conf (don't assert accuracy — it's beta).
- **Real-frame integration** — run steps 1–8 on `Stitched Images/2.0X…` (a frame where OCR is
  more likely to work); assert dots > 1000, a box grid is fit, and *either* auto-register
  succeeds *or* one scripted manual anchor makes it register. Log, don't hard-fail, on the
  dim 3.5×/4.2× frames (expected classifier limitation).

---

## 9. Milestones

1. **M1 — Port `glyphtrack` headless** into `rwtag/glyph/`; copy `glyph_knn.yml`; geometry +
   registration + club unit tests green. No GUI.
2. **M2 — Tabbed workspace**; `DetectPanel` with **Detect grid** on the Stage-1 corrected
   image → dots + dash-locked box grid overlay.
3. **M3 — Read + Solve**: glyph reads, `build_grid_model`, per-state labels + **box numbers**;
   summary + log.
4. **M4 — Manual anchors** (click-to-number / click-to-letter) + re-solve; **Auto-deskew**
   wired back to Stage 1.
5. **M5 — Marked-image export** (PNG + sidecar JSON); `stage2` session section; store
   `DetectResult` for Stages 3–4.

---

## 10. Resolved decisions (confirmed 2026-07-17)

1. **Numbering source** — **(A) read-and-register (predict numbers)**. Warp-reference (B) is
   deferred to Stage-4 tagging.
2. **Classifier** — **reuse** the existing beta `glyph_knn.yml`; rely on the **manual-anchor**
   fallback where OCR fails (≥3× expansion). No retrain in Stage 2. *(A future retrain on real
   labelled crops remains the accuracy lever if manual anchoring becomes tedious.)*
3. **Design constants** — **unchanged**: 5×5 boxes, 150 µm, dot pitch 8 µm, numbers 1–25 via
   `N=col*5+row+1`, letters A–D at the edge slots. Ported `lattice` constants hold.
4. **Stage-2 input** — the **Stage-1 corrected image**.

## 11. Still to confirm before/while building (non-blocking)
- Which expansion frames auto-register vs need manual anchors (empirical — informs how much to
  invest in the manual-anchor UX vs a later retrain).
- Whether the marked-image PNG + `*.stage2.json` sidecar is the desired hand-off format for
  Stage 3, or you want the result kept only in the session file.
