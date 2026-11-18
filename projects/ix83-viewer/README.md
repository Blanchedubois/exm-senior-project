# IX83 Analysis Pipeline

Viewer for Micro-Manager acquisitions from the IX83 (one wavelength per folder).
See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the roadmap. **Phases 0 (data layer), 1 (single-channel viewer), 2 (side-by-side wavelengths), 3 (channel alignment), 4 (adjustments), 5 (export) and 6 (analysis and extras) are done.**

Run everything from this folder.

```bash
# Open the viewer (with a date folder, a single acquisition folder, or nothing)
python3 -m ix83viewer gui "../../Experimentation/IX83 Data/16Oct26"

# Group a date folder's acquisitions into fields of view (488/561/633 sets)
python3 -m ix83viewer scan "../../Experimentation/IX83 Data/16Oct26"

# Metadata for one acquisition (wavelength, frames, objective, pixel size, stage XYZ, warnings)
python3 -m ix83viewer info "../../Experimentation/IX83 Data/16Oct26/561-Sample1-100cts-400ms_2"

# Collapse a stack (mean|max|min|sum|median|frame), optionally dark-subtract, save a TIFF
python3 -m ix83viewer project "../../Experimentation/IX83 Data/16Oct26/488-Sample1-100cts-400ms_1" \
    -m mean --dark "../../Experimentation/IX83 Data/16Oct26/DarkCount_1" -o 488_mean.tif

# Tests (synthetic tests, plus real-data tests when the 16Oct26 folder is present)
python3 -m unittest discover -s tests -v
```

## Viewer (Phase 1)
- **Left panel:** acquisitions grouped into fields of view (Set A, B, …), each with its wavelength colour. Orange names have warnings; hover over one to read them. *File ▸ Add acquisition folder…* opens a single folder.
- **Centre:** the image, with **Show** set to a single *Frame* (use the slider; elapsed time is shown) or to all frames combined (*Mean / Max / Median / Min / Sum*).
- **Intensity scale:** to the right of the image is a histogram, with the colour bar labelled in raw ADU. Drag the yellow handles to set black and white levels, and scroll the axis to zoom it. *Auto contrast* clips the darkest 0.1% and brightest 0.1% of pixels. Levels are remembered per acquisition and per display mode, and are kept while you scrub through frames, so you can watch bleaching.
- **LUT:** wavelength colour (the colour mapping is under *View ▸ Wavelength colours*), Gray, Inferno, Viridis or Magma.
- **Subtract dark:** subtracts the median of `DarkCount_1`. It's now set per channel in the **Adjust** tab (see below), and is available when the date folder contains a dark acquisition.
- **Scale bar:** resizes as you zoom. The pixel size can be edited, and the default is 1.1 µm/px at 10×.
- **Cursor readout:** pixel x and y, the value (plus the raw value when any processing is on), and the position in µm.
- **Zoom:** stays fixed when you switch between acquisitions of the same size, which makes it easy to flip between channels of one view.

## Side by side (Phase 2)
- **Opening it:** click a **Set** header in the left list to open the *Side by side* tab. You can also select several acquisitions (⌘-click or Shift-click), right-click, and choose **Show N side by side**; they can come from different sets. Clicking the *Added folders* header shows everything you've added by hand.
- **Panels:** there is one panel per wavelength, ordered 633 → 561 → 488, plus a **Merged** panel.
  - Each panel has **its own contrast**, set with the horizontal histogram underneath it. *Auto contrast all* resets every panel.
  - When a wavelength has replicates (for example 561-400ms_1/_2/_3), a drop-down picks which one to show. The one with the most frames is the default, so truncated stacks aren't picked.
- **Linked controls:** *Show* (frame or combined) and the frame slider drive every panel together. When a stack is shorter, its panel stays on its last frame and labels it.
- **Link zoom:** panning and zooming one panel moves all of them. A dashed crosshair follows the cursor in every panel, and the readout gives each channel's value at that pixel.
- **Merged panel:** each channel is scaled by its own levels, coloured, and added together. Untick **Merge** on a panel to leave it out. Channels are aligned using the offsets from the Alignment panel (see below).
- **Layout:** *Row* (1 × N) or *Grid* (2 × 2).
- **Shared contrast:** contrast chosen in either tab is remembered for that acquisition and display mode, and reused in the other tab.
- **Warnings:** the bar above the panels shows the set's warnings, such as mixed exposures (Set F: 400 vs 500 ms) or a Z difference between channels.

