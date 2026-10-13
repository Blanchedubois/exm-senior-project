# Reference-Warp Tagger — Stage 4 Implementation Plan
### Reference-warp tagging: every filtered point gets its unique design tag

**Project:** `Reference_Warp_Tagger/` · **Scope:** Stage 4 (a fourth tab — the app's namesake)
**Ported from:** `Old_Trackers_Detection/point_tracking_gui/refwarp/` (validated system)
**Consumes:** Stage-1 corrected image · Stage-2 `DetectResult` (fit + registration) ·
Stage-3 `FilterResult` (kept dots/dashes) · **Written:** 2026-07-17

> **Decisions locked (2026-07-17):** (1) the tab tags the current frame **and** includes a
> built-in headless **series batch** (sidecar-driven, ascending expansion) for coreg rescue,
> pairing and strain; (2) **strain table + plot ship now**; (3) baseline = **lowest accepted
> expansion, automatic**; (4) frames failing acceptance are **rejected loudly** with the
> reason — rescue is a manual Stage-2 anchor + re-tag; no silently-wrong numbering enters
> pairing/strain.

---

## 0. Where this fits

| Stage | Goal | Status |
|---|---|---|
| 1 | Correct optics. | done |
| 2 | Detect & identify; number & orient the boxes. | done |
| 3 | Filter false-positive dots & dashes. | done |
| **4** | **Warp the tagged STL reference onto the processed image and give every *filtered* point its unique, grid-relative tag; pair frames by tag; measure expansion.** | **this document** |

**The core requirement (user-specified):** tagging happens on the **processed image** (Stage-1
output) and on the **filtered points / grid** (Stage-3 output). Both are already first-class
state (`corrected_image`, `DetectResult`, `FilterResult`), so Stage 4 plugs into the existing
pipeline with no re-detection.

---

## 1. The idea (why reference-warp)

Build the tag map **once, from the Nanoscribe STL** — every printed feature gets a unique,
grid-relative tag with its exact design position in µm. Then, per expansion image, **fit a
warp from the reference design frame onto the image** and give each detected point the tag of
the *nearest warped reference point of the same category*. Pairing across expansions is then
automatic: two frames tagged from the same reference share tags on the same physical points.

This inverts the older approach (compute a tag independently per image and hope they agree).
The reference is the single source of truth; the warp carries the tags in — so per-image
dot-index quantisation brittleness disappears, and **glyphs the classifier can't read still
get tagged by position** (the memory-noted design).

**This architecture is already validated** (old-app results, hardening review): strain within
~1σ of expected across 1.5×–4.2×, self-consistent under composition, 2–4× tighter scatter
than the previous system, warp residual ~3 px (<0.1 dot pitch) on 1.5×.

---

## 2. The reference tag map (`reference_tags.json` — copy, don't rebuild)

`reference/reference_tags.json` (~1 MB, built once from
`Markers CAD/base_design_for_nanoscribe_2026_01_14.stl`) — pure data; **no STL processing at
runtime**. Copy it from the old app. Design ground truth: 750×750 µm, 5×5 boxes of 150 µm;
interior dots on a *global* 8 µm lattice at phase 5 µm; 10 dashes per box-edge at 12+14k µm.

| Tag scheme | Category | Count | Meaning |
|---|---|---|---|
| `node\|{i}_{j}` | node | 36 | intersection dot at (150i, 150j) |
| `dash\|V{i}\|{m}` / `dash\|H{j}\|{m}` | dash | 600 | dash m=10·span+k on grid line i/j |
| `dot\|B{N}\|{di}_{dj}` | dot | 6400 | interior dot, box-relative lattice index |
| `num\|B{N}\|{slot}\|{k}` | number | ~250 | digit k of box N's number at a slot |
| `let\|B{N}\|{slot}` | letter | ~100 | orientation letter A–D |

`rwtag/glyph/stl_glyphs.py` + `reftags.build()` are ported for **rebuild tooling only**
(regenerating the JSON if the CAD changes), not the runtime path.

---

## 3. What to port (all headless, numpy/OpenCV/scipy — no Qt)

| Module (old `refwarp/`) | Role | Port |
|---|---|---|
| `reftags.py` | load (and rebuild) the reference tag map | **verbatim** → `rwtag/refwarp/reftags.py` |
| `warp.py` | design→image warp: affine seed (from fit+reg) → ICP homography → **TPS** refine; `warp_points` | **verbatim** |
| `tagmatch.py` | one-to-one nearest-neighbour tag assignment per category, gated by dot pitch | **verbatim** (input change §5) |
| `coreg.py` | high-expansion rescue: transfer box numbers from a lower, correctly-registered frame (FOV-constrained design overlap + handedness check) | **verbatim** |
| `strain.py` | per-point local F from k-NN pairs → J = det F → measured expansion mean±σ | **verbatim** |
| `io_csv.py` | per-image tagged CSV + wide pairing CSV | **verbatim** |
| `session.py` | series driver (baseline → direct/auto candidates → accept by overlap) | **adapt** (§6): consume our Stage-1..3 state & sidecars instead of re-detecting internally |
| `app.py` | old standalone GUI | **not ported** — rebuilt as the Stage-4 tab (§7) |

New runtime dependency: none (scipy `RBFInterpolator`/`cKDTree` already required).

---

## 4. The per-frame tagging pipeline

Inputs: `corrected_image` (Stage 1), `DetectResult.fit/model.reg/basis` (Stage 2),
`FilterResult.kept_dots / kept_dashes` (Stage 3), glyph blob positions (Stage 2).

1. **Seed** — `warp.coarse_map`: reference µm → image px through the glyph-fit lattice + the
   solved registration (global affine; good to ~5 px on low expansion).
2. **ICP homography** — iterate: warp reference dots, match to **filtered** detected dots
   (KD-tree, gate 0.5×pitch), `cv2.findHomography(RANSAC)`; repeat ×6.
3. **TPS refine** — thin-plate spline (`RBFInterpolator`, smoothing 1.0, ≤500 control pairs)
   through the homography-matched dot pairs — absorbs the non-uniform expansion that a single
   homography can't (§8-I2: this is also what finally makes the drawn grid hug the dashes at
   the frame corners).
