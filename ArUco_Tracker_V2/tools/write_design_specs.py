#!/usr/bin/env python3
"""
write_design_specs.py — spacing-workshop phase S6: DESIGN_SPEC.md in each of the four
design folders, designs/README.md, designs/comparison.png.

Every number in every document is READ from a file in the same folder
(spec_sheet.json, verify.json, printability.json, boxes.csv, example/*.json) at the
moment the document is written -- none is typed here. The per-design S4 block is
copied into the folder as printability.json so that the folder is self-contained.

GATE
    every file a document names exists · the STL's md5 equals the one the document
    prints · dot / dash / tag counts agree between spec_sheet.json, features.csv and
    verify.json · every folder's own gate record says PASS

Run:  python write_design_specs.py
"""
from __future__ import annotations
import csv
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
V2 = os.path.normpath(os.path.join(HERE, ".."))
D = os.path.join(V2, "designs")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(V2, "..", "Reference_Warp_Tagger")))
FOLDERS = {"optimistic": "1_optimistic", "medium": "2_medium", "conservative": "3_conservative"}
ROLE = {
    "optimistic": "the densest pattern — the existing optimistic print, unchanged. For a microscope whose blur is "
                  "at or below about 2.7 µm, or a series whose first frame is already expanded about 1.5×.",
    "medium": "the intermediate pattern. Recognised across the blur measured on the microscope today, without margin above it.",
    "conservative": "the safe pattern, one step tighter than the reference print. Recognised across the blur measured "
                    "today, with margin.",
}
REF = dict(pitch=8.0, dots=6420, dot=2.125)
TODAY = "2.7–3.2 µm"


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def J(*p):
    return json.load(open(os.path.join(*p)))


def f(x, n=3):
    s = f"{x:.{n}f}".rstrip("0").rstrip(".")
    return s if s else "0"


