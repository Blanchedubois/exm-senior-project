# IX83 Multi-Wavelength Viewer — Implementation Plan

## 1. What the data actually looks like (16Oct26 survey)

### Folder layout
Each acquisition is one Micro-Manager 2.0.3 folder with exactly four files:

| File | Contents | Use in the app |
|---|---|---|
| `<prefix>_MMStack_Pos0.ome.tif` | 16-bit grayscale stack, axes **T×Y×X**, 1412×1412 px | Image data |
| `<prefix>_MMStack_Pos0_metadata.txt` | JSON: `Summary` + one `FrameKey-T-C-Z` block per frame | Exposure, objective, stage XYZ, timestamps |
| `DisplaySettings.json` | Micro-Manager display state (min/max/gamma, colour) | Optional: seed initial contrast |
| `comments.txt` | Free-text comment (all say `"ND2"`) | Show in info panel |

### Key facts
- **One channel per folder.** Metadata says `ChNames: ["Default"]` and `ChannelGroup: ""`. There's no laser or filter information anywhere in the metadata, so **the wavelength can only come from the folder name** (`488-…`, `561-…`, `633-…`).
- **Every folder is a time series, not a single image.** The `100cts` in the name means 100 frames (counts) of the same field of view. Combining frames by mean or max improves signal-to-noise a lot, so the viewer must handle stacks, not just single images.
- **Some stacks were cut short.** Three files hold fewer frames than the metadata intended: 84, 12 and 24 of 100. `tifffile` warns *"MMStack series is missing files"* for these. The 4.2× stacks (50 frames) and the 34.2× stack (2 frames) were *intended* to be that short, even though their names say `100cts`. The loader uses however many frames actually exist.
- **Naming convention:** `<wavelength>-<sample>-[<factor>x-]<N>cts-<exposure>ms_<rep>`. Exposures are 150, 400 or 500 ms. The `3.0x` / `4.2x` / `34.2x` field is probably the expansion factor (`34.2x` looks like a typo; see open questions).
- **Pixel size in the metadata is wrong for these images.** All sample images were taken with the 10× objective (`3-UPLFLN10X2PH`), but `PixelSizeUm = 0.102` is the 100× calibration. With an 11 µm camera pixel (GSENSE400BSI) behind a 10× objective, the real size is about **1.1 µm/px**. Scale bars need a pixel size per objective, and the user must be able to override it.
- **Camera offset is about 100 ADU.** The DarkCount_1 stack (1000 frames at 10 ms) has a median of about 99. Subtracting a dark frame is a cheap, useful correction.
- **Files are large.** A full stack is 400 MB and DarkCount is 4 GB, all stored in iCloud. Load lazily (memory-map or read single pages) and never pull a whole folder into RAM.
- **Mislabelled folder:** `633-Sample1-3.0x-100cts-400ms_2/` contains files whose prefix is `561-Sample1-3.0x-100cts-400ms_2`. Its intensity profile (median about 330, high background) matches the other 633 stacks, not the 561 ones. So it is probably 633 data with an old prefix, and **the folder name should win over the file name**.

### Brightness by channel (frame 0, ADU)
| Channel | Typical median | Typical bright pixels (99.9th percentile) | Notes |
|---|---|---|---|
| 488 | 190–600 | 1.3k–5.7k | Bleaches about 20% over 100 frames at 400 ms |
| 561 | 120–630 | 0.3k–11.6k | Brightest at 150 ms; stable over time |
| 633 | 115–350 | 140–490 | Weak signal on a high background; the 4.2× stack is essentially empty |

Each channel has a very different dynamic range, so **every channel needs its own contrast setting**. A shared min/max would make 633 look black.

