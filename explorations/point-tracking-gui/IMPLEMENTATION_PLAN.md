# Implementation Plan — Point-Tracking GUI for Hydrogel Marker Images

**Goal.** A desktop GUI that loads a TIFF image of the printed marker grid, corrects the
optics, finds and *identifies* every trackable feature — ArUco tags, dots, and boundary
dashes — and outputs each feature's absolute label + subpixel position. The pipeline runs
as **four explicit stages**. This is the *identify-and-track* half of the project; the later
half (measuring expansion/strain from a reference vs. deformed pair) consumes this output and
is scoped in §12.

This document plans the code. It is written to be handed to an implementer and executed stage by stage. It is **not** the implementation.

> **Companion pieces already in the repo**
> - `hydrogel_marker_analysis/toolkit/grid_metadata.json` — the **reference backbone** (every
>   node's ArUco ID + µm coordinate; every box's 4 corner IDs and every dot's local index +
>   µm coordinate). This is the "predefined reference for where the trackers should be".
> - `hydrogel_marker_analysis/docs/ANALYSIS_PLAN.md` — the headless analysis pipeline this GUI
>   operationalises interactively.
> - `expansion_camera_sim/` — produces **labelled synthetic TIFFs** (with *known* vignette,
>   lens distortion, rotation, warp, noise) → our **ground-truth test set** (§11).

---

## 1. Design principle — headless core, thin GUI (the reusability requirement)

The single most important structural rule, driven by the request that *"the scripts can be
used in other GUIs for other image-processing code using the same process"*:

> **All image-processing logic lives in a headless, GUI-free Python package (`gridtrack/`).
> The GUI (`app/`) never computes — it only calls `gridtrack` functions and draws their
> results.**

Concretely:
- `gridtrack/` imports **no** GUI toolkit. Every function is pure: it takes NumPy arrays +
  a small dataclass of parameters and returns NumPy arrays + dataclasses. No global state, no
  file dialogs, no `print`. It can run in a Jupyter notebook, a batch script, a pytest, or a
  different GUI unchanged.
- The GUI holds a single mutable `PipelineState` (§4) and, per stage, calls one or two
  `gridtrack` entry points, then renders overlays from the returned data.
- Every stage is therefore independently runnable **headless**:
  ```python
  from gridtrack import io, correct, address, reference, measure
  img   = io.load_tiff("frame.tif")
  corr  = correct.apply(img, correct.CorrectionParams(vig_strength=0.88, k1=-0.05))
  det   = address.detect_and_orient(corr, aruco_dict="DICT_6X6_1000")
  grid  = reference.map_grid(det, ref=reference.load("grid_metadata.json"))
  feats = measure.detect_features(det.image, grid)   # dots + dashes, tagged
  feats.to_parquet("frame_features.parquet")
  ```
- This same call sequence is what a future "reference-vs-deformed expansion" GUI will reuse
  verbatim (§12).

**Consequence for testing:** because the core is headless, the whole pipeline is unit-testable
against the simulator's ground truth without ever opening a window (§11).

---

## 2. High-level architecture

```
point_tracking_gui/
  IMPLEMENTATION_PLAN.md         # this document
  README.md                     # quick start once built
  requirements.txt
  gridtrack/                    # ==== headless core (NO gui imports) ====
    __init__.py
    types.py         # dataclasses: CorrectionParams, MarkerDetection, GridModel, FeatureTable, PipelineState
    io.py            # load_tiff, to_uint8, save_features, save_session, load_session
    correct.py       # vignette + lens-distortion correction (Stage 1)
    address.py       # aruco detect + global orientation (Stage 2)
    reference.py     # load grid_metadata, map detections -> grid, fit transforms (Stage 3)
    measure.py       # dot + dash detection, subpixel refine, tagging (Stage 4)
    correspond.py    # Hungarian assignment detected<->predicted (shared by 3 & 4)
    overlays.py      # PURE geometry helpers that produce drawable primitives (points, labels,
                     #   lines) as plain arrays/dicts — NOT Qt objects. The GUI renders them.
  app/                          # ==== GUI layer (imports gridtrack + Qt) ====
    __init__.py
    main.py          # entry point; builds the QMainWindow + wizard
    state.py         # holds PipelineState, signals on change
    canvas.py        # image viewport (pyqtgraph): zoom/pan + scatter/label/line overlays
    reference_panel.py# renders the reference grid schematic (Stage 3 visual reference)
    stage1_correct.py# sliders -> correct.apply -> live preview
    stage2_address.py# detect + orient controls, ID list
    stage3_grid.py   # grid mapping controls, labels, red/amber node markers
    stage4_points.py # dot/dash detector controls, red/amber feature markers, tags
    widgets.py       # reusable slider-with-spinbox, collapsible panel, log console
  tests/
    test_correct.py test_address.py test_reference.py test_measure.py
    conftest.py      # loads expansion_camera_sim frames + grid_metadata as fixtures
```

