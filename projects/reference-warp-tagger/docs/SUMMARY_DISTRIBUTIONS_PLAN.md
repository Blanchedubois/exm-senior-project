# Summary-Tab Distributions Plan
### Histogram, box-and-whisker + jitter (expansion), box-and-whisker + jitter (warp residual)

**Scope:** Tab 8 · Summary only. **Written:** 2026-07-17.
**Decisions locked:** RMS quantity = **per-dot warp residual** (px) after removing each
image's best-fit **similarity** (uniform expansion + rotation + translation) from the
initial→expanded pairs — the classic registration RMS, showing pure non-uniform warpage.
Pixel sizes are identical across frames (same microscope/objective), so px are directly
comparable between images. Histogram = **all expanded images overlaid**, colour-coded.

---

## 1. What is added

A **View selector** on the Summary tab with four modes (the current view stays first):

| Mode | X | Y | Marks |
|---|---|---|---|
| **Trend (mean ± σ)** *(existing)* | expected λ | measured λ | points + error bars + identity |
| **Histogram — expansion** | per-dot local linear expansion | count | one semi-transparent step-histogram per expanded image, colour-coded, dashed vertical line at each image's expected λ, legend |
| **Box + jitter — expansion** | expected λ (one box per image) | per-dot local linear expansion | IQR box, median line, 1.5·IQR whiskers with caps, outliers + ALL raw points jittered inside the box width, identity line |
| **Box + jitter — warp residual** | expected λ (one box per image) | per-dot similarity residual (px) | same box/whisker/jitter construction |

All modes share the same per-image colour palette and feed from one headless computation.

## 2. Headless additions (`rwtag/pairing.py`, Phase 1)

- `similarity_residuals(pairs)` — Umeyama-style fit `p_exp ≈ s·R·p_init + t` over the paired
  dots (Kabsch rotation, least-squares scale), returning per-dot residual distances (px),
  plus the fitted `s` (a second, independent measure of expansion) and angle.
- `expansion_distributions(init_tags, expanded)` — per expanded image:
  `{name, label, expected, lin (per-dot local linear expansion, finite), resid (per-dot
  similarity residual px), tags}` — the single data source for all three new modes.
- `write_distributions_csv(dists, path, init_label)` — long-format export:
  `image_label, expected, tag, local_linear_expansion, warp_residual_px`.

**Tests:** synthetic uniform expansion → residuals ≈ 0 and `s` = λ exactly; injected
sinusoidal warp → residual distribution matches the injected amplitude; distributions'
`lin` median = λ; CSV columns.

## 3. GUI (`gui/summary_panel.py`, Phase 2)

- View combo `Trend | Histogram | Box+jitter expansion | Box+jitter residual`; table,
  exports and refresh untouched. Distributions computed once per Refresh (cached).
- **Box renderer** (pyqtgraph has no boxplot — drawn from primitives): box = Q1→Q3 outline,
  median line, whiskers to the last datum within 1.5·IQR + caps; **jitter** = deterministic
  RNG (seeded per image, reproducible) spreading raw points across 80 % of the box width,
  semi-transparent so density reads; outliers beyond whiskers drawn slightly larger.
- Box width ≈ 6 % of the x-range (expected-λ axis kept true-to-scale, so box spacing shows
  the design spacing of the expansions); identity line in the expansion mode.
- New **Export distributions CSV…** button; plot PNG export works in every mode.

## 4. Phases

| Phase | Deliverable | Check |
|---|---|---|
| **1** | headless residuals + distributions + CSV, tests green | synthetic + real 1.5↔2.0 numbers |
| **2** | view selector, histogram, box+jitter renderer ×2, exports | offscreen smoke + rendered-image inspection |
| **3** | regression suite, README/plan notes | all suites green |
