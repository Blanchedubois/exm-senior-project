# ArUco Reference Tagger

The analysis app for the ArUco print. It takes a series of microscope images of
one printed marker field at different expansion states, finds every feature
(ArUco tag, dash, dot) with its position, rotation and uncertainty, gives each
feature its design identity, pairs features across the series, and exports
tables from which local distortion and its spatial correlation are measured.
It is a data producer: the one piece of analysis it keeps is a visual check
(overlay, vector field, distortion map) that a series is sane before export.

It is ported, one module at a time, from the V1 glyph tagger in
[`../reference-warp-tagger`](../reference-warp-tagger/). The port plan and one
document per phase are in [docs/](docs/00_PORT_OVERVIEW.md).

## Run

macOS: double-click `Launch ArUco Reference Tagger.command`. It creates a local
Python environment on first run and opens the GUI. Windows: the `.bat` file.
By hand:

```bash
pip install -r requirements.txt
python run.py
```

## Test

The tests use dummy frames rendered by the marker-design simulator, so generate
them first from the repository root:

```bash
python projects/aruco-marker-design/tools/make_dummy_series.py --preset all
```

```bash
python tests/run_all.py
```

## Folders

- `rwtag/`: the headless library. `aruco/` decodes tags and fits the
  design-to-image transform, `refwarp/` warps the design onto the image and
  tags dots, `dotfilter.py`, `pairing.py`, `project.py`, `export.py`.
- `gui/`: the Qt window, one panel per stage.
- `scripts/`: command-line entry points (`find_aruco.py`, `export_project.py`).
- `designs/`: the `reference_tags.json` design files the app can load.
- `tests/`: one file per phase.
