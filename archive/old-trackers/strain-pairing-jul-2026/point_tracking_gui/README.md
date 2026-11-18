# Point-Tracking GUI

A staged desktop GUI to load a TIFF of the printed marker grid, correct the optics, and
identify + track every feature (ArUco tags, dots, dashes) with absolute labels and subpixel
positions — the *identify-and-track* half of the expansion-measurement project.

**Status:** five stages implemented (optics correction; ArUco detect + orient-upright; grid
mapping against the reference; dot/dash detection + tagging + export; quality filters). See
**[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)** for the full design — architecture, module
layout, per-stage algorithms, libraries, and milestones.

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # (Stage 1 needs: numpy opencv-contrib-python tifffile scipy PySide6 pyqtgraph)
python run.py                            # launch the GUI
```

Then **Open TIFF…** (e.g. a frame from `../expansion_camera_sim/tiffs/`), and:
- **Stage 1** — drag the vignette / lens-distortion sliders (or **Auto-estimate vignette**) with
  live preview; toggle the straightness grid and before/after to judge the correction.
- **Stage 2** — click **Detect & orient**: tags are decoded, the image is rotated upright, and
  each tag is boxed (green) + centred (amber) + ID-labelled; the panel lists the tag numbers
  and the rotation removed.
- **Stage 3** — the reference grid (`grid_metadata.json`) loads automatically and is shown as a
  schematic; click **Map grid** to fit the reference→image transform, label each tag with its
  ID + (i,j), draw the lattice (amber detected / red predicted-missing nodes), and report the
  fit residual and recovered scale.
- **Stage 4** — click **Detect & track**: trackpy localises every dot (subpixel), each is
  tagged `(box, local_i, local_j)` by Hungarian assignment to the reference, dashes are tagged
  by box edge, centres are marked (amber matched / red missing / orange dash), and **Export**
  writes the feature table to parquet + csv + an annotated PNG.
- **Stage 5** — toggle quality filters and click **Apply filters**: bad dots turn red and are
  marked `status="filtered"` with a reason (never deleted). Filters: **min separation** (discard
  dots closer than a fraction of the ArUco-derived expected pitch), **blob quality** (mass/size
  MAD), **prediction residual**, **neighbour smoothness**, and **border proximity**. Re-tuning
  always restarts from the unfiltered result; **Export filtered** saves the result.

Headless use of the same core:
```python
from gridtrack import io, correct
from gridtrack.types import CorrectionParams
img  = io.load_tiff("frame.tif")
corr = correct.apply(img, CorrectionParams(vig_strength=0.88, vig_power=1.8, k1=-0.05, k2=-0.01))
```

Run the tests (validate correction against the simulator's ground truth):
```bash
python -m pytest tests/ -q
```

## The four stages
1. **Correct optics** — sliders for vignetting + lens distortion (live preview).
2. **Address + orient** — detect ArUco tags, read their IDs, rotate the image upright.
3. **Map grid** — match tags to the `grid_metadata.json` reference (shown alongside), label
   IDs on the image, mark tag positions, predict missing nodes.
4. **Track points** — detect + subpixel-localise every dot/dash, tag each by its absolute
   `(box, local_i, local_j)` via the per-box homography, export the feature table.

## Key design rule
All image processing lives in a **headless core package `gridtrack/`** (no GUI imports); the
`app/` layer only calls it and draws overlays. So the same processing is reusable in other
GUIs and batch scripts. Validation uses the labelled synthetic frames from
`../expansion_camera_sim/` as ground truth.
