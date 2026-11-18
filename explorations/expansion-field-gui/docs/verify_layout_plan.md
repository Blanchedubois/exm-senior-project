# Implementation Plan — Restructure the Verify View so the Image is Large

> **Status: IMPLEMENTED** (Levers B + C). `StageWorkspace` now has a horizontal stage bar on top and a
> `canvas | scrollable-controls` splitter with the controls pinned to ~290 px so the image gets every
> other pixel. Measured canvas width: **310 px @1200, 710 @1600, 1030 @1920** (was ~160). The standalone
> point-tracking app, which has no competing side panel, gives the image ~986 px. Setup/Pairing stay
> visible per the decision below.

**Problem.** On the Verify tab the microscope image is squished to a thin strip — you can't actually
see it. This doc diagnoses why and proposes a restructure. Design to workshop first — see **Open
questions** at the end.

---

## 1. Why it's squished (root cause)

The Verify tab currently competes for horizontal space with **four** side-by-side columns:

```
MainWindow QSplitter:
 ┌ image list ┐┌──────────── view_tabs (Verify) ────────────┐┌ ctrl_tabs ┐
 │  ≤ 230 px  ││ StageWorkspace:  nav(170) │ CANVAS │ ctrl(≥320) ││  ≥ 320 px │
 └────────────┘└─────────────────────────────────────────────┘└───────────┘
```

Fixed width consumed at a 1200 px window ≈ `230 (list) + 170 (stage nav) + 320 (stage controls) +
320 (Setup/Pairing tabs)` = **~1040 px of chrome**, leaving the **canvas ≈ 160 px**. That's the strip.

Two structural faults:
1. **The right `ctrl_tabs` (Setup / Pairing) stay open while verifying** — they're irrelevant to
   Verify but still eat ~320 px.
2. **`StageWorkspace` spends width on a left stage-nav list (170 px)** in addition to the stage
   controls (≥320 px), so even alone it gives the canvas only the leftover.

---

## 2. Design goals
- On the Verify tab the **image is the dominant element** (target ≥ 55–60 % of width).
- Keep everything reachable: image cycling, the five stage panels, their overlays.
- **Don't regress** the standalone `point_tracking_gui` app — it embeds the *same* `StageWorkspace`,
  so improvements there benefit both.

---

## 3. Proposed restructure (three independent levers)

### Lever A — Give the Verify tab the full width (reclaim the right 320 px)
When the **Verify** tab is active, **collapse the right `ctrl_tabs`** (Setup/Pairing) and restore it
on any other tab. Implement via `view_tabs.currentChanged`: hide `ctrl_tabs` on Verify, show otherwise.
Setup/Pairing aren't part of the verify workflow, so hiding them is lossless and instantly reclaims
~320 px for the image. *(Alternative: move Setup/Pairing into a top toolbar/menu; heavier change.)*

### Lever B — Stage nav becomes a horizontal bar on top of the canvas (reclaim 170 px)
Replace `StageWorkspace`'s left **`QListWidget` stage-nav column** with a **horizontal segmented bar**
(`QTabBar` or a row of checkable buttons: `1 Correct · 2 Address · 3 Grid · 4 Track · 5 Filter`)
sitting **above the canvas**. Same signal (`_switch_stage(row)`), no vertical column → the freed 170 px
goes straight to the image. This is a change *inside* `StageWorkspace`, so the standalone app gets the
same, better layout.

### Lever C — Canvas | controls become a 2-pane splitter weighted to the image
Inside `StageWorkspace`, keep **canvas (left)** and **stage controls (right)** as a `QSplitter`, but:
- Wrap the stage controls in a **`QScrollArea`** (the Stage-3 reference schematic + Stage-4 table are
  tall/wide — scrolling stops them forcing the panel wider).
- Set **initial splitter sizes** so the canvas gets the majority (e.g. `[canvas 3 : controls 1]`) and
  give the canvas `stretchFactor` so it grows with the window; cap the controls' *sensible* width
  (~300–340 px) rather than letting the schematic dictate it.

