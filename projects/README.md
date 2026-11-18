# Projects

The code the research depends on. Each folder is a self-contained sub-project
with its own README, requirements and tests. Status as of November 2026.

| Project | What it is | Status |
|---|---|---|
| [aruco-marker-design](aruco-marker-design/) | Design of the Nanoscribe ArUco fiducial print: pattern generator, camera simulator, detector prototypes, gating studies against the measured PSF, CAD exports and the final design | Design finalised and validated in simulation |
| [aruco-reference-tagger](aruco-reference-tagger/) | The analysis app for the ArUco print: optics correction, tag decoding, dot detection, filtering, tagging, pairing across an expansion series, error model, cross-image views, export | Built and tested on dummy frames (97 tests); awaits the first real print |
| [reference-warp-tagger](reference-warp-tagger/) | The V1 app for the earlier glyph-numbered print, with the full correct-detect-filter-tag-pair-overlay-field-summary workflow | Complete; validated on six real frames at 1.5× to 4.2×; the ArUco port starts from this code |
| [ix83-viewer](ix83-viewer/) | Desktop viewer for Micro-Manager acquisitions from the Olympus IX83: per-wavelength colour, overlays, channel alignment, contrast, export, analysis | In use; phases 0 to 6 done |
| [ix83-bead-analysis](ix83-bead-analysis/) | Extension of the viewer for the MAGNIFY bead-in-hydrogel experiments: image panels, reference-bead GUI, illumination correction, bead density and expansion estimate | In use for the November 2026 bead gels |
| [texm-iris-stretcher](texm-iris-stretcher/) | Hardware for tensile expansion: iris stretcher CAD, ESP32 firmware and nine-channel NAU7802 strain-gauge readout | Mechanics printed; strain-gauge readout under investigation |

## How they fit together

```
aruco-marker-design  ──design (reference_tags.json, STL)──▶  Nanoscribe print
        │                                                        │
        │ dummy frames (camera simulator)                        │ real frames (IX83)
        ▼                                                        ▼
aruco-reference-tagger ◀──── ported from ──── reference-warp-tagger
        │
        ▼
  distortion metrics (anisotropy, inhomogeneity, local warping)

ix83-viewer / ix83-bead-analysis   look at what the microscope recorded
texm-iris-stretcher                produces the tensile expansion
```

Several `aruco-marker-design` scripts import from `reference-warp-tagger`, and
the `aruco-reference-tagger` tests read dummy frames from
`aruco-marker-design/dummy/`. Keep the three folders side by side.
