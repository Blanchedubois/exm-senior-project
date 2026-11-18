# Implementation Plan — Glyph (number/letter) Marker Detection & Orientation

**Context.** The `Stitched Images/` here are an **older, non-ArUco** marker system. This plan adapts the
copied Point-Tracking GUI to detect that system's **numbers and letters**, then orient the image from
the letters. Design to workshop first — see **Open questions** at the end.

---

## 1. What the marker system is (from the images + the reference STL)

The reference `base_design_for_nanoscribe_2026_01_14.stl` (a 750 µm × 750 µm, 2 µm-tall Nanoscribe
print) decodes cleanly to a **5 × 5 grid of 25 boxes**, numbered **1–25**, laid out **bottom-to-top
then left-to-right** (box 1 = bottom-left, box 5 = top-left, box 21 = bottom-right, box 25 =
top-right). Each box carries a **3 × 3 fiducial layout**:

```
 [num]    D    [num]         · num  = the box's own number, printed at all 4 CORNERS + the CENTER
   A    [num]    C           · A/B/C/D = orientation letters at the edge MIDPOINTS:
 [num]    B    [num]           A = left edge, B = bottom edge, C = right edge, D = top edge
```

- **Numbers** are 1–2 digit (10, 20 use a `0`); five copies per box give redundancy and sub-box
  localisation. At every interior junction four *different* box numbers cluster (e.g. 13·18 over
  14·19).
- **Letters A B C D** appear once per edge and **encode absolute orientation** (A points left, etc.).
- **Dots** fill each box on a fine lattice (measured pitch ≈ 41 px; dot ⌀ ≈ 12 px, area ≈ 110 px).
- **Dashed lines** (~10 dashes per box edge) draw the box boundaries.
- **Alphabet is closed:** digits `0-9` + letters `A B C D` = **14 classes**.

Measured on the real `2.0X` frame (2668 × 2651, 16-bit, bright-ish background, median 107): **glyphs
≈ 28 px tall (~16 µm), area ≈ 466 px** — a clean **~4× size separation from dots**, which is what lets
us segment glyphs from the dot field by size. The sample is rotated a modest amount and vignetted.

### Why this is *easier* than generic OCR
The STL is the exact printed design, and we know each glyph's position in it (box 13 sits centre, its
corners read "1""3", etc.). So we can **auto-extract a fully-labelled template/traiing set for all 14
classes with zero manual labelling** — a luxury generic OCR never has.

---

## 2. What we reuse vs. build

| Piece | Status |
|---|---|
| **Stage 1 — optics correction** (vignette flat-field, FFT low-pass, contrast/levels) | **Reuse as-is.** These frames are vignetted, noisy and low-contrast — Stage 1 is exactly the preprocessing glyph detection needs. |
| **Canvas, StageWorkspace, panels, AppState, session IO** | Reuse (same GUI shell/format). |
| **`gridtrack.address` (ArUco decode), `reference.map_grid`** | **Not used** for this marker type — replaced by the glyph pipeline (see Q3 on keeping it selectable). |
| **`measure` (trackpy dots), `filters`** | Reuse later (dots inside the oriented boxes). |
| **New `glyphtrack` module** | Build: segmentation → recognition → orientation. |

The new work lives in a headless `glyphtrack/` package (peer of `gridtrack/`), mirroring the
headless/GUI split we already use, so it is unit-testable without Qt.

---

## 3. Recognition approach — recommendation

**Recommended: OpenCV blob segmentation + a lightweight classifier (HOG + SVM/kNN) trained on
synthetic glyphs generated from the STL.** No new dependencies (OpenCV ships `HOGDescriptor`,
`ml.SVM`, `ml.KNearest`), no OCR engine to install, and it is robust to the blur/rotation/brightness
these prints show.

Why not the alternatives:
- **Tesseract OCR** — built for clean, axis-aligned document text. Here glyphs are isolated, rotated,
  blobby, low-contrast, and sit in a dot field; Tesseract needs heavy per-glyph preprocessing and its
  language model adds nothing for a 14-symbol closed set. Fragile + an extra native dependency.
- **Pure NCC template matching** — simplest (correlate each blob against 14 STL templates), zero
  training, good baseline, but more sensitive to blur/scale than a HOG classifier. Good fallback.
- **Tiny CNN** — most robust, but pulls in PyTorch/TF. Overkill for 14 classes; hold in reserve.

