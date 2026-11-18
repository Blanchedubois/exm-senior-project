# Expansion + Camera Simulation

Simulated **microscope camera images** of the hydrogel marker grid as it is
**gradually expanded**, viewed through a **fixed microscope** (fixed field of
view / fixed magnification), with rigid ArUco markers and a realistic camera
model. The markers are the toolkit's *conjoined* tags (with struts), so this
matches the real "new" marker design.

## What it models

- **Fixed zoom / fixed FOV.** The microscope images a fixed `fov_um` window at a
  fixed pixel size, so **every frame has the same pixel dimensions and the ArUco
  markers stay a constant size** (48 px). As the gel swells the features spread
  apart *within* this fixed frame and peripheral markers leave the field of view
  — so fewer markers are visible at higher `λ` (that is what a fixed zoom does;
  in practice you would tile/stitch). Increase `fov_um` to keep more markers in
  view at high `λ` (at the cost of more empty margin at `λ = 1`).
- **Rigid islands.** Each tag and dot keeps its exact printed size and internal
  pattern (a rigid stamp that only translates); only the spacing grows:
  `X' = fov_centre + drift + λ·(X − pattern_centre) + warp(X)·λ`.
- **Rigid dashed boundary.** The boundary dashes are rigid printed marks: each
  dash keeps its **fixed length and width** at every `λ`. Only the *period*
  scales with `λ`, so a fixed set of dashes **spreads apart** (gaps grow) as the
  boundary stretches — exactly like the rigid dots. The trim stays clear of each
  tag's quiet zone.
- **Minimal distortion throughout (multi-area warp).** `warp(X)` is a smooth sum
  of ~12 small, randomly-oriented Gaussian lobes spread across the field — a
  little non-uniform distortion *everywhere*, not one localized bulge. Dots that
  warpage pushes into a tag's keep-out are dropped (occluded by the opaque rigid
  tag), keeping quiet zones clean.
- **Accumulating rotation.** The whole sample rotates progressively more at each
  expansion stage: stage `k` is turned `rotation_deg + k·rotation_step_deg`
  (default 2° → 20° across the sweep), as if the sample drifts a little more each
  acquisition. The scene rotates so each rigid tag rotates with it (ArUco decodes
  rotated tags natively). The render margin is auto-sized to the largest rotation
  so no blank corners are ever cropped into the fixed FOV.
- **Per-frame drift.** A small random `(x, y)` shift of the whole sample each
  frame (`drift_um`, stage repositioning error).
- **Lens distortion.** A Brown-Conrady radial distortion of the whole image
  about the optical axis (`lens_k1 = -0.05` = barrel: straight lines bow outward,
  as a real objective does; positive = pincushion). It is a property of the
  optics, so it is identical on every frame. The decoder **calibrates it out**
  (an exact radial un-distortion) before detection, as a real pipeline does — so
  the saved frames stay distorted while detection works on the corrected image.
- **Fluorescence contrast (`invert = True`).** Frames are inverted monochrome —
  bright pattern on a dark background, as a fluorescence microscope captures it.
  Inversion is applied before blur/noise so shot noise lands on the bright
  features.
- **Optical blur.** Gaussian PSF, `FWHM = 0.30 µm` (confocal-ish) — the camera
  resolution limit.
- **Vignetting.** A strong optical radial brightness falloff (`vignette_strength
  = 0.88`, corners at ~12% brightness), applied before sensor noise. It is a property of the microscope
  optics, so it is **identical on every frame** (the FOV is fixed, so the mask is
  the same size and centred on the sensor for all `λ`). The decoder undoes it by
  **flat-field correction** (divide by the known flat) — so saved frames stay
  realistically vignetted while detection is unaffected.
- **Camera noise.** Poisson shot noise (full-well ≈ 350 e⁻) + Gaussian read
  noise (≈ 4 grey levels), on a `background_level ≈ 14` pedestal (camera bias /
  faint autofluorescence) so the dark background sits at a slightly brighter grey
  rather than pure black.

Markers near the centre decode at every `λ`; some markers at the vignette-dark,
lens-distorted **frame edge** are lost (most visibly at `λ = 1.5`, where the
pattern fills right to the FOV border) — realistic edge degradation that the
analysis pipeline recovers from each box's other corners. Decode is reported as
in-frame-decoded / in-frame-total.