**Stage ↔ module map**

| Stage | GUI page | Core module(s) | Primary output added to `PipelineState` |
|---|---|---|---|
| 1 Correct optics | `stage1_correct` | `correct` | `corrected_image`, `CorrectionParams` |
| 2 Address + orient | `stage2_address` | `address` | `MarkerDetection` (ids, corners, θ), `oriented_image` |
| 3 Map grid | `stage3_grid` | `reference`, `correspond` | `GridModel` (node table, transforms) |
| 4 Track points | `stage4_points` | `measure`, `correspond` | `FeatureTable` (dots + dashes, tagged) |

---

## 3. The reference backbone (`grid_metadata.json`)

`reference.load()` parses the toolkit metadata into a `Reference` dataclass. Verified schema:

```
config: { n_boxes_x, n_boxes_y, box_um, margin_um, marker_um, dot_pitch_um,
          dot_diameter_um, quiet_um, boundary_* , px_per_um, ... }
field_um: [W, H]
aruco_dict: "DICT_6X6_1000"
nodes: [ { node_i, node_j, aruco_id, x_um, y_um }, ... ]          # 25 for the 4x4 demo
boxes: [ { box_i, box_j,
           corner_aruco_ids: { tl, tr, bl, br },
           dot_pitch_um, n_dots,
           dots: [ { i, j, x_um, y_um }, ... ] }, ... ]           # dots already exclude keep-outs
```

Everything downstream is expressed **relative to this reference**:
- `aruco_id → (node_i, node_j, x_um, y_um)` — identity + expected position of every tag.
- `box → its 4 corner IDs` — defines the per-box quad used for local prediction.
- `box.dots` — the **actual** dot list for that box (already omits the corner keep-out
  positions), so predictions iterate this list, never an assumed full N×N lattice.

The GUI must tolerate a metadata file for a *different* grid size (parametrised generator), so
nothing is hard-coded to 4×4/25 nodes.

---

## 4. Data model (`types.py`)

All dataclasses; arrays are NumPy; tables are pandas DataFrames.

```python
@dataclass
class CorrectionParams:
    # vignette (flat-field): V(r) = 1 - s*(r/rmax)^p, centre (cx,cy) in fractional coords
    vig_strength: float = 0.0
    vig_power:    float = 2.0
    vig_cx: float = 0.5
    vig_cy: float = 0.5
    # Brown-Conrady radial lens distortion (about optical centre)
    k1: float = 0.0
    k2: float = 0.0
    dist_cx: float = 0.5
    dist_cy: float = 0.5
    invert: bool = True          # fluorescence (bright-on-dark) -> invert for ArUco
    clahe_clip: float = 2.0

@dataclass
class MarkerDetection:
    image: np.ndarray                     # oriented (upright) image used downstream
    ids:   np.ndarray                     # (N,) int aruco ids
    corners: dict[int, np.ndarray]        # id -> (4,2) subpixel corners, canonical order
    centers: dict[int, np.ndarray]        # id -> (2,) subpixel centre
    theta_deg: float                      # global rotation removed to make tags upright
    dict_name: str

@dataclass
class NodeRecord:
    aruco_id: int; node_i: int; node_j: int
    ref_xy_um: tuple; img_xy_px: tuple     # expected (reference) vs measured (image)
    status: str                            # "detected" | "predicted" | "missing"

@dataclass
class GridModel:
    nodes: list[NodeRecord]
    ref_to_img: np.ndarray                 # global 3x3 homography reference(px) -> image(px)
    box_homographies: dict                 # (box_i,box_j) -> 3x3, from that box's corner tags
    px_per_um: float                       # recovered image scale (for reporting only)

# FeatureTable is a pandas DataFrame with columns:
#   type ("dot"|"dash"), box_i, box_j, local_i, local_j, edge (for dashes),
#   ref_x_um, ref_y_um, img_x_px, img_y_px, mass, size, ecc, sigma, status
#   ("matched"|"unmatched_detection"|"predicted_missing")

@dataclass
class PipelineState:                       # the one object the GUI mutates
    raw_image: np.ndarray | None = None
    correction: CorrectionParams = field(default_factory=CorrectionParams)
    corrected_image: np.ndarray | None = None
    detection: MarkerDetection | None = None
    grid: GridModel | None = None
    features: "pd.DataFrame | None" = None
    reference: "Reference | None" = None
    source_path: str | None = None
```