**Training data for free.** Render the STL top-down (done: `stl_topview.png`), crop each glyph at its
known grid position → labelled canonical set. Augment (blur to match PSF, ±rotation for the grid
tilt, brightness/contrast jitter, additive noise, slight scale) to synthesise thousands of realistic
samples per class. Train HOG+SVM on those; validate on hand-checked real glyphs.

---

## 4. Stage 1 (new) — Detect glyphs: position, orientation, class

Input: the Stage-1-corrected image. Steps:

1. **Global rotation estimate (deskew).** Estimate the grid tilt θ from the **dot lattice** (2-D FFT
   peak angle) and/or the **dashed boundary lines** (Hough). This is rotation **mod 90°** — enough to
   deskew glyphs upright for recognition (the 90°/flip ambiguity is resolved by letters in Stage 2).
2. **Glyph segmentation.** CLAHE + adaptive/Otsu threshold → connected components (or MSER). **Keep
   components in the glyph size band (area ≈ 200–4000 px, height ≈ 20–40 px); discard dot-sized and
   dash-sized blobs.** This cleanly isolates candidate glyphs from the dot fill.
3. **Digit grouping.** Two-digit numbers are two adjacent single-glyph blobs; group blobs whose
   centres are within ~1 glyph-width along the (deskewed) x-axis into a number token.
4. **Recognition.** Deskew each glyph crop by θ, normalise size, classify with the HOG+SVM model into
   `0-9 / A-D` with a confidence. Reject low-confidence blobs (dashes/partial prints/noise).
5. **Per-glyph orientation.** Record each glyph's angle (from the deskew θ, optionally refined by
   matching at θ ± small offsets) and its centroid.

**Output (headless):** a `GlyphDetection` table — `x, y, class ('digit'|'letter'), value ('0'..'9' /
'A'..'D'), angle_deg, confidence`, plus grouped `NumberToken`s (`value=14, x, y, member glyphs`).

**GUI:** replaces the Stage-2 "Address" panel. Controls: threshold/segmentation sliders, size band,
confidence cutoff, "show class labels" toggle. Canvas overlay: boxes around glyphs coloured by
letter/number, with the recognised character drawn — so you can eyeball recognition quality.

---

## 5. Stage 2 (new) — Orient the image from the letters + mark them

1. **Collect the letters** A/B/C/D from Stage 1 with their positions.
2. **Resolve absolute orientation.** Each box's four edge letters must read A-left, B-bottom, C-right,
   D-top. Fit the single global rotation (0/90/180/270 + the fine θ) that makes the **A→C axis point
   +x and D→B axis point −y** for the most letters (robust vote across all detected letters; RANSAC to
   ignore misreads). This upgrades the mod-90° deskew to a **fully resolved orientation**.
3. **Rotate the image upright** by that angle (reuse the existing `address.rotate_expand` /
   analytic-corner-transform machinery so overlays stay registered).
4. **Overlay letter markers.** Draw a labelled marker on every A/B/C/D at its oriented position (and,
   optionally, arrows A→C / D→B showing the recovered axes) — the deliverable you asked for.

**Output:** the oriented image + the global orientation (angle, flip) + the letter markers table.

**Later stages (out of scope for now, noted):** Stage 3 — assign box numbers from the number tokens
and build the 5×5 box lattice (absolute map); Stage 4 — trackpy dots within boxes; Stage 5 — filter.

---

## 6. Data structures (headless, in `glyphtrack/types.py`)
```python
@dataclass
class GlyphDetection:
    x: float; y: float; kind: str          # "digit" | "letter"
    value: str                             # "0".."9" | "A".."D"
    angle_deg: float; confidence: float
    bbox: tuple                            # (x,y,w,h) in image px

@dataclass
class NumberToken:
    value: int; x: float; y: float; members: list   # grouped digits -> box number

@dataclass
class OrientationResult:
    angle_deg: float; flip: bool
    oriented_image: "np.ndarray"
    letters: list                          # [GlyphDetection] A/B/C/D with oriented positions
```

---

## 7. Validation
- **Synthetic ground truth from the STL:** render the design at known rotations/blur/noise, run the
  pipeline, assert recovered glyph classes, positions, and orientation match — a closed-loop check
  like the ArUco simulator gave us.
- **Real frames:** hand-label the letters (and a sample of numbers) on the 2.0X frame; report
  recognition precision/recall and orientation error. Sweep across the 1.5×–4.2× series.
