# Reference-Warp Tagger — Stage 1 Implementation Plan
### The image-editing / optics-correction GUI

**Project:** `reference-warp-tagger/` · **Scope of this document:** Stage 1 only
**Ported from:** `Old_Trackers_Detection/point_tracking_gui/` (the "Point-Tracking GUI")
**Written:** 2026-07-17 · handed to an implementer

---

## 0. Purpose & where this fits

The Reference-Warp Tagger will grow into a four-stage tool:

| Stage | Goal | Status |
|---|---|---|
| **1** | **Load an expansion image and correct it — rotation, gamma, vignette, lens, denoise, levels — with live preview, so the frame is clean and upright for analysis.** | **this document** |
| 2 | Detect + identify dots, dashes, numbers, letters; infer box numbering & orientation; render the marked grid. | planned (later doc) |
| 3 | Filter false-positive dots/dashes; render the filtered marked grid. | planned (later doc) |
| 4 | Tag every point with the box/local addressing scheme — **on the processed image and the filtered points/grid**. | planned (later doc) |

Stage 1 is the foundation: **every later stage consumes the *corrected* image and the
correction parameters produced here.** The instruction "tagging should occur to the
*processed* image and filtered points/grid" (Stage 4) means the corrected image and the
geometric transform (rotation especially) must be captured as first-class, serialisable
state that flows forward. This document specifies that state and the GUI that produces it.

The immediate ask: **first perfect the image-editing GUI so it is usable for analysis.**
This plan ports the proven Stage-1 mechanics from the old app, cleans up the panel, and adds
the enhancements needed to work on the real stitched expansion frames.

---

## 1. The real data (drives every decision below)

The working set is `reference-warp-tagger/Stitched Images/*.ome.tif`:

| Frame | Shape (px) | dtype | min | max |
|---|---|---|---|---|
| 1.5× | 2676 × 2678 | uint16 | 0 | 1209 |
| 2.0× | 2668 × 2651 | uint16 | 0 | 1258 |
| 2.5× | 2713 × 2712 | uint16 | 0 | 893 |
| 3.0× | 2703 × 2714 | uint16 | 0 | 664 |
| 3.5× | 2653 × 2698 | uint16 | 0 | 516 |
| 4.2× | 2659 × 2716 | uint16 | 0 | 379 |

Four facts that shape the design:

1. **~7.3 megapixels, single-page OME-TIFF, ~18 MB each.** Recompute of the full
   vignette/lens/FFT chain on a 7 MP `float32` on every slider tick will not stay
   interactive at the old app's 40 ms debounce. → **preview downsampling** (§7.1).
2. **The 16-bit range is barely used** (max ≈ 1200 down to 379, not 65535). The levels
   tooling must key off the *actual* image max, not an assumed full scale — the ported
   `correct._value_scale()` already does this (`255` for ≤255 data, else the image max).
3. **Higher-expansion frames are dimmer and lower-contrast** (max 1209 → 379 as material
   spreads and photons-per-feature drop). This is exactly why **per-image levels/gamma**
   (not one global contrast) is mandatory, and why the histogram/floor tooling earns its
   keep on the hard frames.
4. **Each frame is independently tilted/shifted** (established: expansion frames do not
   share a global grid). → **rotation must be a per-image parameter**, tuned per frame.

---

## 2. Decisions taken (from review)

- **Single image at a time.** The workspace has one active image: *Open Image → tune →
  save*. No multi-image session object in Stage 1. (Stages 2–4 will add series-level state;
  Stage 1 stays a focused editor.)
- **Port the proven headless core verbatim.** Copy `gridtrack/correct.py` and the two
  Stage-1 dataclasses from `gridtrack/types.py` into the new package unchanged. The optics
  math is tested (`tests/test_correct.py`) and is the numeric inverse of the camera sim — do
  not re-derive it. Rebuild only the GUI panel/canvas on top.
- **Enhancement in scope: per-image vs shared params + copy-to-all.** Each control is tagged
  *shared* (persists as you open the next image — e.g. microscope vignette/lens) or
  *per-image* (bound to the source path — e.g. rotation, levels). A **Copy to all** action
  propagates the current correction to every image in the source folder via sidecar sessions.
  (Crop/ROI, flip/transpose, and CLAHE were considered and **deferred** — not in Stage 1.)