`io.save_session()/load_session()` serialise `PipelineState` (params as JSON, images as
references to files) so a tuning session is reproducible and re-openable.

---

## 5. GUI shell

**Framework recommendation: PySide6 (Qt) + pyqtgraph.** Rationale: pyqtgraph's `ImageView`
gives fast zoom/pan on large 16-bit images, `ScatterPlotItem`/`TextItem`/`PlotCurveItem` for
red/amber point, label, and grid-line overlays, and `LinearRegionItem`/`InfiniteLine` for ROI
work — all GPU-light and Python-native. Qt gives a clean wizard/stack layout and slider
widgets. *Alternatives:* **napari** (excellent Points/Shapes layers, but its viewer paradigm
fights a rigid 4-stage wizard) or **Tkinter+Matplotlib** (no external Qt dep, but sluggish
pan/zoom and clumsy overlays). Recommend PySide6; keep the choice isolated to `app/` so the
core is unaffected. *(This framework pick is the one open decision worth confirming — see §13.)*

**Window layout**

```
┌───────────────────────────────────────────────────────────────────────────┐
│  Toolbar:  [Open TIFF]  [Save session]  [Export features]     Stage ● ● ● ● │
├─────────────┬─────────────────────────────────────────┬─────────────────────┤
│ Stage nav   │            IMAGE CANVAS (pyqtgraph)      │  CONTROLS (current   │
│ 1 Correct   │  - zoom / pan / pixel readout           │  stage's params)     │
│ 2 Address   │  - overlay layers toggled per stage:    │  e.g. Stage-1        │
│ 3 Grid  ◀   │      · corrected image                  │  sliders; Stage-3    │
│ 4 Points    │      · ArUco boxes + id labels          │  reference schematic │
│             │      · red/amber node & feature points  │  panel               │
│ [Run stage] │      · grid lines / predicted positions │                      │
├─────────────┴─────────────────────────────────────────┴─────────────────────┤
│ Log / status console  (counts decoded, matched, dropped; warnings)          │
└─────────────────────────────────────────────────────────────────────────────┘
```

Rules: a stage's **Run** calls exactly one core entry point and repaints overlays. Advancing a
stage is gated on the previous stage having a result. Overlay colour convention throughout:
**green** = ArUco tag boxes, **amber** = detected/matched feature centre, **red** = predicted /
missing / unmatched (needs attention), **cyan** = reference schematic.

---

## 6. Stage 1 — Correct vignetting & lens distortion (sliders)

**Purpose.** Undo the microscope optics so tags and dots are geometrically true and evenly lit
*before* any detection. These are the exact inverse of the effects `expansion_camera_sim` adds,
which makes the simulator the perfect calibration/validation target.

**Core API (`correct.py`)**
```python
def vignette_mask(shape, p: CorrectionParams) -> np.ndarray            # radial map in [0,1]
def correct_vignette(img, p) -> np.ndarray                            # img / clip(mask, floor)
def correct_distortion(img, p, fnorm=None) -> np.ndarray             # exact radial un-distort
def apply(img, p: CorrectionParams) -> np.ndarray                    # vignette -> distortion -> (optional) normalise
def estimate_vignette(img) -> CorrectionParams                        # auto: fit low-freq background
def estimate_distortion_from_markers(det) -> tuple[float,float]       # auto: minimise tag-row curvature
```
- **Vignette (flat-field):** divide by the radial model `V(r)=1 − s·(r/r_max)^p`. Reuse the
  exact formula from `expansion_camera_sim` (`flat_field`) so a corrected sim frame is flat.
  Provide an **auto** button: fit a smooth low-order polynomial / large-Gaussian background to
  estimate `s,p` from the image itself; sliders then fine-tune.
