# Implementation Plan — In-App 5-Stage Verify / Tune View (multi-image)

**Goal.** Add a **Verify** view to the Expansion-Field app that lets you **cycle through every
image**, **tune the 5 stage parameters**, and **see each stage's overlays update live** — so you
can QC and fine-tune the tracking on the whole series before pairing.

### Decisions locked in
| Question | Choice |
|---|---|
| Parameter scope | **Per-image overrides** (Stage-1 optics shared; Stages 2–5 per image) |
| Where the 5-stage UI comes from | **Shared `stageui` package** (extract from point_tracking_gui) |
| On selecting an image | **Auto-run all 5 stages** and show overlays |

### Already done (change #1)
This app imports `gridtrack` from `../point_tracking_gui/gridtrack`, so the single-tag Stage 2 fix,
tiered Stage 3, region-grow, and dash tagging are **already active** here (verified: `l5` →
`single_marker`, λ≈4.93, 468 dots + 13 dashes; `fieldkit.pipeline` already feeds dots into Stage 3).
No porting needed. This plan is purely the Verify UI (change #2).

---

## 1. Current state
- **This app** (`expansion_field_gui/app`): a *Setup* panel (shared Stage-1 correction sliders +
  "Run all"), a *Pairing* panel, a *Field* view, and an image list. It has **no per-stage tuning
  or overlays** — you can't see Stage 2/3/4/5 on an image, or adjust their params.
- **`point_tracking_gui/app`**: a full single-image 5-stage tuner — `ImageCanvas` (with
  `draw_detection`/`draw_grid`/`draw_features` overlays), `Stage1..5Panel`, `ReferencePanel`,
  `AppState`. Exactly the UI we want, but for one image and locked inside that app's `app` package.

The two apps already share the headless **`gridtrack`** core; this plan extends that sharing to the
**GUI stage panels**.

---

## 2. Architecture — a shared `stageui` package
Extract the reusable single-image 5-stage GUI out of `point_tracking_gui/app` into
**`point_tracking_gui/stageui/`** (a peer of `gridtrack`). Because this app already puts
`../point_tracking_gui` on `sys.path` (via `fieldkit.__init__`), it can `import stageui` directly —
same mechanism as `gridtrack`. No cross-`app` import collision.

```
point_tracking_gui/
  gridtrack/                     (headless core — unchanged)
  stageui/            NEW        shared GUI building blocks (no app-specific globals)
    __init__.py
    widgets.py                   SliderSpin, Collapsible          (moved)
    canvas.py                    ImageCanvas + overlays           (moved)
    state.py                     AppState / PipelineState wrapper (moved, generalised)
    reference_panel.py           Stage-3 reference schematic       (moved)
    stage1_correct.py … stage5_filter.py   the five panels        (moved)
    workspace.py     NEW         StageWorkspace: bundles canvas + stage nav + stacked
                                 panels + a log hook into ONE embeddable QWidget
  app/main.py         thin shell that embeds stageui.StageWorkspace (behaviour unchanged)
```

**`StageWorkspace(state, log_fn)`** is the key new abstraction — it is exactly what
`point_tracking_gui/app/main` builds inline today (left stage-nav list, `QStackedWidget` of the
five panels, the canvas, wired together), packaged as a single widget so **both** apps embed it.

The panels keep their `(state, canvas, log)` contract; add one signal `paramsChanged(stage:int)`
each emits when a slider/param moves, so an embedder (the Verify view) can persist per-image params
and invalidate downstream stages.

**Refactor safety:** `point_tracking_gui/app/main.py` becomes ~30 lines around `StageWorkspace`;
its existing test suite + a launch smoke test guard the move (V0 below).

---

## 3. Per-image parameter model
- **Shared** (all images, physically the same optics): `project.correction` — vignette, lens,
  `invert`, `clahe_clip` (Stage 1, and the Stage-2 preprocessing it carries).
- **Per-image** (Stages 2–5 adapt to each frame's brightness/expansion):
  a new `ImageParams(measure: MeasureParams, filters: FilterParams, transform_model: str,
  ransac_px: float)` stored as `project.image_params[path]`, defaulting to the project defaults.

`fieldkit.project`:
- `image_params: dict[str, ImageParams]` (default-filled on add).
- `process_one(path)` uses `image_params[path]` (measure/filters/transform) instead of the single
  project-wide `measure`/`filters`. **Pairing is unaffected** — it fits on the tags and joins on the
  absolute dot/dash tags, which don't depend on per-image detection thresholds (only *which* dots
  pass do).
- `project.json` gains a `image_params` block (persist/restore).

Editing a Stage-1 slider writes to the shared `project.correction` (affects **all** images → mark
them stale); editing Stage 2–5 writes to the current image's `ImageParams` only.

---

## 4. The Verify view (new tab in this app)
A new central tab **"Verify"** beside *Image* and *Field*, driven by the existing left image list.

```
┌ image list ─┬──────────────  Verify tab  ──────────────────────────────┐
│ ● initial   │  [◀ Prev]  image: l3p00x  [Next ▶]   [copy params → all] │
│ ○ l2  ✓✓✓✓✓ │ ┌─ StageWorkspace (embedded stageui) ───────────────────┐│
│ ○ l3  ✓✓✓✓· │ │  stage nav 1..5 │   CANVAS + overlays   │ stage panel  ││
│ ○ l5  …     │ │                 │ (correct/tags/grid/…) │ (sliders)    ││
│ [◀ ▶ keys]  │ └───────────────────────────────────────────────────────┘│
└─────────────┴──────────────────────────────────────────────────────────┘
```

- Selecting an image (list click, Prev/Next buttons, ←/→ keys) binds the workspace's `AppState` to
  that image: `state.correction = project.correction` (shared), `state.measure/filters =
  image_params[path]` (per-image), loads the raw image.
- **Auto-run all 5 stages** with those params and render the current stage's overlay (§5).
- Tuning a slider re-runs from that stage down for the current image and writes the new value into
  `image_params[path]` (or `project.correction` for Stage 1).
- **"Copy params → all"** copies this image's `ImageParams` to every image (convenience for a
  consistent series).

