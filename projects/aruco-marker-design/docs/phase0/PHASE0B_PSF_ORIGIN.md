# Phase 0b — Is the PSF a hard optical limit, or is it fixable?

**Status: PARTIAL — indirect evidence complete, direct z-stack still required**
Tool: `tools/psf_origin.py` · Raw: `psf_origin_*.json`, `psf_origin_run.txt`, `psf_fieldmap_*.png`

**Question.** The plan treats the ~3 µm PSF as a fixed property of the optics ("locked optics"),
which caps dot density. Is it actually NA/diffraction-limited — a hard wall needing a new
objective — or is it defocus, tilt, or per-tile focus error, which is free to fix?

**Answer so far.** It is **not purely diffraction-limited.** The blur varies by **36–38% across
the field** in two independent frames, and it is **worse in the middle than at the edges** —
which no objective does. That signature points at the *sample or the focus*, not the optics.
Flattening the field to the sharpness it already achieves in its best region would be worth
**~2.2× more dots**.

> ⚠️ This is indirect. A z-stack is still needed to confirm it and to rule out the one serious
> alternative explanation (§5). The protocol is in §6 — it is one field, no stitching, ~10 min at
> the scope.

---

## 1. Why a single plane can answer this at all

A diffraction-limited system has a PSF that is **uniform across the field and isotropic**.
Defocus, sample tilt, field curvature and per-tile focus error all imprint **spatial structure**.
So: fit an elliptical Gaussian to every detected dot, map the width across the field, and look
for structure.

The key trick — the printed dot is a constant 2.125 µm square *everywhere*, so it contributes a
fixed term that **cancels when comparing one part of the field to another**. The spatial
variation is pure PSF, and it is independent of the disputed pixel size (§0a).

---

## 2. Results

| | 1.5× frame | 2.0× frame |
|---|---|---|
| Usable elliptical fits | 2,808 | 1,755 |
| Imaged FWHM, median | 7.17 px | 7.38 px |
| **Best cell → worst cell** | **5.54 → 8.24 px** | **6.02 → 8.68 px** |
| **Spread (% of median)** | **37.8%** | **36.0%** |
| Radial correlation | **−0.54** | **−0.45** |
| Anisotropy (median) | 1.086 | 1.104 |
| Tiling signature | none (0.29) | none (0.24) |
| Wing excess (halo) | −16.0% | −7.1% |
| **Density gain if flattened** | **1.66×** | **1.51×** |

Two independently acquired frames agree closely on every measure, which is the main reason to
trust the result.

### 2.1 The blur is structured, and structured the *wrong way*

A 36–38% spread is far too large for diffraction, which would be uniform. More telling is the
**sign**: the correlation with radius is **negative** in both frames — the field is **blurrier in
the centre and sharper toward the periphery**.

That is diagnostic. Classic field curvature and spherical aberration go the *other* way (worse at
the edges). Nothing in an objective is blurrier in the middle. What does produce this:

- a **domed or tilted sample** — the gel sits higher in the middle, so a focus set on the
  periphery leaves the centre defocused;
- focus deliberately set at the rim.

Both are sample/focus faults. **Neither is an optics limit, and neither needs a new objective.**

`psf_fieldmap_1.5x.png` shows the pattern directly: a broad blurry band through the upper-centre,
sharpest at the lower edge and corners — a tilt/dome gradient, not a radial bowl.

### 2.2 What it is *not*

- **Not per-tile focus error in the MIST mosaic.** After removing the smooth trend, no repeating
  structure survives at any lag ≥ 2 cells (strength 0.29 / 0.24, threshold 0.45).
  *An earlier version of this test reported tiling; that was an artifact.* It measured the
  strongest autocorrelation at **lag 1**, which any smooth field produces simply because
  neighbouring cells resemble each other. The corrected test de-trends first and ignores lag 1.
- **Not scatter through the gel.** The wing excess is *negative* in both frames: the radial
  profile is more compact than a Gaussian, exactly as a square printed dot convolved with a
  compact PSF should be. No halo.
