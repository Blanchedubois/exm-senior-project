# Consolidated Findings — Hydrogel Warpage Marker System

## 1. Design
Tile the field into boxes; a 6×6 ArUco tag at each box corner encodes the box address
(ID = node coordinate); each box interior holds a fine dot grid (default 1.5 µm pitch,
~225 dots/box) for dense local-distortion sampling; dashed per-box boundary. The ArUco IDs
solve correspondence globally, so the pattern is trackable through 2–5× expansion from a
single before/after image (no time-lapse required). Closest published analog: GelMap
(Nature Methods 2023) — a fluorescent reference grid in expansion-microscopy gels,
~0.07 µm residual at 10 µm spacing, 4–10× expansion.

Sizing (6×6 dict = 8 modules): size the tag to decode in the *unexpanded* reference image.
At ~100 nm/px effective pixel size, ~3.5–5 µm tags and ~5 µm box/checker pitch are the sweet
spot. The one input needed to finalize numbers is the effective pixel size at the sample.

## 2. Marker robustness under deformation (simulations)

**Expansion + rotation (simulate_expansion.py).** Uniform expansion (to 5×) and whole-grid
rotation (to 90°) are a similarity transform → ArUco is invariant → 16/16 tags decode. Each
tag decodes from its own local pixels, indifferent to growing gaps between tags.

**Non-uniform warp (co-swelling case).** Fine for gentle warp; a tag's code only corrupts
when the warp *wavelength* falls below ~2–3× the marker size. Rule: keep the marker < ~1/3
of the shortest distortion wavelength (huge margin for smooth gel swelling).

**Rigid tag must stay ONE piece.**
- Naive "every module separate" (simulate_module_spread.py): the solid ArUco border
  fragments once gaps open → fails by λ≈1.15. WRONG physical model but instructive.
- Conjoined model (simulate_conjoined_spread.py): edge-touching black stays conjoined and
  the border ring never fragments → tag stays *locatable* at any λ; but genuinely separate
  interior pieces drift and the ID is lost above ~λ1.2 for multi-piece IDs.

## 3. Fixes that make it robust

**Fix 1 — connected IDs (conjoined_ids.json).** Of 1000 IDs in DICT_6X6_1000:
533 are single 4-connected (already solid); 954 are single 8-connected (one piece once
strutted). Use IDs from the 954 pool.

**Fix 2 — smooth diagonal struts (strut_prominence.py).** A thin elliptical neck along the
black diagonal at each corner pinch ties the tag into one rigid piece. It sits in ArUco's
ignored corner-sampling margin, so the decoded code is unchanged (verified on worst-case
ID 544: 6 pieces → 1, still decodes). Prominence plot: decoding holds to ~0.9 module wide
(~0.68 µm); the binding limit is Nanoscribe's ~0.2 µm minimum feature, not recognition.
Recommended neck ~0.2–0.25 µm — thin, printable, ~3× headroom below the recognition ceiling,
and mechanically a real bridge (a rounded fillet distributes stress a sharp pinch would not).

With struts, worst-case ID 544 (which failed by λ1.2 unstrutted) decodes at every λ.

## 4. Optical blur / low resolution (blur_resolution.py, multi_marker_test.py)
Gaussian blur models the microscope PSF. Tags decode until σ ≈ 0.3–0.5 of a module.
Design rule: keep one module ≥ ~2.5× the PSF σ (tag ≥ ~8× optical FWHM). A 6 µm tag
tolerates FWHM up to ~0.5 µm → confocal (0.2–0.3 µm) with 2–3× margin, most widefield OK.
Across 250 different curated tags: all decode sharp; blur threshold min 0.30 / median 0.50 /
max 0.70 module; zero weak IDs. Expansion only makes it easier (modules grow vs a fixed PSF),
so the worst case is always the pre-expansion reference image. Levers if resolution is worse
or the tag smaller: enlarge the tag, or use a lower-bit dictionary (4×4 → bigger modules,
fewer IDs).

## 5. End-to-end measurement (rigid_spread_field.png, conjoined_distortion_map.png)
From a conjoined grid expanded 3× + rotated + locally bulged: all 16 markers decode, the
displacement/warpage field is recovered (marker-center localization ~100 nm), and per-box
areal expansion J = det F comes out 8.7–10.2 against the uniform expectation of 9 (higher
where the bulge was imposed).

## 6. Fabrication realizations on the gel (design doc §5)
A rigid resin prints a rigid tag; three ways to realize the pattern on a deforming gel:
(A) discrete rigid coded islands + fine dots — prototype first;
(B) co-swelling hydrogel resist — highest fidelity;
(C) label-only photo-activation — lowest mechanical perturbation.
Interior DOTS may separate (each tracked independently); a tag's black may not.

## 7. Open items / next steps
- Confirm effective pixel size to finalize tag/box/pitch numbers.
- Confirm gel chemistry / expansion mechanism (sets feasibility of co-swelling vs label-only).
- Consolidate the ID-filter + smooth struts + PSF tag-size check into generate_pattern.py.
- Build the before/after analysis pipeline (decode boxes → match dots by ID →
  displacement/strain/warpage field) on real microscope images.

## References
GelMap (Nat. Methods 2023); Expansion Microscopy (Science 2015); OpenCV ArUco/ChArUco;
AprilTag; µCodes (Small 2025); 3D-Aligner (Comms Bio 2024); 2PP soft/4D printing
(Laser Photonics Rev. 2021, Adv. Funct. Mater. 2023).
