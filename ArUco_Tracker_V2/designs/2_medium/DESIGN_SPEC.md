# Medium — design specification

*Spacing workshop, design 2 of 3. Written 2026-09-29 by
`tools/write_design_specs.py` from the files in this folder; every number below is read from
`spec_sheet.json`, `verify.json` or `printability.json` (sources in §10).*

**What it is:** the intermediate pattern. Recognised across the blur measured on the microscope today, without margin above it.

## 1. At a glance

| | this design | reference print |
|---|---|---|
| dot | **2.125 µm square, 2 µm tall** | 2.125 µm |
| **dot spacing, centre to centre** | **6 µm** | 8.0 µm |
| gap between neighbouring dots | 3.875 µm | 5.875 µm |
| **dots** | **11,700** (1.82 × the reference) | 6,420 |
| ArUco tags | 36, 23 µm, `DICT_4X4_50` | (printed digits) |
| dashes | 480, 8.125 × 2.125 µm | 600 |
| envelope | 750 × 750 × 2 µm | same |
| areal fill | 13.6 % | 13.2 % |
| largest blur at which it is fully recognised | **3.1 µm** measured · 2.69 µm by the design rule | — |
| write time (laser scan length) | 1.03 × the reference | 1 |

The three designs of this workshop differ **only in the dot spacing**. Tags, their positions and
ids, and the dashes are identical in all three and in the spectrum print.

## 2. Geometry

All dimensions in micrometres, in the **design frame**: origin at the bottom-left corner of the
print, x to the right, **y up**.

**Grid.** 5 × 5 boxes on a 6 × 6 lattice of nodes.
Node (i, j) is at

```
x = 11.5 + i × 145.4        y = 11.5 + j × 145.4        i, j = 0 … 5
```

Box N has its lower-left node at (col, row) with `N = col*5 + row + 1`; col and row count
from the bottom-left box, so box 1 is bottom-left, box 5 is top-left, box 25 is top-right.

**Tier 1 — ArUco tags.** One at every node, centred on it. `DICT_4X4_50`, 6 × 6 modules
(4 × 4 payload + border), tag 23 µm, module 3.833 µm. The printed material is the tag's
**black** modules. Rounded so a tag cannot come apart as the gel swells: necks 0.2 µm wide
across every diagonal pinch, fillets of 0.3 µm radius in every concave corner
(21 pinches bridged over the 36 tags). Ids by node (top row of the table is the top of the print):

| | i = 0 | i = 1 | i = 2 | i = 3 | i = 4 | i = 5 |
|---|---|---|---|---|---|---|
| j = 5 | 36 | 38 | 44 | 45 | 2 | 11 |
| j = 4 | 24 | 29 | 32 | 33 | 34 | 35 |
| j = 3 | 5 | 6 | 7 | 15 | 16 | 20 |
| j = 2 | 42 | 43 | 48 | 49 | 1 | 4 |
| j = 1 | 23 | 25 | 30 | 37 | 40 | 41 |
| j = 0 | 3 | 10 | 13 | 17 | 21 | 22 |

**Tier 2 — dashes.** 8.125 × 2.125 µm, 10 per box edge, centred on the grid lines
(long axis along the line), omitted where they would run into a tag. 480 in total.

**Tier 3 — dots.** 2.125 µm squares on a square lattice of pitch 6 µm, axis-aligned, centred
in each box. In box N with lower-left node at (x₀, y₀), dot (di, dj) is at

```
x = x₀ + 3.7 + di × 6        y = y₀ + 3.7 + dj × 6        di, dj = 0 … 23
```

Dots are omitted where they would come closer than 3.875 µm (edge to edge) to a tag or
to a dash line — the same gap a dot keeps from its neighbours — which leaves 468 of the
576 lattice sites in each box. `features.csv` lists every dot that is printed, with its
(box, di, dj); recognition code should take the list from there rather than re-derive the omissions.