- **Not primarily astigmatism.** Median anisotropy 1.09–1.10, below the 1.15 flag. Present, but
  a minor term next to the 38% field variation.

---

## 3. What flattening the field is worth

The sharpness already achieved in the best part of the field is a fair target for the whole
field, since the optics are the same everywhere.

| Calibration | Field state | PSF | Dot pitch | Dots |
|---|---|---|---|---|
| Conservative (0.510 µm/px) | as-is | 2.98 µm | 5.49 µm | 18,053 |
| Conservative | **flattened** | **1.86 µm** | **3.70 µm** | **40,178** |

**≈ 2.2× more dots, for a focus fix rather than a print run or an objective.** That is comparable
to the entire V2 print redesign, and it stacks with it.

*(The absolute dot counts here anchor on this frame's 7.17 px median rather than the plan's
7.5 px, so they run slightly high; the **2.2× ratio** is the robust number and is what §2.1 of
the plan now carries.)*

---

## 4. Bonus: this constrains Phase 0a

An imaged spot can never be **narrower than the printed dot inside it**. The sharpest cell in the
1.5× frame is 5.54 px, so:

```
effective pixel size  >  2.125 µm / 5.54 px  =  0.383 µm/px
```

| Calibration | Value | Against the floor |
|---|---|---|
| OME metadata | 0.510 µm/px | OK |
| Dot lattice | 0.381 µm/px | **violates (marginally)** |

At 0.381 µm/px the sharpest cells would imply a PSF of **zero**, which is impossible. The same
shows up in §3: the optimistic calibration drives the flattened PSF to 0.00 µm.

**Weigh this carefully.** The violation is marginal (0.381 vs 0.383), rests on a single best cell
of ~30 dots, and the 2.0× frame's floor (0.353) does not violate at all. So this is *suggestive*
evidence for the metadata calibration, **not proof**. 0a still needs its own measurement.

---

## 5. The alternative explanation this cannot rule out

**The dots themselves might vary across the field.** If Nanoscribe dose or focus drifted during
the write, printed dot size would vary spatially — and that would produce exactly the same
field map, with no imaging fault at all.

Nothing in a single plane separates the two, because both scale the imaged spot the same way.

**The z-stack settles it.** A focus fault changes sharply with z and has a clear minimum; a
printed-size variation is flat in z. This is the main reason the z-stack is still required rather
than optional.

---

## 6. PROTOCOL — the z-stack (≈10 min at the scope)

Same objective, same settings as the expansion series.

1. Pick a field with plenty of dots. Run this **twice**: once near the **centre** of the pattern,
   once near a **corner** — the centre/edge difference in §2.1 is the thing being tested.
2. Step **0.5 µm over ±10 µm** (≥ 21 planes).
3. Save each as a **single multi-page TIFF**. No stitching, no processing.

```bash
cd aruco-marker-design/tools
python psf_origin.py --zstack /path/to/centre_stack.tif --zstep 0.5
python psf_origin.py --zstack /path/to/corner_stack.tif --zstep 0.5
```

The tool reports median dot FWHM per plane, finds best focus, and decides:

- **A sharper plane exists** (FWHM well under the current 7.2–7.5 px) → the blur is focus.
  Flattening is worth ~2.2×, and **plan §3.1 re-opens at the optimistic end**.
- **No sharper plane** → the blur is genuinely NA/diffraction-limited, or the dots really are
  that size. "Locked optics" stands, and §5's alternative becomes the leading explanation.

---

## 7. Recommendation

Even before the z-stack, two things are worth doing because they are cheap and the evidence
already supports them:

1. **Level the sample and refocus on the pattern centre**, then re-acquire one frame and rerun
   `psf_origin.py --field`. If the spread collapses, the diagnosis is confirmed at zero cost.
2. **Hold the plan at the conservative variant** regardless. This result argues the optimistic
   end may become reachable, but §4 shows the optimistic *calibration* is probably wrong — those
   are different things, and neither is settled.

## 8. Reproduce

```bash
cd aruco-marker-design/tools
python psf_origin.py --frames 1.5,2.0 --cells 12
```

~3 min. Needs the `reference-warp-tagger` venv and the stitched frames.
