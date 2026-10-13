# Spectrum — design specification

*Spacing workshop, design 4: the test print. Written 2026-09-29 by
`tools/write_design_specs.py` from the files in this folder (sources in §9).*

**What it is:** one print whose 25 boxes are 25 different dot patterns, so that one print and one
image show which spacing and which dot size this microscope and this gel can use. **Print this
first**; its result names which of designs 1–3 to print.

## 1. At a glance

| | |
|---|---|
| envelope | 750 × 750 × 2 µm |
| boxes | 5 × 5, node to node 145.4 µm |
| dots | **9,244** in 25 patterns — sizes 2.125, 2.5, 3, 3.5, 4 µm; spacings 5 – 8.875 µm |
| ArUco tags | 36, 23 µm, `DICT_4X4_50` — identical to designs 1–3 |
| dashes | 480, 8.125 × 2.125 µm — identical to designs 1–3 |
| areal fill | 18.5 % |

## 2. Layout

The gap between dots widens **left → right**; the dot grows **top → bottom**. Spacing (centre to
centre) = gap + dot. Each cell: **spacing (µm)** · dots printed · box number.

| dot ↓ / gap → | 2.875 µm | 3.375 µm | 3.875 µm | 4.375 µm | 4.875 µm |
|---|---|---|---|---|---|
| **2.125** | **5** · 713 · box 5 — OPTIMISTIC | **5.5** · 560 · box 10 | **6** · 468 · box 15 — MEDIUM | **6.5** · 396 · box 20 | **7** · 320 · box 25 — CONSERVATIVE |
| **2.5** | **5.375** · 609 · box 4 | **5.875** · 480 · box 9 | **6.375** · 396 · box 14 | **6.875** · 357 · box 19 | **7.375** · 285 · box 24 |
| **3** | **5.875** · 480 · box 3 | **6.375** · 396 · box 8 | **6.875** · 357 · box 13 | **7.375** · 285 · box 18 | **7.875** · 252 · box 23 |
| **3.5** | **6.375** · 468 · box 2 | **6.875** · 357 · box 7 | **7.375** · 285 · box 12 | **7.875** · 252 · box 17 | **8.375** · 221 · box 22 |
| **4** | **6.875** · 357 · box 1 | **7.375** · 285 · box 6 | **7.875** · 252 · box 11 | **8.375** · 221 · box 16 | **8.875** · 192 · box 21 — SAFEST |

- **Top-left is the Optimistic pattern; the top row is designs 1, 2 and 3** (columns 1, 3, 5) with
  two spacings between them, at the reference dot size.
- **Bottom-right is the safest pattern on the print**: the largest dot with the widest gap.
- Box numbers follow `N = col*5 + row + 1` with col and row counted from the bottom-left, so
  the top-left box is box 5 and the bottom-right is box 21.
- Each box is identified in an image by the four tags at its corners (`corner_tag_ids` in
  `spec_sheet.json`), never by its position in the frame.

Largest blur each box tolerates, by the design rule (spacing ≥ 1.75 × the imaged dot), µm:

| dot ↓ / gap → | 2.875 | 3.375 | 3.875 | 4.375 | 4.875 |
|---|---|---|---|---|---|
| **2.125** | 1.91 | 2.32 | 2.69 | 3.05 | 3.39 |
| **2.5** | 1.78 | 2.24 | 2.65 | 3.03 | 3.39 |
| **3** | 1.51 | 2.07 | 2.54 | 2.96 | 3.35 |
| **3.5** | 1.01 | 1.78 | 2.35 | 2.83 | 3.26 |
| **4** | — | 1.33 | 2.06 | 2.63 | 3.12 |

Every column tolerates about the same blur in every row — which is why the columns step the gap
and not the centre-to-centre spacing: reading **down a column isolates the dot size**, reading
**along a row isolates the spacing**.

## 3. Geometry

As designs 1–3 (design frame: origin bottom-left, x right, **y up**):

```
node (i, j):   x = 11.5 + i × 145.4     y = 11.5 + j × 145.4
dot (di, dj) of a box with lower-left node (x₀, y₀):
               x = x₀ + phase + di × spacing               y = y₀ + phase + dj × spacing
```

with `spacing`, `phase` (= `phase_in_box`) and the dot size taken from that box's row of
`boxes.csv` / `spec_sheet.json → boxes`. In every box the dots keep from tags and dash lines the
same gap they keep from each other. Tags: 23 µm, module 3.833 µm, rounded (necks
0.2 µm, fillets 0.3 µm); ids in `ids.json`, the same as in designs 1–3.

## 4. Reading the print — `analyse_spectrum.py`

```
python analyse_spectrum.py  IMAGE  [--um-per-px 0.51] [--out DIR]
```

One stitched image in; `<image>_spectrum.csv`, `.png` and `.json` out, and one line on the screen.
Per box: dots in view, **recognised** (found and identified), merged, contrast, scatter about the
lattice, blur. For the frame: tags decoded, expansion, blur, and the verdict —

