# Implementation Plan — Tiered ArUco Tagging (down to a single marker)

**Goal.** Make Stage 3 (`gridtrack.reference.map_grid`) tag every visible dot from **whatever
ArUco markers are in frame — even a single one**. At large expansion most tags leave the field
of view, so the pipeline must degrade gracefully: use a global fit when ≥3 tags are visible, an
exact two-point fit with 2, and a **single-marker local-lattice** method with 1. Output is
unchanged downstream: per-box transforms + node records that Stage 4 (`measure`) consumes as it
does today.

## Decisions (locked in with the user)
| Question | Choice |
|---|---|
| Local spacing for the 1-tag case | **Measure it from the detected dots** (locally-regular lattice) |
| Method tiering | **1 / 2 / ≥3** split |
| Reach from a single tag | **Region-grow with a confidence cutoff** |
| Zero tags in frame | **Flag / require ≥1 tag** |

---

## 1. Why this is needed (the current gap)
`reference.map_grid` today hard-requires **≥3 tags** (`if len(ref_pts) < 3: raise`) and
`box_homographies` needs a box's **4 corner tags** (detected or globally-predicted). With 1–2
tags there is no global transform and no box homographies → **nothing is tagged**. But each tag's
subpixel corners already fix a *local* position **and** orientation (the tag is axis-aligned with
the grid; `corner_TR − corner_TL` is the grid's local +x), so one tag is enough to anchor.

## 2. The one physical subtlety
A tag is **rigid** — it does not expand — so its pixel size gives only the **camera magnification**
(`side_px / marker_um` = px/µm), *not* the local expansion `λ`. The dots between tags *do* expand.
So from a single tag we know position + orientation + magnification, but the **local dot spacing**
must come from the **detected dots themselves**. That measured spacing `pitch_px` corresponds to
`dot_pitch_um`, giving the full local scale `s = pitch_px / dot_pitch_um` (= camera px/µm × λ_local),
and hence `λ_local = s / (side_px / marker_um)` for reporting.

---

## 3. Decision flowchart

```
Stage 2 detect  →  N = number of decoded tags in frame, each with corners+orientation
│
├─ N ≥ 3 : GLOBAL FIT               (existing, made non-fatal)
│           RANSAC similarity/affine/homography (ref µm → img px)
│           → predict every node → per-box homographies
│
├─ N = 2 : TWO-POINT SIMILARITY
│           2 known nodes ⇒ exact scale s, rotation θ, translation t
│           orientation cross-check (both tags + the node-to-node direction agree)
│
├─ N = 1 : SINGLE-TAG LOCAL LATTICE      ← new
│           tag ⇒ node (i,j), ref (x,y)µm, image centre, local axes e_x,e_y, camera px/µm
│           measure local pitch_px from nearby dots ⇒ scale s = pitch_px / dot_pitch_um
│           seed similarity T₁: img = centre + s·[e_x|e_y]·(p_µm − node_µm)
│
└─ N = 0 : FLAG (no absolute anchor) → GridModel with status="unanchored"; Stage 4 skipped
```

**Then, for N ∈ {1,2,≥3}:** a shared **region-grow** propagates the seed transform box-by-box
across the frame, refining locally to follow the warp, and stops where dot matches fail
(§4f). The result — per-box transforms + node predictions — feeds Stage 4 unchanged.

---

## 4. Method detail

### 4a. Tag frame (`lattice.marker_frame`)
From a detected tag `id`:
- `node_ij`, `node_um` ← `reference.id_to_node[id]`.
- `centre_px` ← mean of the 4 subpixel corners.
- Local axes (unit, image px): `e_x = norm(TR − TL)`, `e_y = norm(BL − TL)`; `R = [e_x | e_y]`.
- Camera scale: `side_px = mean(|TR−TL|,|BR−BL|,|BL−TL|,|BR−TR|)`, `camera_ppu = side_px / marker_um`.

### 4b. Local pitch from dots (`lattice.estimate_pitch`) — the key new estimator
Input: detected dot centroids near the anchor, and the grid axes `e_x, e_y` (from the tag).
- Build a KD-tree of dots; for each dot near the anchor take its k nearest neighbours.
- Rotate each neighbour offset into the tag frame (project onto `e_x, e_y`). For a square lattice
  the offsets cluster at `(±p,0)`, `(0,±p)` (and diagonals `(±p,±p)`).
- `pitch_px` = robust mode/median of the smallest axis-aligned offset magnitudes (per axis; the two
  should agree — report both and their ratio as a squareness check).
- Fallback if too few dots: fall back to `camera_ppu · dot_pitch_um · λ_prev` (λ from a prior frame),
  else flag low confidence.

### 4c. Single-marker seed transform (`lattice.single_marker_transform`)
`s = pitch_px / dot_pitch_um`; seed similarity (ref µm → img px):
`img(p_µm) = centre_px + s · R · (p_µm − node_µm)` — a 2×3 affine `A₁`.
Assumes local uniform expansion around the tag; the region-grow then corrects for warp outward.

### 4d. Two-point similarity (`lattice.two_point_transform`)
Nodes `n1,n2` (µm) at image `p1,p2`:
`s = |p2−p1| / |n2−n1|`, `θ = atan2(p2−p1) − atan2(n2−n1)`, `t` s.t. `n1→p1`.
Compose `A₂`. Cross-check: each tag's own `e_x` angle and the `p2−p1` direction agree within a
tolerance; if a tag disagrees, flag a possible mis-decode and drop it.

### 4e. Global fit (N ≥ 3) — unchanged
`fit_global_transform` (RANSAC similarity/affine/homography). This already handles the warp
gradient and rejects outliers; keep it as the seed for region-grow.

### 4f. Region-grow (shared, `lattice.region_grow`)
BFS over boxes, seeded from the box(es) nearest the anchor(s):
1. Seed the anchor box(es) with the tier's transform (`A₁`/`A₂`/global).
2. For a box: predict its reference dots (from `reference.boxes[b].dots`) into the image with its
   current transform; match to detected dots (nearest within `tol = gate_frac · pitch_px`).
3. **Confidence cutoff:** if `matched / expected ≥ accept_frac`, mark the box *solved*; if it has
   ≥ N_min matched dots, **refit a local affine** for that box from its matched pairs (follows the
   warp), and enqueue its 4-neighbour boxes seeded with this refined transform. Otherwise mark
   *unreached* and do not expand through it.
4. Stop when the frontier is empty. Boxes never reached stay untagged (reported).
- This turns one anchor into a spreading front of locally-refined affines — the mechanism that
  carries a single marker across a smoothly-warped field, and the thing that *stops* it before it
  drifts into mis-tagging.

### 4g. Orientation consistency (all tiers with ≥1 tag)
- 1 tag: its decoded orientation resolves the lattice's direction & handedness (no 4-fold
  ambiguity — ArUco decodes orientation), fixing which detected-lattice axis is +i vs +j.