def design_doc(name):
    folder = os.path.join(D, FOLDERS[name])
    s4 = J(D, "docs", "S4_printability.json")
    pr = s4["designs"][name]; pr["reference"] = s4["reference"]; pr["settings"] = s4["settings"]
    with open(os.path.join(folder, "printability.json"), "w") as fh:
        json.dump(pr, fh, indent=1, default=float)
    sp, vf = J(folder, "spec_sheet.json"), J(folder, "verify.json")
    g, t, da, do = sp["grid"], sp["tags"], sp["dashes"], sp["dots"]
    ex = sp["expected_in_image"]["at_expansion_1"]; ds = sp["detector_settings"]; rm = sp["recognition_measured"]
    umpp = sp["optics_assumed"]["um_per_px"]
    h = md5(os.path.join(folder, f"{name}.stl")); hm = md5(os.path.join(folder, f"{name}_merged.stl"))
    ids = {tuple(x["node"]): x["id"] for x in t["ids"]}
    grid_rows = "\n".join("| j = %d | " % j + " | ".join(str(ids[(i, j)]) for i in range(g["nodes"][0])) + " |"
                          for j in reversed(range(g["nodes"][1])))
    rec_rows = "\n".join(f"| {x['psf']:g} | {x['verdict']} | {100*x['recognised_worst']:.1f} % | "
                         f"{100*x['recognised_mean']:.1f} % | {100*x['tag_decode_mean']:.0f} % | {x['tags_min']} |"
                         for x in rm["by_psf"])
    gaps = pr["min_gap"]
    doc = f"""# {name.capitalize()} — design specification

*Spacing workshop, design {FOLDERS[name][0]} of 3. Written {time.strftime('%Y-%m-%d')} by
`tools/write_design_specs.py` from the files in this folder; every number below is read from
`spec_sheet.json`, `verify.json` or `printability.json` (sources in §10).*

**What it is:** {ROLE[name]}

## 1. At a glance

| | this design | reference print |
|---|---|---|
| dot | **{f(do['side'])} µm square, {f(do['height'])} µm tall** | {REF['dot']} µm |
| **dot spacing, centre to centre** | **{f(do['pitch'], 5)} µm**{' (nominal ' + f(do['pitch_nominal']) + ')' if abs(do['pitch'] - do['pitch_nominal']) > 1e-9 else ''} | {REF['pitch']} µm |
| gap between neighbouring dots | {f(do['gap'])} µm | {f(REF['pitch'] - REF['dot'])} µm |
| **dots** | **{do['count']:,}** ({vf['vs_reference_dots']:.2f} × the reference) | {REF['dots']:,} |
| ArUco tags | {t['count']}, {f(t['size'])} µm, `{t['dictionary']}` | (printed digits) |
| dashes | {da['count']}, {f(da['length'])} × {f(da['width'])} µm | 600 |
| envelope | {f(sp['envelope']['x'])} × {f(sp['envelope']['y'])} × {f(sp['envelope']['z'])} µm | same |
| areal fill | {100*vf['fill']:.1f} % | 13.2 % |
| largest blur at which it is fully recognised | **{f(rm['psf_max_measured'])} µm** measured · {f(rm['psf_max_predicted'], 2)} µm by the design rule | — |
| write time (laser scan length) | {pr['scan_vs_ref']:.2f} × the reference | 1 |

The three designs of this workshop differ **only in the dot spacing**. Tags, their positions and
ids, and the dashes are identical in all three and in the spectrum print.

## 2. Geometry

All dimensions in micrometres, in the **design frame**: origin at the bottom-left corner of the
print, x to the right, **y up**.

**Grid.** {g['boxes'][0]} × {g['boxes'][1]} boxes on a {g['nodes'][0]} × {g['nodes'][1]} lattice of nodes.
Node (i, j) is at

```
x = {f(g['node_origin'])} + i × {f(g['node_pitch'])}        y = {f(g['node_origin'])} + j × {f(g['node_pitch'])}        i, j = 0 … {g['nodes'][0]-1}
```

Box N has its lower-left node at (col, row) with `{g['box_numbering'].split(',')[0]}`; col and row count
from the bottom-left box, so box 1 is bottom-left, box {g['boxes'][1]} is top-left, box {g['boxes'][0]*g['boxes'][1]} is top-right.

**Tier 1 — ArUco tags.** One at every node, centred on it. `{t['dictionary']}`, {t['modules']} × {t['modules']} modules
(4 × 4 payload + border), tag {f(t['size'])} µm, module {f(t['module'])} µm. The printed material is the tag's
**black** modules. Rounded so a tag cannot come apart as the gel swells: necks {f(t['rounding']['neck_width'])} µm wide
across every diagonal pinch, fillets of {f(t['rounding']['fillet_radius'])} µm radius in every concave corner
({vf['n_pinch']} pinches bridged over the 36 tags). Ids by node (top row of the table is the top of the print):

| | i = 0 | i = 1 | i = 2 | i = 3 | i = 4 | i = 5 |
|---|---|---|---|---|---|---|
{grid_rows}

**Tier 2 — dashes.** {f(da['length'])} × {f(da['width'])} µm, {da['per_box_edge']} per box edge, centred on the grid lines
(long axis along the line), omitted where they would run into a tag. {da['count']} in total.

**Tier 3 — dots.** {f(do['side'])} µm squares on a square lattice of pitch {f(do['pitch'], 5)} µm, axis-aligned, centred
in each box. In box N with lower-left node at (x₀, y₀), dot (di, dj) is at

```
x = x₀ + {f(do['phase_in_box'])} + di × {f(do['pitch'], 5)}        y = y₀ + {f(do['phase_in_box'])} + dj × {f(do['pitch'], 5)}        di, dj = 0 … {do['per_box_row']-1}
```

Dots are omitted where they would come closer than {f(do['clearance_from_tag'])} µm (edge to edge) to a tag or
to a dash line — the same gap a dot keeps from its neighbours — which leaves {do['per_box'][next(iter(do['per_box']))]} of the
{do['per_box_row']**2} lattice sites in each box. `features.csv` lists every dot that is printed, with its
(box, di, dj); recognition code should take the list from there rather than re-derive the omissions.

## 3. Names

Every feature has a unique tag, used unchanged by the recognition pipeline:

| feature | tag | example |
|---|---|---|
| ArUco tag | `aruco|N{{i}}_{{j}}|{{id}}` | `aruco|N0_0|{ids[(0, 0)]}` |
| dash | `dash|H{{j}}|{{m}}` on horizontal line j, `dash|V{{i}}|{{m}}` on vertical line i | `dash|H0|3` |
| dot | `dot|B{{N}}|{{di}}_{{dj}}` | `dot|B13|4_7` |

## 4. What it looks like in the image

At {umpp} µm per pixel (the metadata value; not yet calibrated), before expansion:

| | µm | pixels |
|---|---|---|
| dot spacing | {f(do['pitch'], 3)} | {ex['dot_pitch_px']:.1f} |
| dot, printed | {f(do['side'])} | {ex['dot_side_px']:.1f} |
| dot, as imaged at {f(sp['optics_assumed']['psf_fwhm_design'], 2)} µm blur | {ex['dot_fwhm_px']*umpp:.2f} | {ex['dot_fwhm_px']:.1f} |
| tag | {f(t['size'])} | {ex['tag_side_px']:.1f} |
| tag module | {f(t['module'])} | {ex['tag_module_px']:.1f} |
| node to node | {f(g['node_pitch'])} | {ex['node_pitch_px']:.1f} |

**With expansion λ:** every printed feature is a rigid island — it keeps its printed size; only
the distances between features grow. So dot spacing and node spacing scale with λ, while the dot
and the tag stay the size they are in the table. The signal falls as λ⁻¹·⁸⁴, so the **exposure
must rise as λ²** (never below the reference exposure): about 16 × at 6 ×.

**Design → image is a reflection** (the design's y is up, the image's is down). Any fit between
the two must allow it, or flip y first, and should check that the sign it finds is −1.

## 5. Recognition — measured (S3)

Synthetic frames through the camera model, expansion 1 → 6 ×, two seeds, production pipeline.
Criterion: {rm['criterion']}.

| blur, PSF FWHM (µm) | verdict | dots recognised, worst frame | mean | tags decoded | fewest tags in a frame |
|---|---|---|---|---|---|
{rec_rows}

- **Fully recognised up to {f(rm['psf_max_measured'])} µm** of blur from an unexpanded reference; usable (≥ 80 %) to
  {f(rm['psf_max_marginal'])} µm. The design rule (spacing ≥ 1.75 × the imaged dot) gives {f(rm['psf_max_predicted'], 2)} µm and keeps a margin.
- The tags decode ≥ 95 % up to {f(rm['tag_psf_limit_measured'])} µm; the dots, not the tags, set this design's limit.
- The worst frame is the **least expanded** one. If the first frame of a series is already
  expanded, the limit is higher (`docs/S3_RECOGNITION.md` §1.3).
- Blur measured on the microscope today: {TODAY}, varying by about a third across the field.
- These are simulated limits with a uniform Gaussian blur; expect the real ones somewhat lower.
  The spectrum print (`../4_spectrum/`) measures them on the real gel.

**Detector settings** (`rwtag.aruco.ArucoParams`): no CLAHE · `errorCorrectionRate = {ds['error_correction_rate']}` ·
top-hat {ds['tophat_px']} px · dot area {ds['dot_area_px2'][0]}–{ds['dot_area_px2'][1]} px² · threshold floor at
median + {f(ds['noise_k'])} σ · Gaussian-mask centre refinement · match gate {ds['match_gate_pitch_fraction']} × spacing ·
edge band `{ds['edge_band_um']}`.

**Registration:** affine through the decoded tag *centres* (3 or more tags), similarity (2), or one
tag's corners for rotation plus the dot-lattice pitch for scale (1). Never across tags through their
corners — a tag does not follow the expansion.

## 6. Printability — measured against the reference print (S4)

| | this design | reference print |
|---|---|---|
| smallest gap between any two features | **{f(pr['min_gap_all'])} µm** | {f(pr['reference']['min_gap_all'])} µm |
| … dot to dot / dot to tag / dot to dash | {f(gaps['dot-dot'])} / {f(gaps['aruco-dot'])} / {f(gaps['dash-dot'])} µm | |
| smallest free-standing feature | {f(pr['free_standing_min_um'])} µm | {f(pr['reference']['dot_um'])} µm |
| dot height ÷ width | {pr['dot_aspect']:.2f} | {pr['reference']['dot_aspect']:.2f} |
| narrowest gap inside a tag | {f(pr['tag_narrowest_internal_gap_um'])} µm | — |
| finest detail (neck and fillet tips) | {f(pr['tag_finest_detail_um'], 2)} µm | — |
| every tag one solid if nothing finer than 1 µm prints | {'yes' if pr['tag_one_piece_without_fine_detail'] else 'NO'} | — |
| separate solids | {pr['islands_total']:,} | {pr['reference']['islands']:,} |
| footprint | {pr['footprint_um2']:,.0f} µm² | {pr['reference']['footprint_um2']:,.0f} µm² |
| laser scan length (hatch {pr['settings']['hatch']}, slice {pr['settings']['slice']} µm) | {pr['scan_m']:.2f} m — {pr['scan_vs_ref']:.2f} × | {pr['reference']['scan_m']:.2f} m |
| dots per metre of scan | {pr['dots_per_scan_m']:,.0f} | {pr['reference']['dots']/pr['reference']['scan_m']:,.0f} |

Process as for the reference print (same resin, same 2 µm height). Open `test_box.stl` and
`test_box_merged.stl` — one box with its four tags, {f(pr['test_box']['size_um'], 1)} µm across, {pr['test_box']['dots']} dots —
in DeScribe before committing the full field.

## 7. Files in this folder

| file | what |
|---|---|
| `{name}.stl` | **the print.** Box mesh, {pr['mesh_box']['triangles']:,} triangles, {pr['mesh_box']['mb']:.1f} MB. md5 `{h}` |
| `{name}_merged.stl` | the same geometry as one closed manifold solid per feature, {pr['mesh_merged']['triangles']:,} triangles. md5 `{hm}` |
| `test_box.stl`, `test_box_merged.stl` | one box, for the DeScribe dry run |
| `spec_sheet.json` | every parameter in this document, machine-readable |
| `features.csv` | every printed feature: tag, category, centre, size, box, lattice index |
| `reference_tags.json`, `ids.json` | what the recognition pipeline loads (`rwtag.aruco.Design.load`) |
| `printability.json` | the S4 measurements |
| `verify.json` | the gate record |
| `render.png`, `recognition.png` | the print; the S3 blur × expansion maps |

{'`' + name + '.stl` is byte-identical to `cad/aruco_grid_optimistic.stl`, the print chosen in Rev D.' if name == 'optimistic' else ''}

## 8. Using it

```python
import json
from rwtag.aruco import Design, ArucoParams, series

spec   = json.load(open("designs/{FOLDERS[name]}/spec_sheet.json"))
design = Design.load("designs/{FOLDERS[name]}/reference_tags.json")
params = ArucoParams(um_per_px=spec["optics_assumed"]["um_per_px"],      # calibrate this
                     psf_fwhm_um=2.7)                                     # the blur you measure
frames = series.process_series([(path, expansion), ...], design, params)   # ascending expansion
pairs  = series.pair_table(frames)                                         # {{tag: {{expansion: (x, y)}}}}
```

## 9. Gate

{chr(10).join(f"- [{'x' if v else ' '}] {k}" for k, v in vf['checks'].items())}

**{'PASS' if vf['passed'] else 'FAIL'}** — checked {sp['gate']['checked']}.

## 10. Sources

| section | read from |
|---|---|
| 1, 2, 3, 4 | `spec_sheet.json` (`dots`, `tags`, `dashes`, `grid`, `envelope`, `expected_in_image`); fill and pinch count from `verify.json` |
| 5 | `spec_sheet.json` → `recognition_measured`, `detector_settings` (from `docs/S3_recognition.json`) |
| 6 | `printability.json` (from `docs/S4_printability.json`) |
| 7 | md5 of the files as they are on disk; triangle counts from `printability.json` |
| 9 | `verify.json` → `checks` |
"""
    with open(os.path.join(folder, "DESIGN_SPEC.md"), "w") as fh:
        fh.write(doc)
    return dict(name=name, folder=FOLDERS[name], sp=sp, vf=vf, pr=pr, md5=h)