### Matching fields of view (grouped by stage XY and Z position)
| Set | Stage XY (µm) | Members | Complete RGB? |
|---|---|---|---|
| A | (−254, −2296), Z 4096 | 488-150ms_1, 488-150ms_2, 561-150ms_1 | No 633 |
| B | (−71.5, −1763.5), Z ≈4861–4874 | 488-400ms_1, 561-400ms_1/2/3, 633-400ms_1 | ✅ |
| C | (−71.5, −2233.3), Z 5057.56 | 488-3.0x_2, 561-3.0x_1, 633-3.0x_2 | ✅ |
| D | (−198.7, −2237.4), Z ≈4797–4798 | 488-4.2x, 561-4.2x, 633-4.2x | ✅ (633 nearly empty) |
| — | (−71.5, −2233.3), Z 4873 / 4797 | 488-3.0x_1, 488-34.2x_1 | Single channel |

*(Corrected in Phase 0: 488-4.2x reports stage Y = −2233.3 while 561/633-4.2x report −2237.4, yet the images line up at (0, 0) px. The grouping tolerance is therefore 10 µm, not 2 µm. The real scan finds 6 fields of view, 3 of them with all three wavelengths.)*

**Grouping folders automatically by stage position is the most useful "auto" feature.** It produces correct RGB sets without the user having to pair folders by hand.

### Measured alignment between channels (phase correlation on the mean of 10 frames, 561 as reference)
- Set B: 488 shifted by **(dy, dx) = (2, 4) px**; 633 by (0, 0)
- Sets C and D: all channels at (0, 0) to the nearest whole pixel
- Drift within one stack over 100 frames: about **1 px**

Channel offsets are small and are simple shifts (translation only). Phase correlation with sub-pixel refinement handles them reliably, and manual nudge controls cover the rest.

### Calibration folders
- `DarkCount_1`: 1000 frames, 10 ms, 100× objective → build a **master dark frame** (median across frames).
- `Bead-Calibration_1`: 100× objective, single "Default" channel → could later support chromatic registration, but only if bead images exist for each wavelength.

## 2. Technology choices

| Concern | Choice | Why |
|---|---|---|
| GUI | **PySide6** (6.11 already installed) | Native macOS, mature, LGPL |
| Image canvas | **pyqtgraph** (0.14 already installed) | Displays 16-bit 1412² images in real time; built-in histogram/LUT widget gives the intensity scale bar; linked pan and zoom across views |
| TIFF I/O | **tifffile** (installed) | Reads Micro-Manager OME-TIFF natively, page by page and lazily |
| Registration | **scikit-image** `phase_cross_correlation` + **scipy** `ndimage.shift` (installed) | Sub-pixel, fast, well tested |
| Publication plots | **matplotlib** (installed) | Figure export with a colour bar and scale bar |
| Export | tifffile (16-bit / ImageJ hyperstack), Pillow (PNG/JPEG) | |

Alternative considered: **napari**. It does about 70% of this out of the box. A custom PySide6 app gives you control over the folder-naming, auto-grouping and export workflow, and teaches the internals. A small "Open in napari" button could still be added later.

## 3. Architecture

```
ix83viewer/
  app.py                  # entry point: python -m ix83viewer
  io/
    mm_dataset.py         # MMDataset: lazy frame access + parsed metadata
    naming.py             # parse folder name -> wavelength, exposure, factor, rep
    scan.py               # scan a date folder, group datasets by stage XYZ
  core/
    channel.py            # Channel = dataset + colour + display settings + offset
    projection.py         # frame, mean, max, median, sum over T (cached)
    corrections.py        # dark subtraction, flat-field (later), background
    registration.py       # auto offset (phase correlation), apply shift
    composite.py          # additive RGB blend of N coloured channels
    display.py            # DisplaySettings: min/max/gamma/brightness/contrast/LUT
  gui/
    main_window.py
    browser_panel.py      # tree of date folder -> FOV sets -> channels
    single_view.py        # one channel + histogram + intensity colour bar
    composite_view.py     # overlay + per-channel visibility
    grid_view.py          # side-by-side views with linked pan and zoom
    align_dialog.py       # auto-align + nudge arrows + numeric dx/dy + blink
    adjust_panel.py       # sliders for each channel
    export_dialog.py
  session.py              # save and load a .json project (folders, offsets, settings)
tests/
```

**Core rule: keep processing separate from display.** Raw `uint16` data is never modified. Corrections and offsets are stored as *parameters*. Display settings (contrast, gamma, colour) only affect the rendered view and cosmetic exports. Quantitative exports always write corrected 16-bit data with **no** contrast stretch.

