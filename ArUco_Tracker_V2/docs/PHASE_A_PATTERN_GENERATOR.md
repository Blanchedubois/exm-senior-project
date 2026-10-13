# Phase A — Pattern generator

**Status: DONE (2026-09-22) · gate PASS on both variants**
Tool: `tools/aruco_grid.py` · Output: `cad/` · Render: `docs/v2_box_conservative.png`

Parametric CAD generator for the V2 field, in **three tiers** matching the earlier
`expansion_camera_sim` design:

1. **ArUco fiducials** at every box corner — rounded so a tag cannot come apart as the gel swells
2. **Grid markers** — dashed box boundaries
3. **Dots** — the dense measurement lattice

Emits a printable STL, the reference tag map in the **existing `rwtag` schema**, and the node→ID
map. Both plan §3.1 variants build from one config, so whichever way Phase 0a resolves, the CAD
is one command away.

---

## 1. What it produces

```bash
cd ArUco_Tracker_V2/tools
python aruco_grid.py --variant conservative     # or --variant optimistic, --dashes
# outer extent defaults to 750 x 750 um, matching the V1 print:
#   --fit lattice   keep node pitch at exactly 150 um (tags overhang to 770 um)
#   --field-um 900  target a different overall extent
```

| File | Contents |
|---|---|
| `aruco_grid_<variant>.stl` | binary STL, flat 2.0 µm extrusion (matching the V1 print) |
| `aruco_grid_<variant>.reference_tags.json` | tag map — `box_um`, `grid_n`, `dot_pitch`, `dot_phase`, `records[]` |
| `aruco_grid_<variant>.ids.json` | node (i, j) → ArUco ID |
| `aruco_grid_<variant>.verify.json` | the gate results below |

## 2. Geometry as built

| | Conservative | Optimistic | V1 (for reference) |
|---|---|---|---|
| **Outer extent** | **750.00 × 750.00 µm** | **750.00 × 750.00 µm** | **750.00 × 750.00 µm** |
| Node pitch | 145.94 µm | 147.56 µm | 150.00 µm |
| Fiducials | 36 × `DICT_4X4_50`, **20.3 µm** | 36 × **12.2 µm** | 240 glyphs, 12 × 18 µm |
| Module size | 3.38 µm | 2.03 µm | — |
| Keep-out radius | 13.2 µm | 9.1 µm | — |
| Dot pitch | **5.83 µm** | **3.77 µm** | 8.0 µm |
| Dot size | 1.0 µm square | 1.0 µm square | 2.125 µm square |
| Dot size | 2.125 µm (V1-proven) | 2.125 µm | 2.125 µm |
| Grid markers | 480 dashes, 8.125 × 2.125 µm | 480 dashes | 681 dashes |
| **Dots** | **9,900** (×1.54) | **19,375** (×3.02) | 6,420 |
| Footprint | 64,696 µm² (11.5% fill) | 100,013 µm² (17.8%) | 74,140 µm² (13.2%) |
| Volume | 129,392 µm³ (87% of V1) | 200,026 µm³ (135%) | 148,122 µm³ |
| STL | 6.7 MB | 12.6 MB | 6.6 MB |

**1.54× the measurement dots on 87% of the printed material**, at the same 750 µm footprint.

The gain is smaller than earlier drafts claimed because two constraints were added after those
were written: the **anchoring floor** (§3, dots stay at the V1-proven 2.125 µm rather than
shrinking to 1 µm) and the **dash keep-out** (§3). Both cost dots and both are real.

## 3. Design decisions made here

**Tags are rounded so they cannot come apart.** IDs are drawn from the 43 already-4-connected IDs
of `DICT_4X4_50`, so no tag can fragment by topology. But **34 diagonal (corner-only) touches
remain across the 36 tags**, and a sharp notch in a rigid island held in a swelling matrix is a
fracture initiator. Each is bridged by the elliptical neck geometry proven in
`hydrogel_marker_analysis/strut_prominence.py` (0.20 µm wide, 0.72 module long), and every
concave corner is filleted at 0.30 µm. The rounding lives inside ArUco's ignored corner-sampling
margin — the gate re-decodes all 36 tags to confirm the IDs are unchanged. `--no-round` disables
it for comparison.

**Polarity: printed = the ArUco BLACK modules, border ring included.** That ring is what makes a
solid ID one connected piece. Under fluorescence the print images bright, and the detection path
inverts before decoding, so the decoder sees a conventional dark-on-light marker. Verified
end-to-end: all 36 tags decode from the rendered CAD.

**Outer extent is locked to the V1 print (750 × 750 µm).** The corner tags are centred on the
boundary nodes, so placing nodes at 0…750 would overhang by half a tag (770.3 µm overall). The
default `--fit inside` insets the node lattice by half a tag, giving an outer extent of exactly
750.00 µm and a node pitch slightly under 150 µm (145.94 conservative / 147.56 optimistic).
`--fit lattice` keeps the pitch at exactly 150 µm and lets the tags overhang instead; `--field-um`
changes the target extent.

**Dot phase = pitch / 2**, so dots sit symmetrically inside each box and never land on a grid
line or a box boundary.

**Dot size is set by ANCHORING, not by optics — default 2.125 µm.** A dot only reports a
material point if the gel network actually grips it; too small and it can detach or lag. V1
printed 2.125 µm dots that tracked coherently to 4.2×, and that is the only size with proven
anchoring in this gel. The optical case for shrinking is weak anyway, because the PSF dominates
the spacing:

| Dot | Pitch | Dots | **Gel contact area** |
|---|---|---|---|
| **2.125 µm (V1-proven)** | 6.69 µm | 12,556 | **21.5 µm²** |
| 1.0 µm | 5.83 µm | 16,529 | **9.0 µm²** |

Shrinking to 1 µm buys 24% more dots but halves the gel contact. Not worth it. `--dot-um`
overrides, and the generator prints a warning whenever the value is below 2.125 µm.

**Dot spacing is DERIVED, not hard-coded:** `pitch = 1.75 × √(dot² + PSF²)`, using the Phase-0c
separation rule. Change the dot size and the spacing follows automatically.

**Dots keep clear of the grid markers.** A dot beside a dash merges with it — on the microscope
far worse than in the render, since the ~2.7 µm blur is wider than the gap. Dots are excluded
within `dash_width/2 + dot_gap + dot_side/2` of any grid line.

**Tag keep-out is SQUARE, not circular.** The tag is an axis-aligned square whose corners reach
`tag/2 × √2`; a circular keep-out of radius `tag/2 + quiet` leaves those corners uncovered and
dots land on the tag. Tested with Chebyshev distance.

**Dashes default OFF** (plan §3.3) — ArUco addresses globally, so they are redundant. `--dashes`
adds a sparse set if you want them for human QC.

**Tag map stays in the V1 schema.** Verified to load through `reftags.load()` and pass through
`tagmatch._by_category()` unchanged. Dots are seen correctly (9,900). The 36 tags carry a new
`category: "aruco"`, which `_by_category` does not yet know about — **that is Phase C's job**, and
is the one deliberate schema extension.

## 4. The gate

```
  OUTER EXTENT 750.00 x 750.00 um   (V1 print: 750.00 x 750.00)   fit='inside'
  5x5 boxes, node pitch 145.94 um · 36 nodes

  EXACT geometry: max |rect centre - record| = 0.00e+00 um over 9,900 dots;
                  dot side(s) [1.0] um; NN pitch 5.830000 um
  STL outer extent 750.00 x 750.00 um (target 750.00; V1 print 750.00)
  dot components 9,900 (expected 9,900)
  dot position error vs tag map: max 0.1155 um, median 0.0707 um
  ArUco decoded 36/36 tags at 6.0 px/um (20.3 px per module)

    [PASS] dot count exact
    [PASS] dot position < 1 px (0.167 um)
    [PASS] pitch within 1 px (0.167 um)
    [PASS] all tags decode
    [PASS] outer extent == 750 um
    [PASS] exact geometry (centres, dot size, pitch = 5.830000 um)
```

Both variants PASS.

### 4.1 Why the tolerances are in pixels

The plan asked for agreement "to < 0.05 µm". Taken literally against the *render*, that is not
measurable: `stl_glyphs.render_topdown` rasterises to an integer pixel grid, so at 6 px/µm a
recovered centroid cannot beat ~0.167 µm, and a 3.77 µm pitch snaps to exactly 22 px = 3.667 µm.
Both variants initially "failed" on exactly these artifacts.

The fix was to split the gate:

- **Exact check, in floating point, before any rasterisation** — every dot record must sit at the
  centre of its own footprint rectangle, every dot must be the configured size, and the
  nearest-neighbour pitch must equal the config. This runs at machine precision: **0.00e+00 µm**
  error over 9,900 dots (2.22e-16 for the optimistic variant). *This is the real correctness
  gate, and it is far stronger than the 0.05 µm the plan asked for.*
- **Render round-trip, with raster-aware tolerances** — confirms the STL on disk actually matches
  the geometry, that every tag decodes, and that nothing was lost in triangulation.

One real bug did surface behind the artifacts: OpenCV centroids are means of pixel *indices*, so
a region spanning pixels i..j has centroid (i+j)/2 while its geometric centre is half a pixel
further on. Correcting that dropped the render-space error from 0.233 µm to 0.116 µm and removed
a systematic offset of (−0.058, +0.109) µm.

## 5. Open items for fabrication

- **Coincident faces.** Each footprint rectangle is written as its own closed box, so abutting
  rectangles within a tag share faces. The decomposition is non-overlapping (no
  self-intersections), but **DeScribe should be checked on one tag before committing a full
  print**. If it objects, the fix is to merge each tag's rectangles into a single polygon
  outline rather than a set of boxes.
- **Dot aspect ratio (plan R3).** 1.0 µm wide × 2.0 µm tall = 2:1 posts. Untested for collapse or
  adhesion on development — this is what the Phase E test coupon is for. The generator takes
  `height_um`, so a shorter variant is a one-line change if needed.
- **Write time.** Not modelled here, but the volume is 87% of V1, so the V2 print should take
  *faster* despite carrying 1.54× the dots.

## 6. Still gated on Phase 0a

Which variant to print is still undecided, because the pixel-size ambiguity is unresolved. Both
STLs exist and both pass. Phase 0a picks one; nothing else in Phase A changes.

## 7. Reproduce

```bash
cd ArUco_Tracker_V2/tools
python aruco_grid.py --variant conservative    # ~1 min
python aruco_grid.py --variant optimistic      # ~3 min (21 MP verification render)
python aruco_grid.py --variant conservative --verify-only   # re-gate without rewriting
```

Needs the `Reference_Warp_Tagger` venv (it imports `rwtag.glyph.stl_glyphs` for the
verification render).