Resulting Verify tab:
```
┌ image list ─┬─────────────────  Verify  ─────────────────────────────┐
│ ● initial   │ [◀ Prev] l3p00x [Next ▶]     [Re-run] [copy → all]      │
│ ○ l2 …      │ [ 1 Correct | 2 Address | 3 Grid | 4 Track | 5 Filter ] │
│ ○ l3 …      │ ┌──────────── CANVAS (large) ───────────┬─ controls ──┐ │
│             │ │        corrected / tags / grid / …     │  sliders    │ │
│             │ │                                        │ (scroll)    │ │
│             │ └────────────────────────────────────────┴─────────────┘ │
└─────────────┴──────────────────────────────────────────────────────────┘
```
Now the chrome is just `list (≤230, optionally collapsible) + controls (~300)`, so the canvas gets
**~670 px** of a 1200 px window instead of 160 — a 4× improvement, more when maximised.

### Lever D (optional) — make the left image list collapsible / narrower on Verify
The Prev/Next buttons + ←/→ keys already cycle images, so the list is a convenience on this tab. Option
to narrow it (~180 px) or add a collapse toggle to hand even more to the image. (Low priority given A–C
already fix the squish.)

---

## 4. Scope of change
- **`stageui/workspace.py`** — swap the left nav list for a top `QTabBar`; wrap controls in a
  `QScrollArea`; set initial splitter sizes + stretch. (Benefits both apps.)
- **`expansion_field_gui/app/main.py`** — on `view_tabs.currentChanged`, show/hide `ctrl_tabs` for the
  Verify tab; optionally set the outer splitter's initial sizes so Verify starts wide.
- **`point_tracking_gui/app/main.py`** — no change needed (it embeds `StageWorkspace`); just confirm it
  still looks right with the horizontal nav (its 25 tests + a launch check guard it).
- No headless/`gridtrack`/`fieldkit` changes — this is pure GUI layout.

---

## 5. Validation
- Offscreen (launch venv): construct the window, switch to Verify, assert `ctrl_tabs.isVisible()` is
  False on Verify and True on Image/Field; assert the canvas widget width > controls width at 1200 px.
- Manual: open the app, Verify tab, confirm the image is large and every stage panel still scrolls to
  its full content; cycle images.
- Standalone app: launch, confirm the new top stage-bar switches stages and overlays render.

---

## 6. Risks / notes
- **`QTabBar` vs list** — the list showed stage names cleanly; a tab bar with 5 tabs is compact but
  labels must stay short ("1 Correct", …). Acceptable.
- **Scroll area + pyqtgraph** — the canvas must stay *outside* the scroll area (only the controls
  scroll) so image zoom/pan isn't captured by the scroll. Keep canvas as its own splitter pane.
- **Hiding Setup/Pairing on Verify** — a run started from Setup keeps running (worker thread); we only
  hide the panel, not stop it. Switching back to the Setup tab shows live progress again.

---

## Decisions (locked in)
1. **Setup/Pairing stay visible** (do **not** auto-hide on Verify). → Lever A is dropped; we lean
   harder on Levers B + C, plus set the outer splitter's initial sizes to favour the Verify pane and
   cap the stage-controls width so the image still gets the majority of what's left.
2. **Stage nav → horizontal bar on top of the canvas** (Lever B). Applies to both apps.
3. **Keep the image list as-is (~230 px)** (Lever D dropped). Prev/Next + ←/→ still cycle.

**Net effect within these constraints.** Chrome = image list (~230) + Setup/Pairing (~320) +
stage-controls (~300, now scrollable) ⇒ canvas ≈ 350 px at 1200 px and ≈ 750 px at 1600 px / maximised,
vs ~160 px today. The outer splitter is drag-adjustable and the canvas has the stretch factor, so
widening the window (or the splitter) flows straight to the image.