### Wavelength → colour mapping (default, editable)
| Laser | Default display colour | Physically accurate colour (optional) |
|---|---|---|
| 488 | Green (0, 1, 0) | (0, 1, 0.9) cyan-green |
| 561 | Red-orange or yellow (1, 1, 0)* | (1, 0.9, 0) |
| 633 | Red (1, 0, 0) or Magenta (1, 0, 1)* | (1, 0, 0) |

\*You asked for 633=RED, 561=GREEN, 488=BLUE (a "spectral order" RGB mapping). That will be the default preset. The standard biology preset (488=green, 561=red, 633=magenta, which is colour-blind safe) and a custom option will also be offered.

## 4. Phased delivery

Each phase ends with something you can run and try, so we can adjust before building the next.

### Phase 0: Data layer and command line (no GUI). About one session.
- `MMDataset`: open a folder, read the frame count actually present, read a single frame lazily, parse `Summary` and per-frame metadata (exposure, objective, XYZ, timestamps).
- `naming.parse()`: regex for wavelength, sample, factor, counts, exposure, rep. **The folder name takes priority over the file prefix** (this fixes the mislabelled 633 folder).
- `scan.group_by_position()`: group by stage XY with a tolerance of about 1 µm, and optionally by Z.
- Projections over frames (mean, max, median), cached to disk as `.npy` in a cache folder so iCloud files aren't re-read.
- Dark-frame builder from `DarkCount_1`.
- **Deliverable:** `python3 -m ix83viewer scan "<date folder>"` prints the FOV-set table above, and a `unittest` suite runs against these real folders. ✅ **Done**: see README.md.

