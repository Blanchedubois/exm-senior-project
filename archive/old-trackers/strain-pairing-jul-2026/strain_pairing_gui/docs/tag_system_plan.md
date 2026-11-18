# Implementation Plan — Canonical Tag System for Pairing

**Problem you identified (correct).** Pairing currently matches points *between* two images by nearest
box-fraction. That is fragile: it depends on both images being processed together, drops points near
box edges (the 18.75-dots-per-box rounding), and breaks when a frame's fraction drifts. The dots
aren't being given a **consistent identity** across expansions.

**Your fix (adopted).** Give every point a **canonical tag** derived from the reference STL geometry —
independent of the image, the expansion, or the FOV. Then pairing is a **join on equal tags**, not a
proximity search. This is the structure-first identity taken to its conclusion.

---

## 0. Impact analysis — which system works

| Property | Current (cross-image nearest-fraction) | Proposed (canonical STL tags) |
|---|---|---|
| Identity of a point | implicit (its match in the other image) | **explicit, absolute** (a tag) |
| Pairing | proximity search between two clouds | **dict join on tag** — O(N), trivial |
| Per-image independence | no (needs both images at once) | **yes** — tag each image alone, join later |
| Edge dots (18.75/box rounding) | lost (~6% even in good boxes) | assigned to nearest ideal node → **kept** |
| Registration drift within a box | erodes matches | absorbed (nearest ideal node) |
| Double counting | greedy one-to-one, ad-hoc | **one-to-one by construction** (tag↔point) |
| N-way pairing (1 initial → many exps) | pairwise, repeated | **one join across all** (tag is the key) |
| Debuggability | opaque | every point carries a human-readable tag |
| **Still requires** | consistent **box numbering** across frames | **same** — the real prerequisite |
| Doesn't fix | genuine non-overlap (different regions) | **same** (e.g. 1.5× vs 3.0×) |

**Verdict:** the tag system is strictly better on every axis except it shares the same hard
prerequisite — consistent box numbers across frames (handled in §1). It directly fixes the
edge-dot / drift losses you saw and makes N-way pairing a join. **Adopt it, replacing the
fraction-matching in `pair.py`.**

---

## 1. Common box numbers (your step 1)
Registration already assigns each in-view box an absolute number (1–25). Take the **intersection** of
box numbers present in the initial and in each expansion — only those boxes can be paired. A frame that
mis-registers (wrong offset) simply shares fewer/no numbers; the existing **Stage-2 manual box anchor**
pins it. (No new work beyond intersecting.)

---

## 2. The three coordinate grids (from the STL) — your steps 2–4

Measured from `base_design_for_nanoscribe_2026_01_14.stl` (box = **150 µm**):

### (a) Dot grid — the fill squares
- Dots sit on a **global 8.0 µm square lattice**; ratio box:dot = 150 / 8.0 = **18.75** (deliberately
  not box-aligned — a uniform fill). So a box holds an 18–19 × 18–19 patch of the lattice, its exact
  phase depending on the box.
