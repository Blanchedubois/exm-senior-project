# Build: ExM Distortion Explorer (interactive ACF / CCF GUI)

## Goal

Build a desktop GUI that lets me place **local sites of anisotropic (or lagging) expansion** on the real fiducial grid, drag them around, resize them, change their shape and strength, and watch the **ACF of the pre image, the ACF of the post image, and the pre-vs-post CCF** update live, together with the ground truth they should recover.

It extends a batch simulation that already works (`reference/exm_sim.py`, `reference/exm_analysis.py`). Reuse its physics and analysis code, and match its results (see "Acceptance tests").

Before writing code, read everything in `reference/`, then give me a short implementation plan (modules, threading model, how you will hit the performance targets) and wait for my OK.

## Reference material (in `reference/`, do not modify)

| File | What it is |
|---|---|
| `reference_tags.json` | Every printed feature with design coordinates: 17,825 dots, 480 dashes, 36 ArUco tags (`records`: tag, category, x_um, y_um, meta) |
| `spec_sheet.json` | Grid geometry, optics, frame conventions, detector settings. Read the `_notes` block carefully |
| `ids.json` | ArUco id at each node |
| `exm_sim.py` | Batch simulator: renders pre (1x) and post (4x) 16-bit images. Rendering, rigid islands, noise model, frames |
| `exm_analysis.py` | Batch analysis: ACF + lattice fit, tag-centre affine, global CCF, windowed lattice-aware CCF with unwrapping, plane-fit local expansion |
| `check_tags.py` | ArUco detection (invert polarity, small min perimeter for post) |
| `autocorr_demo.py` | Earlier matplotlib toy explorer. UX inspiration only |
| `results.json`, `acf-ccf-simulation-results.md`, `fig_*.png` | Results of the batch run. Use them as regression targets and to see what the panels should look like |

## Physics and imaging (must match the reference)

**Frames.** Design frame is in µm, origin at the bottom-left of the print, **y up**. Images are **y down**, so design to image is a reflection (det = -1). Keep one helper module for all frame conversions and test it.

**Optics.** 0.51 µm/px, isotropic Gaussian PSF with FWHM 1.91 µm (expose as a control, range 1.5 to 3.0). Printed material is bright on a dark background. Noise is Poisson shot noise plus Gaussian read noise (peak ~600 e-, background ~100 e-, read 4 e-; post signal multiplied by λ^0.16, per the spec sheet).

**Rigid islands.** Every printed feature keeps its printed size and shape at every expansion. Only island *centres* move. An island translates with the displacement at its centre and rotates with the global stage rotation only. Tags are rigid too, so never fit anything through tag corners, only tag centres.

**Global transform.** post_position = λ · R(θ_stage) · (x + u(x)) + offset + gel_jitter, applied about the grid centre, with x in the image-plane µm frame of the pre sample. Defaults: λ = 4.0, θ_stage = 4°, gel jitter 0.4 µm rms (post µm), print jitter 0.08 µm rms (shared by pre and post since it is the same print), pre stage rotation 0.6°.

**Expansion presets.** TExM λ = 3.3, ExM λ = 4.0, MAGNIFY λ = 10. Custom range 1 to 12.

### Local sites (the thing I want to move around)

Each site is an elliptical region with a smooth edge carrying an **eigenstrain**: the gel there *wants* to expand differently from the rest.

Per-site parameters (all editable live):
- **Position** (cx, cy) in design µm.
- **Size**: semi-axes a and b (µm), and **orientation** φ of the ellipse.
- **Proportion**: shown as the aspect ratio a/b. Changing it keeps the area constant.
- **Eigenstrain inside the site**: principal strains ε₁ (along the ellipse major axis) and ε₂ (along the minor axis), as fractions of the global expansion. Examples: ε₁ = ε₂ = -0.12 is an isotropic lagging patch (expands 12% less). ε₁ = +0.05, ε₂ = -0.05 is a purely anisotropic site. Add a "lock isotropic" toggle (ε₂ follows ε₁) and an optional independent eigenstrain angle (defaults to φ).
- **Edge softness**: width of the transition, as a fraction of the size. 0 means a sharp edge.
- Enabled / disabled, colour, name.

Envelope: f(r_ell) = 0.5·(1 − tanh((r_ell − 1)/w)) with r_ell the normalised elliptical radius. Sum the eigenstrain tensors of all sites (overlaps add).