## 3. Names

Every feature has a unique tag, used unchanged by the recognition pipeline:

| feature | tag | example |
|---|---|---|
| ArUco tag | `aruco|N{i}_{j}|{id}` | `aruco|N0_0|3` |
| dash | `dash|H{j}|{m}` on horizontal line j, `dash|V{i}|{m}` on vertical line i | `dash|H0|3` |
| dot | `dot|B{N}|{di}_{dj}` | `dot|B13|4_7` |

## 4. What it looks like in the image

At 0.51 µm per pixel (the metadata value; not yet calibrated), before expansion:

| | µm | pixels |
|---|---|---|
| dot spacing | 6 | 11.8 |
| dot, printed | 2.125 | 4.2 |
| dot, as imaged at 2.69 µm blur | 3.43 | 6.7 |
| tag | 23 | 45.1 |
| tag module | 3.833 | 7.5 |
| node to node | 145.4 | 285.1 |

**With expansion λ:** every printed feature is a rigid island — it keeps its printed size; only
the distances between features grow. So dot spacing and node spacing scale with λ, while the dot
and the tag stay the size they are in the table. The signal falls as λ⁻¹·⁸⁴, so the **exposure
must rise as λ²** (never below the reference exposure): about 16 × at 6 ×.

**Design → image is a reflection** (the design's y is up, the image's is down). Any fit between
the two must allow it, or flip y first, and should check that the sign it finds is −1.

## 5. Recognition — measured (S3)

Synthetic frames through the camera model, expansion 1 → 6 ×, two seeds, production pipeline.
Criterion: every frame registers, worst-frame dots recognised >= 90%, tags correct >= 99%.

| blur, PSF FWHM (µm) | verdict | dots recognised, worst frame | mean | tags decoded | fewest tags in a frame |
|---|---|---|---|---|---|
| 1.5 | PASS | 95.6 % | 97.6 % | 99 % | 4 |
| 1.7 | PASS | 95.6 % | 97.6 % | 99 % | 4 |
| 1.9 | PASS | 95.6 % | 97.6 % | 99 % | 4 |
| 2.1 | PASS | 95.6 % | 97.6 % | 99 % | 4 |
| 2.3 | PASS | 95.5 % | 97.6 % | 99 % | 4 |
| 2.5 | PASS | 95.5 % | 97.5 % | 99 % | 4 |
| 2.7 | PASS | 95.3 % | 97.4 % | 99 % | 4 |
| 2.9 | PASS | 95.1 % | 97.2 % | 99 % | 4 |
| 3.1 | PASS | 95.0 % | 96.5 % | 99 % | 4 |
| 3.4 | MARGINAL | 80.7 % | 92.3 % | 99 % | 4 |
| 3.7 | FAIL | 27.2 % | 77.4 % | 90 % | 3 |
| 4 | FAIL | 1.1 % | 57.6 % | 83 % | 3 |

- **Fully recognised up to 3.1 µm** of blur from an unexpanded reference; usable (≥ 80 %) to
  3.4 µm. The design rule (spacing ≥ 1.75 × the imaged dot) gives 2.69 µm and keeps a margin.
- The tags decode ≥ 95 % up to 3.4 µm; the dots, not the tags, set this design's limit.
- The worst frame is the **least expanded** one. If the first frame of a series is already
  expanded, the limit is higher (`docs/S3_RECOGNITION.md` §1.3).
- Blur measured on the microscope today: 2.7–3.2 µm, varying by about a third across the field.
- These are simulated limits with a uniform Gaussian blur; expect the real ones somewhat lower.
  The spectrum print (`../4_spectrum/`) measures them on the real gel.

**Detector settings** (`rwtag.aruco.ArucoParams`): no CLAHE · `errorCorrectionRate = 1.0` ·
top-hat 15 px · dot area 12–220 px² · threshold floor at
median + 5 σ · Gaussian-mask centre refinement · match gate 0.45 × spacing ·
edge band `abs(k1) * FOV_um / 2 * 1.4`.