---

## 3. Feature inventory — port these exactly

Every Stage-1 control from the old app, its math home, and its behaviour. **Port all of
them**; the UI is reorganised (§6) but the math and semantics are unchanged.

| Feature | Controls | Math (ported fn in `correct.py`) | Shared / per-image |
|---|---|---|---|
| **Vignetting (flat-field)** | strength 0–1, power 0.5–5, **Auto-estimate** | `correct_vignette` / `vignette_mask` / `estimate_vignette` | **shared** |
| **Lens distortion** | k1 −0.30–0.30, k2 −0.10–0.10 (Brown-Conrady radial) | `correct_distortion` / `_inverse_scale_map` | **shared** |
| **Low-pass (FFT denoise)** | enable, cut-off (×Nyquist), shape {gaussian, butterworth, ideal}, order (butterworth only) | `lowpass` / `_lowpass_mask` | **shared** |
| **Rotation (deskew)** | rotation −180–180° | `rotate` | **per-image** |
| **Contrast / threshold (levels)** | enable; black-point mode {auto = bg+k·σ, percentile, value}; k / pct / value; white point; **gamma** | `levels` / `resolve_black_norm` / `resolve_black_level` | **per-image** |
| **Intensity histogram (pre-levels)** | read-only; black + white lines drawn on it | driven by `resolve_black_level`, `_value_scale` | — |
| **Mid-row brightness profile** | read-only flatness check | panel-local (`_update_profile`) | — |
| **Straightness grid overlay** | on/off | canvas | — |
| **Before/after toggle** | show raw vs corrected | panel | — |
| **Reset** | reset optics section | panel | — |

**Pipeline order (fixed — see `correct.apply`):** vignette (photometric) → lens (geometric)
→ FFT low-pass (denoise) → rotation (deskew). Then **levels/gamma** is applied *per-image*
on the result (old app: `apply()` then `levels()`). Preserve this exact order; later stages
assume it.

### 3.1 Deliberately dropped in the port
- **Auto-deskew from the glyph classifier** (`_auto_deskew`, needs `reference/glyph_knn.yml`).
  It depends on the not-yet-ported glyph reader. **Keep the manual rotation slider**; add a
  stub **Auto-deskew** button that is disabled with tooltip "available after Stage 2". Re-wire
  it when the glyph classifier lands.
- `invert` / `clahe_clip` fields on `CorrectionParams` — carried in the dataclass (they
  travel with the correction) but **not surfaced** as Stage-1 controls yet (CLAHE deferred;
  invert is a Stage-2 detection hint).

---

## 4. Package layout (new)

Mirror the old separation of **headless core** (`gridtrack`-style, no Qt) from **GUI**
(`stageui`-style). This is what let the old core be unit-tested and embedded; keep it.

```
reference-warp-tagger/
  run.py                      # launch: python run.py
  requirements.txt
  README.md
  docs/
    STAGE1_IMPLEMENTATION_PLAN.md   # this file
  rwtag/                      # headless core (NO Qt, NO GUI imports)
    __init__.py
    types.py                  # PORTED: CorrectionParams, LevelsParams  (+ forward slots)
    correct.py                # PORTED VERBATIM: vignette/lens/lowpass/rotate/levels/estimate
    io.py                     # PORTED + extended: load_tiff, to_uint8, save/load session
  gui/                        # PySide6 GUI (depends on rwtag, never the reverse)
    __init__.py
    app.py                    # MainWindow: toolbar (Open / Save / Load / Copy-to-all) + log
    state.py                  # AppState(QObject): one active image + params + signals
    canvas.py                 # PORTED + trimmed: pyqtgraph viewport, straightness grid
    widgets.py                # PORTED VERBATIM: SliderSpin, Collapsible
    correct_panel.py          # REBUILT: the Stage-1 control panel (was stage1_correct.py)
  tests/
    test_correct.py           # PORTED: optics round-trip tests (headless, no Qt)
    test_io.py                # session round-trip; OME-TIFF load
```

**Naming:** the new core package is `rwtag` (Reference-Warp Tagger). Import Qt **before**
OpenCV in the GUI entry point (`from PySide6 import ... ` first) — the old `app/main.py`
does this deliberately to avoid the Qt-plugin hijack; keep the comment and the ordering.