"Proportion" could mean the ellipse aspect or the strain anisotropy ratio. Implement both, label them clearly ("site shape a/b" and "strain anisotropy (1+ε₁)/(1+ε₂)"), and make the site's ellipse handle control shape while the side panel controls strain.

### Displacement solver

Solve for the displacement u(x) produced by the eigenstrain field ε*(x) embedded in the gel. Use the isotropic linear-elastic (Navier) solution in Fourier space on a padded periodic grid:

- Equilibrium with σ = C : (ε(u) − ε*) gives, per wavevector k:
  [μ|k|² I + (λ_L + μ) k kᵀ] û = −i (C : ε̂*) k
- Solve the 2×2 system per k, set û(0) = 0.
- Poisson ratio ν is a control (0 to 0.49, default 0.3), with a **plane strain / plane stress** toggle (plane stress uses λ_L = 2μν/(1−ν); plane strain uses λ_L = 2μν/(1−2ν)). μ cancels, so set μ = 1.
- Grid: about 2 µm spacing, padded to at least 2× the 750 µm field so periodic images don't interact. Precompute k-space operators once per (ν, mode, grid).
- Also offer a **"Kinematic (legacy)"** model that reproduces `exm_sim.py` exactly: isotropic part only, u = ∇φ with ∇²φ = 2e. It exists only for the regression test against `results.json`.

Ground truth fields to expose: u, local expansion λ·√det(I + ∇u), local anisotropy (ratio of singular values of I + ∇u), local rotation.

## What the GUI shows

Main window, dark theme, resizable splitters. Use **PySide6 + pyqtgraph** (fast image updates, built-in draggable/rotatable/scalable ROIs). It must run on Fedora 43 (Wayland, with an xcb fallback documented), CachyOS, and macOS on Apple Silicon.

1. **Sample view (main canvas).** The pre image, or a clean design render, with each site drawn as a draggable ellipse (pyqtgraph `EllipseROI` or a custom ROI with move, scale and rotate handles). Overlay toggles: true displacement arrows, true local expansion heatmap, true local anisotropy heatmap, measured local expansion (from CCF), node grid and tag ids. Click a site to select it, double-click empty space to add one, Delete key removes it.
2. **Post view.** The post image rendered at native resolution for the visible region only (the full 4x image is 6,600 px wide and 16,000 px at λ = 10, so never render it whole in live mode).
3. **ACF panels.** ACF(pre), ACF(post), each with a lag zoom slider (dot lattice to node lattice) and the fitted lattice vectors drawn. Also ACF(corrected post) − ACF(pre) in the pre frame, with the peak-shift arrows and widening rings from the earlier demo.
4. **CCF panels.** Global CCF(pre, corrected post) with zoom, the main peak and the best competing peak marked. Windowed CCF result as |displacement| map or quiver, switchable between *naive* (largest peak in the search box) and *lattice-aware* (wrapped to one cell, then quality-guided unwrapping, as in `exm_analysis.py`).
5. **Metrics panel** (updates live):
   - Global transform from ACF, from tag centres, and truth: scale, anisotropy, stretch direction, rotation.
   - ACF peak height post/pre vs lag (small plot).
   - Global CCF peak vs next-best peak and its ratio (ambiguity margin).
   - Windowed CCF vs truth: rms displacement error, % of windows off by a lattice cell (naive and lattice-aware), local expansion r and rms error.
   - Compute time of the last update.
6. **Controls dock.** Global parameters (λ preset and value, stage rotation, gel jitter, print jitter, noise on/off, PSF), solver (model, ν, plane strain/stress), registration source (tag centres / ACF / truth), CCF settings (window size, step, search radius, naive vs lattice-aware), site list with a property editor, seed.

## Performance and threading

- **Fast tier (while dragging):** target < 150 ms on an M1. Debounce ROI changes (~30 ms). Run computation on a worker thread with latest-request-wins (drop stale jobs, never queue them). The UI thread never blocks.
- **Full tier (on release or "Recompute full"):** target < 5 s. Full field, full windowed CCF, full post ACF.
- Suggested ways to get there (you choose, but justify):
  - The displacement solve on the coarse grid is cheap. Cache the FFT operators.
  - The pre image and its ACF never change when sites move, so cache them.
  - In live mode, render the **corrected post directly in the pre frame** from the mapped island positions, instead of rendering the 4x image and resampling it. All dots share one kernel, so render them by bilinear splatting of centres followed by one FFT convolution with the dot kernel (rect ⊗ PSF), and render dashes and tags as separate small layers. In this frame a rigid dot is 1/λ of its pre size.
  - Restrict the live windowed CCF to a region around the selected site (plus a margin), and update the global CCF and metrics from cached parts where possible.
  - The post ACF in live mode is computed on the visible post region. Full mode does the whole image (zero-padded only by the max lag, as in `exm_analysis.py`).
