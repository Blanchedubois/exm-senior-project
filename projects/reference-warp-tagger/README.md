# Reference-Warp Tagger

A staged desktop tool to correct, detect, filter, and tag the printed marker grid
on an expanding hydrogel, imaged under a microscope. Ported from the
`Old_Trackers_Detection/point_tracking_gui` app.

**Status: full expansion-analysis workspace** — a project sidebar + 8 tabs. Tabs 1–4 are
the per-image pipeline (correct optics → detect & identify → filter → reference-warp tag);
tabs 5–8 are the cross-image analysis (pair → aligned overlay → displacement field →
expansion summary). See the plans in [docs/](docs/) (STAGE1–4 and PHASE5 plans).

## The workspace (multi-image)

**Add images…** builds the project: expected-expansion labels parse from `1.5X…` filenames
(editable); the lowest label is the **Initial** image automatically ("Set as initial"
overrides). The sidebar lists every image with its stage status (✓✓✓✓); the stage tabs
operate on the **selected** image; **Run stages 2–4 / Run all pending** batch-process with
each image's saved tuning — every non-baseline frame is **cross-validated** against the
accepted frames (shared-tag count, coreg auto-rescue from a lower frame, loud rejection),
because a frame's own registration can be confidently wrong (periodic-lattice trap).
**Save/Open project** persists the list, roles, labels and anchors (`project.rwproj.json`).

- **5 · Pair** — tag-join of initial ↔ each expanded image: every shared point with its
  position in both frames; counts; `pairs_<label>x.csv` + wide pairing CSV.
- **6 · Overlay** — rigid alignment about a common box centre (Kabsch rotation +
  translation, **scale untouched**): initial cyan, expanded red, grey = coincidence;
  layer opacities; overlay PNG export.
- **7 · Field** — per-pair displacement `u = aligned − initial` + local linear expansion;
  quiver + heat map (quantity selectable), per expanded image; `field_<label>x.csv`.
- **8 · Summary** — measured vs expected expansion per expanded image, with four views:
  the mean ± σ trend (identity line), overlaid per-dot expansion **histograms** (dashed
  lines at each expected λ), and **box-and-whisker + jittered raw dots** for both the
  per-dot expansion and the **warp residual** (px from each image's best-fit uniform
  expansion — pure warpage, RMS shown in the table). Exports: `expansion_summary.csv`,
  per-dot `distributions.csv`, plot PNG.

## Run

**Easiest — double-click the launcher** (installs everything on first run into a local,
non-synced folder, then opens the app):
- **macOS:** `Launch Reference-Warp Tagger.command`
- **Windows:** `Launch Reference-Warp Tagger.bat`

Both create their Python environment *outside* the iCloud/OneDrive-synced project folder
(macOS `~/Library/Application Support`, Windows `%LOCALAPPDATA%`) because Qt fails to load
from cloud-synced placeholders; only the `.py` source is read from the synced folder.

Or run it manually:

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

### Tab 1 — Correct optics
**Open image…** (defaults to `Stitched Images/`) and tune, with live preview:

- **Vignetting** — flat-field divide by a radial illumination model (strength /
  power, or **Auto-estimate vignette**).
- **Lens distortion** — exact inverse Brown–Conrady radial un-distortion (k1, k2).
- **Low-pass (FFT denoise)** — Fourier low-pass, cut-off in ×Nyquist, shape
  {gaussian, butterworth, ideal}.
- **Rotation (deskew)** — rotate the whole frame upright (per-image).
- **Contrast / threshold (levels)** — black point (auto = bg+k·σ / percentile /
  value), white point, **gamma**; an intensity histogram shows the floor being cut.
  Essential here: high-expansion frames are much dimmer than low-expansion ones.
- **View** — straightness grid overlay; **B** before/after, **G** grid, **R** reset.

**Per-image vs shared.** Each section header has a *shared across series* toggle:
vignette / lens / low-pass persist as you move between frames (microscope optics);
rotation / levels are remembered per file. **Copy to all** writes the current
correction as a `<image>.rwsession.json` sidecar for every image in the folder.
**Save/Load session** round-trips the full tuning (optics + levels + flags), so the
exact processed image can be regenerated — which later stages tag on.

### Tab 2 — Detect & identify
Runs on the Stage-1 corrected frame. Three steps:
- **1 · Detect grid** — finds the fine dots, recovers the lattice pitch/angle, and locks
  the 5×5 box grid to the boundary dashes (grid lines follow the dashes).
- **2 · Read glyphs** — classifies digit/letter glyphs at the fiducial slots (green = letter,
  cyan = digit; recognition on real prints is *beta*).