---

## 5. Data contracts

Port these two dataclasses **unchanged** from `gridtrack/types.py` into `rwtag/types.py`
(they are already JSON-serialisable via `to_dict` / `from_dict`):

- **`CorrectionParams`** — vignette (`vig_*`), lens (`k1,k2,dist_*`), low-pass (`lp_*`),
  `rotate_deg`, plus the forward hints `invert`, `clahe_clip`.
- **`LevelsParams`** — `lv_enable`, `lv_white`, `lv_gamma`, `lv_black_mode`, `lv_black_k`,
  `lv_black_pct`, `lv_black`.

Keep a slimmed **`PipelineState`** with only the Stage-1 fields plus **explicit forward
slots** so stages 2–4 can attach without reshaping state:

```python
@dataclass
class PipelineState:
    source_path: str | None = None
    raw_image:   np.ndarray | None = None          # float32, original scale
    correction:  CorrectionParams = field(default_factory=CorrectionParams)   # shared optics
    levels:      LevelsParams = field(default_factory=LevelsParams)            # per-image
    corrected_image: np.ndarray | None = None      # float32, after apply()+levels()  <- feeds Stage 2
    # forward slots (unused in Stage 1, present so later stages don't reshape state):
    detection: object = None      # Stage 2: dots/dashes/glyphs
    grid:      object = None       # Stage 2: box numbering / warped reference
    features:  object = None       # Stage 3-4: filtered + tagged points
```

> **Note vs old app:** the old `AppState` kept `LevelsParams` inside the Stage-1 *panel*
> (`self._levels`) and only the optics in `PipelineState`. Here, **promote `levels` into
> `PipelineState`** so the corrected image is fully reproducible from state alone — Stage 4
> needs to reconstruct exactly the processed image the points were tagged on.

### 5.1 Session JSON (the forward-compatibility contract)

Extend the old `save_session` (which stored only `source_path` + `correction`) to capture
**everything needed to regenerate the processed image**:

```json
{
  "version": 1,
  "source_path": ".../3.0X...ome.tif",
  "correction": { ...CorrectionParams... },
  "levels":     { ...LevelsParams... },
  "shared_flags": { "vig_strength": true, "k1": true, "rotate_deg": false, ... }
}
```

- Saved next to the image as `<imagename>.rwsession.json` (sidecar) so per-image params are
  auto-discovered on open. `shared_flags` records which controls were marked shared (§8).
- `load_session` restores both dataclasses via their `from_dict`. Unknown keys are ignored
  (forward-compatible — stages 2–4 may add sections).

---

## 6. The Stage-1 panel (rebuilt UI)

Same controls as `stage1_correct.py`, reorganised into clean collapsible sections. Reuse
`SliderSpin` and `Collapsible` verbatim. Layout top→bottom in the right-hand control column:

1. **Vignetting (flat-field)** — strength, power, `[Auto-estimate vignette]`. *(shared)*
2. **Lens distortion** — k1, k2. *(shared)*
3. **Low-pass (FFT denoise)** — Enable · cut-off (×Nyquist) · shape combo · order spin
   (enabled only for butterworth) · unit read-out label ("cut-off ≈ X cyc/px (period ≥ Y
   px)"). *(shared)*
4. **Rotation (deskew)** — rotation slider · `[Auto-deskew]` (disabled stub, §3.1) · label.
   *(per-image)*
5. **Contrast / threshold (levels)** — Enable · black-point mode combo · `[auto-estimate]` ·
   the one active black control (k **or** percentile **or** value, shown by mode) · white
   point · **gamma** · floor/white read-out label. *(per-image)*
6. **Intensity histogram (pre-levels)** — `pg.PlotWidget`, 96-bin histogram of the
   pre-levels image with a red **black-point** line and a blue **white-point** line
   (`resolve_black_level`, `_value_scale`). Height ~150.
7. **Mid-row brightness profile** — `pg.PlotWidget`, `band.max(axis=0)` envelope over the
   middle ±15 rows; the flatness check for vignette. Height ~150.
8. **View** — Straightness grid overlay · Show original (before).
9. **`[Reset correction]`**.