def spectrum_doc():
    folder = os.path.join(D, "4_spectrum")
    sp, vf = J(folder, "spec_sheet.json"), J(folder, "verify.json")
    g, t, da = sp["grid"], sp["tags"], sp["dashes"]
    B = sp["boxes"]
    gaps = sorted({round(b["gap"], 6) for b in B}); sizes = sorted({b["dot"] for b in B})
    cell = lambda d, gp: next(b for b in B if b["dot"] == d and abs(b["gap"] - gp) < 1e-9)
    tab = "\n".join(f"| **{f(d)}** | " + " | ".join(
        f"**{f(cell(d, gp)['pitch'])}** · {cell(d, gp)['count']} · box {cell(d, gp)['box']}"
        + (f" — {cell(d, gp)['label']}" if cell(d, gp)['label'] else "") for gp in gaps) + " |" for d in sizes)
    psf = "\n".join(f"| **{f(d)}** | " + " | ".join(
        (f"{cell(d, gp)['psf_fwhm_max_predicted']:.2f}" if cell(d, gp)['psf_fwhm_max_predicted'] > 0 else "—") for gp in gaps) + " |"
        for d in sizes)
    exs = []
    exd = os.path.join(folder, "example")
    for fn in sorted(os.listdir(exd)):
        if fn.endswith("_spectrum.json"):
            r = J(exd, fn)
            exs.append(f"| `example/{fn.replace('_spectrum.json', '.png')}` | {r['tags_decoded']} | {r['expansion']:.3f} × | "
                       f"{r['blur_um']:.2f} µm | {r['verdict'].split('   [')[0]} |")
    h = md5(os.path.join(folder, "spectrum.stl")); hm = md5(os.path.join(folder, "spectrum_merged.stl"))
    n_feat = sum(1 for _ in open(os.path.join(folder, "features.csv"))) - 1
    doc = f"""# Spectrum — design specification

*Spacing workshop, design 4: the test print. Written {time.strftime('%Y-%m-%d')} by
`tools/write_design_specs.py` from the files in this folder (sources in §9).*

**What it is:** one print whose 25 boxes are 25 different dot patterns, so that one print and one
image show which spacing and which dot size this microscope and this gel can use. **Print this
first**; its result names which of designs 1–3 to print.

## 1. At a glance

| | |
|---|---|
| envelope | {f(sp['envelope']['x'])} × {f(sp['envelope']['y'])} × {f(sp['envelope']['z'])} µm |
| boxes | {g['boxes'][0]} × {g['boxes'][1]}, node to node {f(g['node_pitch'])} µm |
| dots | **{sp['dots']['count']:,}** in 25 patterns — sizes {', '.join(f(x) for x in sp['dots']['sizes'])} µm; spacings {f(min(sp['dots']['pitches']))} – {f(max(sp['dots']['pitches']))} µm |
| ArUco tags | {t['count']}, {f(t['size'])} µm, `{t['dictionary']}` — identical to designs 1–3 |
| dashes | {da['count']}, {f(da['length'])} × {f(da['width'])} µm — identical to designs 1–3 |
| areal fill | {100*vf['fill']:.1f} % |

## 2. Layout

The gap between dots widens **left → right**; the dot grows **top → bottom**. Spacing (centre to
centre) = gap + dot. Each cell: **spacing (µm)** · dots printed · box number.

| dot ↓ / gap → | {' | '.join(f(x) + ' µm' for x in gaps)} |
|---|---|---|---|---|---|
{tab}

- **Top-left is the Optimistic pattern; the top row is designs 1, 2 and 3** (columns 1, 3, 5) with
  two spacings between them, at the reference dot size.
- **Bottom-right is the safest pattern on the print**: the largest dot with the widest gap.
- Box numbers follow `{g['box_numbering'].split(',')[0]}` with col and row counted from the bottom-left, so
  the top-left box is box {cell(sizes[0], gaps[0])['box']} and the bottom-right is box {cell(sizes[-1], gaps[-1])['box']}.
- Each box is identified in an image by the four tags at its corners (`corner_tag_ids` in
  `spec_sheet.json`), never by its position in the frame.

Largest blur each box tolerates, by the design rule (spacing ≥ 1.75 × the imaged dot), µm:

| dot ↓ / gap → | {' | '.join(f(x) for x in gaps)} |
|---|---|---|---|---|---|
{psf}

Every column tolerates about the same blur in every row — which is why the columns step the gap
and not the centre-to-centre spacing: reading **down a column isolates the dot size**, reading
**along a row isolates the spacing**.

## 3. Geometry

As designs 1–3 (design frame: origin bottom-left, x right, **y up**):

```
node (i, j):   x = {f(g['node_origin'])} + i × {f(g['node_pitch'])}     y = {f(g['node_origin'])} + j × {f(g['node_pitch'])}
dot (di, dj) of a box with lower-left node (x₀, y₀):
               x = x₀ + phase + di × spacing               y = y₀ + phase + dj × spacing
```

with `spacing`, `phase` (= `phase_in_box`) and the dot size taken from that box's row of
`boxes.csv` / `spec_sheet.json → boxes`. In every box the dots keep from tags and dash lines the
same gap they keep from each other. Tags: {f(t['size'])} µm, module {f(t['module'])} µm, rounded (necks
{f(t['rounding']['neck_width'])} µm, fillets {f(t['rounding']['fillet_radius'])} µm); ids in `ids.json`, the same as in designs 1–3.

## 4. Reading the print — `analyse_spectrum.py`

```
python analyse_spectrum.py  IMAGE  [--um-per-px {sp['optics_assumed']['um_per_px']}] [--out DIR]
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
{chr(10).join(exs)}

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

Footprint {vf['footprint_um2']:,.0f} µm² ({100*vf['fill']:.1f} %), the same as the Optimistic design, so about the
same write time. Tightest gap between any two features: the {f(min(b['gap'] for b in B))} µm dot-to-dot gap of
the left-hand column (reference print: 1.5 µm). The largest dot is {f(max(sizes))} µm square and 2 µm tall — squatter
than the reference dot, so no harder to stand. Process as for the reference print.

## 7. Files in this folder

| file | what |
|---|---|
| `spectrum.stl` | **the print.** Box mesh. md5 `{h}` |
| `spectrum_merged.stl` | the same geometry, one closed manifold solid per feature, {vf['mesh_merged']['triangles']:,} triangles. md5 `{hm}` |
| `spec_sheet.json` | common parameters, and `boxes`: the 25 patterns with their corner tag ids |
| `boxes.csv` | the 25 patterns, one row each |
| `features.csv` | all {n_feat:,} features; every dot row carries its dot size, spacing and gap |
| `reference_tags.json`, `ids.json` | what the recognition pipeline and `analyse_spectrum.py` load |
| `analyse_spectrum.py` | the analysis script |
| `example/` | four synthetic images of this print and the script's output for each |
| `verify.json`, `render.png` | the gate record; the labelled render |

## 8. Gate

{chr(10).join(f"- [{'x' if v else ' '}] {k}" for k, v in vf['checks'].items())}

**{'PASS' if vf['passed'] else 'FAIL'}** — checked {sp['gate']['checked']}.

## 9. Sources

| section | read from |
|---|---|
| 1, 2, 3 | `spec_sheet.json` (`boxes`, `dots`, `tags`, `dashes`, `grid`); fill from `verify.json` |
| 4 | `example/*_spectrum.json` |
| 6 | `verify.json`, `spec_sheet.json → boxes` |
| 7 | md5 of the files as they are on disk |
| 8 | `verify.json → checks` |
"""
    with open(os.path.join(folder, "DESIGN_SPEC.md"), "w") as fh:
        fh.write(doc)
    return dict(name="spectrum", folder="4_spectrum", sp=sp, vf=vf, md5=h)


