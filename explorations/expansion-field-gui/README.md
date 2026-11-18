# Expansion-Field GUI

A multi-image GUI that loads an **initial** image plus a **series of expansion images** of the
same printed pattern, runs the **same five tracking stages** on every image (reusing the
`gridtrack` core from `../point-tracking-gui`), and then **pairs the initial markers to each
expansion's markers by their tags** to produce the **expansion displacement vector field**.

**Status:** all phases implemented (P0–P6). Project scaffold + reuse of `gridtrack`; batch
per-image stages 1–5 → per-stage CSVs; **pairing** initial↔each expansion → displacement-field
CSVs; **strain** (`F`, `J = det F`, principal strains); **field view** with magnitude/J heatmaps
+ quiver + hover; and polish (headless CLI, session save/load, threaded run). See
**[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)** for the full design.

### Headless batch (CLI)
```bash
../point-tracking-gui/.venv/bin/python run_batch.py \
  --initial init.tif --expansions e2.tif e3.tif --out OUT \
  --vig-strength 0.88 --vig-power 1.8 --k1 -0.05 --k2 -0.01
```

## Run

```bash
# reuses the deps already installed for ../point-tracking-gui
../point-tracking-gui/.venv/bin/python run.py     # launch the GUI
../point-tracking-gui/.venv/bin/python -m pytest tests/ -q
```

In the GUI: **Add initial image**, **Add expansion images**, **Set output dir**, set the shared
optics correction, then **Run all** → per-stage CSVs appear under `<out>/<image_name>/`. Switch
to the **Pairing** tab → **Run pairing** to write the displacement-field CSVs under
`<out>/pairing/` and view the quiver (full / residual, adjustable arrow scale) in the **Field**
tab.

Headless pairing:
```python
pr.process_all(); pr.pair_all()          # writes pairing/pairing_<name>_vs_initial.csv + summary
pr.pairings[exp_path].lambda_rel         # recovered relative expansion factor
```

Headless use:
```python
from fieldkit.project import ExpansionProject
from gridtrack.types import CorrectionParams
pr = ExpansionProject(initial_path="init.tif", expansion_paths=["e2.tif", "e3.tif"],
                      out_dir="out", correction=CorrectionParams(vig_strength=0.88, k1=-0.05))
pr.process_all()          # stages 1-5 on every image + CSVs
```

## What it does
1. Add an initial image + several expansion images (same pattern, same `grid_metadata.json`).
2. Set the shared Stage-1 optics correction once; batch-run stages 2–5 on every image.
3. **Pair** each expansion image to the initial by tag (ArUco `aruco_id`; dots `(box,i,j)`) and
   compute, per shared marker, **both** the full displacement (shows the expansion) **and** the
   residual warpage (mean expansion removed), in **both µm and pixels**.
4. Visualise the vector field (quiver, full/residual toggle) and read off the recovered relative
   expansion factor per image.

## Data out (all CSV)
- Per image: `stage1_correction.csv`, `stage2_tags.csv`, `stage3_nodes.csv`,
  `stage4_features.csv`, `stage5_features_filtered.csv`, `markers.csv`.
- Per expansion: `pairing/pairing_<name>_vs_initial.csv` (the displacement field) +
  `pairing/strain_<name>_vs_initial.csv` (F, J, principal strains) +
  `pairing/pairing_summary.csv` (λ, rotation, RMS, counts).

## Reuse
The per-image processing is the exact five stages already built and validated in
`../point-tracking-gui/gridtrack/` — this project imports that core and adds only multi-image
orchestration (`fieldkit`) and the pairing/field GUI. Correspondence is a **table join on the
tag** because every feature already carries an absolute address.
