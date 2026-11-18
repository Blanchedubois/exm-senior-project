# ExM Distortion Explorer

Place local sites of anisotropic or lagging expansion on the real fiducial grid, drag them around, resize, rotate and reshape them, and watch the ACF of the pre image, the ACF of the post image and the pre-vs-post CCF update live, next to the ground truth they should recover.

It extends the batch simulation in `reference/` (`exm_sim.py`, `exm_analysis.py`) and reproduces its results (`reference/results.json`). Everything except the window (`app.py`, `panels.py`, `worker.py`) is plain Python, so the tests and the command-line runner use the same code.

## Install and run

Python 3.11 or newer.

### macOS (Apple Silicon)

Double-click **`Launch ExM Explorer.command`**. The first run creates a Python environment in `~/Library/Application Support/HydrogelMarkerGUI/exm_explorer` (outside iCloud: Qt fails to load when its files are evicted from iCloud) and installs the libraries. It takes a few minutes, once.

Or by hand:

```bash
python3 -m venv ~/.venvs/exm-explorer
```

```bash
~/.venvs/exm-explorer/bin/pip install -e ".[test]"
```

```bash
~/.venvs/exm-explorer/bin/python -m exm_explorer
```

### Fedora 43 (Wayland)

```bash
sudo dnf install python3 python3-pip xcb-util-cursor
```

```bash
python3 -m venv ~/.venvs/exm-explorer && ~/.venvs/exm-explorer/bin/pip install -e ".[test]"
```

```bash
~/.venvs/exm-explorer/bin/python -m exm_explorer
```

Qt picks Wayland by itself. If the window misbehaves (blank, no decorations, dragging stutters), use the X11 path through XWayland instead:

```bash
QT_QPA_PLATFORM=xcb ~/.venvs/exm-explorer/bin/python -m exm_explorer
```

`xcb-util-cursor` is what Qt 6 needs for the xcb platform; without it the xcb plugin refuses to load.

### CachyOS / Arch

```bash
sudo pacman -S python python-pip xcb-util-cursor
```

Then the same `venv` and `pip install -e ".[test]"` steps as Fedora. The `QT_QPA_PLATFORM=xcb` fallback applies here too.

### Open a scenario directly

```bash
python -m exm_explorer my_scenario.json
```

## Using the window

- **Sites.** Double-click empty space to add one. Drag the ellipse to move it, the two square handles change the semi-axes, the round handle rotates it. Delete or Backspace removes the selected site. The side panel holds everything else:
  - "site shape a/b" changes the ellipse's aspect, keeping its area;
  - ε₁, ε₂ are the eigenstrain along and across the eigenstrain angle (which follows φ unless unticked); "lock isotropic" keeps ε₂ = ε₁;
  - "strain anisotropy (1+ε₁)/(1+ε₂)" changes the anisotropy, keeping the area change;
  - edge softness is the tanh edge width as a fraction of the size (0 = sharp); the "gaussian" profile reproduces the batch run's patches.
- **Overlays.** True displacement arrows, true local expansion / anisotropy / rotation, measured local expansion / anisotropy (from the windowed CCF, dot windows only), node grid and tag ids, and **maxima ▲ / minima ▼** of the shown map with a minimum separation and minimum deviation. Click a row in the list to centre the view on it.
- **Panels.** Post (the post image of the visible region only), ACF (pre, post, and corrected-post minus pre with peak-shift arrows and widening rings), CCF (global CCF with the main and best competing peaks; the windowed map naive or lattice-aware, as |displacement|, quiver or error vs truth, with its maxima), Metrics (global transform from ACF, tags and truth; CCF ambiguity margin; windowed errors vs truth; ACF peak height post/pre vs lag; compute times).
- **Two compute tiers.** While dragging, the fast tier analyses the windows around the selected site. On release (or **Recompute full**) the full tier analyses every window and the post ACF of the whole image (up to a 4096 px crop above λ ≈ 5).
- **Run faithful pipeline** renders the real post image, decodes the tags with OpenCV, fits the affine from tag centres, resamples and runs the CCF: the batch run's path. Live mode instead renders the corrected post straight into the pre frame and simulates tag detection (true centres plus noise).
- **Presets menu.** The example, the exm_sim batch run, a no-site control, and the four test-workshop scenarios from the blog. λ presets (TExM 3.3, ExM 4, MAGNIFY 10) are in the λ box.