- **Lens distortion:** exact radial inverse of Brown-Conrady `r·(1+k1 r²+k2 r⁴)` (the
  numerically-inverted LUT already prototyped in `expansion_camera_sim.undistort_lens`), or
  `cv2.undistort` with `K=[[f,0,cx],[0,f,cy],[0,0,1]]`, `dist=[k1,k2,0,0]`. Sliders for `k1,k2`
  (and optional centre).

**GUI (`stage1_correct.py`)**
- Sliders (each a labelled slider+spinbox from `widgets.py`): `vig_strength`, `vig_power`,
  `k1`, `k2`, plus `invert`, `clahe_clip` toggles; **Auto-estimate** buttons.
- **Live preview**: on any slider change, call `correct.apply` on a *downsampled* copy for
  interactivity, full-res on release. Show a toggle **before/after** and a **straight-line
  reference grid overlay** (a faint regular grid) so the user tunes `k1` until the dashes/edges
  read straight, and a **row-intensity plot** so they flatten the vignette.
- Output → `state.corrected_image`, `state.correction`.

**Acceptance:** on a sim frame with known params, the sliders set to those params yield a flat,
straight image; `estimate_*` lands within a few % of the truth.

---

## 7. Stage 2 — Upload, detect ArUco, orient upright

**Purpose.** Find every tag, read its number, and rotate the whole image so all tags are
vertically upright.

**Core API (`address.py`)**
```python
def preprocess_for_aruco(img, p) -> np.ndarray        # invert if fluorescence, CLAHE, to uint8
def detect_markers(img, dict_name) -> tuple[ids, corners]     # cv2.aruco + cornerSubPix
def global_rotation(corners) -> float                 # median tag "up-edge" angle (deg)
def orient_upright(img, corners, ids) -> MarkerDetection      # rotate by -theta, re-detect, refine
def detect_and_orient(img, dict_name, p) -> MarkerDetection   # the one entry point
```
- **Load:** `io.load_tiff` (via `tifffile`) handles 8/16-bit and multipage (choose a page /
  max-projection). `to_uint8` normalises (percentile stretch) for detection while keeping the
  float image for measurement.
- **Preprocess:** the printed pattern images bright-on-dark (fluorescence) → **invert** so tags
  are dark-bordered on light (what ArUco expects); CLAHE to beat residual shading. Mirrors the
  simulator's decode path.
- **Detect:** `cv2.aruco.ArucoDetector(getPredefinedDictionary(DICT_6X6_1000))`. Refine each
  tag's corners with `cv2.cornerSubPix`. Record `ids`, `corners`, `centers`.
- **Orient:** ArUco returns corners in the tag's canonical order (TL,TR,BR,BL), so the vector
  `TR−TL` is each tag's local +x. The grid is rigid, so take the **circular median** of all
  tags' edge angles → global `θ`. Rotate the *corrected* image by `−θ` (expand canvas), then
  **re-detect** on the upright image so all downstream corners are in the upright frame. Store
  `theta_deg`.
- **Note the numbers:** expose the sorted list of detected IDs; flag duplicates / IDs absent
  from the reference.

**GUI (`stage2_address.py`)**
- Button **Detect & orient**; spinner for multipage TIFF page.
- Canvas overlays: green tag boxes (`cv2.aruco.drawDetectedMarkers`-style, drawn by
  `overlays.py` primitives), each tag's **ID label**, and the rotation value shown; a small
  before/after rotation toggle.
- Right panel: scrollable **ID list** ("found 24 / expected 25; missing: 544"), θ readout.
- Output → `state.detection` (upright image + tags), `state.correction` carried forward.

**Robustness:** if very few tags decode, surface it (usually a Stage-1 correction problem);
allow the user to jump back. Handle the fluorescence/greyscale inversion mismatch gracefully
(try both polarities, keep the one that decodes more).

---

## 8. Stage 3 — Map the grid against the reference (neighbours + labels)

**Purpose.** Tie detected tags to the **predefined reference**, show that reference in the GUI,
label each tag's number on the image, drop red/amber points at tag positions, and draw the grid
— including predicting where undetected tags *should* be.