- **Ideal positions & tag:** the ideal dot nodes are the lattice nodes. Index each by its **integer
  lattice coordinate** `(Di, Dj)` (in dot-pitch units, in the design frame, anchored to the box grid).
  A box's dots are the nodes whose position falls in that box. Tag → `dot|B{box}|{di}_{dj}` where
  `(di,dj)` is the node's index relative to that box's origin (equivalently the global `(Di,Dj)`; the
  two differ only by the box's integer base). **Grid lines** = the 8 µm lattice lines.

### (b) Fiducial grid — numbers & letters
- Per box, a **3×3 slot grid**: number at the 4 corners (inset ≈23 µm) + centre (75 µm); letters
  A/B/C/D at the edge midpoints (≈27/74/122/123 µm). *(known `FIDUCIALS`.)*
- A number is **1–2 digits**; the two digits sit at ± a fixed digit pitch about the slot centre
  (measure exactly in P1). **Tags:** `num|B{box}|{slot}|{tens|units}` and `let|B{box}|{slot}`.
  **Grid lines** for this system are the 75 µm (half-box) fiducial lines + the digit sub-offset.

### (c) Dash grid — the dashed boundaries
- Each box edge carries **exactly 10 dashes** at **14 µm** spacing, first centre at **12 µm**
  (`x = 12 + 14·k`, k = 0…9). Dashes live on the **box-boundary grid lines** (6 horizontal + 6 vertical
  for the 5×5 grid), not inside a box.
- **Tag:** by grid line to avoid boundary double-counting — `dash|{H|V}{line}|{k}` where `line` is the
  boundary index (from the box numbering) and `k` = 0…9 along it. **Grid lines** = the box-boundary
  lines.

Each grid is a **separate coordinate system with its own grid lines**, exactly as you asked.

---

## 3. Per-image tagging (your step 4) — nearest ideal, no double counting
For one processed image (its filtered dots/dashes/glyphs, each already box-tagged + design-frame
position):
1. Build the **ideal tag set** for every box present (dots, fiducials) and every boundary line (dashes),
   with each tag's **ideal design coordinate**.
2. **Assign one-to-one**: for each ideal tag, take the **nearest filtered point** of the matching kind
   within a cutoff (a fraction of that grid's spacing); each point is used once (bipartite nearest —
   greedy or Hungarian). This is your "closest point to each tag's coordinate" with **no double
   counting**. Points with no nearby tag are dropped (spurious); tags with no point are "absent".
3. Emit a per-image **tagged CSV**: `tag, kind, box_number, coord, x_px, y_px`.

Because a tag is absolute, the *same physical point gets the same tag in every image*.

---

## 4. Pairing = tag join (your step 5)
Load each image's tagged points into a dict keyed by tag. The **wide pairing CSV** is then a simple
outer-join: one row per tag (present in the initial), columns per expansion holding that tag's
`x, y, present`. No proximity search. Strain then consumes the joined pixel positions exactly as now
(the pairs are just cleaner and more numerous). N expansions join in one pass.

---

## 5. Code changes (surgical)
- **`glyphtrack`/new `pairkit.tags`** — build the ideal grids from the STL once, cached to
  `reference/tag_grids.json` (dot pitch/phase, fiducial slots + digit offset, dash line spacing), so the
  app needs no STL at runtime.
- **`pairkit.process`** — after Stage 4, assign a tag to each filtered point (nearest ideal, one-to-one)
  and store it on `PointRecord.tag`; keep `box_number`, `sub_id`, position.
- **`pairkit.pair`** — replace fraction-matching with a **tag join** across the initial + expansions.
- **`pairkit.io_csv`** — per-image tagged CSV + the wide tag-joined pairing CSV.
- **GUI** — unchanged flow; optionally show tag on hover and a per-box "tags matched" count. Strain
  untouched.

---

## 6. Phases (each with a verification check)
- **P1 — Tag grids from the STL. ✅ DONE & VERIFIED.** `pairkit/tags.py` (dot lattice pitch 8.0 µm /
  phase 5.0 µm; fiducial slots + digit half-offset 6.9 µm; dashes 10/edge @ 12 + 14k µm) +
  `reference/tag_grids.json`. Ideal counts: 361 dot nodes / box, 14 fiducial tags / box, 10 dashes /
  edge. *Verified on the STL:* 6507 dots → 6503 unique indices (4 dup, 0.06%); 600 dashes → 600 unique.
- **P2 — Per-image tagging. ✅ DONE & VERIFIED.** `pairkit.tags.assign_tags(point_table)` (nearest ideal,
  one-to-one, cutoff 0.5 × spacing) sets `PointRecord.tag`; `pairkit.process` tags after Stage 4;
  `io_csv.write_tagged` per-image CSV. *Verified:* 1.5× 2742 pts → 2223 tagged (81%), **0 duplicates**;
  2.0× 1669 → 1299 (78%), **0 duplicates**; shared tags 1.5×∩2.0× = 1116 (946 dot, 115 dash, 55 digit;
  letters 0 — recognition sparsity).
- **P3 — Tag-join pairing. ✅ DONE & VERIFIED.** `pair.py` rewritten as a dict join on `tag`
  (`PairingResult` unchanged, so strain/CSV consume it untouched); `io_csv.write_pairing` now tag-keyed.
  *Verified:* **self-join 2223/2223 = 100%**; 2.0× 1116 pairs (946 dot/115 dash/55 digit), **0
  double-counts**; 2.5× 590 pairs, 0 dup; 3.0× → 0 (genuine non-overlap, correct). NOTE: the tag join
  pairs *fewer* dots than the old fraction-matcher (946 vs 1444 at 2.0×) — quantizing an 8 µm lattice
  with ~2–3 µm position noise flips some dots at cell boundaries — but every pair is provably correct
  (unique tag, no proximity mismatch), which is what the numbering fix required.
- **P4 — Wire + strain re-check. ✅ DONE & VERIFIED.** GUI "Pair to initial" already routes through
  `project.pair` → the tag join (no change); added "Export tagged CSVs…" toolbar action +
  `project.write_tagged_csvs`. *Verified* (offscreen GUI + headless): strain holds — 2.0×
  **1.307 ± 0.047** (expected 1.333, global_scale 1.275), 2.5× **1.643 ± 0.036** (expected 1.667,
  global_scale 1.676); trend graph unchanged.

---

## P2b — Tilt/shift fix (lattice-anchored dot indexing) ✅ DONE & VERIFIED
**Problem the user caught:** the first P2 derived each dot's global index by quantising its
**fiducial-fit box fraction** to the 8 µm lattice. That fraction is only good to a few % of a box, and
two images are tilted/shifted differently — so the fraction could differ by up to **0.05 (a full 7.5 µm
dot pitch)**, snapping the same physical dot to a *neighbouring* node (or box) between images. Measured:
after a global similarity fit, 43 % of shared tags were > ½ a dot-pitch off; box-local fractions of
matched tags disagreed by up to 0.05.

**Fix (`tags.robust_dot_indices`, called from `process`):** snap every dot to the image's OWN detected
dot lattice (`refine_basis` → `origin`, `v1`, `v2`; sub-pixel exact) giving integer lattice coords
`(m,n)`; fit the signed permutation `S` relating the lattice to the design frame (least-squares →
rounded, det = ±1 checked); take the **robust per-box median** integer offset between the noisy fraction
index and `S·(m,n)`; final `Di,Dj = S·(m,n) + offset[box]`. Exact within a box (no per-dot jitter),
anchored to the shared design frame. `assign_tags` now reserves these exact dot tags and only
nearest-assigns dashes/glyphs.

**Verified (1.5×→2.0×):** shared dot tags **946 → 1404** (0 duplicates); **per-box** residual after a
per-box similarity fit = median **5.7 px, max 15 px, 0 % over 15 px** (dot pitch ≈ 40 px), i.e. every
shared tag is provably the *same physical dot*; strain unchanged (2.0× 1.307 ± 0.045 on n=1574; 2.5×
1.645 ± 0.033). 2.5× shared dots 484 → 743.

## P5 — High expansions (3.0× and above): registration, not overlap ✅ DIAGNOSED + WORKFLOW
**Finding.** 3.0×/3.5×/4.2× DO overlap the initial (the printed numbers on 3.0× read 8,12,13,14,17,18 —
the same centre boxes as 1.5×), but the **glyph classifier can't read the digits at that scale** (reads
collapse to '0'/'7'/'9' at every rotation), so auto-registration anchors the grid at the wrong absolute
box (centre labelled box 1 instead of 13). Wrong box numbers → tags in the wrong boxes → 0 pairs. This is
the box-numbering-consistency prerequisite (§1) failing, exactly as the user predicted — NOT physical
non-overlap.