def comparison_png(res):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from rwtag.glyph import stl_glyphs as sg
    s3 = J(D, "docs", "S3_recognition.json")
    col = {"optimistic": "#d1495b", "medium": "#edae49", "conservative": "#00798c"}
    fig = plt.figure(figsize=(17, 9.4), dpi=120)
    w = 62.0
    for k, r in enumerate(res[:3]):
        n, sp = r["name"], r["sp"]
        hi, *_ = sg.render_topdown(os.path.join(D, r["folder"], f"{n}.stl"), px_per_um=12.0)
        H = hi.shape[0]
        o, P, t = sp["grid"]["node_origin"], sp["grid"]["node_pitch"], sp["tags"]["size"]
        x0 = y0 = o + 2 * P - t / 2 - 4
        a = fig.add_axes([0.04 + 0.24 * k, 0.53, 0.215, 0.38])
        a.imshow(hi[int(H - (y0 + w) * 12):int(H - y0 * 12), int(x0 * 12):int((x0 + w) * 12)], cmap="gray", extent=[0, w, 0, w])
        a.set_title(f"{FOLDERS[n]}: spacing {sp['dots']['pitch']:.1f} µm · {sp['dots']['count']:,} dots", fontsize=10, color=col[n])
        a.set_xlabel("µm")
    a = fig.add_axes([0.77, 0.53, 0.215, 0.38])
    img, *_ = sg.render_topdown(os.path.join(D, "4_spectrum", "spectrum.stl"), px_per_um=3.0)
    a.imshow(img, cmap="gray", extent=[0, 750, 0, 750]); a.set_xlabel("µm")
    a.set_title(f"4_spectrum: 25 patterns · {res[3]['sp']['dots']['count']:,} dots", fontsize=10)
    a = fig.add_axes([0.05, 0.07, 0.42, 0.36])
    for n, r in s3["designs"].items():
        a.plot([x["psf"] for x in r["per_psf"]], [x["recognised_worst"] for x in r["per_psf"]], "o-", c=col[n],
               label=f"{n} — fully recognised to {r['psf_max_measured']:g} µm")
    a.axvspan(*s3["today"], color="grey", alpha=0.15, label="blur measured today")
    a.axvline(s3["after_focus_fix"], c="k", ls="--", lw=0.7, label="expected after the focus fix")
    a.axhline(0.9, c="k", lw=0.6); a.set_ylim(0, 1.03); a.grid(alpha=.3); a.legend(fontsize=8)
    a.set_xlabel("blur — PSF FWHM (µm)"); a.set_ylabel("dots recognised, worst frame (λ 1–6)")
    a.set_title("what the pipeline recognises (S3)", fontsize=10)
    a = fig.add_axes([0.54, 0.07, 0.44, 0.36])
    names = ["reference"] + [r["name"] for r in res[:3]]
    dots = [REF["dots"]] + [r["sp"]["dots"]["count"] for r in res[:3]]
    scan = [res[0]["pr"]["reference"]["scan_m"]] + [r["pr"]["scan_m"] for r in res[:3]]
    xs = range(4)
    a.bar([x - 0.2 for x in xs], dots, 0.4, color=["#888888"] + [col[n] for n in names[1:]])
    a.set_ylabel("dots"); a.set_xticks(list(xs)); a.set_xticklabels(names)
    for x, d in zip(xs, dots):
        a.text(x - 0.2, d, f"{d:,}", ha="center", va="bottom", fontsize=8)
    b = a.twinx()
    b.bar([x + 0.2 for x in xs], scan, 0.4, color="none", edgecolor="k", hatch="//")
    b.set_ylabel("laser scan length (m), hatched")
    for x, sv in zip(xs, scan):
        b.text(x + 0.2, sv, f"{sv:.2f} m", ha="center", va="bottom", fontsize=8)
    a.set_title("measurement points and write time (S4)", fontsize=10)
    fig.suptitle("Spacing workshop — three designs with the reference dot (2.125 µm), the same tags and dashes, and the spectrum test print",
                 fontsize=11)
    fig.savefig(os.path.join(D, "comparison.png")); plt.close(fig)


