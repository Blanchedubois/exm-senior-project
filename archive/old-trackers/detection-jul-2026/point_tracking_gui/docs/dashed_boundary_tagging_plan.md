# Implementation Plan — Tagging the Dashed Boundary (single-tracker robust)

**Goal.** Bring the two capabilities we just built for the dots — (1) anchoring from a **single**
ArUco tag, and (2) **region-grow** that follows the warp — to the **dashed box boundary**, so every
visible dash is given a stable, absolute tag even when only one tag is in view.

This document is a plan (think-through), not the implementation.

---

## 1. Why the current dash tagging fails (and why it's harder than dots)
`measure.tag_dashes` today:
- defines each box edge from `grid.nodes` **image positions**, and
- assigns each detected dash to the nearest edge, indexing it by **arrival order**
  (`assigned[key] += 1`).

Both break for a single tracker:
1. For 1–2 tags the far node positions come from the **drifted global transform** (region-grow
   only refined `box_homographies`, not the node records) → edges are in the wrong place → dashes
   attach to the wrong edge.
2. The index is **iteration order**, not a position — so it is not a stable/absolute label at all.

And dashes are structurally different from dots in three ways that must shape the design:
- **They are a 1-D lattice on the box edges** (the node lattice), not a 2-D interior lattice.
- **The reference does not enumerate them.** `grid_metadata` stores the dash *pattern*
  (`boundary_dash_um`, `boundary_gap_um`) but no individual dash centres (unlike `box.dots`).
- **Their spatial model under expansion is subtle** (next section).

---

## 2. The physical subtlety — think it through
How does a dash centre move as the gel expands? Two candidate models:

**(a) Material point.** The dash centre expands with the gel, exactly like a dot: undeformed
centre `p_um` → image via the same box transform. True if the boundary is a scribed line in the
gel.

**(b) Rigid-offset (what our simulator does).** Dashes are rigid marks placed a **fixed**
clearance `off` from the (rigid) tag, with the **spacing** growing as `λ`. So along an edge the
k-th dash sits at arclength `off + dash/2 + k·(dash+gap)·λ` — the *spacing* expands but the
*first-dash offset stays rigid*.

These diverge a lot. If we predict dash positions with the material-point model but the marks are
rigid-offset, the arclength error of dash k is
`≈ (λ−1)·(off + dash/2)·camera_ppu`. With `off≈7 µm`, `λ=5`, `camera_ppu≈8` that is **~260 px** —
many dash periods, i.e. a gross mis-index. **So we cannot rely on absolute position-matching
against an expanded-reference prediction; the offset model is unknown for real data.**

**Consequence for the design:** work in each **edge's own 1-D coordinate** and index **relative to
the node anchor**, measuring the dash spacing from the detected dashes themselves — exactly the
"measure the lattice from the features" principle we used for the single-tag dots. Absolute
position of a dash is model-dependent; its **order from the node** is not.

---

## 3. Approach — edge-local 1-D indexing, anchored at the node

For each box edge `(A → B)` (A, B are adjacent nodes):

1. **Accurate edge geometry (the enabler).** Get A, B image positions from the **region-grown**
   transforms, not the drifted global ones (§4). The edge is the segment A→B.
2. **Assign dashes to the edge.** A detected dash belongs to this edge if its perpendicular
   distance to the segment is small (< a fraction of the local dash period) and its foot-point lies
   within `[0, L]`. Cross-check the dash's **orientation** against the edge direction (a dash lies
   *along* its edge) to reject dots/noise and resolve corner ambiguity.
3. **Project to 1-D.** For each assigned dash, `t = ((q − A)·û)`, arclength from A along the edge.
4. **Estimate the local dash lattice** from the detected `t`'s (self-contained, model-free):
   `period = median(diff(sorted t))`; the run of `t`'s gives the spacing even if the offset model
   is (a) or (b).
5. **Index from the node.** `k = round((t − t0) / period)`, where `t0` is the arclength of the
   dash nearest the node's first-dash position. This yields the absolute dash index `k = 0,1,2…`
   from A. **Gaps** (a missing dash) show up as a `~2·period` jump and are handled by the `round`
   (indices simply skip), so a dropout does not shift every later label.
6. **Validate against the reference count.** The reference gives how many dashes an undeformed
   edge holds, `K` (from `off, dash, gap, box_um`, §5). Assert `max(k)+1 ≤ K` and flag edges whose
   detected count is far from expected (occlusion / detection failure).