## Alignment (Phase 3)
The **Alignment** panel is on the right of the *Side by side* tab.
- **Reference:** the other channels are moved to match it. The default is 561.
- **Auto-align:** estimates each unlocked channel's offset from the images on screen; use *Mean* for the cleanest result. Only **reliable** results are applied: confidence ≥ 20 and an offset within ±20 px. Uncertain estimates are shown in orange but not applied, unless you tick *Apply uncertain results*.
- **Manual adjustment:** select a channel (radio button), then use the **arrow keys** to nudge it by 1 px, or **Shift+arrow** keys for 0.1 px. You can also type dx/dy. **Lock** a channel to protect it from Auto-align and nudging.
- **Merged view:**
  - *Overlay* shows every channel.
  - *Blink* alternates the reference and the selected channel every 0.5 s. If structures jump, they're misaligned.
  - *Difference* shows |reference − selected| in gray. Structure that both channels share goes dark when aligned. Structure that only one channel has (e.g. 561 nuclei vs 488 cytoplasm) stays bright whatever the alignment.
- **Reset to auto / Zero / Save as calibration:**
  - *Reset to auto* restores the last auto result.
  - *Zero* sets the selected channel's offset to 0.
  - *Save as calibration* stores the selected channel's offset for this **objective and wavelength pair**, so it's used for every field of view that doesn't have its own offset.
- **Show channel panels aligned:** draws the individual panels shifted too, so the crosshair and readout compare the same point in the sample.
- **Where offsets are saved:** automatically, in `~/Library/Application Support/ix83viewer/offsets.json` (change with `IX83_CONFIG_DIR`). They're keyed by acquisition folder, and each direction is derived from the other (488→561 = −(561→488)).

**About the 16Oct26 data:** the channels label different structures, and every image carries static patterns: camera pixels, the illuminated-field edge, and debris in the light path. Those patterns pull estimates towards (0, 0). Two *different* fields of view still scored 17. Only some pairs come out reliable, e.g. Set B 488→561 = (+4.35, +2.55) px and Set A 488→561 ≈ −0.75 px. For dependable offsets, image **multi-colour beads** (such as TetraSpeck) in all three channels with each objective, auto-align them, and *Save as calibration*.

## Adjust (Phase 4)
The **Adjust** tab is on the right of the *Single channel* view, and next to *Alignment* in *Side by side*, where a **Channel** drop-down picks which channel you're editing.
- **Display (cosmetic):** these settings only change how pixels are drawn.
  - *Black/white* levels.
  - *Brightness* and *Contrast*: another way of moving the same levels, as in ImageJ.
  - *Gamma* (0.2–5): applied through the lookup table, so the histogram's colour bar shows the real curve.
  - *Colour* (any colour; *Default* returns to the wavelength colour) and *Invert*.
  - *Merge weight* (Side by side only): how strongly the channel shows in the merged image.
  - *Auto contrast* and *Reset display*.
- **Processing (changes pixel values):** applied in this order: dark → background → denoise. Negative values are clipped to 0.
  - **Subtract dark frame:** removes the master dark frame (~100 ADU camera offset).
  - **Background:**
    - *Constant: percentile* subtracts the Nth percentile; 5% works for a flat background.
    - *Constant: region* subtracts the median inside a yellow box you drag onto an empty area.
    - *Rolling ball (radius)* removes uneven background such as the high 633 background (median 353 → 16 ADU in Set B). It leaves bright artefacts along the sharp edge of the illuminated field; use a larger radius, or ignore the corners.
  - **Denoise:** Gaussian (σ) or median (size).
  - **Contrast memory:** levels are remembered separately for each processing combination, so switching processing on or off brings back the right contrast.
- **Copy to other channels:** copies processing, gamma and invert, but not levels or colour, which are channel-specific.
- **Apply to all sets:** gives every acquisition of this wavelength and objective in the open date folder these settings and levels.
- **Reset channel:** clears all settings for the channel.
- **Presets:** *Save…* stores every visible channel's settings and levels by wavelength. *Load* applies them to matching channels, for a consistent look across experiments.
- **Undo / Redo:** *Edit ▸ Undo* (⌘Z) and *Redo* (⇧⌘Z). Slider and histogram drags count as one step, and so do *Copy* and preset *Load*. Undo history resets when you open another acquisition or set.
- **Saving:** everything is saved automatically in `display.json`, next to `offsets.json`, and comes back when you reopen an acquisition.