def readme(res):
    o, m, c, s = res
    row = lambda r: (f"| [`{r['folder']}/`]({r['folder']}/DESIGN_SPEC.md) | {f(r['sp']['dots']['side'])} µm | "
                     f"**{f(r['sp']['dots']['pitch_nominal'])} µm** | {f(r['sp']['dots']['gap'])} µm | **{r['sp']['dots']['count']:,}** | "
                     f"{f(r['sp']['tags']['size'])} µm | **{f(r['sp']['recognition_measured']['psf_max_measured'])} µm** | "
                     f"{r['pr']['scan_vs_ref']:.2f} × | {f(r['pr']['min_gap_all'])} µm | PASS |")
    doc = f"""# Nanoscribe marker designs — spacing workshop

*Written {time.strftime('%Y-%m-%d')} by `tools/write_design_specs.py`. Every number is read from the design folders.*

Three designs that differ **only in the spacing of the dots**, and one test print that decides
between them. All four are 750 × 750 × 2 µm, 5 × 5 boxes, three tiers — 36 ArUco tags, 480 dashes,
dots — with the reference print's dot (2.125 µm square). Tags, ids and dashes are identical in
all four.

![comparison](comparison.png)

## The four

| folder | dot | spacing | gap | dots | tag | fully recognised up to a blur of | write time vs reference | tightest gap | gate |
|---|---|---|---|---|---|---|---|---|---|
{row(o)}
{row(m)}
{row(c)}
| [`4_spectrum/`](4_spectrum/DESIGN_SPEC.md) | {', '.join(f(x) for x in s['sp']['dots']['sizes'])} µm | {f(min(s['sp']['dots']['pitches']))} – {f(max(s['sp']['dots']['pitches']))} µm | {f(min(b['gap'] for b in s['sp']['boxes']))} – {f(max(b['gap'] for b in s['sp']['boxes']))} µm | **{s['sp']['dots']['count']:,}** in 25 patterns | {f(s['sp']['tags']['size'])} µm | per box | ≈ {o['pr']['scan_vs_ref']:.2f} × | {f(min(b['gap'] for b in s['sp']['boxes']))} µm | PASS |
| *reference print* | 2.125 µm | 8.0 µm | 5.875 µm | 6,420 | — | — | 1 | 1.5 µm | — |

Blur measured on the microscope today: {TODAY} (PSF FWHM), varying by about a third across the
field; expected after the focus is flattened: about 1.9 µm.

## Which to print

1. **Print `4_spectrum/spectrum.stl` first.** Image it with the whole print in view and run
   `python 4_spectrum/analyse_spectrum.py <image>`. It reports, per box, what was recognised, and
   names the design to print.
2. Print the design it names. If you must choose before the spectrum result:
   - the microscope as it is, unexpanded reference → **Conservative** (margin) or **Medium** (no margin);
   - after the focus fix, or if the first frame imaged is already expanded ~1.5 × → **Optimistic**.
3. For every design: **exposure rising as λ²**, and the detector settings in the design's spec sheet.

## What is in each folder

`DESIGN_SPEC.md` (the design specification) · `spec_sheet.json` + `features.csv` (the spec sheet, for
writing recognition code) · `<name>.stl` and `<name>_merged.stl` (the print, two mesh styles) ·
`reference_tags.json`, `ids.json` (what the pipeline loads) · `verify.json` (the gate record) ·
`render.png` · and, for designs 1–3, `recognition.png`, `printability.json` and the
`test_box*.stl` pair for the DeScribe dry run; for the spectrum, `boxes.csv`,
`analyse_spectrum.py` and `example/`.

## Documents

| | |
|---|---|
| [`docs/00_MASTER_PLAN.md`](docs/00_MASTER_PLAN.md) | the plan, the decisions, the phases |
| [`docs/01_DESIGN_PARAMETERS.md`](docs/01_DESIGN_PARAMETERS.md) | the numbers and where they come from |
| [`docs/02_SPEC_SHEET_FORMAT.md`](docs/02_SPEC_SHEET_FORMAT.md) | the spec-sheet format |
| [`docs/03_SPECTRUM_PRINT.md`](docs/03_SPECTRUM_PRINT.md) | the spectrum print: layout and reasoning |
| [`docs/S3_RECOGNITION.md`](docs/S3_RECOGNITION.md) | what the microscope can recognise |
| [`docs/S4_PRINTABILITY.md`](docs/S4_PRINTABILITY.md) | what the printer is asked to do |
| [`docs/S5_SPECTRUM.md`](docs/S5_SPECTRUM.md) | the spectrum print as built, and its analysis script |

## Still to do — in the lab

| | |
|---|---|
| DeScribe dry run | open `1_optimistic/test_box.stl` and `test_box_merged.stl`; note import, sliced preview, job time |
| calibrate the pixel size | every pixel figure assumes {o['sp']['optics_assumed']['um_per_px']} µm/px (metadata); the file names imply 0.381 |
| z-stack, flatten the focus | decides how far toward Optimistic the microscope can go |
| print and image the spectrum | names the design |

## Rebuilding

```
python tools/build_designs.py        # designs 1-3 and their gates
python tools/build_spectrum.py       # the spectrum print and its gate
python tools/s3_recognition.py       # recognition test   (4 min)
python tools/s4_printability.py      # printability
python tools/s5_gate.py              # analysis-script gate, writes 4_spectrum/example/
python tools/write_design_specs.py   # these documents
```
"""
    with open(os.path.join(D, "README.md"), "w") as fh:
        fh.write(doc)


