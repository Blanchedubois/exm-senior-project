# Marker System for Mapping Local Warpage of an Expanding Hydrogel

**A two-photon-printed grid of ArUco-coded boxes, each filled with a fine checkerboard, for measuring the local distortion of a hydrogel as a displacement/strain vector field**

Design document — Summer Research Project · **Rev C (coded-boxes + fine interior checkerboard)** · 2026-07-15

---

## 0. Scope & assumptions

| Parameter | Value assumed |
|---|---|
| Length scale / imaging | Microscope, µm–mm field of view (confocal or widefield) |
| Expansion ratio | Large, **≈2–5×** linear (areal ≈4–25×, volumetric ≈8–125×) |
| Fabrication | **Nanoscribe** two-photon polymerization (2PP / direct laser writing) |
| Marker architecture | **ArUco tags at box corners (address) + fine checkerboard inside each box (measurement)** |
| Output | Local distortion as a **vector field** `u(x)` — in-plane + out-of-plane **warpage** `w(x)`, plus strain/expansion maps |
| Deliverable | Design + method |

> **One input needed to finalize numbers:** your **effective pixel size at the sample** (camera pixel ÷ total magnification, or the confocal pixel size). Tables below are worked for 50 / 100 / 160 / 325 nm/px — tell me your row and I'll lock the geometry.

---

## 1. The architecture (your design)

Tile the field into **boxes** on a regular grid. Then two tiers, separated by scale:

- **Address tier — ArUco tags at the box corners.** A small ArUco marker sits at each grid node (box corner). Its unique, error-corrected ID encodes the node's absolute coordinate, so any box is named by its four corner IDs ("box number"). These are sparse and can be made large enough to decode reliably.
- **Measurement tier — a fine checkerboard inside each box.** The box interior is filled with a dense checkerboard whose corners are the high-precision measured material points. Pitch is set only by the distortion resolution you want (and the fab/optics floor), *not* by having to fit a tag in every square.

**Why this is better than interleaved ChArUco.** In a standard ChArUco board the ArUco tags live in every white square, so decode-robustness (which wants big tags) fights sampling density (which wants small squares) — the pixel-starvation tension from Rev B. Your design **breaks that coupling**: the tags are large and sparse (robust addressing), while the checkerboard is as fine as fabrication and optics allow (dense measurement). You get both.

**The deeper elegance — correspondence stays a *local* problem.** The ArUco boxes partition the field into individually-named cells. To identify any fine corner you only ever have to (i) read which box it's in — solved instantly by the box's ArUco IDs, robust to arbitrarily large *global* displacement — and then (ii) index it within that box by counting from a box corner, which is a tiny, unambiguous local problem because a box only contains a handful of corners and local deformation is smooth. You never have to track a fine corner across a big, ambiguous jump. That is exactly what makes this survive 2–5× expansion where a plain checkerboard (identical corners everywhere) or a continuity tracker would get lost.

Each fine corner therefore gets a **global address `(nodeX, nodeY, i, j)`** = (which box, local row, local col), stable before→after with no time-lapse required.

Precedent: **GelMap** (Nature Methods 2023) embeds a fluorescent reference grid in expansion-microscopy gels and maps deformation by registration (~0.07 µm residual at 10 µm spacing, 4–10× expansion). Your scheme is a deterministic, self-addressing, corner-accurate version.

---

## 2. Why this beats the alternatives

| Approach | Correspondence at 2–5× | Sampling density | Position precision |
|---|---|---|---|
| Subset DIC | breaks at large finite strain (needs incremental) | dense | good on speckle |
| Plain dot grid + VFX tracker | only by time-lapse continuity; identical dots slip | medium | subpixel centroid |
| Interleaved ChArUco | unique IDs ✔ | **limited** — tag in every square | checkerboard corner |
| **Coded boxes + fine checkerboard (this)** | unique IDs ✔, and **localized to each box** | **dense** — free-running fine grid | checkerboard corner (best) |

Keep DIC and a Blender continuity track as optional independent cross-checks (§8), not as the primary method.

---

## 3. Geometry — three lengths to choose