**Registration:** affine through the decoded tag *centres* (3 or more tags), similarity (2), or one
tag's corners for rotation plus the dot-lattice pitch for scale (1). Never across tags through their
corners — a tag does not follow the expansion.

## 6. Printability — measured against the reference print (S4)

| | this design | reference print |
|---|---|---|
| smallest gap between any two features | **3.875 µm** | 1.5 µm |
| … dot to dot / dot to tag / dot to dash | 3.875 / 9.137 / 7.575 µm | |
| smallest free-standing feature | 2.125 µm | 2.125 µm |
| dot height ÷ width | 0.94 | 0.94 |
| narrowest gap inside a tag | 2.675 µm | — |
| finest detail (neck and fillet tips) | 0.44 µm | — |
| every tag one solid if nothing finer than 1 µm prints | yes | — |
| separate solids | 12,216 | 7,341 |
| footprint | 76,229 µm² | 74,061 µm² |
| laser scan length (hatch 0.2, slice 0.3 µm) | 2.54 m — 1.03 × | 2.47 m |
| dots per metre of scan | 4,605 | 2,599 |

Process as for the reference print (same resin, same 2 µm height). Open `test_box.stl` and
`test_box_merged.stl` — one box with its four tags, 168.4 µm across, 540 dots —
in DeScribe before committing the full field.

## 7. Files in this folder

| file | what |
|---|---|
| `medium.stl` | **the print.** Box mesh, 154,212 triangles, 7.7 MB. md5 `4ccda47b1f6e876015564f039f079abc` |
| `medium_merged.stl` | the same geometry as one closed manifold solid per feature, 206,096 triangles. md5 `e2d716ab72b67a9b7d87f52894324e0a` |
| `test_box.stl`, `test_box_merged.stl` | one box, for the DeScribe dry run |
| `spec_sheet.json` | every parameter in this document, machine-readable |
| `features.csv` | every printed feature: tag, category, centre, size, box, lattice index |
| `reference_tags.json`, `ids.json` | what the recognition pipeline loads (`rwtag.aruco.Design.load`) |
| `printability.json` | the S4 measurements |
| `verify.json` | the gate record |
| `render.png`, `recognition.png` | the print; the S3 blur × expansion maps |



## 8. Using it

```python
import json
from rwtag.aruco import Design, ArucoParams, series

spec   = json.load(open("designs/2_medium/spec_sheet.json"))
design = Design.load("designs/2_medium/reference_tags.json")
params = ArucoParams(um_per_px=spec["optics_assumed"]["um_per_px"],      # calibrate this
                     psf_fwhm_um=2.7)                                     # the blur you measure
frames = series.process_series([(path, expansion), ...], design, params)   # ascending expansion
pairs  = series.pair_table(frames)                                         # {tag: {expansion: (x, y)}}
```

## 9. Gate

- [x] dot count exact
- [x] dot position < 1 px (0.167 um)
- [x] pitch within 1 px (0.167 um)
- [x] all tags decode
- [x] outer extent == 750 um
- [x] exact geometry (centres, size, pitch)
- [x] every box: count, pitch and clearances exact
- [x] zero overlapping features
- [x] spec sheet agrees with the rendered STL

**PASS** — checked 2026-09-29.

## 10. Sources

| section | read from |
|---|---|
| 1, 2, 3, 4 | `spec_sheet.json` (`dots`, `tags`, `dashes`, `grid`, `envelope`, `expected_in_image`); fill and pinch count from `verify.json` |
| 5 | `spec_sheet.json` → `recognition_measured`, `detector_settings` (from `docs/S3_recognition.json`) |
| 6 | `printability.json` (from `docs/S4_printability.json`) |
| 7 | md5 of the files as they are on disk; triangle counts from `printability.json` |
| 9 | `verify.json` → `checks` |