- Full mode must also offer a **"faithful pipeline"** path: render the real post image, detect ArUco tags with OpenCV, fit the affine from tag centres, resample, then run the CCF. Live mode uses simulated tag detection (true centres plus a small configurable noise).

## Export

- Save / load a scenario (all sites and parameters) as JSON.
- Export the current pre and post images as 16-bit PNG or TIFF, the per-feature truth table (CSV, same columns as the batch run), the metrics as JSON, and a PNG snapshot of the window.
- A command-line entry point that runs a scenario JSON headless and writes the same outputs (useful for batch sweeps).

## Code layout (suggested)

```
exm_explorer/
  frames.py        design <-> image <-> post conversions
  grid.py          load reference_tags.json, build island + rectangle lists
  field.py         eigenstrain sites, Navier and kinematic solvers, truth fields
  render.py        image rendering (exact erf path and fast splat path), noise
  analysis.py      ACF, lattice fit, affine fits, global CCF, windowed CCF,
                   unwrapping, local expansion (port from exm_analysis.py)
  tags.py          ArUco detection
  scenario.py      dataclasses + JSON I/O
  worker.py        compute jobs, latest-wins scheduling
  app.py           Qt main window, docks, ROIs, plots
  cli.py           headless runner
tests/
```

Use Python 3.11+, numpy, scipy, PySide6, pyqtgraph, opencv-contrib-python-headless, pillow, pytest. Provide `pyproject.toml`, a README with install and run steps for Fedora and macOS, and `python -m exm_explorer` to launch.

## Acceptance tests (pytest, must pass)

1. **Frames:** design to image to design round-trips; handedness is −1; all 36 ArUco tags decode with correct ids in both rendered images (exact render path).
2. **Solver, uniform:** a site covering the whole padded domain with eigenstrain ε* gives ∇u ≈ ε* away from the boundary.
3. **Solver, Eshelby:** a sharp-edged circular isotropic site (radius 60 µm, ε* = −0.1, plane strain, ν = 0.3) has uniform interior strain ε₁₁ = ε₂₂ = ε*/(2(1−ν)) within 3%, and the exterior displacement decays as 1/r. Repeat for ν = 0.0 and 0.45.
4. **Solver, anisotropic:** an elliptical site with ε₁ = +0.05, ε₂ = −0.05 produces interior anisotropy > 1 aligned with the site axis (within 2°), and rotating the site rotates the field.
5. **No sites:** ACF scale = λ within 0.1%, tag-affine scale within 0.05%, windowed CCF rms error < 0.3 px, < 0.5% of windows off by a cell.
6. **Regression vs the batch run:** kinematic model, the three `PATCHES` from `exm_sim.py`, same seed and parameters, faithful pipeline. Reproduce `results.json` within tolerance: ACF scale 4.006 ± 0.002, tag scale 3.979 ± 0.002, rotation 3.39° ± 0.02°, lattice-aware windowed CCF rms < 1.2 px and < 2% windows off by a cell, naive > 5% off by a cell, local expansion r > 0.93.
7. **Fast vs faithful:** for the regression scenario, the fast in-pre-frame rendering gives windowed CCF displacements within 0.3 px rms of the faithful pipeline.
8. **Performance:** a benchmark test (skippable in CI) that reports fast-tier and full-tier timings.

## Working style

- Plan first, then build in milestones and stop after each one so I can try it:
  1. grid, frames, field solver + tests 1 to 4
  2. rendering + analysis port + tests 5 to 7
  3. GUI skeleton: sample view, draggable sites, live truth overlays
  4. live ACF and CCF panels + metrics
  5. faithful pipeline, export, CLI, presets, performance pass
- Keep the analysis code free of Qt so the CLI and tests can use it.
- Commit after each milestone with a clear message.
- If something in the reference is ambiguous or looks wrong, ask instead of guessing.
