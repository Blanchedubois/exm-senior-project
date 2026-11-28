# Quantifying expansion anisotropy in osmotic and tensile expansion microscopy

**Senior project, Department of Physics, Case Western Reserve University.**
Tejasvin Shrikanth, advised by Lydia Kisley and Vignesh Venkataramani.

This repository is the public record of the project: the research proposal, the
code for every piece of the analysis, the lab notebook, a blog of progress, and
the reports and presentations given along the way. Start here, then follow the
links.

| | |
|---|---|
| **Proposal** | [docs/proposal/](docs/proposal/) · [PDF](docs/proposal/research_proposal.pdf) · [plain-language summary](blog/2026-10-30-research-proposal-anisotropy.md) |
| **Blog** | [blog/](blog/README.md), newest post first |
| **Lab notebook** | [lab-notebook/](lab-notebook/README.md), one folder per bench session |
| **Documentation** | [docs/](docs/README.md): presentations, weekly reports, derivations |
| **Code** | [projects/](projects/README.md) (the research), [explorations/](explorations/README.md) (side studies), [archive/](archive/README.md) (superseded) |

## Abstract

Expansion microscopy achieves super-resolution imaging by embedding a biological
specimen in a hydrogel and physically enlarging it, so that features below the
diffraction limit become separable under an ordinary light microscope. Every
measurement made this way is scaled back by a single expansion factor, which
assumes the gel expands isotropically. Two distinct approaches achieve the
expansion: osmotic swelling (as in the MAGNIFY protocol), driven by charge
repulsion and osmotic pressure in water; and tensile expansion (TExM), which
stretches the hydrogel mechanically with a custom device.

This project quantifies and compares the magnitude and spatial structure of
anisotropy in both. Two-photon-polymerised fiducial markers, printed by direct
laser writing on a Nanoscribe, are transferred into the hydrogel at gelation and
provide a reference of known geometry against which local deformation is
measured before and after expansion. Self-identifying ArUco markers let the
correspondence between design and image be established automatically rather
than by manual landmarking. The recovered marker coordinates are compared with
an ideal similarity transform, and the deviations yield a map of local and
large-scale anisotropy, characterised by magnitude, orientation and spatial
correlation and tracked through the course of expansion. Finally, cells are
expanded alongside the markers under different homogenisation conditions to
evaluate how homogenisation influences anisotropy, contrasting the mechanical
fidelity of osmotic swelling with tensile expansion.

## Why it matters

Protocols report 1 to 4 % distortion, but the existing checks (registering
biological structure with a similarity transform, GelMap grids, manually matched
TExM markers) report a single residual number. None says how the distortion is
distributed by direction, by position, or over what length scale it is
correlated, and none has been applied to both osmotic and tensile expansion with
the same reference. A reference of known geometry in the gel, with every marker
carrying its own identity, measures the local deformation field directly.

## Objectives

1. **Printed reference markers in MAGNIFY and TExM hydrogels** (end of fall
   semester). Design and print a self-identifying fluorescent marker pattern,
   transfer it into both hydrogels, and confirm the markers stay anchored and
   fluorescent before, during and after expansion. Acquire expansion series in
   both systems.
2. **Analysis pipeline with quantitative distortion metrics** (spring break).
   Extend the marker-detection pipeline to measure local deformation and
   separate it into anisotropy, inhomogeneity and local warping, establish the
   smallest distortion the method can detect, and compare both techniques across
   expansion factor.
3. **MAGNIFY and TExM with cells** (end of senior year). Expand cells alongside
   the marker pattern in both systems and use the measured deformation fields to
   assess how faithfully each technique preserves nanoscale cellular structure,
   including a direct comparison at a matched expansion factor of about 4.2×. A
   shortened digestion is compared with the standard protocol.

## Methodology

### The marker system

The pattern is printed by two-photon polymerisation in fluorescent resist and
transferred into the hydrogel at gelation. It is a 750 × 750 µm field of 5 × 5
boxes with three tiers of features:

- **ArUco tags** (DICT_4X4_50, 23 µm) at each of the 36 grid nodes. The decoded
  id gives the node, so every box has an identity and a local frame.