- ≥2 tags: verify tag orientations agree (rigid grid) and that inter-tag image displacement matches
  the reference node adjacency; mis-decoded/outlier tags are dropped before fitting.

### 4h. Zero tags
Return a `GridModel` with `method="unanchored"`, no box transforms; the GUI reports "no ArUco
marker in view — cannot assign absolute IDs"; Stage 4 is skipped for that frame.

---

## 5. Data-model changes (`types.py`)
`GridModel` gains:
- `method: str` — `"global" | "two_point" | "single_marker" | "unanchored"`.
- `box_confidence: dict[(bi,bj)->float]` — region-grow match rate per solved box.
- `lambda_local: float | None` — recovered local expansion (single/two-marker tiers).
- (existing `box_homographies` now holds each solved box's **local** transform, whatever tier
  produced it — so Stage 4 is unchanged.)
`NodeRecord.status` gains `"anchor"` for the tag(s) actually used to seed.

---

## 6. Module layout
```
gridtrack/
  lattice.py      NEW — marker_frame, estimate_pitch, single_marker_transform,
                        two_point_transform, region_grow  (headless, pure)
  reference.py    map_grid becomes a TIERED DISPATCHER (N=0/1/2/≥3) that calls lattice.*,
                  then region_grow, and assembles the GridModel. fit_global_transform,
                  box_homographies, transform_points stay.
  measure.py      UNCHANGED — still consumes grid.box_homographies for the authoritative
                  subpixel + Hungarian dot tagging.
```
`map_grid(det, reference, dots_xy=None, ...)` gains an optional `dots_xy` (detected dot centroids)
— **required** for the N=1 tier (pitch estimate + region-grow) and used to refine all tiers. The
GUI/pipeline runs a quick dot detection before Stage 3 (or reuses Stage 4's) and passes it in.

## 7. Integration
- **Stage 2** already gives per-tag corners/orientation — no change (its whole-image "orient
  upright" still works with 1 tag: it uses that tag's angle).
- **Stage 3 GUI panel** gains a read-out: method used (global/two-point/single-marker/unanchored),
  #tags, `λ_local`, #boxes solved, and colours boxes by confidence.
- **Stage 4** unchanged.
- **Expansion-field tool** (`fieldkit`) automatically benefits — high-λ frames that today share
  too few tags will now tag their central dots via the single-marker tier, improving pairing reach.

## 8. Validation (simulator is ground truth)
`../expansion_camera_sim/tiffs`: the fixed-zoom frames lose tags as λ grows, so they exercise
every tier:
- `l1p00` (25 tags) → global; `l2p00` (9) → global; **`l4p00` / `l5p00` (~1 tag) → single-marker**.
- Assert: the single-marker tier tags the visible dots with the **correct (box, i, j)** (compare to
  `grid_metadata` mapped through the known deformation), `λ_local` matches the frame's λ, and
  region-grow stops before mis-tagging (no wrong IDs among accepted dots).
- Assert graceful `method` selection at each N, and `unanchored` on a tag-free crop.

## 9. Phases
1. **T1 — `lattice.py` core:** `marker_frame`, `estimate_pitch`, `single_marker_transform`,
   `two_point_transform`. Unit-test pitch/transform on a sim single-tag crop.
2. **T2 — region-grow:** BFS + local refit + confidence cutoff; test reach/stop on sim.
3. **T3 — `map_grid` dispatcher:** wire N=0/1/2/≥3, assemble `GridModel`, keep ≥3 behaviour
   identical. Validate all tiers on the sim series.
4. **T4 — GUI read-out + confidence colouring** (Stage 3 panel); `fieldkit` picks it up for free.
5. **T5 — polish:** low-confidence flags, squareness/orientation warnings, `λ_local` reporting.

## 10. Open items
- **Pitch estimator robustness** near box boundaries / keep-outs (gaps in the lattice) — the
  KD-tree/mode approach should tolerate gaps; verify on real images.
- **Warp limit for region-grow** — how large a per-box affine change to allow before declaring the
  field too warped to trust (a second cutoff on transform drift, not just match rate).
- **Anchor choice with 1 tag near the frame edge** — corners may be less reliable; prefer the most
  central / largest tag as the seed.
