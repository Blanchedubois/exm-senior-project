# Reorganisation plan: one public showcase repo

Status: proposal (Phase 1). Nothing has been moved yet.

## Recommendation in one paragraph

Use **one public repository** (a "monorepo"), not a GitHub organisation of
small repos and not git submodules. A professor or a visitor should land on
one README, read the abstract, and click through to the proposal, the blog,
the lab notebook and each piece of code without leaving the page. Submodules
("sub repos") show up on GitHub as empty grey folders that need an extra
clone step, and separate repos spread the story across many pages with no
shared history. Everything you want to show is small enough to live in one
repo (about 50 MB of code, docs and figures once the raw audio and duplicate
STLs are handled), and `git mv` keeps the full history of every file.

Make it a **new** public repo (suggested name: `expansion-microscopy-senior-project`,
or shorter `exm-senior-project`) and keep `aruco-reference-tagger` as the frozen
private original. Reason: the current repo name describes one sub-project, and a
fresh repo lets us decide deliberately what goes public instead of inheriting
everything in the old history.

## Proposed layout

```
exm-senior-project/
├── README.md                  Senior project introduction: abstract, overview,
│                              methodology and approach, status, links to everything below
├── docs/
│   ├── proposal/              <- proposal/ (LaTeX source, PDF, figures)
│   ├── presentations/         <- Subgroup presentations (PDF exports of the pptx)
│   ├── weekly-reports/        <- Weekly reports (PDF)
│   └── reports/               <- pipeline_derivation.pdf, Iris maths PDF, etc.
├── blog/                      <- blog/ (posts + images), unchanged
├── lab-notebook/              <- blog/lab-notebooks/ (one folder per session:
│                                 notes, transcripts, images; raw audio optional)
├── projects/                  Research progression: the work the proposal depends on
│   ├── README.md              table of every project, its status and one-line purpose
│   ├── aruco-marker-design/       <- ArUco_Tracker_V2 (Nanoscribe pattern, sim, gating, CAD)
│   ├── aruco-reference-tagger/    <- ArUco_Reference_Tagger (the analysis app, active)
│   ├── reference-warp-tagger/     <- Reference_Warp_Tagger (V1 glyph app, complete)
│   ├── ix83-viewer/               <- Code/IX83 Analysis Pipeline (Micro-Manager viewer)
│   ├── ix83-bead-analysis/        <- Code/IX83 Bead Analysis (Magnify bead experiment)
│   └── texm-iris-stretcher/       <- Code/Strain Gauges + IrisModule1.0 + CAD (TExM hardware)
├── explorations/              Side studies: useful, but not on the critical path
│   ├── exm-distortion-explorer/   <- ArUco_Reference_Tagger/exm_explorer_prompt (CCA/ACF study)
│   ├── hydrogel-marker-analysis/  <- hydrogel_marker_analysis
│   ├── expansion-camera-sim/      <- expansion_camera_sim
│   ├── point-tracking-gui/        <- point_tracking_gui
│   └── expansion-field-gui/       <- expansion_field_gui
└── archive/                   Superseded code kept for the record
    ├── old-trackers/              <- Old_Tracker_StraiN_Pairing, Old_Trackers_Detection
    └── iris-stretcher-versions/   <- Code/ARCHIVE (Iris 1.0 to 6.0, MATLAB tests)
```

The three code tiers answer "is this research or an exploration": `projects/`
is what the proposal builds on, `explorations/` is what you tried on the side,
`archive/` is what was replaced. A visitor sees the distinction from the folder
name alone, and the projects README states it for each entry.

## What stays out of the public repo

- Raw microscope data (`*.tif`, the 16 GB Experimentation folder), already ignored.
- `Important Documentation/` (visa, I-9, employment letters): personal, never in git.
- IX83 Bead Analysis `outputs/` (140 MB of derived images); the code and the
  experiment JSON go in, outputs are regenerated.
- Raw lab-notebook audio (`page.m4a`, 47 MB) and transcript drafts: decision
  below.
- Local-machine paths in a few run logs and `.rwsession.json` sidecars
  (`~/...`). Harmless, but we strip them.
- The three institutional emails in `proposal/doc_body.tex` are the authors'
  and belong on a proposal; they stay unless you prefer otherwise.

## Decisions I need from you

1. **Repo name**: `expansion-microscopy-senior-project` (clear) or `exm-senior-project` (short).
2. **Lab-notebook audio**: keep the raw `.m4a` in the public repo (47 MB today,
   growing every session), or keep only notes, transcripts and images and leave
   audio on iCloud? I recommend dropping the audio.
3. **Presentations**: commit the `.pptx` (82 MB) or PDF exports only? I recommend PDF.
4. **Weekly reports**: all 20 PDFs (38 MB), or only the 2026 ones for this project?
5. **TExM hardware** (Iris stretcher, strain gauges, CAD): include as a project,
   or is that a separate effort you would rather keep out?

## Phases

| Phase | What happens | Ends with |
|---|---|---|
| 1 (this turn) | Study repo, clone to `~/projects/exm-senior-project`, propose structure | Your sign-off on layout and the five decisions |
| 2 | `git mv` into the new layout, copy in the sibling folders, fix every relative link in READMEs and blog posts, update `.gitignore`, strip local paths | Repo builds, links checked, tests still pass; one commit per move group |
| 3 | Top-level README (abstract, overview, methodology, approach, links), `projects/README.md` status table, a README per project and exploration that lacks one | You review the text |
| 4 | Create the public GitHub repo, push, set description and topics, confirm the old private repo is left as is | Public URL to send to your professor |