- **Headless unit tests** for segmentation size-banding, digit grouping, classifier accuracy on a
  held-out synthetic set, and orientation voting.

---

## 8. Risks / notes
- **Blur & touching glyphs.** At high expansion or defocus, adjacent digits or glyph+dot can merge.
  Mitigations: size-band + shape filters, watershed split for merged blobs, confidence rejection.
- **Bright background / uneven illumination.** The auto contrast/levels + low-pass (Stage 1) handle
  most of it; adaptive (not global) thresholding for segmentation.
- **Rotation ambiguity.** Lattice gives θ mod 90°; **letters are what break the ambiguity** — so a box
  with too few readable letters can't be oriented alone (fall back to the global letter vote).
- **Stitching seams.** MIST stitch borders (visible black steps) can spawn spurious blobs; mask the
  non-imaged border first.
- **Font faithfulness.** Templates come from the STL, so they match the *printed* shape (better than a
  system font). If prints deviate, add a few real crops to the training set.
- **Digit `0` vs letter `O`/`D`, `1` vs `A` legs** — closed alphabet + HOG features + confidence make
  confusions rare; the orientation vote is robust to the odd misread.

---

## Decisions (locked in)
1. **Recognition engine — HOG + SVM** (OpenCV `ml.SVM`), trained on glyphs auto-extracted from the STL
   with realistic augmentation. NCC template match kept as a baseline/fallback. No new dependencies.
2. **Detect scope — letters AND numbers** up front: Stage 1 outputs the full glyph map (A–D + read box
   numbers 1–25).
3. **Repurpose fully** — this copy's stages become the glyph pipeline; the ArUco `gridtrack.address` /
   `reference` decode path is retired here (still lives in the main project).

## Build order (phases)
- **P1 — recognition foundation** (`glyphtrack/`) — ✅ **DONE & VALIDATED.**
  - `stl_glyphs.py`: parse the binary STL → clean top-down render → **auto-mine 305 correctly-labelled
    glyphs** (A/B/C/D = 25 each, '0' = 10, digit counts match box-number frequencies; verified by
    montage). Glyphs are separated from dots/dashes by a **height + fill-ratio** filter (glyphs fill
    ~0.45 of their bbox; boundary dashes are solid bars, dots are tiny).
  - `classifier.py`: HOG + k-NN (OpenCV, no new deps), trained on the STL glyphs with realistic
    augmentation (blur/rotation/scale/shift/noise). **100% on held-out clean, 97.2% on augmented**;
    reads clean real glyphs correctly. Model saved → `reference/glyph_knn.yml` (~12.5k samples).
  - `types.py`: `GlyphDetection`, `NumberToken`, `OrientationResult`, `GlyphDetectParams`.
- **P2 — Stage “Detect glyphs”** — **ARCHITECTURE PIVOT (evidence-based).** A *segment-everything →
  classify* detector was tried and **rejected**: on the real frames there are ~40 boundary **dashes
  per box** vs 9 glyphs, and once blurred, a solid rounded dash is HOG-indistinguishable from a round
  glyph (`0/C/D`). Five mitigations were tested and all failed to separate them per-blob — bbox extent
  (fails on rotated bars), solidity (blurred glyphs are solid too), min-axis/aspect (real dashes are
  fat, aspect≈1.5), a trained **dash reject-class** (thin STL + fat synthetic capsules — still not
  rejected), and less/more augmentation blur. Conclusion: **no per-blob feature separates fat dashes
  from round glyphs.** (Kept montages document this.)

  **Correct approach — structure-first (grid scaffold).** The markers are a *rigid regular grid*, so
  detect the geometry first and read glyphs only where they can be:
  1. **Dot lattice** → grid geometry. Detect the fine dots (small bright blobs, pitch ≈ 41 px on the
     2.0X frame), fit the two lattice basis vectors + rotation (FFT peak / nearest-neighbour vector
     histogram). Robust because thousands of dots vote.
  2. **Box grid** → boundaries. The **dashes are collinear along box edges**; group them into the 5×5
     box lattice (≈ 5×dot-pitch spacing / from the dashed lines). This gives each box's quad.
  3. **Fiducial slots** → recognition. Within each box the glyph positions are the fixed 3×3 slots
     (corners + centre = numbers, edge-mids = letters). **Sample only those slots** and classify with
     the validated model — *no dashes live there*, so the dash problem vanishes and slot ROLE
     (letter vs number) is known a-priori.
  This reorders the plan: the box-grid map (was P4) becomes the **backbone** of detection. It is a
  substantial build (robust lattice detection on rotated/partial/noisy real frames).
