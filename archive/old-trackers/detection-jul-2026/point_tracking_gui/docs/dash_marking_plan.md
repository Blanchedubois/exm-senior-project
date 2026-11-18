# Implementation Plan — Mark dashed-boundary centres in Stage 2

> **Status: IMPLEMENTED (all phases).** `lattice.dashes_on_grid` keeps dash centres within
> 0.15·box-pitch of a boundary line; Stage 2 detects them in `run()`, stores the on-grid centres, and
> draws them as **hot-pink ▲** via `canvas.draw_glyph_grid(dash_pts=…)`, behind a "Show dash centres"
> toggle. On the 2.0× frame: 166 dashes detected → **159 marked on-grid, 7 off-line dropped**; the
> triangles sit on the dashed box boundaries along the cyan grid lines.

**Goal.** In Stage 2 (Glyph grid), also detect the **boundary dashes** and mark each **dash centre**
with a **unique-coloured dot**. Only mark dashes that lie **on / close to the box grid lines** (the
dashes ARE the box boundaries), so spurious detections are excluded.

The dashes give an independent set of boundary fiducials (the printed edge marks), complementary to
the dots (box interiors) and the glyphs (fiducial slots).

---

## 0. What we already have
- `lattice.detect_dashes(u8)` → centroids of the solid dash bars (used today only to lock the box-grid
  phase). Its size/solidity filter already isolates dash-shaped blobs from dots and glyphs.
- `fit_box_grid(...)` → the box grid `{u, v, box_pitch, phase_u, phase_v}` whose boundary lines are
  where the dashes sit.
- Stage 2 `run()` overlays dots (amber), box boundaries (cyan), fiducial slots.

## 1. Phase 1 — Headless: dash centres on the grid lines
New `lattice.dashes_on_grid(dash_pts, grid, tol_frac=0.15)`:
- Project each dash centre onto the box axes `u, v`; the **perpendicular distance to the nearest box
  boundary line** is `min(|(pu−phase_u) mod P|, |(pv−phase_v) mod P|)` wrapped to `[−P/2, P/2]`.
- Keep dashes whose distance `< tol_frac × box_pitch` — i.e. **on / close to a grid line** — and return
  their centres (plus how many were dropped as off-line).
- The dash **centre** is the connected-component centroid `detect_dashes` already returns (the middle
  of the bar), which sits on the boundary line by construction.

## 2. Phase 2 — Stage-2 overlay (unique colour)
- In `GlyphGridPanel.run()`: after the grid is fit, compute `dashes = detect_dashes(u8)` →
  `dashes_on_grid(dashes, grid)`; store on the panel.
- Add a **"Show dash centres"** checkbox (default on).
- Draw the dash centres in a **unique colour not used by any other overlay** — hot-pink `▲` (dots are
  amber ●, grid lines cyan, number slots amber +, letter slots green ◆). Add a `dash_pts` argument to
  `canvas.draw_glyph_grid` so they render in the same pass (which clears/redraws overlays).
- Summary line reports how many dash centres were marked (and how many dropped as off-line).

## 3. Phase 3 — Validation & polish
- Visual: the pink triangles should sit **along the dashed box boundaries**, on the cyan grid lines,
  with none floating in box interiors or on glyphs.
- Headless count on the 2.0× frame; confirm marked dashes ≈ the visible boundary dashes and that
  off-line spurious ones are dropped.
- Keep `tol_frac` a sensible constant (0.15); expose later only if needed.

## 4. Notes
- Uses the *approximate* box grid from `fit_box_grid` (available at Detect-grid time) — good enough
  because dashes lie right on the boundaries and that grid's phase was derived from them.
- Purely additive: no change to dots, glyphs, registration, or later stages.