- **Dashes** on the box boundaries: the human-readable grid and coarse strain field.
- **Dots** (2.125 µm, 5 µm pitch, 17,825 per field) filling every box. These are
  the measurement tier: each dot is addressed as (node, row, column) from the tag ids.

![Final design: full field, one box, corner detail](projects/aruco-marker-design/designs/1_optimistic/render.png)

![One box of the final design](projects/aruco-marker-design/docs/v2_box_optimistic.png)

Three gated sizes of the same pattern exist (23, 27 and 34 µm tags), chosen by
the measured point-spread function of the microscope. Validated end to end
through a calibrated camera model, the 23 µm design still decodes 4 of 4 tags in
frame at 6× expansion and recovers the expansion factor to 0.02 %:

![End-to-end validation of the final design](projects/aruco-marker-design/final_design/optimistic_one_figure.png)

### The analysis

1. Correct the microscope optics (vignetting, lens distortion, denoise, deskew)
   and per-image contrast.
2. Decode the ArUco tags, fit the design-to-image transform from their centres,
   detect and sub-pixel refine the dots.
3. Filter false positives and tag every surviving point with its design identity.
4. Pair the same points across an expansion series by tag.
5. Fit the local deformation gradient around each point from its neighbours and
   decompose it into rotation and stretch, separating three modes of distortion:
   **anisotropy** (stretch that varies with direction), **inhomogeneity**
   (stretch that varies with position) and **local warping** (what no locally
   uniform stretch explains).
6. Map each mode across the gel and report it against the expected expansion factor.

The same markers, imaging and analysis are applied to MAGNIFY (expansion varied
by ionic strength) and TExM (expansion varied by iris position) so the two can
be compared directly. The detection floor is set first from simulated
deformations of known magnitude and from static control samples.

### Approach

The work is built in verified stages, each one tested on synthetic images with a
known answer before it meets real data. The V1 glyph-marker pipeline was
validated on six real stitched frames at 1.5× to 4.2×. The ArUco design was
sized from the microscope's measured point-spread function and validated through
a camera simulator. The ArUco analysis app is ported from the V1 code one module
at a time, each phase tested against generated dummy frames whose truth is
known. Bench work is recorded in the lab notebook and summarised on the blog,
including the experiments that did not go to plan.

## Status (November 2026)

- Marker design finalised and validated in simulation
  ([aruco-marker-design](projects/aruco-marker-design/)).
- V1 tagger complete; the ArUco tagger is built, with 97 tests passing on dummy
  frames, and awaits the first real print
  ([aruco-reference-tagger](projects/aruco-reference-tagger/)).
- Trained on the lab's Olympus IX83 and built a viewer for its Micro-Manager
  acquisitions ([ix83-viewer](projects/ix83-viewer/),
  [blog post](blog/2026-11-03-learning-the-ix83.md)).
- Two batches of MAGNIFY bead gels made and measured; the nominal 11× gels
  expanded about 1.2 to 2.4×, traced to expanding in PBS rather than water
  ([ix83-bead-analysis](projects/ix83-bead-analysis/),
  [blog](blog/2026-11-17-magnify-second-batch-coverslip-sandwich.md)).
- Two batches of thinner gels from the MAGNIFY fixed tissue kit failed to
  polymerise in any mould, including thick silicone-ring controls, which points
  at degraded kit reagents rather than the mould; waiting on a new cell culture
  kit ([blog](blog/2026-11-27-magnify-gels-did-not-set-solution-not-mould.md)).
- TExM hardware: iris stretcher CAD and nine-channel strain-gauge firmware
  ([texm-iris-stretcher](projects/texm-iris-stretcher/)).

## Repository layout

```
README.md          this page
docs/              proposal, presentations, weekly reports, derivations
blog/              dated progress posts with figures
lab-notebook/      raw bench notes: transcripts, photos, entry records
projects/          the research code, one folder per sub-project
explorations/      side studies and early prototypes
archive/           superseded code kept for the record
```

Microscope TIFF frames, simulator stacks and raw audio are not committed; they
live with the lab's data. See [docs/REORGANISATION_PLAN.md](docs/REORGANISATION_PLAN.md)
for how this repository was assembled.