**Workflow (works today).** Manual box anchor: open the high-expansion image, in Stage 2 click **Set box
number**, click any box whose number you can read, type it; click **Reprocess current**. Registration
re-numbers from that trusted anchor (weight 6 ≫ the garbage auto-reads) and the exact interactive deskew
is reused so the anchor node lines up.
*Verified 3.0×:* auto boxes [1,2,6] → anchored [8,12,13,14,17,18]; 0 → **285 shared dot tags**; strain
**2.038 ± 0.194** (expected 2.000, n=351 paired).

**Code:** `StrainProject.manual`/`corrections` (per-image), `process_one` applies them; GUI points the
workspace anchor store at `project.anchors(path)` per image and adds a **Reprocess current** action.

## P6 — Auto-registration by geometric alignment (no digit reading) ✅ DONE & VERIFIED
`pairkit/coreg.py`: register a high expansion by aligning it to an already-correct LOWER expansion and
transferring box numbers. Both images' dots, in DESIGN box-coords `(col+fx, row+fy)`, are the same
physical lattice related only by a **signed permutation S + integer box offset t** (a grid symmetry, no
scale — each image's fit normalises its own box pitch). Brute-force the 8 orientations × integer offsets
(`candidates`), score by dot overlap, generate trusted anchors (`anchors_for`), reprocess, and **accept
only when the reprocessed image pairs to the reference with a proper (det>0) local deformation**
(`strain_is_proper`) — iterating candidates until one validates.

Two traps found & handled: (1) the square dot grid is near transpose-symmetric, so a **mirror** alignment
can out-score the correct one — rejected because it makes every strain gradient det<0; (2) `det(S)` does
NOT predict pixel chirality (each image's deskew handedness matters) and `register()` can re-solve to a
different orientation, so chirality is validated **post-reprocess**, not from `S`.
`StrainProject.auto_register(path)`; GUI **Auto-register current** action.
*Verified (fully automatic, deterministic across runs):* 3.0×→2.03, 3.5×→2.34, 4.2×→3.04 (expected
2.00/2.33/2.80), all within ~1σ; earlier expansions unchanged. Manual anchoring (P5) remains as fallback.

## Decisions (locked in)
1. **Dot tag = global 8 µm lattice index** `(di,dj)`, computed from each image's **own detected dot
   lattice** and anchored per box (see P2b — NOT from the fiducial-fit fraction, which is too coarse for
   tilted/shifted frames).
2. **Dash tag = global boundary-line + position** `dash|{H|V}{line}|{k}` (avoids shared-edge double count).
3. **Assignment = nearest point per ideal tag, one-to-one, cutoff 0.5 × grid spacing**; unmatched tags
   absent, unmatched points dropped.
4. **Replace** the fraction-matcher in `pair.py` with the tag join (single code path).

## Open questions (resolved above)
1. **Dot tag coordinate** — index dots by their **global 8 µm lattice coordinate** (anchored to the box
   grid; box-relative index derived from it), which is the cleanest unique key (recommended), or force a
   strictly per-box reset index (identical info, just relabelled)?
2. **Dash tag reference** — tag dashes by **global boundary-line + position** `dash|V3|k`
   (recommended — a boundary is shared by two boxes, so a line-based tag avoids double-counting), or by
   `box + edge + k` with a rule that the lower-numbered box owns the shared edge?
3. **Assignment rule & cutoff** — for each **ideal tag, take the nearest point** within a cutoff of
   **0.5 × that grid's spacing**, one-to-one (recommended); unmatched tags = absent, unmatched points =
   dropped. OK with 0.5× spacing, or tighter/looser?
4. **Replace vs keep** — **replace** the fraction-matching in `pair.py` with the tag join
   (recommended), or keep the old matcher available as a fallback toggle?