**Core API (`reference.py`, `correspond.py`)**
```python
def load(path) -> Reference                                  # parse grid_metadata.json (§3)
def id_to_node(reference) -> dict[int, NodeRecord]
def fit_global_transform(ref_pts_um, img_pts_px) -> H        # RANSAC similarity/affine/homography
def map_grid(det: MarkerDetection, reference) -> GridModel   # the one entry point
def predict_missing(grid, reference) -> GridModel            # fill undetected nodes via H + neighbours
def box_homography(grid, box) -> np.ndarray                  # 3x3 from that box's 4 corner tags
```
Algorithm:
1. For each detected `id`, look up its reference `(node_i,node_j,x_um,y_um)` → correspondence
   pair `(ref_µm, img_px)`.
2. `fit_global_transform` (RANSAC) → global `ref→img` homography `H`; rejects mis-decodes.
3. **Neighbours:** reference adjacency is implicit in `(node_i,node_j)` (±1 in i or j). Verify
   each detected tag's neighbours are the tags `H` predicts there (consistency check); this
   both validates decoding and orders the tags into the grid.
4. `predict_missing`: any reference node with no detection gets an **image position predicted**
   from `H` (and refined from its detected neighbours) → `status="predicted"`; flagged red.
5. `box_homography` for every box from its 4 corner tags (fallback to `H` if a corner is
   missing) — this is what Stage 4 uses to place dots.

**GUI (`stage3_grid.py`)**
- **Reference panel (right):** `reference_panel.py` renders the reference grid schematic from
  metadata — nodes as cyan dots at their `(node_i,node_j)` with ID labels, box outlines — so the
  user has the *"predefined reference for where the trackers should be"* on screen beside the
  live image for visual comparison.
- **Canvas overlays:** ID + `(i,j)` **label on top of each oriented tag**; **amber** point at
  every detected tag centre, **red** point at every predicted-missing node; **grid lines**
  connecting neighbouring nodes (the mapped lattice). A toggle overlays the transformed
  reference lattice on the image to show fit residuals.
- Right panel: transform type selector (similarity/affine/homography), RANSAC threshold,
  residual RMS readout, counts (detected / predicted / total).
- Output → `state.grid`.

---

## 9. Stage 4 — Detect & tag dots and dashes

**Purpose.** Find every dot and dash, mark its centre red/amber, and give each an **absolute
tag** `(box_i, box_j, local_i, local_j)` by matching to the reference dot list through the
per-box homography.

**Library choice.** Primary dot detector: **`trackpy.locate`** (Crocker–Grier) — purpose-built
for sub-pixel particle localisation on dot fields, returns `x, y, mass, size, ecc`, and its
`ecc` (eccentricity) cleanly separates round **dots** from elongated **dashes**. Fallbacks /
alternatives kept behind one interface: `skimage.feature.blob_log` (LoG blobs) and
`cv2.SimpleBlobDetector`. Sub-pixel refinement: optional 2-D Gaussian fit per feature (gives a
localisation σ for later uncertainty). Dashes: threshold → `skimage.measure.label` /
`regionprops` → filter by area + elongation (`major/minor axis`, `ecc`) → centroid + orientation;
assign each to the nearest box edge.

**Core API (`measure.py`, `correspond.py`)**
```python
def detect_blobs(img, diameter, minmass, backend="trackpy") -> DataFrame   # x,y,mass,size,ecc
def split_dots_dashes(blobs, ecc_thresh, area) -> (dots_df, dashes_df)
def refine_gaussian(img, xy) -> (xy_subpix, sigma)
def predict_box_dots(grid, reference, box) -> DataFrame                     # ref dots -> image px via box H
def tag_features(detected_df, predicted_df) -> DataFrame                    # Hungarian assignment
def detect_features(img, grid, reference, params) -> FeatureTable          # the one entry point
```
Algorithm (per box, looping the boxes from `state.grid`):
1. ROI = the box quad from `box_homography`; run `detect_blobs` inside it.
2. `split_dots_dashes` by eccentricity/size.
3. `predict_box_dots`: map that box's **actual** reference dot list (`box.dots`, which already
   omits corner keep-outs) into the image with the box homography → predicted `(local_i,local_j)`
   positions. **Never** synthesise a full N×N lattice.