The five panels/overlays are exactly the ones you already use in point_tracking_gui:
Stage 1 sliders + before/after, Stage 2 tags + IDs, Stage 3 grid + reference schematic + method/λ,
Stage 4 dot/dash markers + table, Stage 5 filter toggles + red/amber.

---

## 5. Auto-run + caching (keep it responsive)
Stage 4 (trackpy) takes ~seconds/image, so:
- **Threaded run.** On image select, run Stages 1→5 in a `QThread` (reuse the `BatchWorker`
  pattern) with a small spinner; the UI stays live.
- **Cache** per image keyed by a hash of its effective params. Cache hit → show instantly.
- **Incremental invalidation.** A Stage-k param change invalidates stages ≥ k for the current image
  and re-runs from k only. A Stage-1 (shared) change invalidates **all** images (optics changed) —
  re-run current now, mark others stale (a ✗ in the list) to re-run on visit or at "Run all".
- Optional **fast preview**: while dragging a Stage-4 slider, run trackpy on a centre crop /
  downsample for instant feedback; full-frame on release. (Deferred; only if latency bites.)

---

## 6. Integration with the batch + pairing
- **"Run all"** now iterates `image_params[path]` per image (was one shared set). Same outputs, same
  CSVs; per-image params are recorded in each image's `stage*` CSVs (Stage-1 correction row already
  written; add a per-image params row).
- **Pairing / field** unchanged — they consume the tagged features + tag centres.
- Verify → Run all → Pair is the workflow: eyeball/tune each image in Verify, then batch + pair.

---

## 7. Phases (build order) — status
1. **V0 — Extract `stageui`.** ✅ DONE. Panels/canvas/widgets/state moved into
   `point_tracking_gui/stageui/`; `StageWorkspace` added; `point_tracking_gui/app/main` is a thin
   shell. Gate met: 25 tests pass + import-check OK.