- **3 · Solve grid** — clubs digits into numbers, votes each box, **registers** the grid
  (orientation + offset from the rule `N = col*5+row+1`) and **auto-completes every box
  number**, coloured by state (confirmed / corrected / predicted / conflict).

If auto-register fails (dim, high-expansion frames), use **Identify a box**: click a box and
type its number — one or two anchors lock the whole grid. **Auto-deskew** writes a rotation
back to Stage 1. **Export marked image…** (toolbar) saves the marked PNG + a `.stage2.json`
with the reads and registration.

### Tab 3 — Filter
Consumes the Stage-2 detection (no re-detection) and drops false positives, live as you move
the sliders:
- **Dots** — too close to a neighbour · sitting on a number/letter · off their ideal lattice node.
- **Dashes** — too far from a grid line · at a grid intersection · too close to each other.

Kept points are green ● / pink ▲; dropped points are coloured by reason (toggle **Show
dropped**). The box grid, box numbers and glyph labels from Stage 2 stay overlaid, so you see
the **clean filtered marked image**. **Export filtered CSVs…** writes `dots_filtered.csv` +
`dashes_filtered.csv`; the toolbar **Export marked image…** saves the filtered PNG. The kept
dots/dashes are published for Stage 4 to tag.

### Tab 4 — Tag (reference-warp)
The tag map is built once from the Nanoscribe STL (`reference/reference_tags.json`) — every
printed feature has a unique grid-relative tag (`dot|B13|4_7`, `dash|V2|23`,
`num|B13|center|0`, …). **Tag current frame** fits a design→image warp (affine seed → ICP
homography → **thin-plate spline**) against the Stage-3 filtered dots and gives every
filtered point the nearest same-category tag — glyphs are tagged **by position**, so
unreadable digits still tag correctly. **Hover any marker to read its tag**; filter by
kind/box; overlay the TPS-warped reference grid (the definitive grid following the dashes)
and box numbers. *Frames must be deskewed first (Stage 2 Auto-deskew) — the panel warns if
tilted.*

**Series**: **Process series** batch-tags every labelled frame in the folder (factors parsed
from filenames like `1.5X…`), ascending; the lowest frame is the baseline, and mis-registered
high-expansion frames are rescued by geometric auto-alignment to a lower accepted frame
(`auto<-1.5x`). Frames that fail acceptance are rejected loudly with the reason. The
**Strain** table/plot shows measured vs expected expansion from tag-paired dots. Exports:
per-frame tagged CSVs and the wide **pairing CSV** (`tag, 1.5x_x/_y/_present, …`).

Validated on the six real frames: 6/6 accepted (3×–4.2× via auto-rescue), warp residual
~1.3 px, strain within a few % of expected across 1.5×–4.2×. Known data limits: letters and
corner intersection dots print faint and rarely match — their tags exist but stay unmatched.

## Layout

```
run.py                 launch the GUI
rwtag/                 headless core (no Qt): types, correct (optics+levels), io
rwtag/glyph/           Stage-2/3 core: lattice, reader, classifier, gridmodel,
                       detect, dotfilter, stl_glyphs
rwtag/refwarp/         Stage-4 core: reftags, warp (ICP+TPS), tagmatch, coreg,
                       strain, series, tagframe, io_csv
rwtag/project.py       multi-image project model + validated batch runner
rwtag/pairing.py       cross-image analysis: pair join, rigid Kabsch alignment,
                       overlay composite, displacement field, expansion summary
gui/                   PySide6 GUI: app (sidebar + 8 tabs), state, canvas, widgets,
                       correct/detect/filter/tag panels (stages 1-4),
                       project/pair/overlay/field/summary panels (workspace)
reference/             glyph_knn.yml (classifier) + reference_tags.json (STL tag map)
tests/                 headless tests (no display)
docs/                  STAGE1_/STAGE2_IMPLEMENTATION_PLAN.md
Stitched Images/       real expansion frames (1.5×–4.2×)
Markers CAD/           reference STL
```

## Tests

```bash
python tests/test_correct.py     # optics round-trips + levels/rotation (no Qt)
python tests/test_io.py          # session round-trip + OME-TIFF load
python tests/test_glyph.py       # geometry, numbering-rule registration, clubbing, real frame
python tests/test_dotfilter.py   # dot/dash false-positive filters, real frame
python tests/test_refwarp.py     # warp round-trip, tag recovery, strain, real frame
python tests/test_project.py     # project model, roles, validated batch runner
python tests/test_pairing.py     # pair join, Kabsch/rigid align, field, summary
```