4. `tag_features`: Hungarian assignment (`scipy.optimize.linear_sum_assignment`) of detected →
   predicted, gated by a max radius (≈ ½ dot pitch in image px). Matched dots inherit
   `(box_i,box_j,local_i,local_j)`. Unmatched detections and unmatched predictions are recorded
   (never silently dropped) with a `status`.
5. Dashes: tagged by `(box edge, index along edge)` derived from the boundary geometry (dashes
   are not enumerated in metadata, so their reference is generated from the box-edge lines).

**GUI (`stage4_points.py`)**
- Detector controls: backend selector, `diameter`, `minmass`, `ecc` threshold, per-box vs
  whole-image mode; **live re-detect**.
- Canvas overlays: **amber** dot at every matched feature centre with its **tag label**
  (toggle labels on/off — there are hundreds); **red** for unmatched/predicted-missing; dashes
  drawn with their orientation tick.
- Right panel: counts per box (expected / matched / dropped), a table view of the
  `FeatureTable`, and **Export** (`.parquet` + `.csv` + an annotated PNG/TIFF overlay).
- Output → `state.features`.

**Scale sanity:** median matched dot spacing in px ÷ reference `dot_pitch_um` gives the image
`px/µm`; compare to `config.px_per_um` as a self-check and report it.

---

## 10. Libraries

| Concern | Library | Notes |
|---|---|---|
| TIFF IO (8/16-bit, multipage) | `tifffile`, `imageio` | keep float image + a uint8 view |
| ArUco detect/decode, subpixel, undistort | `opencv-contrib-python` | `cv2.aruco`, `cornerSubPix`, `undistort` |
| Dot localisation (primary) | `trackpy` | Crocker–Grier, subpixel, `ecc` for dot/dash split |
| Blob fallback | `scikit-image` | `blob_log`, `regionprops` (dashes) |
| Assignment, transforms, fits | `scipy`, `numpy` | `linear_sum_assignment`, `optimize`, `linalg` |
| Tables / export | `pandas`, `pyarrow` | `FeatureTable` → parquet/csv |
| GUI | `PySide6` + `pyqtgraph` | isolated to `app/` (see §5) |
| Tests | `pytest` | fixtures from `expansion_camera_sim` |

`requirements.txt` pins these; a `.venv` is set up the same way as `expansion_camera_sim`.

---

## 11. Validation strategy — the simulator is the ground truth

Because `expansion_camera_sim` writes frames with **known** vignette/distortion/rotation and a
**known** `grid_metadata.json`, it is a complete, labelled test set. Build tests from day one:

1. **Correction (Stage 1):** feed a sim frame with known `vignette_strength/k1/k2`; assert
   `correct.apply` with those params yields a flat, straight image (row-intensity variance below
   a threshold; a rendered straight line stays straight), and `estimate_*` recovers the params.
2. **Address (Stage 2):** assert all in-FOV tag IDs decode after correction, and recovered `θ`
   matches the sim's per-frame accumulated rotation within ~0.2°.
3. **Grid (Stage 3):** assert every detected tag maps to the correct `(node_i,node_j)`; global
   transform residual RMS is sub-pixel; predicted-missing positions land within a pixel of the
   ground-truth tag centres.
4. **Points (Stage 4):** assert matched-dot image positions agree with the metadata dot
   positions mapped through the true transform to within the localisation σ; dropped-count is
   small and reported; no mis-tags.
5. **Regression harness:** run all seven `λ` frames headless; log decode/match rates. This is
   also the acceptance gate for the whole GUI.

---

## 12. Future — from tracked points to expansion (out of scope now, designed for)

Once two `FeatureTable`s exist (a **reference** frame and a **deformed** frame), expansion
measurement is a thin layer on top, reusing the *same* `gridtrack` calls (§1):
- Correspondence is **free**: features already carry absolute tags `(box_i,box_j,local_i,
  local_j)` and `aruco_id`, so reference↔deformed matching is a table join on the tag — no
  tracking-through-motion needed.