Rendering is supersampled (2×) then area-downsampled to the camera grid
(`8 px/µm` = 0.125 µm/px) for anti-aliasing.

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install numpy opencv-contrib-python matplotlib pillow
python simulate_expansion_camera.py
```

(A `.venv/` was already created here with these packages.)

## Outputs

| Path | Contents |
|---|---|
| `degradations/<name>/expansion_l<λ>x.tif` | fidelity sweep — the full λ set at each blur/noise level, in its own folder |
| `degradations/<name>/expansion_stack.tif` | multipage TIFF of that level's frames |
| `degradations/<name>/montage.png` | contact sheet + decode count, annotated with the level's blur/noise |
| `pngs/expansion_l<λ>x.png` | baseline level (`L0_baseline`) mirrored as 8-bit PNG |
| `tiffs/expansion_l<λ>x.tif` | baseline level mirrored as 8-bit TIFF (separately) |
| `tiffs/expansion_stack.tif` | baseline multipage TIFF, all frames |
| `montage.png` | baseline contact sheet + in-frame decode count per level |

Default sweep: `λ = 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0`.

### Fidelity degradation sweep (`degradations/`)

Every level re-uses the **exact same rendered scene** (identical warp / drift /
rotation / lens / vignette) and only changes the **optical blur (PSF FWHM)** and the
**camera noise** (read noise, full-well shot noise, background pedestal). So each
folder holds progressively **blurrier + noisier** images of the *same* sample — drop
any one folder into the analysis tool and score its fidelity against the cleaner
folders. Blur climbs gently (0.30 → 0.50 µm FWHM, "slightly more blurry"); noise
climbs hard (read noise 4 → 30, full well 350 → 60 e⁻, "much noisier"). `L0_baseline`
equals the default camera model (and is also mirrored to `pngs/` + `tiffs/` so the
existing downstream project keeps working).

| Level | PSF FWHM (µm) | Read noise | Full well (e⁻) | Background |
|---|---|---|---|---|
| `L0_baseline` | 0.30 | 4  | 350 | 14 |
| `L1_mild`     | 0.34 | 8  | 240 | 16 |
| `L2_moderate` | 0.38 | 14 | 160 | 18 |
| `L3_strong`   | 0.44 | 20 | 100 | 20 |
| `L4_severe`   | 0.50 | 30 | 60  | 24 |

The printed in-frame ArUco decode count falls off across the levels (a quick
built-in fidelity signal); the marker grid itself stays fully present at every level,
so the dense dot field remains available to a more robust tracker even where the
strict tag decoder gives up.

## Tuning

All parameters are in the `SimConfig` dataclass at the top of
`simulate_expansion_camera.py`:

- `expansions` — the λ sweep.
- `fov_um` — the fixed field of view (bigger = more markers stay in view at high
  λ, more empty margin at λ = 1).
- `camera_px_per_um`, `psf_fwhm_um` — effective pixel size (zoom) and blur.
- `rotation_deg`, `rotation_step_deg` — first-stage rotation and the extra
  rotation added at each later stage (accumulating tilt).
- `drift_um` — max per-frame random x/y shift.
- `warp_amp_um`, `n_warp_lobes`, `warp_sigma_um` — the multi-area distortion:
  per-lobe amplitude (set `warp_amp_um = 0` for pure uniform expansion), number
  of lobes, and lobe width.
- `lens_k1`, `lens_k2` — barrel (negative) / pincushion (positive) lens
  distortion; `0` disables it.
- `vignette_strength`, `vignette_power` — optical falloff depth and steepness.
- `read_noise`, `full_well_photons` — noise severity (lower well = noisier). These are
  the *baseline*; the per-level values live in `degradations`.
- `background_level` — dark-background pedestal (raise for a brighter noise floor).
- `degradations` — the fidelity sweep: a tuple of `DegradationLevel(name, psf_fwhm_um,
  read_noise, full_well_photons, background_level)`. Add, remove, or retune rows to
  change how many degradation folders are produced and how blurry/noisy each is. The
  scene is rendered once and re-degraded per level, so extra levels are cheap.
- `invert` — `True` (default) fluorescence; `False` black-on-white.
- `supersample`, `render_margin`, `render_px_cap` — render quality / rotation
  margin / memory guard.