> *tightest spacing recognised at the 2.125 µm dot: 6 µm (97 %) → print MEDIUM*

the tightest reference-size spacing that is at least 95 % recognised with every wider one
recognised too.

**Image the print with all of it in view** (any expansion up to about 1.6 × in a 1365 µm field).
Boxes cut by the edge of the field are reported, marked `*`, and not judged.

What the script says of four synthetic images of this print (`example/`):

| image | tags | expansion | blur measured | verdict |
|---|---|---|---|---|
| `example/synthetic_blur1.9um_1x.png` | 36 | 0.999 × | 2.08 µm | tightest spacing recognised at the 2.125 um dot: 5 um (100%) -> print OPTIMISTIC |
| `example/synthetic_blur2.7um_1x.png` | 36 | 0.999 × | 2.67 µm | tightest spacing recognised at the 2.125 um dot: 5 um (99%) -> print OPTIMISTIC |
| `example/synthetic_blur3.1um_2x.png` | 16 | 1.996 × | 2.74 µm | inconclusive: 5.5 um is 94% recognised, and the wider spacings that would decide ([6.0, 6.5, 7.0] um) are cut by the field edge. Image the print at a lower expansion, with all of it in view |
| `example/synthetic_blur3.4um_1x.png` | 36 | 0.999 × | 3.23 µm | tightest spacing recognised at the 2.125 um dot: 7 um (96%) -> print CONSERVATIVE |

On these the script's recognised fraction agrees with the simulator's truth to within 0.6 % in
every box (`docs/S5_gate.json`).

## 5. What to look for

| read | tells you |
|---|---|
| along the top row | the tightest spacing your microscope resolves at the reference dot → which design to print |
| down a column | whether a larger dot is recognised better, is brighter, sits steadier |
| `blur_um` | the blur of your microscope, measured on the print itself |
| the bottom-left box (4 µm dot, tightest gap) | the known-bad corner: by the design rule it resolves at no blur. If it fails while its neighbours pass, the test is discriminating |

In simulation at 3.4 µm blur, a 3.0 µm dot at 5.875 µm spacing is 97 % recognised where the
reference 2.125 µm dot at 6.0 µm is 82 % — the larger dot is brighter. Whether that holds on the
real gel, and whether a 3 µm dot prints and anchors as well, is what rows 2–5 are for.

## 6. Printability

Footprint 104,019 µm² (18.5 %), the same as the Optimistic design, so about the
same write time. Tightest gap between any two features: the 2.875 µm dot-to-dot gap of
the left-hand column (reference print: 1.5 µm). The largest dot is 4 µm square and 2 µm tall — squatter
than the reference dot, so no harder to stand. Process as for the reference print.

## 7. Files in this folder

| file | what |
|---|---|
| `spectrum.stl` | **the print.** Box mesh. md5 `1771065277379be4fd70e0fa361d1433` |
| `spectrum_merged.stl` | the same geometry, one closed manifold solid per feature, 166,800 triangles. md5 `3075d89148fa2f8aba01e12ceda49e5b` |
| `spec_sheet.json` | common parameters, and `boxes`: the 25 patterns with their corner tag ids |
| `boxes.csv` | the 25 patterns, one row each |
| `features.csv` | all 9,760 features; every dot row carries its dot size, spacing and gap |
| `reference_tags.json`, `ids.json` | what the recognition pipeline and `analyse_spectrum.py` load |
| `analyse_spectrum.py` | the analysis script |
| `example/` | four synthetic images of this print and the script's output for each |
| `verify.json`, `render.png` | the gate record; the labelled render |

## 8. Gate

- [x] dot count exact
- [x] dot position < 1 px (0.167 um)
- [x] pitch within 1 px (0.167 um)
- [x] all tags decode
- [x] outer extent == 750 um
- [x] exact geometry: every dot at its rectangle centre, sizes are the five specified
- [x] every box: its own size, pitch, count and clearances (exact)
- [x] zero overlapping features
- [x] tags and dashes identical to the optimistic design
- [x] top row carries the three designs (5.0 / 6.0 / 7.0 um at 2.125 um)
- [x] merged mesh manifold, volume == footprint x height
- [x] spec sheet and 25-box table agree with the rendered STL
- [x] OPTIMISTIC is top-left, SAFEST is bottom-right

**PASS** — checked 2026-09-29.

## 9. Sources

| section | read from |
|---|---|
| 1, 2, 3 | `spec_sheet.json` (`boxes`, `dots`, `tags`, `dashes`, `grid`); fill from `verify.json` |
| 4 | `example/*_spectrum.json` |
| 6 | `verify.json`, `spec_sheet.json → boxes` |
| 7 | md5 of the files as they are on disk |
| 8 | `verify.json → checks` |