- **P3 — Orient**: with slots read, orientation falls out of the letters (A-left…D-top) directly.
- **P4 — dots (trackpy) inside boxes + filters** (as before).

### P2 grid-scaffold — progress (`glyphtrack/lattice.py`)
- **Dot detection** — ✅ 1519 dots on the 2.0X frame; overlay sits exactly on the dots.
- **Dot-lattice basis** — ✅ pitch 40.4 px, angle 48.8° (square lattice). Fixed a bug where the k-NN
  pitch was inflated by 2nd/3rd neighbours; now uses the 1st-NN distance. Overlay mesh locks on.
- **Geometry from the STL** — ✅ dot pitch **8.00 µm**, box **150 µm = 18.75 dots**, all fiducial slot
  offsets measured. STL dots are axis-aligned with boxes (0.2°) ⇒ **box axes = dot axes** (free
  orientation + scale). Ratios are expansion-invariant.
- **Box grid (approx.)** — ✅ pitch 757 px; the overlaid box boundaries follow the dashed lines and
  `detect_dashes` gives an approximate phase.
- **Precise registration** — ✅ `fit_fiducial_lattice` snaps detected glyphs to their nearest
  fiducial slot and re-fits (O, U, V) by least squares; inliers cluster tightly at the 9 slots and the
  boundary dashes fall out as outliers. This locks the box geometry AND assigns each glyph a slot role.
- **GUI** — ✅ the copy's app is repurposed to two stages: **1 Correct optics** and **2 Glyph grid**
  (`stageui/stage_glyphgrid.py` + `canvas.draw_glyph_grid`). "Detect grid" overlays dots + box
  boundaries + fiducial slots; **"Read glyphs (beta)"** classifies each interior glyph — restricted to
  its slot role (letters at edges, digits at corners/centre via `classifier.predict_restricted`) — and
  overlays the character (green=letter, cyan=digit; faint=low-confidence, toggleable).
- **Deskew (Stage 1) — ✅ the accuracy fix.** Root cause of the bad reads: the grid is rotated ~49°,
  far outside the classifier's ±18° tilt range. Added a **deskew** to Stage-1 optics
  (`correct.rotate` + `CorrectionParams.rotate_deg`, slider + **Auto-deskew** button). Auto-deskew
  (`reader.estimate_deskew`) takes the dot-lattice angle and picks the upright quadrant by recognition
  confidence. Effect on the 2.0X frame: mean read confidence **0.36 → 0.78**, confident reads
  **32% → 93%**, glyphs read **34 → 67**, and the labels are now **correct** (1·3 on every "13", B on
  the B). Slot-role restriction (letters↔ABCD, numbers↔digits) stacks on top.
- **Remaining polish:** coverage (some corner/edge glyphs still unlabelled) and further accuracy could
  come from training on real crops (the scaffold auto-collects them); **orientation** (A-left…D-top →
  absolute upright + box numbering) is now unblocked since the letters read reliably.
- **Precise registration** — ⏳ **the open step.** Folding all glyph detections into one box (mod
  box-pitch) shows loose clusters near the 9 fiducial slots but **smeared** — a tiny error in the
  dot→box ratio (18.75) drifts across ~3.5 boxes. Global `refine_basis` (iterated closest-node least
  squares) helped the *dot* lattice but not enough. **Next:** fit the **box** lattice directly to the
  dash/glyph positions (period + phase) rather than deriving it from the dot pitch; then lock phase
  from the clean folded clusters.
- **Then:** sample the 9 slots per box → classify with the validated model (numbers at corners+centre,
  letters at edges) → read box numbers 1–25; **orientation** falls out of the letters (A-left…D-top).

### Phase-1 assets in place (reusable by the grid-scaffold)
`glyphtrack/{stl_glyphs,classifier,types}.py`, `reference/glyph_knn.yml` (7 MB, rebuild via
`classifier.build_glyph_model(stl_path)`), classifier validated at **100%/97.2%** clean/augmented and
correct on clean real glyphs — exactly the tool step 3 needs.

## Open questions
_All resolved above._