### Phase 1: Single-channel viewer and intensity scale (requirements 1 and 5). About one to two sessions.
- Main window: folder browser on the left, image canvas in the centre, info and metadata on the right.
- pyqtgraph `ImageView` with:
  - a **frame slider** plus a projection selector (Frame n / Mean / Max / Median),
  - a pseudo-colour LUT taken from the wavelength (black→colour ramp), with a choice of Gray, Fire or Viridis,
  - a **histogram and intensity colour bar** showing ADU values, with draggable min/max,
  - a cursor readout of x, y and the raw ADU value,
  - an auto-contrast button that clips 0.1% and 99.9% (like Micro-Manager's autostretch),
  - a scale bar with a pixel-size setting per objective.
- **Deliverable:** open any folder, see it coloured by its laser, scrub through frames, and read intensities. ✅ **Done.** Run `python3 -m ix83viewer gui "<date folder>"`. Changes from the plan above: a Min/Sum mode, a dark-subtraction toggle, and an info panel with image statistics including saturated pixels. View ▸ Wavelength colours switches between three colour presets.

### Phase 2: Multiple folders, multiple wavelengths, side by side (requirements 2 and 4). About one session.
- "Add folder…" (more than one at once) and "Scan date folder…", which fills the browser grouped by FOV set.
- Grid view: one panel per channel (1×3 or 2×2), with a merged panel optionally included. **Pan, zoom and frame/projection are linked across panels.** Each panel keeps its own contrast.
- A drop-down to swap which replicate represents a channel (for example 561-400ms_1, _2 or _3).
- **Deliverable:** load set B and see 488, 561 and 633 side by side, zooming them together. ✅ **Done.** Click a Set header, or multi-select ▸ right-click ▸ Show side by side. Changes from the plan above: a crosshair that follows the cursor across panels with every channel's value in one readout, per-panel Merge toggles, set warnings shown above the panels, and contrast shared with the single-channel tab. The merged panel is a preview that is **not aligned**; alignment comes in Phase 3.

### Phase 3: Composite stack, auto-stack and manual alignment (requirement 3). About two sessions.
- Composite builder: choose a reference channel (default 561, or the brightest), then additively blend channels with their LUTs, clipped to [0, 1].
- **Auto-stack:** sub-pixel phase correlation (upsample factor 10) on the mean projection of each channel against the reference. The dialog shows the measured offset and a confidence score.
  - Set B check: 488 should come out at about (2, 4) px.
  - Optional per-frame drift correction within a stack before projecting (the measured drift is about 1 px).
- **Manual edit:**
  - Select a layer, then move it with arrow keys (1 px) or Shift+arrows (0.1 px), or type dx/dy directly.
  - A **blink/flicker** toggle between the reference and the moving layer, plus a checkerboard or difference view to judge the alignment.
  - Lock or unlock each layer, and reset to the auto result.
- Offsets are saved in the session file, so an alignment is done once and reused.
- Later option: rotation and scale (affine) if bead calibration shows chromatic magnification differences.
- **Deliverable:** one-click merged RGB of set B with an adjustable offset for each channel. ✅ **Done.** The Alignment panel is in the Side by side tab.

**What we learned building auto-align on 16Oct26:**
- Every image carries static patterns that don't move with the sample: hot pixels, the illuminated-field edge, and debris in the 561 path.
- Phase correlation locks onto those patterns at (0, 0). Two *different* fields of view still score confidence 13–17.
- Channels label different structures, so cross-channel scores range from 11 to 140.
- Mitigations: a 3×3 median, a central 60% crop, a band-pass filter (σ 2–20 px), a ±20 px limit, and a confidence threshold of 20. Phase correlation finds the peak, then plain correlation refines it (sub-pixel error ≤ 0.05 px against 0.25 px for phase correlation alone).
- Result: Set A/B 488→561 come out reliable, at −0.75 px and (+4.35, +2.55) px. Weak pairs are flagged and not applied.
- **Recommendation:** image multi-colour beads in all three channels for each objective, and use *Save as calibration*. Calibrations apply to every field of view taken with that objective.

**Changes from the plan:**
- The merged panel is now live layers added together by Qt, so nudging, blinking and difference views are instant. `core/composite.py` stays for export.
- The checkerboard view was dropped; Difference covers it.
- Offsets are saved in `offsets.json` right away, rather than in a session file (sessions come in Phase 6).
- Drift correction across frames is deferred: the measured drift is about 1 px over 100 frames.

### Phase 4: Cosmetic adjustments (requirement 6). About one session.
- Per-channel panel: min/max (black and white levels), brightness, contrast, gamma, colour and opacity, a visibility toggle, and invert.
- Optional processing toggles (these change the *processed* data, and the change is recorded):
  - dark-frame subtraction,
  - background subtraction (rolling ball, or a constant from a selected ROI),
  - Gaussian or median denoise.
- Undo/redo, plus "copy settings to other channels" and "apply to all sets".
- Presets saved to JSON, so the same look can be applied across experiments.

✅ **Done.** The Adjust tab is in both views. Changes from the plan above:
- **Dark subtraction** moved from a view-wide checkbox to a per-channel processing setting.
- **Background options:**
  - Constant (percentile).
  - Constant (region box).
  - Rolling ball, run on a 4× block-averaged copy: 0.06 s instead of minutes, and less biased by noise.
- **Brightness/contrast** are expressed as levels, so the histogram, the sliders and the stored state stay in step.
- **Contrast memory** is keyed by acquisition + mode + processing.
- **Undo:** slider drags merge into one step, and copy and preset load are each a single step.
- **Persistence:** display settings save automatically in `display.json`.
- **Known limitation:** rolling-ball subtraction brightens the sharp edge of the illuminated field.

### Phase 5: Export (requirement 7). About one session.
| Export | Format | Contents |
|---|---|---|
| Raw | 16-bit TIFF, one per channel | Projection or single frame, dark-subtracted if enabled, **no** contrast stretch |
| Hyperstack | ImageJ/Fiji TIFF (C×Y×X) or OME-TIFF | Aligned channels with pixel-size metadata, opens in Fiji |
| Edited | PNG (lossless) or JPEG (quality setting) | 8-bit RGB as currently displayed |
| Figure | PNG, PDF or SVG via matplotlib | Panels side by side plus the merged image, with a colour bar per panel, scale bar and labels |
| Stack movie | MP4 or GIF (optional) | Time-lapse of the frames |
| Sidecar | `.json` next to every export | Source folders, offsets, display settings, corrections, app version |

- Batch export: one click exports every FOV set in a date folder using the current presets.

✅ **Done.** Open it with File ▸ Export… (⌘E). Changes from the plan above:
- **Quantitative vs rendered outputs:** quantitative TIFFs hold processed values. A 32-bit float option keeps the exact mean. Display levels and colours go only into metadata, so Fiji opens the stack looking right without the numbers being stretched.
- **Merge ticks:** the merged image, figure and movie respect each panel's *Merge* tick.
- **Movies:** each frame is re-read and re-processed. GIF uses Pillow; MP4 pipes frames to `ffmpeg`, since the Python ffmpeg package isn't installed.
- **Batch:** uses each acquisition's saved settings and offsets (via *Apply to all sets* or presets), rather than one preset for everything.
- **Not done:** export of an arbitrary frame range for movies; it always uses all frames.

### Phase 6: Extra features worth adding, in rough order of value
1. **Session/project files.** Reopen exactly where you left off: folders, offsets, contrast.
2. **Line profile and ROI statistics.** Draw a line and plot intensity per channel (useful for comparing resolution and expansion), or draw a box and get mean, std and SNR per channel.
3. **Photobleaching curve.** Mean ROI intensity against frame number for each channel (488 drops about 20% over 100 frames).
4. **Expansion-factor helper.** Use the pixel size with the expansion factor to give the effective pre-expansion scale bar.
5. **Colocalisation metrics.** Pearson and Manders coefficients for each pair of aligned channels.
6. **Saturation and clipping overlay.** Highlight pixels at 0 or 65535, and pixels clipped by the display.
7. **Thumbnails** in the browser, made from cached mean projections.
8. **Data sanity warnings.** Truncated stacks, a folder/prefix mismatch, or channels in a set with mismatched exposure or Z.

✅ **Done (all eight).** Changes from the plan:
- **Analysis dock:** line, box, bleaching and colocalisation share one bottom dock. The shapes are drawn once and mirrored on every panel, with alignment taken into account.
- **Bleaching fit:** includes an exponential fit (τ, half-life, R²), and drops under 2% are not fitted.
- **Sessions:** auto-save on quit and auto-restore on launch. Session files embed the settings and offsets they use.
- **Thumbnails** use frame 0, not the mean, so opening a folder doesn't read ~5 GB from iCloud.
- **Bug fixed while building this phase:** pyqtgraph's two-way X/Y view linking ran away (zoom went from 776 px to 2.5 million px) when aspect-locked tiles changed shape, e.g. when the dock opened. It's replaced by `gui/view_sync.py`, which keeps one shared centre and scale and re-applies it on resize instead of learning from resize side effects.

## 5. Testing approach
- Unit tests in `tests/` (standard-library `unittest`, since pytest isn't installed) against the real 16Oct26 folders: frame counts (84 / 12 / 24 truncated; 2 / 50 / 100 / 1000 complete), name parsing (including the mislabelled 633 folder), FOV grouping (sets A–D), and a registration regression (set B: 488 at about (2, 4) px).
- Synthetic tests: shift an image by a known sub-pixel amount and check that registration recovers it to within 0.1 px.
- The GUI is checked by hand at the end of each phase, against a short checklist.

## 6. Open questions for you
1. **Colour mapping:** keep 633=R, 561=G, 488=B as the default, or use the standard green/red/magenta?
2. Is `3.0x` / `4.2x` the **expansion factor**? Is `34.2x` a typo (for 4.2x or 3.0x)? Its stage XY matches set C but its Z matches set D.
3. Is the `633-…3.0x_2` folder really 633 data? Its file prefix says 561.
4. Which frame combination should be the default: mean or max? Should frames be drift-corrected before averaging?
5. Will future data include multiple channels inside one file (a Micro-Manager channel group), Z-stacks or multiple positions? The loader can be built for C/Z/P axes from the start.
6. Pixel size: confirm about 1.1 µm/px for the 10× objective, or give me the calibrated value.