1. **ArUco tag size `s_m`** — set purely by decoding (see §4). Because tags are sparse (only at nodes) they can be generous without costing measurement density.
2. **Box size `B₀`** (node spacing, undeformed) — choose so that (a) after expansion at least ~2–3 boxes still span your field of view, and (b) a tag plus a quiet border fits at each corner without touching the fine checkerboard. Typical `B₀ ≈ 20–40 µm`.
3. **Fine checkerboard pitch `p_fine`** — your distortion resolution. Bounded below by corner support (~a few px per square) and the 2PP feature floor (~0.5–1 µm square). Typical `p_fine ≈ 2–5 µm`.

Corners per box ≈ `(B₀/p_fine − 1)²`. Example: `B₀ = 30 µm`, `p_fine = 3 µm` → ~9×9 ≈ **81 measured corners per box**. Very dense.

**Node coding.** Put one ArUco tag at each node and set its ID = a function of its integer node coordinates (e.g. `ID = nodeY·Ncols + nodeX`), so reading any single tag gives an absolute position; a box is then defined by its four corner node IDs. Interior nodes are shared by four boxes — efficient with IDs. `DICT_4X4_1000` covers a 31×31 node grid; use `_5X5_1000`/larger dicts for bigger fields.

**Quiet zone.** ArUco detection needs a clear ~1-module border. Leave a small blank margin between each corner tag and the start of the fine checkerboard so the two patterns don't corrupt each other's detection (or separate them by channel — see §6).

---

## 4. Sizing math

**ArUco tag (decode floor).** A 4×4-dict tag spans `N+2 = 6` modules. Reliable decode wants several px/module: aggressive ≈3 px/module (18 px tag), safe ≈6 px/module (36 px tag). Fabrication floor: module ≥ ~0.4 µm (2PP) → tag ≥ ~2.4 µm. **Size the tag to decode in the *unexpanded reference* image** (its smallest state if rigid; co-swelling tags only grow).

| Effective pixel size | Safe ArUco tag (6 px/mod) | Fine pitch `p_fine` floor* | Comment |
|---|---|---|---|
| **50 nm/px** | 1.8 µm | ~1.5–2 µm | tag near 2PP fab floor; fine grid excellent |
| **100 nm/px** | 3.6 µm | ~2–3 µm | **sweet spot** |
| **160 nm/px** | 5.8 µm | ~3–4 µm | robust addressing; still dense fine grid |
| **325 nm/px** | 11.7 µm | ~5–7 µm | tags large → use big boxes, or **AprilTag** (decodes from fewer px) |

*`p_fine` floor ≈ max(4 px, ~0.6 µm fab feature) per checkerboard square, times ~1 (a square). The point: **fine pitch is limited by optics/fab, no longer by the tag** — that's the win of separating the tiers.

Worked target at ~100 nm/px: **ArUco ≈ 3.5 µm at nodes, `B₀ ≈ 30 µm`, `p_fine ≈ 3 µm`** → ~81 corners/box, boxes ~120 µm after 4× so several fit the FOV.

---

## 5. Make-or-break: the pattern on a *deforming* gel

A rigid sheet measures nothing, and standard 2PP resist (IP-Dip/IP-S) is rigid. Three realizations, same as before but now note the tier interaction:

**A — Discrete rigid coded islands + co-anchored fine features.** Print each ArUco tag and each fine-checkerboard corner as small rigid tiles anchored pointwise, bare gel between them. Rock-solid decoding and detection; the gel deforms in the gaps. Cost: strain shielding under each tile (keep volume fraction ≲1–2%). Best first prototype. *Caveat:* mixing rigid tags with a rigid fine grid is fine mechanically, but a fully-tiled rigid checkerboard would over-constrain the gel — so print the fine tier as discrete corner marks (crosses/saddles), not solid filled squares.

**B — Co-swelling sheet.** Print everything from a swellable hydrogel 2PP resist (PEGDA / poly(amino acid) / responsive 4D formulations) tuned to the gel's swelling, with fluorescent/non-fluorescent contrast. The whole pattern grows *with* the gel; uniform expansion just scales it and **deviation from uniform scaling = warpage**. Highest fidelity and most literal. Cost: matched swelling, maintained contrast, tags small vs local distortion wavelength.

