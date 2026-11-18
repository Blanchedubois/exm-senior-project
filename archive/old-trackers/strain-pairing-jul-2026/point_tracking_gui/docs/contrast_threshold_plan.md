# Implementation Plan — Contrast Boost + Noise-Floor Threshold (Stage 1)

> **Status: IMPLEMENTED.** `LevelsParams` (gridtrack.types) + `correct.levels` / `resolve_black_norm`
> / `resolve_black_level` (black→0, white→full, gamma; auto k·σ / percentile / value modes). It is
> **per-image**: `LevelsParams` lives on `fieldkit.ImageParams` (persisted in `project.json`), and the
> pipeline applies it right after the shared vignette/lens/low-pass, before detection. Stage-1 panel
> gains the Levels controls + an intensity **histogram** with black/white markers (shared by both
> apps); the Verify view binds it per image. 5 headless tests pass; auto floor on the sim lands at
> ~25 grey (pedestal 14 + ~3σ). Off by default.
>
> **Decisions:** Levels model · Auto k·σ (default, + percentile/value modes) · **Per-image** · Histogram.

**Goal.** Add a Stage-1 control that (a) **drops the noise floor to black** — pixels at/under a
threshold become 0 — and (b) **increases contrast** of the real features above the floor. It sits in
the **Shared Optics Correction** section alongside vignette / lens / low-pass, applied *after* the FFT
low-pass (denoise first, then clamp the residual floor).

Design to workshop first — see **Open questions** at the end.

---

## 1. The operation — a "Levels" remap (recommended)

Rather than two disconnected knobs, model it as one photometric **Levels** remap (the Photoshop/ImageJ
idea), which gives *both* asks in one well-understood transform:

```
v   = img / scale                      # normalise to [0,1]  (scale = 255 or a robust per-image max)
t   = clip((v - black) / (white - black), 0, 1)   # black point -> 0, white point -> 1, stretch between
out = (t ** gamma) * scale             # gamma shapes mid-tones; back to original value scale
```

- **`black` (noise floor → black).** Everything ≤ `black` maps to **0** — exactly "drop noise to
  black". This is your threshold.
- **`white`.** Everything ≥ `white` maps to full brightness — pulls dim real features up.
- **Stretch.** Because `[black, white]` is expanded to `[0,1]`, the features between them gain
  **contrast** (a narrow bright band becomes the full range).
- **`gamma`.** `<1` brightens mid-tones (lift faint dots), `>1` deepens them; `1.0` = pure linear.

Setting `white=1, gamma=1` and only raising `black` gives a **pure noise-floor cut** (features above
the floor pass through unchanged in relative terms). So the same control covers "just threshold" and
"threshold + contrast".

### Simpler alternatives (if you prefer)
- **Hard threshold only:** `out = where(img <= black, 0, img)` — kills the floor, leaves everything
  above *untouched* (no stretch, no brightening). Minimal, but doesn't add contrast.
- **CLAHE (local adaptive contrast):** already available as `clahe_clip` for Stage-2 preprocessing;
  could be surfaced in Stage 1. Great for uneven illumination, but it *amplifies* noise in flat areas
  (so it works best *with* the low-pass + a floor cut), and it doesn't "drop to black".

I recommend **Levels** as the primary, with the black-only case being the "just threshold" mode.

---

## 2. Choosing the black point (the noise floor)

Three ways to set `black`, ranked by robustness:

| Mode | How | Pros | Cons |
|---|---|---|---|
| **Auto (k·σ over background)** | estimate background `bg` = median of the dark pixels, `σ` = MAD; `black = bg + k·σ` (k≈3) | adapts to each frame's real noise; "just works" | needs a background estimate |
| **Percentile** | `black` = the p-th percentile of the histogram (e.g. 40 %) | robust, simple | assumes a known dark-fraction |
| **Manual value** | a slider in normalised `[0,1]` | full control, predictable | you re-tune per brightness |

**Recommendation: Auto (k·σ) with a manual override** — auto-estimate on load, then a slider nudges
`k` (or the value) if needed. In the simulator the background pedestal ≈ 14 with read-noise ≈ 4, so
`k=3` ⇒ `black ≈ 26`, which cleanly zeroes the dark field while leaving dots/tags intact.

---

## 3. Parameters (added to `CorrectionParams`)

```python
# Stage-1 contrast / noise-floor levels (applied after low-pass)
lv_enable: bool  = False        # off -> apply() unchanged
lv_black:  float = 0.0          # black point, normalised [0,1] (noise floor -> 0)
lv_white:  float = 1.0          # white point, normalised [0,1]
lv_gamma:  float = 1.0          # mid-tone shaping (1 = linear)
lv_black_mode: str = "auto"     # "auto" (k·σ) | "percentile" | "value"
lv_black_k: float = 3.0         # k for auto mode (or percentile for "percentile" mode)
```

