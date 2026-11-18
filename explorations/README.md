# Explorations

Side studies and early prototypes. They informed the research but are not on
its critical path, and some have been superseded by the code in
[projects/](../projects/). Each keeps its own README.

| Exploration | What it is | When | Where it led |
|---|---|---|---|
| [hydrogel-marker-analysis](hydrogel-marker-analysis/) | First design study of an ArUco-plus-dot-grid marker: pattern generator and simulations of expansion, rotation, warp, rigid islands, struts and blur | July 2026 | The three-tier design in `aruco-marker-design` |
| [expansion-camera-sim](expansion-camera-sim/) | Simulated microscope images of the marker grid under gradual expansion through a fixed field of view, with degradation levels | July to September 2026 | Synthetic truth for the early GUIs; replaced by the simulator in `aruco-marker-design/sim` |
| [point-tracking-gui](point-tracking-gui/) | First staged GUI: optics correction, ArUco detection, grid mapping, dot and dash tracking, quality filters | July 2026 | Rebuilt as `reference-warp-tagger` |
| [expansion-field-gui](expansion-field-gui/) | Multi-image GUI that pairs markers across an expansion series and shows the displacement and strain field | July 2026 | Its pairing and field tabs became tabs 5 to 8 of `reference-warp-tagger` |
| [exm-distortion-explorer](exm-distortion-explorer/) | Interactive study of whether spatial statistics (autocorrelation, cross-correlation) can detect sites of anisotropic or lagging expansion; simulated images only | October 2026 | A test workshop; see the [blog post](../blog/2026-10-30-test-workshop-spatial-structure.md). Results are about detectability, not about real gels |

`point-tracking-gui` and `expansion-field-gui` share a virtual environment: the
field GUI's launcher expects `../point-tracking-gui/.venv`.