**Interaction contract (port from old panel):**
- One `QTimer(singleShot, 40 ms)` debounce; every slider/checkbox `→ timer.start()`; timer
  `→ _recompute()`. Keeps dragging smooth.
- Each control shows only its active variant (`_on_lp_shape` gates the order spin to
  butterworth; `_on_lv_mode` shows exactly one of k/pct/value).
- `_recompute()`: `pre = correct.apply(raw, correction)` → `out = correct.levels(pre,
  levels)` → `state.set_corrected(out)` → canvas shows `raw if before else out` → update
  profile (on shown) + histogram (on `pre`, `levels`).
- **Every edit writes through to the shared `PipelineState` dataclasses** (as `_params()` /
  `_levels_params()` do), so the state is always the single source of truth.

---

## 7. "Perfect it for analysis" — required improvements over the old app

These are the gaps that make the old panel unpleasant on real 7 MP frames. All are Stage-1.

### 7.1 Preview downsampling (performance) — **must have**
The old `_recompute` runs the full chain on the full-resolution `float32` every tick. On
2700² that is sluggish (FFT low-pass especially). Add a **preview scale**:
- Keep the full-res `raw_image` as ground truth.
- During interactive dragging, compute on a **downsampled** copy (e.g. longest side ≤ 1200
  px, `cv2.INTER_AREA`) for the live preview.
- On drag-end (timer settles) **or** on explicit `[Render full]` / before `set_corrected`
  for downstream use, compute once at full resolution.
- Vignette/lens/levels are per-pixel and scale-invariant; FFT cut-off is defined in
  ×Nyquist so it is resolution-relative — the preview looks like the full result. Rotation
  is affine. Document that `set_corrected()` must always store the **full-res** result
  (Stage 2 detects on it), never the preview.

### 7.2 Robust OME-TIFF loading
The frames are `.ome.tif`; `io.load_tiff` already prefers `tifffile` and falls back to
`cv2`. Confirm it reads these single-page OME files (it will: `data.ndim == 2`). Keep the
multipage/`project="max"` path for future z-stacks. Add: on load, log `shape`, `dtype`,
`[min,max]` (old app already logs this) and **remember the working folder** so *Open* and
*Copy-to-all* default to `Stitched Images/`.