4. **Quality** — `per_det_median` (px), `matched_frac`, `n_pairs`; validity gate: H exists,
   median < ~10 px, handedness == baseline sign.
5. **Tag** — `tagmatch.tag_image`: push every reference tag through the warp; each detected
   feature takes the nearest same-category tag, one-to-one, gated per category
   (dot 0.45 / dash 0.9 / glyph 1.2 ×pitch). Detected sets = **Stage-3 kept** dots/dashes +
   Stage-2 glyph positions.
6. **Overlay** — warped reference **box-boundary lines** (the 6+6 grid lines pushed through
   the TPS, i.e. the definitive "grid following the dashes"), tag markers coloured by kind,
   hover-to-read tag, per-box / per-kind filtering.

**High-expansion path (when Stage-2 registration is wrong/unregistered):** `coreg.auto_register`
aligns this frame's dots (in its own design coordinates) to a **lower, accepted frame's**
design coordinates over the 8 grid symmetries × integer box offsets, transfers box-number
anchors, re-registers, re-fits the warp, and accepts only on low residual + correct
handedness. This is the fix for the memory-noted "3×+ mis-registers box numbers" failure —
and it inherently needs a lower frame (§6).

---

## 5. Improvements over the old app (added to this port)

- **I1 — Tag the *filtered* points.** The old app tagged raw detections; we tag Stage-3
  survivors (user requirement). Fewer false tags, cleaner pairing, and the warp's ICP control
  points are also the filtered dots.
- **I2 — TPS-warped grid as *the* grid overlay.** Stage 2/3 draw an affine (fit-lattice) grid
  that visibly drifts at frame corners (real gel warp). Stage 4's TPS grid follows the actual
  boundaries; once fitted, offer the same overlay back on the Stage-2/3 tabs (a
  "refined grid" toggle) so all stages can show the aligned grid.
- **I3 — Auto-label from filename.** Frames are named `1.5X…`, `2.0X…`; parse the expansion
  factor automatically (editable), instead of the old per-file dialog.
- **I4 — Residual QC overlay.** Colour tagged points by their match residual (px) to spot
  locally-bad warp regions at a glance; report per-frame residual stats in the summary.
- **I5 — Session persistence.** A `stage4` section in the sidecar session (warp params,
  source `direct|auto<-Xx`, acceptance report, residuals) so a tagged series reloads without
  reprocessing; pairing/strain read accepted frames from sidecars.
- **I6 — Honest confidence reporting** (from the hardening review): per-frame `source`,
  `matched_frac`, `per_det_median`, and cross-frame tag-overlap *as a report, not a hard
  gate* — overlap alone cannot prove a numbering (box-relative dot tags repeat across boxes);
  the reliable acceptance signal is coreg's FOV-constrained design overlap + handedness.
- **I7 — Known-limit documentation in the UI:** `let|` (letters) and `node|` (corner dots)
  tags exist in the map but are effectively never matched on real prints (letters print
  faint; corner dots sub-threshold) — the hardening review concluded both are data limits,
  not bugs. The summary states this so missing categories aren't chased as defects.

---

## 6. Single-frame vs series — the one real architectural decision