## Export (Phase 5)
**File ▸ Export…** (⌘E) exports what the current tab shows: the single acquisition, or the side-by-side set with its replicates, processing, contrast, colours, offsets and *Merge* ticks.

The default folder is `IX83 Data/Exports/<date>/`. File names start with *Name* (default `16Oct26_Set_B_Mean`).

| Output | File | What's in it |
|---|---|---|
| One TIFF per channel | `…_633.tif` | **Processed values, no contrast stretch**: 16-bit (rounded) or 32-bit float (exact mean). Pixel size and the display colour/levels are stored as Fiji metadata. |
| Multi-channel stack | `…_stack.tif` (or `.ome.tif`) | C×Y×X. It opens in Fiji as a coloured composite with your levels. Offsets are applied if *Apply channel offsets* is on. |
| Merged image | `…_merged.png/.jpg` | 8-bit RGB as in the Merged panel. Only channels with *Merge* ticked are included. Optional burned-in scale bar. |
| Each channel image | `…_561.png/.jpg` | Each channel as displayed, with its LUT and gamma. |
| Figure | `…_figure.png/.pdf/.svg` | Panels side by side plus the merge, an ADU colour bar under each panel, scale bars, and a title. |
| Movie | `…_movie.gif/.mp4` | Every frame of the stack (merged or one channel), processed per frame with your current levels. MP4 uses Homebrew's `ffmpeg`. |
| Sidecar | `….json` | Always written: source folders and files, exposure, objective, pixel size, mode/frame, processing, levels, gamma, colour, offsets (with source and confidence), export options and the list of files. |

**Export panels…** (button at the bottom right of *Side by side*, or ⇧⌘E) writes **one image per set** for the whole date folder. Each image shows every channel and the overlay side by side, with ADU colour bars, scale bars and a caption read from the metadata: objective, camera mode, exposure, frames, levels, processing, offsets, and whether the camera's on-chip processing was on.
- **Options:** *Subtract the dark frame in every panel* (on by default) and *Scale bars in pre-expansion µm*.
- **Extra versions:** *without 633 nm*, and *grayscale, each channel on its own (no overlay)*. Each gets its own panels and comparison, with `_no633` and `_gray` in the file names.
- **Expanded sets use a single frame:** expanded sets (3.0×, 4.2×) show **one frame** (frame 0 by default) instead of an average. Expanded gels drift 16–33 px during a stack, so a mean blurs them. Single frames reuse the contrast saved for the mean.
- **Inferno images:** *Also: an inferno image of each channel* writes one inferno-coloured image per channel, exactly as used in the panels, into `inferno/`.
- **Expansion comparison:** it also makes a figure with one row per expansion factor (1× / 3.0× / 4.2×). Every scale bar is the same pre-expansion length, so the bar grows with the expansion.
- **Which settings it uses:** the set on screen is exported exactly as shown; the other sets use each acquisition's saved settings.
- **For the blog:** `tools/prepare_blog_images.py` converts the panels into WebP images (see `blog_draft/README.md`).

**Batch:** in the Export dialog, tick *Export every set in this date folder*. Each set gets its own subfolder (`Set_A/`, `Set_B/` …) and uses the settings saved for each acquisition, so set up the look once, use *Apply to all sets* or presets, then batch export. All six 16Oct26 sets export to figure + merged image in about 3 s.

## Analysis and extras (Phase 6)
**View ▸ Analysis** (⇧⌘A) opens a bottom panel with four tools. Line and box tools act on the first image and appear as dashed copies on the other panels. Alignment offsets are taken into account, so every channel is measured at the same point in the sample.