`lv_enable=False` keeps `apply()` bit-identical to today; `from_dict` ignores unknown keys, so old
`project.json` / `session.json` load fine.

---

## 4. Where it runs in Stage 1

`apply()` order becomes: **vignette → distortion → low-pass → levels**. Rationale:
- Low-pass first so the threshold clamps a *smoothed* floor (fewer speckles survive as isolated bright
  pixels that a hard cut would keep).
- Levels last so what you see / detect / measure is the final contrast-boosted image, and it's the
  image saved for analysis.

Value scale is **preserved** (multiplied back by `scale`), so every downstream assumption
(`to_uint8` percentile stretch, trackpy `minmass`, filter thresholds) keeps working; you may want to
re-tune Stage-4 `minmass` after a strong stretch (documented).

---

## 5. Maths (`correct.levels`)

```python
def _resolve_black(img, p, scale):
    if p.lv_black_mode == "value":     return p.lv_black
    v = img / scale
    if p.lv_black_mode == "percentile":
        return float(np.percentile(v, p.lv_black_k))          # k reused as percentile
    bg = np.median(v[v < np.median(v)])                       # dark-half median = background
    sigma = 1.4826 * np.median(np.abs(v[v < np.median(v)] - bg))
    return float(bg + p.lv_black_k * sigma)                   # auto k·σ

def levels(img, p):
    if not p.lv_enable: return img.astype(np.float32, copy=False)
    scale = 255.0 if img.max() <= 255 else float(img.max())   # or a robust percentile
    black = _resolve_black(img, p, scale)
    white = max(p.lv_white, black + 1e-3)
    t = np.clip((img/scale - black) / (white - black), 0, 1) ** max(p.lv_gamma, 1e-3)
    return (t * scale).astype(np.float32)
```

---

## 6. GUI (both apps, same as low-pass)
A `Collapsible("Contrast / threshold (levels)")` on the Stage-1 panel **and** the expansion Setup
panel:
- `Enable` checkbox.
- `black-point mode` combo (auto / percentile / value) + one slider whose meaning follows the mode
  (`k·σ`, percentile, or normalised value) + an **"auto-estimate"** button.
- `white point` slider, `gamma` slider.
- Live read-out of the resolved black level in grey-levels (e.g. "floor ≈ 26 / 255").
- A small **before/after histogram** or the existing mid-row profile updates so you can see the floor
  being cut. (Histogram is optional — say if you want it.)
Wired through the existing debounce → `_recompute()`; `_params()`/`set_correction()` carry the six
fields; Setup's `_pull_correction()`/`push_from_project()` include them (live write-through, shared).

---

## 7. Tests (headless)
- **Floor→black:** an image of `background + a few bright disks` → all background pixels become exactly
  0, disks survive (auto mode).
- **Contrast stretch:** a low-contrast band `[100,140]` with `black=100/255, white=140/255` → output
  spans ~`[0,255]`.
- **Gamma monotonic:** `gamma<1` lifts mid-tones, `>1` lowers them; endpoints fixed at 0 and max.
- **Disabled = identity;** **apply() with lv off == today's apply().**
- **Auto black is noise-adaptive:** doubling the noise σ raises the resolved black point ~2×.

---

## 8. Risks / notes
- **Over-thresholding removes dim dots.** A floor set above a faint dot's peak deletes it → tracking
  loss. Mitigate: default **off**, conservative **auto k=3**, and the low-pass first. The Stage-4 dot
  stats are the guide; the before/after preview makes over-cut obvious.
- **Hard black point + ArUco.** The Stage-2 decoder already inverts + CLAHEs; a moderate floor cut
  *helps* decode (cleaner quiet zones), but a very high `black` could clip a marker's darker modules.
  Keep it a floor cut, not a mid-tone cut.
- **Per-image brightness.** If frames differ in exposure, a single shared *value* black point may fit
  some poorly — which is exactly why **auto (k·σ)** is recommended for a shared setting (it adapts per
  frame even though the *rule* is shared). See Q3.
- **Interaction with `to_uint8`.** Display/detection already percentile-stretch; Levels changes the
  input to that. No conflict, but the on-screen look is the *combined* effect.

---

## Open questions
1. **Operation model** — **Levels** (black + white + gamma; recommended, covers threshold *and*
   contrast) / **hard threshold only** / **CLAHE local contrast** / a mix?
2. **Black-point setting** — **Auto k·σ with manual override** (recommended) / **manual value only** /
   **percentile**? (I'll include all three in a combo; this picks the default.)
3. **Scope** — **Shared** across all images like the other optics (recommended; with *auto* mode the
   rule is shared but the resolved floor adapts per frame) or **per-image**?
4. **Before/after histogram** in the panel to see the floor being cut — **yes** (nice for tuning) or
   keep it to the image preview only?
