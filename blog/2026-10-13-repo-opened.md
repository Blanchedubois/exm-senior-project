# Repo opened, port of the V1 tagger begins

*2026-10-13*

This repository now holds the three pieces of the marker-tracking work in one place: the working V1 Reference-Warp Tagger for the glyph-numbered print, the ArUco Tracker V2 design and simulation work, and an empty `ArUco_Reference_Tagger/` folder where the V2 analysis app will be built.

## Where things stand

The V1 app is complete and validated on six real stitched frames from 1.5× to 4.2×, with all six accepted and a warp residual of about 1.3 px. Its weakness is registration: box numbers are read by a glyph classifier that struggles on dim high-expansion frames, so three of the six frames needed a geometric rescue from a lower frame.

The V2 print replaces the printed digits with ArUco tags at every grid node. The design is fixed at 23 µm tags, 2.125 µm dots on a 5 µm pitch, 17,825 dots per 750 µm field, and has been tested end to end through a calibrated camera model. A headless ArUco detector and series driver already exist inside the V1 code and pass their tests against the simulator.

## Next

Port the V1 app into `ArUco_Reference_Tagger/` one module at a time, starting with the detector-agnostic core (types, optics correction, image IO), then swapping the glyph detection stage for the ArUco one and removing the box-numbering rescue that ids make unnecessary.