- Displacement `u = xy_deformed − xy_reference`; fit a global similarity to get the expansion
  factor `λ`; residual = warpage; per-neighbourhood deformation gradient `F`, strain `E`, areal
  `J = det F` (exactly `ANALYSIS_PLAN.md` Stages E–H). A future `expansion/` package and a fifth
  GUI stage consume `FeatureTable`s and emit fields + figures. **No change to Stages 1–4.**

---

## 13. Milestones

1. **M0 — Skeleton. ✅ done.** `gridtrack` + `app` packages, GUI shell (toolbar / stage nav /
   canvas / controls / log), `PipelineState`, `io.load_tiff` (tifffile + OpenCV fallback).
2. **M1 — Stage 1. ✅ done.** `correct.py` (vignette flat-field + exact lens un-distortion +
   auto-estimate) + sliders + live preview + straightness grid + before/after + row-intensity
   profile. Validated on the simulator: corrected frame is flat + straight and a plain ArUco
   detector decodes all 25 in-frame tags (`tests/test_correct.py`).
3. **M2 — Stage 2. ✅ done.** `address.py` (preprocess + `cv2.aruco` detect + subpixel corners
   + circular-mean global-rotation + orient-upright with re-detect, polarity fallback) + GUI
   panel (Detect & orient, ID list, θ + residual readout, green tag quads / amber centres /
   ID labels). Validated on the simulator: decodes all in-frame tags, recovers the accumulating
   rotation (±1.5°), and leaves <0.6° residual tilt (`tests/test_address.py`).
4. **M3 — Stage 3. ✅ done.** `reference.py` (load metadata, RANSAC reference→image transform —
   similarity/affine/homography, per-node ID→(i,j) labelling, predict undetected nodes, per-box
   homographies) + GUI panel with the on-screen **reference schematic** + grid overlay (blue
   lattice, amber detected / red predicted nodes, ID (i,j) labels). Validated on the simulator:
   every decoded tag maps to the correct (node_i,node_j), recovered scale ≈ camera px/µm, and
   out-of-FOV nodes are predicted not dropped (`tests/test_reference.py`).
5. **M4 — Stage 4. ✅ done.** `measure.py` (trackpy dot localisation + eccentricity dot/dash
   split, `correspond.py` per-box Hungarian tagging to the reference dot list, skimage dash
   detection tagged by nearest box edge) + GUI panel (detector controls, amber matched / red
   missing / orange dash overlay, feature table view, parquet+csv+annotated-PNG export).
   Validated on the simulator: ~100% of the 4992 dots found, uniquely tagged (box,i,j), and
   localised < 3 px from prediction; out-of-view dots recorded as predicted_missing
   (`tests/test_measure.py`).
6. **M4b — Stage 5 (Filter points). ✅ done.** `filters.py` — quality filters that MARK offending
   matched dots (`status="filtered"` + `filter_reason`, never deleted): (1) **min separation**
   (discard dots closer than a fraction of the expected pitch = reference `dot_pitch_um` × the
   ArUco-recovered px/µm), (2) **blob quality** (mass/size MAD), (3) **prediction residual** vs
   the box homography, (4) **neighbour smoothness** (displacement vs local median), (5) **border
   proximity**. GUI panel with per-filter toggles + thresholds, re-tune from the unfiltered
   baseline, red overlay, export. Validated on the simulator: clean data survives (>97%),
   injected close-duplicates and outliers are caught (`tests/test_filters.py`).
7. **M5 — Polish.** Session save/load, batch (headless) runner over a folder, annotated-image
   export, docs.
7. **M6 (future).** Expansion/strain stage (§12).

---

## 14. Decisions

**Confirmed**
1. **GUI framework — PySide6 + pyqtgraph.** Isolated to `app/`; the core stays framework-free.
2. **Default dot detector — trackpy** (Crocker–Grier, subpixel, `ecc` dot/dash split), behind a
   backend interface with `scikit-image blob_log` as a fallback.

**Still open (confirm before/while building)**
3. **Dash handling** — treat dashes as first-class tracked features, or as coarse anchors only?
   (Dots are the measurement workhorse; dashes add little precision.)
4. **Correction params source** — always manual sliders, or attempt auto-estimate first then
   let the user tweak? (Plan supports both.)
5. **Metadata coupling** — assume `grid_metadata.json` is always available (recommended, it is
   the backbone), or support a "no-reference" discovery mode that infers the lattice from the
   ArUco IDs alone?
```