2. **V1 — `ImageParams`** in `fieldkit.project`. ✅ DONE. `ImageParams(measure, filters,
   transform_model, ransac_px)` + `project.image_params` + `params_for(path)`; `pipeline.process_image`
   uses per-image params; `project.json` persists/restores `image_params`. Round-trip + drive tested;
   16 fieldkit tests pass.
3. **V2 — Verify tab** embedding `StageWorkspace`. ✅ DONE (`app/verify_view.py`, new "Verify" tab).
   Image-list-driven select; Stage-1 optics shared (`set_correction` writes through to
   `project.correction`), Stages 2-5 bound per-image via panel `set_params`/`read_params`.
4. **V3 — Auto-run** on select. ✅ DONE (`StageWorkspace.run_all`, run on the **main thread** with a
   busy cursor — Qt requires GUI draws on the main thread). Per-image write-back on image switch +
   `flush()` before batch/save. **Deferred:** background threading + result caching + Stage-1 stale
   invalidation flags (main-thread run is responsive enough for QC at current image counts).
5. **V4 — Prev/Next + ←/→ keyboard cycling, "Copy params → all".** ✅ DONE (top bar in the Verify
   tab; cycling drives the image list so selection stays in sync). **Deferred:** per-stage ✓/✗ status
   marks in the list.
6. **V5 — Persist per-image params.** ✅ DONE (in `project.json` via V1). **Deferred polish:** spinner
   widget, optional fast centre-crop preview while dragging Stage-4 sliders.

**Verified end-to-end (offscreen):** select `l5` → auto-runs 5 stages (single-marker tier, λ≈5.14,
~5k features); tune Stage-4 `minmass` → persists to that image; Copy→all propagates; ←/→ cycles and
re-runs (`l1` → 25 tags). Note: the sandbox Python 3.14 venv can't init any Qt platform plugin, so the
GUI is exercised through the **launch venv** (`~/Library/Application Support/HydrogelMarkerGUI/…`),
which the `.command` uses.

**Also fixed here:** `fieldkit/__init__.py` now **appends** `point_tracking_gui` to `sys.path`
(was `insert(0, …)`) so that app's top-level `app` package can't shadow this app's own `app` package
(both apps name it `app`); `gridtrack`/`stageui` still resolve since they exist only in
point_tracking_gui.

---

## 8. Open items / risks (thought through)
- **Refactor risk to point_tracking_gui** — mitigated by its test suite + launch check; the move is
  mechanical (relative imports within `stageui`).
- **GUI can't be fully unit-tested here** (offscreen Qt is flaky in this environment) — validate the
  headless pieces (`ImageParams`, `process_one`, caching keys) with pytest, and import-check the GUI
  modules, as we've done throughout.
- **Auto-run latency** at high image counts — threaded + cached; fast-preview held in reserve.
- **Per-image params vs pairing bias** — per-image detection changes *which* dots are tagged, not
  their positions or the tag-based registration, so the displacement field is unbiased; worth a
  test that pairing λ is stable when two images use different Stage-4 thresholds.
- **Two canvases** (this app's simple `Image`/`Field` canvas vs `stageui`'s rich one) — the Verify
  tab uses `stageui`'s; the Field tab keeps its quiver canvas. Acceptable; could unify later.
- **Shared-correction editing from Verify** — a Stage-1 change while verifying one image affects all;
  the stale-flag + "re-run on visit" keeps this predictable.

---

## 9. What you'll be able to do when it's built
Open the app → add the initial + expansion images → click any image → the **Verify** tab shows it
fully processed (corrected, tags found + oriented, grid mapped with method/λ, dots + dashes tagged,
filtered) → drag any Stage 1–5 slider and watch the overlay update → Prev/Next through the whole
series to confirm each frame → then **Run all** + **Pair** with the per-image params you dialled in.