**C — Label-only.** 2PP photo-activation of a fluorophore on the native network (à la GelMap uncaged rhodamine); minimal mechanical footprint, hardest chemistry.

All need a **copolymerizable anchoring handle** so features move with the network under the 2–5× stretch. Recommendation: prototype **A**, upgrade to **B/C** for fidelity.

---

## 6. Fabrication with Nanoscribe

- **Contrast:** dope resist with a fluorophore / exploit autofluorescence / post-stain (rigid), copolymerizable dye (co-swelling), or uncageable dye (label-only). Both tiers need clean two-level contrast.
- **Two-channel trick (recommended if feasible):** print the ArUco tags and the fine checkerboard in **different fluorophores/channels**. Detection then fully decouples — decode tags in one channel, find checkerboard corners in the other — so a fine corner can sit right next to a tag with zero cross-interference, and you can drop the quiet-zone margin. 2PP two-material writing makes this practical.
- **Datums:** print substrate corner crosses / labelled origin (GelMap-style 200–400 µm nav squares) so pre/post frames tie together independent of the gel.
- **Workflow:** parametrize (box grid, node-ID map, tag size, fine pitch, quiet zone, datums) → print at low dose → gentle develop → record as-printed reference (also known by CAD).

---

## 7. Imaging

- **Modality:** confocal / light-sheet fluorescence for z-resolved corners → 3D warpage; widefield for 2D/thin.
- **States:** reference (as-printed) + one or more expanded; a **time-lapse** is optional here (correspondence doesn't need it) but useful to watch warpage develop and as a backup track.
- **Sampling:** ≥ ~6 px per ArUco module for safe decode; oversample the fine checkerboard for corner precision; z-step ≤ ~½ axial PSF.
- **Datum imaging** each acquisition to remove stage drift / re-mount error.

---

## 8. Analysis pipeline (the method)

Because tags are *not* in every square, the stock ChArUco board detector doesn't apply — use a **two-stage custom detection**:

**Step 1 — Address (ArUco).** `cv2.aruco.detectMarkers` → node IDs + tag corners. Decode each node's absolute coordinate; group nodes into boxes (each box = its 4 corner IDs). This also gives a coarse per-box quad/homography frame.

**Step 2 — Measure (fine checkerboard, per box).** Within each box ROI (bounded by its 4 node tags), detect the fine corners — `cv2.findChessboardCornersSB` (robust, handles the known `kx×ky` interior) or a saddle/Förstner corner detector — then refine with `cornerSubPix` (~0.05–0.1 px). If using the two-channel trick, do this in the checkerboard channel.

**Step 3 — Index & correspond.** Order each box's detected fine corners by `(i,j)` from the box origin (the coarse quad tells you the ordering). Global ID `(nodeX,nodeY,i,j)` → correspondence between reference and expanded is by ID, no time-lapse needed.

**Step 4 — De-expand.** Least-squares similarity/affine reference→expanded on all matched corners; mean linear term = global expansion `λ`; residual = distortion field.

**Step 5 — Field.** `u(Xᵢ) = xᵢ(expanded) − Xᵢ(reference)`; `w = u_z`. Interpolate for display; keep raw vectors for strain.

**Step 6 — Strain.** Per corner, least-squares `dx = F·dX` over neighbours → `F`, `E = ½(FᵀF − I)`, `J = det F` (local areal/volumetric expansion), curvature from ∇w.

**Step 7 — Visualize & quantify uncertainty.** Quiver of `u`; heatmaps of `J`, principal strain, `w`; 3D warped surface (PyVista). Propagate per-corner σ into `u`,`F`,`J`; bootstrap.

**Cross-checks:** incremental µDIC/DICe on a time-lapse; thin-plate-spline registration (SimpleElastix / bewersdorflab `expansion-distortion-analysis`) on the same corners; Blender continuity track as backup ID.

---

## 9. Validation & error budget

1. **Rigid-translation test** — known stage move → uniform `u`; scatter = noise floor (~corner precision).
2. **Uniform-swell test** — bare/homogeneous region → `J ≈ λ^dim`; residuals clustered at markers reveal strain shielding (§5-A).
3. **CAD self-consistency** — reference corners vs printed design → separates print error from deformation.
4. **Method agreement** — box-checkerboard vs TPS vs incremental DIC within error bars.

Budget: corner localization ~0.05–0.1 px (~5–16 nm at 100–160 nm/px); correspondence error ≈ 0 when node IDs decode; strain noise ≈ localization ÷ neighbour baseline (finer pitch = better-sampled field, noisier per-pair; GelMap residuals saturate ~15–25 µm measurement lengths). Expect sub-µm residuals.

---

## 10. Concrete starting recipe (~100 nm/px; adjust per §4)

- **Pattern:** box grid `B₀ ≈ 30 µm`; **ArUco `DICT_4X4_1000`, ~3.5 µm tag at each node**, ID = node coordinate; **fine checkerboard `p_fine ≈ 3 µm`** inside each box (~81 corners/box); ~4 µm quiet border around tags (or two-channel). 300 µm datums + labelled origin.
- **Realization:** Option A — discrete rigid coded islands (tags + fine corner crosses), fluorophore-doped IP, copolymerizable anchor, tile volume-fraction ≲1–2%.
- **Imaging:** confocal, reference + expanded state(s) (add a time-lapse if convenient).
- **Pipeline:** `cv2.aruco` node decode → per-box `findChessboardCornersSB` + `cornerSubPix` → index `(nodeX,nodeY,i,j)` → affine de-expansion (λ) → per-corner `F,E,J,w` → quiver + `J`/`w` heatmaps, with rigid-translation & uniform-swell controls.
- **Cross-check:** incremental µDIC; Blender continuity backup.

Iterate: perturbation → co-swelling (B) or label-only (C); finer field → drop `p_fine` toward the fab floor; pixel-starved → AprilTag nodes + bigger boxes; large area → tile boxes and stitch (the node IDs make stitching trivial).

---

## 11. Open questions to lock before printing

1. **Effective pixel size** (finalizes §4).
2. **Gel chemistry & expansion mechanism** (solvent / ExM polyelectrolyte / thermoresponsive) → feasibility of B/C.
3. **2D surface vs 3D** embedded box lattice.
4. **One fluorophore vs two-channel** (tags vs checkerboard).
5. **Reversibility** (cyclic favours anchored, co-swelling).
6. **FOV vs resolution / tiling.**

---

## References

- GelMap. Nature Methods 2023. https://www.nature.com/articles/s41592-023-02001-y · preprint https://www.biorxiv.org/content/10.1101/2022.12.21.521394v1.full
- Expansion Microscopy. Science 2015. https://www.science.org/doi/10.1126/science.1260088
- OpenCV ArUco / ChArUco / `findChessboardCornersSB`. https://docs.opencv.org/4.x/da/d13/tutorial_aruco_calibration.html
- AprilTag (robust small-marker fiducials). https://april.eecs.umich.edu/software/apriltag
- µCodes: universal grid platform for microscale mapping. Small 2025. https://onlinelibrary.wiley.com/doi/full/10.1002/smll.202506183
- 3D-Aligner (ExM distortion correction). Communications Biology 2024. https://www.nature.com/articles/s42003-024-07035-2
- Two-Photon Laser Writing of Soft Responsive Polymers. Laser & Photonics Reviews 2021. https://onlinelibrary.wiley.com/doi/full/10.1002/lpor.202100090
- Two-Photon Polymerization of Sugar-Responsive 4D Microstructures. Adv. Funct. Mater. 2023. https://advanced.onlinelibrary.wiley.com/doi/full/10.1002/adfm.202213947
- Deformation Gradient by Particle Tracking (quantified error). Experimental Mechanics 2023. https://link.springer.com/article/10.1007/s11340-023-00981-8
- TrackPy. http://soft-matter.github.io/trackpy/ · Bewersdorf Lab expansion-distortion-analysis. https://github.com/bewersdorflab/expansion-distortion-analysis