7. **Tag** `(box_i, box_j, edge, k)` — a stable absolute label. Shared edges (a box's right edge =
   its neighbour's left) are de-duplicated by keying on the **canonical node pair** `(idA, idB)`
   with `idA < idB`, so each dash is tagged once.

This reuses the region-grow's warp-following transforms for the geometry, and the node (from a
single tag, propagated by region-grow) as the indexing anchor — i.e. **both changes, applied to
the boundary**.

---

## 4. Prerequisite: region-grow must also refine the NODES
Region-grow currently updates `box_homographies` only; node records still hold the drifted global
prediction. Add a post-pass in `reference.map_grid`:
- For each node, collect the region-grown transforms of the (≤4) boxes it corners; predict its
  image position with each and take the **mean** (or the highest-confidence box).
- Update `NodeRecord.img_xy_px` and set `status="region_predicted"`.

This gives accurate box edges for dashes **and** improves the grid overlay / dot node markers for
the single-tag case (a general win). No change to the dot tagging itself (that already uses the
box transforms).

## 5. Reference dash lattice (per edge)
Add `reference.edge_dashes(reference)` computing, for each unique edge (node pair), the undeformed
1-D dash centres and count `K` from the config, matching the toolkit's generator exactly:
`off = marker_um/2 + boundary_gap_um`, `period0 = boundary_dash_um + boundary_gap_um`, centres at
`off + dash/2 + k·period0` for `k` while `centre + dash/2 ≤ box_um − off`. (Compute in `reference`
now; optionally bake dash centres into `grid_metadata` via `generate_grid` later, as we do for
dots, to keep one source of truth.) This supplies the expected count `K` and the nominal spacing
used to seed §3.4.

## 6. Module changes
```
gridtrack/
  reference.py   + edge_dashes(); + region-grow node re-prediction in map_grid (§4)
  measure.py     tag_dashes REWRITTEN (§3): edge assignment by distance+orientation, 1-D
                 projection, node-anchored spacing index, reference-count validation, canonical
                 edge de-dup. detect_dashes unchanged (already elongation-filtered).
  lattice.py     (optional) _edge_index() helper for the 1-D spacing/index maths, reused/testable.
```
`FeatureTable` dash rows already carry `edge` + `local_i` (use `local_i` = the index `k`); add
`edge_key` (canonical node pair) for global uniqueness. No GUI change needed — Stage 4 draws dash
markers already; they'll simply be correctly tagged.

## 7. Edge cases (thought through)
- **Only part of an edge in view** (high λ): index from the node still works for the visible
  dashes; if the node itself is off-frame, fall back to spacing-only relative indexing and flag
  `edge` as `node_offscreen` (no absolute k).
- **Missing / merged dashes:** handled by the `round(Δt/period)` indexing (skips indices) rather
  than by counting; report per-edge detected-vs-expected.
- **Corner ambiguity:** a dash near a node could belong to two edges — resolve by orientation
  (parallel to which edge) and smaller perpendicular distance.
- **Dashes vs dots confusion:** keep the `detect_dashes` elongation filter; additionally require a
  dash to lie near an edge line (rejects elongated noise in box interiors).
- **Region-grow didn't reach a box:** its edges are untagged (flagged) — same coverage contract as
  the dots.

## 8. Validation (simulator is ground truth)
`../expansion_camera_sim`: the boundary is rendered with the rigid-offset model (§2b), so it
directly tests the model-robust indexing.
- **Single tag (`l5`, `l4`):** dashes on region-grown edges get a stable `(edge, k)`; assert the
  per-edge index sequence is monotonic, unique, gap-consistent, and `≤ K`.
- **Consistency across λ:** the same physical dash keeps the same `(edge_key, k)` from `l1`→`l5`
  (join on the tag across frames, like the dot pairing) — this is the real correctness test.
- **Node re-prediction:** region-predicted node positions agree with detected ones where both
  exist (< a few px).

## 9. Phases
1. **D1 — node re-prediction** in `map_grid` (§4); verify accurate edges on `l5`.
2. **D2 — `edge_dashes` reference** (§5) + unit test of counts/spacing vs the toolkit generator.
3. **D3 — rewrite `tag_dashes`** (§3): edge assignment + orientation + 1-D node-anchored indexing
   + validation. Test single-tag `l5`/`l4`.
4. **D4 — cross-λ consistency test** (dash keys stable `l1`→`l5`) + flags for partial/failed edges.

## 10. Open items
- Whether to bake dash centres into `grid_metadata` (single source of truth) vs compute from config
  (no regeneration) — recommend compute-now, bake-later.
- Absolute `k` when the anchoring node is off-frame — relative-only vs inferring the offset from a
  neighbouring solved edge.
- Whether real printed boundaries follow model (a) or (b) §2 — the edge-local method is robust to
  both, but if (a) holds we can additionally position-match for a small accuracy gain.