### 7.3 Auto-fit contrast on load
Because the frames span max≈1209→379, a freshly opened frame should not display near-black.
On load, set the pyqtgraph `ImageItem` display levels from a percentile stretch
(`to_uint8`'s 0.5/99.5 logic, or `img_item.setLevels`) so the user sees the features
immediately — independent of the levels/gamma *correction* (which is a separate, exported
transform). Keep display-autolevel and correction-levels clearly distinct in code and UI.

### 7.4 Per-image params + copy-to-all (the chosen enhancement)
- **Shared vs per-image tag per control.** A small checkbox/lock glyph on each section header
  marks it *shared* (default for vignette/lens/low-pass) or *per-image* (default for
  rotation/levels). Persist the flags in the session (`shared_flags`).
- **On opening a new image:** load its sidecar `*.rwsession.json` if present → restore its
  per-image values; **keep** the current shared values (do not overwrite optics you already
  tuned). If no sidecar, start per-image controls at defaults, keep shared as-is.
- **`[Copy to all]` toolbar action:** write the current correction (shared + per-image) as a
  sidecar session for **every** image in the source folder, so a good vignette/lens tuned on
  one frame propagates. Confirm with a dialog listing the N files that will get sidecars
  (writing files → ask first). Per-image controls are copied too but each frame can then be
  re-tuned and re-saved.
- **`[Save session]` / `[Load session]`** as today, now covering both dataclasses + flags.

### 7.5 Small UX affordances
- Pixel/value readout under the cursor (the canvas already emits view coords; add a hover
  label showing `(x, y) = value`).
- Keyboard: `B` toggles before/after; `G` toggles the straightness grid; `R` reset.
- Guard every action on "image loaded" (old app returns early when `raw_image is None`).

---

## 8. Canvas (viewport)

Port `stageui/canvas.py` and **trim to Stage-1 needs**:
- Keep: `pyqtgraph` `GraphicsLayoutWidget` + `ViewBox(lockAspect=True, invertY=True)`,
  `ImageItem`, `set_image(autolevels)`, the straightness reference grid (`_build_grid`,
  `show_grid`), and the click/hover plumbing.
- Keep the generic overlay helpers (`add_points`, `add_polylines`, `add_labels`,
  `clear_overlays`) **even though Stage 1 doesn't use them** — stages 2–4 draw dots, dashes,
  box quads and numbers through exactly these, so porting them now avoids a canvas rewrite.
- Drop the stage-specific `draw_detection` / `draw_grid` / `draw_glyph_grid` /
  `draw_features` for now (they reference not-yet-ported types); re-add per stage.
- Add the §7.3 display-levels-on-load and the §7.5 hover readout.

---

## 9. Testing

Port and keep the headless tests (they need no display):
- **`test_correct.py`** (ported): the optics functions are the numeric inverse of the camera
  sim — round-trip a synthetic vignetted/distorted frame and assert it comes back flat and
  geometrically true. Add a **rotation** round-trip (`rotate(img, +d)` then `-d` ≈ identity
  in the interior) and a **levels** monotonicity/clip test (`black→0`, `white→full`, gamma
  monotone). Assert `apply()` with default params is a near-no-op.
- **`test_io.py`** (new): `save_session`→`load_session` round-trips both dataclasses and
  `shared_flags`; `load_tiff` reads one real `Stitched Images/*.ome.tif` to the right shape
  and `float32`.
- **Manual GUI smoke:** `python run.py`, open 3.0× and 4.2× (the dim frames), confirm live
  preview stays responsive with §7.1, gamma/levels visibly lift the dim frames, rotation
  deskews, Save/Load and Copy-to-all write the sidecars.

Keep `rwtag` importable and tested **without** PySide6 installed (Qt only in `gui/`).

---

## 10. Dependencies

Stage-1 subset of the old `requirements.txt`:
```
numpy
opencv-contrib-python
tifffile
scipy            # curve_fit in estimate_vignette
PySide6
pyqtgraph
```
(`scikit-image`, `pandas`, `pyarrow`, `trackpy` arrive with stages 2–4.)

---

## 11. Milestones

1. **M1 — Core port.** Copy `correct.py` + the two dataclasses into `rwtag/`; port
   `io.py`; get `test_correct.py` green. No GUI. *(headless, verifiable)*
2. **M2 — Minimal GUI.** `run.py` → MainWindow(Open/Save/Load) + canvas + a `correct_panel`
   wired through `AppState`; live preview of vignette/lens/low-pass/rotation/levels with the
   histogram + profile. Feature-parity with the old Stage 1.
3. **M3 — Perfect-for-analysis.** §7.1 preview downsampling, §7.3 display auto-fit, §7.5
   readout/keys. Responsive on the real 2700² frames.
4. **M4 — Per-image + copy-to-all.** §7.4 shared/per-image flags, sidecar sessions,
   Copy-to-all with confirm dialog.
5. **M5 — Freeze the forward contract.** Confirm `PipelineState.corrected_image` +
   session JSON fully regenerate the processed image; add the `[Auto-deskew]` stub and the
   `detection/grid/features` slots. Ready for Stage 2.

---

## 12. Forward hooks for stages 2–4 (build now, use later)

- **`corrected_image` is the single input** to Stage 2 detection — always full-res, always
  `apply()`+`levels()`. Nothing downstream re-reads `raw_image`.
- **`rotate_deg` and the whole correction are serialised**, so Stage 4 can tag on — and
  reproduce — the exact processed frame (the "tag the processed image" requirement).
- **Canvas overlay helpers** (`add_points/polylines/labels`) are ported ready for dots,
  dashes, box quads and box numbers.
- **`PipelineState.detection/grid/features` slots** exist so stages 2–4 attach without
  reshaping state or the session schema (`version` bump + new JSON sections only).
- **Auto-deskew** re-wires to the glyph classifier once Stage 2 ports the reader.

---

## 13. Open questions (not blocking Stage 1)

1. Effective pixel size (µm/px) per frame — needed later to report strain in physical units;
   Stage 1 can carry it as an optional per-image field in the session now if convenient.
2. Is a flat-field / dark reference image available? If so, vignette correction could divide
   by a measured field instead of the radial model (a better Stage-1 option to add later).
3. Confirm all six frames share one microscope optic (justifies *shared* vignette/lens); if
   they were acquired differently, default those to per-image too.