## Export

- **File › Save scenario / Open scenario**: every site and parameter as JSON.
- **File › Export bundle (PNG or TIFF)**: runs the faithful pipeline if the scenario changed since the last run, then writes `scenario.json`, `pre` and `post` 16-bit images, `features_truth.csv` (same columns as the batch run), `metrics.json` (keys as `results.json`, plus the live metrics) and `window.png`.
- **File › Save window snapshot / Save live metrics.**

## Command line (headless, batch sweeps)

```bash
python -m exm_explorer.cli my_scenario.json --out results/
```

```bash
python -m exm_explorer.cli --preset "exm_sim batch run" --out sweep/ --set imaging.lam=3.3,4,10 --set solver.nu=0.2,0.45
```

Each `--set FIELD=V1,V2` is a dotted field of the scenario (`imaging.lam`, `solver.nu`, `sites.0.eps1`, `analysis.registration`…); several make the full grid, one subfolder per run, with `summary.csv` on top. `--registrations tags,acf,truth` runs the CCF after each; `--format tiff`; `--no-images` keeps only the JSON.

## Tests

```bash
python -m pytest -q
```

About 30 s. The acceptance tests from the brief are in `tests/test_frames.py` (1), `tests/test_solver.py` (2–4) and `tests/test_analysis.py` (5–7); `tests/test_gui.py` drives the window offscreen. Timings (test 8):

```bash
EXM_BENCH=1 python -m pytest -q -s tests/test_benchmark.py
```

Two acceptance tests are scored slightly differently from the brief, as agreed while building: test 5 on windows holding only dots (windows with a tag or dash carry a shape bias in the reference method), and test 7 window by window without noise plus by error statistics with noise (the two paths draw different noise).

## Performance

Measured on an Apple M5 Pro (the brief's targets are for an M1, which was not available to measure):

| | time |
|---|---|
| displacement solve (Navier, 775² grid) | ~6 ms |
| live fast tier (while dragging) | ~120 ms |
| live full tier | ~0.8 s |
| faithful pipeline, λ = 4 | ~4 s |
| faithful pipeline, λ = 10 (16 000 px post image) | ~15 s, ~9 GB of memory |

## Frames

Design frame: µm, origin at the bottom-left of the print, y up. Images: y down, so design → image is a reflection (det = −1); `frames.py` holds every conversion. Every printed feature is a rigid island: only island centres move; islands rotate with the stage only. Registration uses tag centres, never tag corners.

## Layout

```
exm_explorer/
  frames.py     design <-> sample <-> pre / post px, affine fits
  grid.py       reference_tags.json -> islands and rectangles
  field.py      eigenstrain sites, Navier and kinematic solvers, truth maps
  render.py     exact erf renderer, fast in-pre-frame splat renderer, noise
  sim.py        island positions and images (exm_sim's random draw order)
  analysis.py   ACF, lattice fit, global and windowed CCF, unwrapping, local expansion
  spatial.py    correlation length, stretch directions, RMS error vs length, extrema
  tags.py       ArUco detection
  pipeline.py   faithful and fast runs
  live.py       jobs for the live window
  scenario.py   dataclasses, JSON, presets
  export.py     images, truth table, metrics
  worker.py     latest-wins compute threads, faithful run with progress
  panels.py     post / ACF / CCF / metrics panels
  app.py        main window
  cli.py        headless runner
studies/        the spatial-structure test workshop (blog post of 2026-10-30)
```