Tagging is per-frame, but three Stage-4 capabilities are inherently **cross-frame**:
- `coreg` auto-registration (high-expansion rescue) *requires a lower accepted frame*;
- the **pairing table** (tag → position per expansion) needs ≥2 frames;
- **strain** (measured vs expected expansion) needs ≥2 frames.

The app is deliberately single-image (Stages 1–3). **Decided resolution:** the Stage-4 tab
tags the *current* frame, and a **Series** group in the same tab batch-processes the sibling
frames headlessly (each via its own sidecar session → Stage 1–3 params → detect → filter →
tag, ascending expansion order, **baseline = lowest accepted expansion, automatic**),
producing the pairing table, **strain table/plot (in scope)**, and per-frame tagged CSVs.
The current frame's interactive view and the series batch share all code. Frames that fail
acceptance are **rejected loudly** (reason shown, frame kept in the list); the rescue path is
a manual Stage-2 box anchor, then re-tag.

---

## 7. GUI — the fourth tab

- **Tag current frame** button → runs §4 on the loaded frame; summary: n tags by category,
  warp kind (homography/TPS), residual median, matched %, source.
- **View:** image under translucent tag markers (kind-coloured: dot amber, dash pink, num
  cyan, let green), **hover to read a tag**, filter combos (box: all/1–25, kind:
  all/dot/dash/num/let), toggle warped reference grid lines + box numbers.
- **Series group:** list sibling frames + parsed factors (editable); **Process series**
  (headless batch, progress in log); per-frame status `label · source · confidence · n tags`,
  rejected frames shown with their reason.
- **Strain group:** measured vs expected table + trend plot (old Strain tab), from tag-paired
  dots across accepted frames.
- **Exports:** per-image tagged CSV (`tag, category, x_px, y_px`), wide pairing CSV
  (`tag, <label>x_x/_y/_present…`), annotated PNG via the existing toolbar export.

Data contract (`rwtag/refwarp/` + `rwtag/glyph/types.py`):

```python
@dataclass
class TagResult:
    tags: dict            # {tag: (x_px, y_px)} on THIS frame (filtered points only)
    warp: dict            # {kind, H, tps, per_det_median, matched_frac, n_pairs}
    source: str           # "baseline" | "direct" | "auto<-1.5x"
    confidence: str       # acceptance report (I6)
    per_category: dict    # counts + residual stats by dot/dash/glyph
```
Stored on a new `PipelineState.tagging` slot; `AppState.taggingChanged` signal.

---

## 8. Known limits (documented, by design)

- Letters & corner node dots: unmatched on real prints (print-quality data limit — §5-I7).
- High-expansion acceptance is evidence-weighed, not provable from tag overlap (I6); a frame
  that fails all candidates is reported `rejected`, kept visible, and can be rescued by a
  manual Stage-2 anchor + re-tag.
- Strain assumes the baseline (lowest) frame is trustworthy — it sets the handedness sign.

---

## 9. Testing

- **Synthetic round-trip:** warp the reference dots by a known homography+bulge, run
  `fit_warp` + `tag_image`, assert >95 % of tags recover their own point and residual ≈ the
  injected noise.
- **Real-frame:** 2.0× — fit converges (median ≲ 5 px, matched_frac > 0.7), ≥1000 dot tags;
  glyph tags land on the digits (spot-check `num|B13|…`).
- **Series:** process all six frames; assert ≥4 accepted; strain mean within ~2σ of the
  expected ratio per frame (the old app's validated benchmark); composition self-consistency.
- **coreg:** force a wrong registration on 3.0× and confirm auto-register recovers the
  correct offset from 2.0×.
- **GUI smoke (offscreen):** tag → hover map non-empty → exports written → session reload.

## 10. Milestones

1. **M1** — port `reftags/warp/tagmatch/strain/io_csv/coreg` + copy `reference_tags.json`;
   synthetic round-trip green.
2. **M2** — single-frame tagging on Stages 1–3 state; TagResult + tab view (markers, hover,
   filters, warped grid); real-frame test green.
3. **M3** — series batch (sidecar-driven) + coreg rescue + pairing CSV.
4. **M4** — strain table/plot; exports; `stage4` session section; GUI smoke test.
5. **M5** — I2 refined-grid toggle on Stages 2/3; docs + README.

---

## 11. Resolved decisions (confirmed 2026-07-17)

1. **Series scope** — current frame + built-in headless series batch in the Stage-4 tab.
2. **Strain** — table + trend plot ship in Stage 4.
3. **Baseline** — lowest accepted expansion, automatic (the old validated policy).
4. **Rejected frames** — reject loudly with the reason; rescue = manual Stage-2 anchor +
   re-tag. Never admit a best-guess numbering into pairing/strain.