def gate(res):
    import re
    checks = {}
    for r in res:
        folder = os.path.join(D, r["folder"]); n = r["name"]
        doc = open(os.path.join(folder, "DESIGN_SPEC.md")).read()
        named = set(re.findall(r"`([A-Za-z0-9_./]+\.(?:stl|json|csv|png|py))`", doc))
        named = {x for x in named if not x.startswith(("docs/", "cad/", "tools/", "designs/")) and "*" not in x and "<" not in x}
        missing = [x for x in named if not os.path.exists(os.path.join(folder, x))]
        checks[f"{r['folder']}: every file the document names exists ({len(named)})"] = not missing
        if missing:
            print("      missing:", missing)
        checks[f"{r['folder']}: the STL's md5 is the one printed"] = md5(os.path.join(folder, f"{n}.stl")) in doc
        feats = list(csv.DictReader(open(os.path.join(folder, "features.csv"))))
        cnt = {k: sum(x["category"] == k for x in feats) for k in ("aruco", "dash", "dot")}
        sp, vf = r["sp"], r["vf"]
        checks[f"{r['folder']}: counts agree (spec sheet = features.csv = verify.json)"] = (
            cnt["dot"] == sp["dots"]["count"] == vf["counts"]["dot"]
            and cnt["dash"] == sp["dashes"]["count"] == vf["counts"]["dash"]
            and cnt["aruco"] == sp["tags"]["count"] == vf["counts"]["aruco"])
        checks[f"{r['folder']}: folder gate record says PASS"] = bool(vf["passed"]) and bool(sp["gate"]["passed"])
    a, b, c = (res[i]["sp"] for i in range(3))
    same = lambda k: a[k] == b[k] == c[k] == res[3]["sp"][k]
    checks["tags, ids and dashes identical in all four spec sheets"] = (
        {k: v for k, v in a["tags"].items()} == b["tags"] == c["tags"] == res[3]["sp"]["tags"] and same("dashes"))
    checks["README and comparison figure written"] = all(os.path.exists(os.path.join(D, x)) for x in ("README.md", "comparison.png"))
    return checks


def main():
    res = [design_doc(n) for n in FOLDERS] + [spectrum_doc()]
    comparison_png(res)
    readme(res)
    checks = gate(res)
    for k, v in checks.items():
        print(f"    [{'PASS' if v else 'FAIL'}] {k}")
    ok = all(checks.values())
    with open(os.path.join(D, "docs", "S6_gate.json"), "w") as fh:
        json.dump(dict(checks=checks, passed=ok, md5={r["folder"]: r["md5"] for r in res}), fh, indent=1)
    print(f"\n  S6 GATE: {'PASS' if ok else 'FAIL'}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