| Tab | What it does |
|---|---|
| Line profile | *Draw line*, drag its ends. Plots intensity per channel along the line in µm (pre-expansion µm if that toggle is on). *Export CSV*. |
| Region stats | *Draw box*, or measure the whole image. Gives mean, median, std, min, max, SNR (mean/std), camera-saturated pixels, pixel count and area for each channel. *Export CSV*. |
| Bleaching | *Compute over all frames*: mean of the box (or image) in every raw frame, dark-subtracted if that channel uses dark subtraction. Plots against time, normalised or in ADU, and fits I = A·e^(−t/τ) + C. Reports % loss, τ and half-life; a drop under 2% is reported as "no significant bleaching". On 16Oct26 Set B: 488 drops 20% in 48 s (τ ≈ 80 s); 561 and 633 are stable. |
| Colocalisation | Pick channels A and B. Gives Pearson's r and Manders M1/M2 (Otsu thresholds, or none) over the box or image, using aligned processed images, plus a 2D intensity histogram. Channels that label different structures score low by design. |

**Other additions:**
- **View ▸ Highlight saturated / clipped pixels:** magenta marks camera-saturated pixels (65535); yellow marks pixels above the current white level.
- **View ▸ Pre-expansion scale bars:** scale bars, profiles and exports can show biological size, i.e. the measured length ÷ the expansion factor, for example "50 µm pre-exp. (÷4.2)".
  - The factor is read from the folder name (`3.0x`, `4.2x`). You can edit it in the *Info* tab's **Expansion** box; `34.2x` is flagged as a probable typo.
  - Export has a matching *Scale bars in pre-expansion units* option.
- **Sessions:**
  - *File ▸ Save session…* (⌘S) and *Open session…* store the folders, both views (set, replicates, mode, frame, LUT, layout, zoom, reference channel, Merge ticks), the View toggles, expansion and pixel-size overrides, and the Analysis line and box.
  - The file also contains copies of the settings, contrast levels and offsets it uses, so it's self-contained.
  - **The last session is saved when you quit and reopened when you launch without a folder.**
- **Thumbnails:** hover over an acquisition in the left list to see its first frame in its wavelength colour. They're made in the background from frame 0 only, so opening a folder stays fast.
- **Tools ▸ Data check…:** one report of everything suspicious in the date folder, warnings first:
  - truncated stacks and folder/prefix mismatches;
  - an implausible expansion factor;
  - mixed exposure or Z within a set;
  - the pixel-size metadata mismatch;
  - missing dark or multi-colour bead calibrations.

## Behaviour worth knowing
- **The wavelength comes from the folder name**, because the metadata has no laser information. When a file's prefix disagrees with its folder name, the folder name wins and a warning is shown.
- **Pixel size is 11 µm divided by the objective's magnification** (Prime 95B camera): 1.1 µm/px at 10×. The `PixelSizeUm` value in the metadata (0.102) is the 100× calibration. Set `MMDataset.pixel_size_override_um` to override it.
- **Stage position comes from the per-frame metadata.** The `Summary.StagePositions` block can be stale.
- **Projections are cached** in `~/Library/Caches/ix83viewer` (change with `IX83_CACHE_DIR`). The cache is safe to delete.
- **Grouping tolerances** default to 10 µm in X/Y and 25 µm in Z. Change them with `scan --xy-tol / --z-tol`.

## Layout
```
ix83viewer/
  io/naming.py       folder-name parser
  io/mm_dataset.py   lazy one-frame-at-a-time reader + metadata
  io/scan.py         scan a date folder, group by stage position
  core/projection.py mean/max/min/sum/median/frame, cached
  core/corrections.py dark frame, dark subtraction
  core/display.py    colour presets, LUTs, auto-contrast, scale-bar lengths
  core/composite.py  additive RGB merge (with per-channel offsets, for export)
  core/registration.py  auto offset estimate (phase correlation) + shifting
  core/offsets.py    saved pair offsets and objective calibrations
  core/processing.py dark / background / denoise pipeline
  core/adjust.py     channel display settings, brightness-contrast <-> levels, gamma
  core/settings_store.py  saved settings, contrast levels, presets
  core/export.py     render, TIFF/hyperstack/OME, PNG/JPEG, movie, sidecar (no Qt)
  core/export_jobs.py  export options, figure, batch over sets
  core/analysis.py   line profile, region stats, bleaching fit, colocalisation, clipping overlay
  core/checks.py     data check findings, thumbnails
  gui/               main window, browser, single-channel + side-by-side views, channel panels,
                     info panel, scale bar, shared loading helpers, background loader,
                     analysis dock, sessions, view sync (linked zoom)
  app.py             GUI entry point
  __main__.py        command line
tests/
```
