# S4 — Can the three designs be printed?

*2026-09-29. Script `tools/s4_printability.py`; data `S4_printability.json`; figure
`S4_printability.png`. Mesh builder `tools/mesh_merge.py`.*

**Result: all three pass.** Measured with the same ruler as the reference print — the one thing
known to print and to survive in this gel — none of the three designs asks the printer for
anything harder than the reference already does. What remains is the one check only your slicer
can make: opening the test files in DeScribe (§5).

---

## 1. Against the reference print

| | reference | Optimistic | Medium | Conservative |
|---|---|---|---|---|
| dot spacing | 8.0 µm | 5.0 µm | 6.0 µm | 7.0 µm |
| **smallest gap between any two features** | **1.5 µm** (digit ↔ dot) | **2.875 µm** | **3.875 µm** | **4.875 µm** |
| gap between neighbouring dots | 5.875 µm | 2.875 µm | 3.875 µm | 4.875 µm |
| smallest free-standing feature | 2.125 µm dot | 2.125 µm dot | same | same |
| dot height ÷ width | 0.94 | 0.94 | 0.94 | 0.94 |
| separate solids to write | 7,341 | 18,341 | 12,216 | 8,516 |
| footprint | 74,061 µm² | 103,887 µm² | 76,229 µm² | 59,521 µm² |
| **write time (laser scan length)** | 2.47 m | 3.46 m — **1.40 ×** | 2.54 m — **1.03 ×** | 1.98 m — **0.80 ×** |
| dots per metre of scan | 2,600 | 5,150 | 4,600 | 4,030 |

- **Gaps.** The tightest clearance in the reference is 1.5 µm, between its printed digits and the
  dots beside them, and that printed. The tightest clearance in any of the three designs is the
  dot-to-dot gap itself, and even Optimistic's 2.875 µm is nearly twice the reference's tightest.
  Tags and dashes are further from everything than the dots are from each other (≥ 5.1 µm).
- **Features.** Dots are the same size and the same height as the reference's, so their adhesion
  and their aspect ratio are the reference's. Nothing free-standing is smaller.
- **Write time.** Scan length for a hatched solid (hatch 0.2 µm, slice 0.3 µm) is a proxy — real
  time also depends on scan speed and on the stage and galvo moves between solids — but it ranks
  the prints on one footing. Medium costs what the reference costs; Conservative is 20 % quicker
  while carrying 25 % more dots; Optimistic is 40 % longer for 2.8 × the dots. All three deliver
  1.5–2 × the reference's measurement points per unit of write time.
- **Solids.** Optimistic has 2.5 × as many separate solids as the reference. If your job's time is
  dominated by moves between solids rather than by scanning, its write time will be nearer 2 × than
  1.4 ×. The DeScribe job estimate (§5) will say which.

## 2. The tags

| | all three designs (the tags are identical) |
|---|---|
| tag | 23 µm, 6 × 6 modules of 3.83 µm |
| narrowest solid part along x or y | 3.83 µm (one module) |
| narrowest internal gap (a white module, less its rounded corners) | 2.68 µm |
| finest detail (neck and fillet tips) | 0.44 µm |
| **still one solid if nothing finer than 1 µm prints** | **yes, all 36** |

The necks and fillets are there to blunt the sharp corners where a rigid tag would otherwise
start to crack as the gel swells. They are the only sub-micron detail on the print, and the tags
do not rely on them: every tag is a single connected solid through full-width modules, so if the
fine detail prints blunter than drawn — or not at all — the tag is still one piece and still
decodes. The internal gaps (2.68 µm) are wider than the reference's tightest gap.

## 3. Assumed printer limits

For orientation only — these are typical figures for a 63× objective in IP-Dip, **not measured on
your printer**, and the gate does not rest on them:

| | assumed | tightest in any design |
|---|---|---|
| smallest gap that stays open | ~0.5 µm | 2.875 µm |
| smallest feature | ~0.2 µm | 2.125 µm free-standing; 0.44 µm detail inside a tag |

## 4. The meshes

Two files per design, identical in geometry:

| | `<name>.stl` (box mesh) | `<name>_merged.stl` (manifold mesh) |
|---|---|---|
| how it is built | every footprint rectangle is its own closed box | one closed solid per printed feature |
| overlapping volumes | none | none |
| volume = footprint × 2 µm | yes | yes |
| every solid closed | yes | yes |
| **every edge shared by exactly two faces** | 99.6–99.8 % — the rest are faces that coincide where rectangles abut inside a tag | **100 %** |
| triangles (Optimistic / Medium / Conservative) | 228 k / 154 k / 110 k | 304 k / 206 k / 147 k |

**A correction to the earlier merged files.** The merged STLs made in W11 (in `cad/`) removed the
coincident internal faces but left T-junctions — edges that run past a neighbour's corner without
a vertex there — on 1–3 % of their edges. The surface was closed, but a strict mesh checker would
flag it. The merged files in the three design folders are rebuilt (`tools/mesh_merge.py`) so that
every edge is shared by exactly two faces. **`optimistic.stl` itself is unchanged and still
byte-identical to the existing print; only `optimistic_merged.stl` differs from its predecessor.**
Dots and dashes are single boxes in either style, so the two files differ only inside the tags.

Which to send to the printer: the merged file is the cleaner mesh; use it unless DeScribe
handles the box mesh better.

## 5. The one check that needs you — DeScribe dry run

Each design folder now has a single-box test pair: one box of the pattern with its four tags,
168 µm across, moved to the origin.

| folder | files | dots in the test box | size |
|---|---|---|---|
| `1_optimistic/` | `test_box.stl`, `test_box_merged.stl` | 805 | 0.54 MB |
| `2_medium/` | same names | 540 | 0.39 MB |
| `3_conservative/` | same names | 320 | 0.25 MB |

Open both files of one folder in DeScribe and note: does each import without a repair prompt;
does the sliced preview show the tag as one solid with its modules intact; and what job time does
DeScribe estimate. One folder is enough for the mesh question — the tags are identical in all
three. The job-time estimate, scaled by 25 boxes, replaces the scan-length proxy in §1.

## 6. Gate

| check | Optimistic | Medium | Conservative |
|---|---|---|---|
| zero overlapping features | ✅ | ✅ | ✅ |
| smallest gap ≥ the reference's (1.5 µm) and ≥ 0.5 µm | ✅ 2.875 | ✅ 3.875 | ✅ 4.875 |
| free-standing features no smaller, dots no slenderer, than the reference's | ✅ | ✅ | ✅ |
| every tag one solid without its fine detail | ✅ | ✅ | ✅ |
| narrowest gap inside a tag ≥ the reference's smallest gap | ✅ 2.68 | ✅ | ✅ |
| box mesh closed, volume correct | ✅ | ✅ | ✅ |
| merged mesh manifold, volume correct, no degenerate faces | ✅ | ✅ | ✅ |
| **S4** | **PASS** | **PASS** | **PASS** |

**What S4 cannot tell you:** whether 5 µm-spaced dots print as separate dots on your instrument at
your dose (proximity effects), and whether they stay anchored. The first is visible under the
microscope on the first print; both are what the spectrum print is for.
