# Phase 0d — Do rigid fiducials stiffen the gel around them?

**Status: DONE (2026-09-22)** · Tool: `tools/fiducial_stiffening.py` · Raw: `fiducial_stiffening.json`, `fiducial_stiffening_run.txt`

**Question (plan risk R6).** The fiducials are rigid resin islands in a gel that swells around
them. Do they hold the gel back locally, biasing the deformation field we are trying to measure?
It matters because a 4×4 ArUco tag (~20 µm) is comparable to the 12 × 18 µm glyphs already
printed — whatever the glyphs do, the tags will do too.

**Answer. No detectable stiffening.** Dots in the ring 8–12 µm from a fiducial move as uniform
expansion predicts, to within **−0.030 ± 0.138 µm**. Allowing generously for correlated errors,
any real effect is **under ~8% of full pinning**. **R6 is retired for tags of this size.**

---

## 1. The test

The sharp question is not "is expansion lower near a tag" (a weak scalar) but **"do nearby dots
lag *toward* the tag"** — a directional signature that stacking many fiducials can pull out of
noise.

For each expanded frame:

1. **Pair dots to the initial frame by tag.** Exact correspondence, no matching heuristics —
   this is what the tag map buys.
2. **Fit the global similarity** init → expanded (uniform expansion + rotation + translation) and
   keep the per-dot residual as a **vector**. `pairing.similarity_residuals` returns only scalar
   distances, so the fit is redone here to retain direction.
3. **Rotate residuals into design coordinates, in µm**, so all frames and all fiducials stack in
   one common frame.
4. For each dot, find the nearest fiducial **in design space** — exact, from the CAD tag map, so
   no fiducial detection is involved and no detection bias can enter — and **project its residual
   onto the outward radial direction** from that fiducial.

Sign: **negative = the dot sits closer to the fiducial than uniform expansion predicts** = it
lagged = stiffening. Positive = pushed away. No effect = flat zero.

Pooled over 5 expanded frames, 4,269 paired dots, 205 fiducials.

---

## 2. Results

| Centre set | Inner ring (0–12 µm) | n |
|---|---|---|
| **Fiducial glyphs** | **−0.030 ± 0.138 µm (−0.2σ)** | 285 |
| Shifted-lattice control | +0.014 ± 0.071 µm (+0.2σ) | 1,087 |
| Random-phantom control | −0.139 ± 0.066 µm (−2.1σ) | 1,108 |
| Fiducial − control | +0.108 ± 0.153 µm (+0.7σ) | |

Dashes (also rigid, much smaller) show no trend either: every bin from 4 to 48 µm sits within
1.1σ of zero, with no systematic sign.

### 2.1 Turning the bound into something physical

If a fiducial *fully pinned* the gel, a dot at radius r would lag by (λ−1)·r. At r = 10 µm that
is 2.9 µm at 2.0× rising to 19.4 µm at 4.2× — an n-weighted mean of **7.27 µm**.

| | 2σ bound | as a fraction of full pinning |
|---|---|---|
| Nominal SEM | < 0.28 µm | **< 3.8%** |
| SEM inflated ×2 for correlation (§3) | < 0.55 µm | **< 7.6%** |

So full pinning is excluded overwhelmingly, and even a few-percent version of it is excluded.

---

## 3. Honest caveats

**The error bars are understated.** The random-phantom control sits 2.1σ from zero, and three of
its twelve bins exceed 2σ — more than chance. The cause is that **residuals are spatially
correlated**: the warp is a smooth field, so neighbouring dots are not independent samples and
the effective n is well below the nominal n. Read §2.1's *bound*, not the p-values. The ×2
inflation above is a rough allowance, not a rigorous correction.

**The near field is invisible.** Stage-3 drops dots sitting on a glyph (`dotfilter` "on_glyph"),
so the innermost populated ring starts at 8 µm — about one glyph half-height. **This test says
nothing about r < 8 µm.** For a 20 µm ArUco tag the keep-out is larger and the blind zone grows
with it, so the very-near field remains untested for V2 geometry.

**Two controls, one of which is better.** The random-phantom control does not reproduce the
*lattice* structure of the real fiducials, so it cannot reveal aliasing between that lattice and
the smooth warp field. The shifted-lattice control — the real fiducial lattice moved half a box —
has identical geometry and only the wrong phase, and is the one to trust. It comes in clean at
+0.2σ, which is the main evidence that the method is unbiased.

---

## 4. Two bugs found and fixed during the build

Both produced confident, wrong numbers, so they are worth recording.

**Kabsch cannot represent a reflection.** Design coordinates are y-up, image coordinates are
y-down, so design → image is a *reflection*, and `kabsch_rotation` forces det = +1. Fitting the
wrong handedness gave a design→image residual of **638 px instead of 11 px**, silently
corrupting every downstream rotation. The tool now tries both handednesses and keeps the one
that fits.

**Wrong scale in the px → µm conversion.** Residuals live in the *expanded* image, so the scale
to divide by is the full design→expanded chain `s0 · s`, not `s0` alone. This inflated residual
RMS to **50–123 µm** — physically impossible, since a whole box is 150 µm. Corrected values are
2.6–3.8 µm, which is a sensible few-percent non-uniformity over the field.

*The first of these is a live hazard elsewhere:* any code fitting design coordinates to image
coordinates with `kabsch_rotation` has the same trap. Worth a look during Phase C.

---

## 5. What this means for V2

- **R6 retired for ~20 µm tags.** The fiducial tier can stay at the size the plan specifies;
  there is no measured mechanical penalty at the scale already being printed.
- **Do not read it as a licence to go bigger.** The bound is at 12–20 µm feature scale. A
  materially larger tag is untested, and the blind inner zone means the effect could be
  concentrated where we cannot see.
- **The keep-out radius is still worth keeping** — not for mechanics, but because Stage-3 has to
  drop dots that overlap the tag anyway.
- **V2 will test this better than V1 can.** Denser dots shrink the blind zone in relative terms,
  and ArUco tags sit at box *corners* rather than scattered through the interior, so the stacked
  geometry is cleaner.

---

## 6. Reproduce

```bash
cd ArUco_Tracker_V2/tools
python fiducial_stiffening.py                 # ~2 min with the tag cache
python fiducial_stiffening.py --no-cache      # ~15 min, re-tags all six frames
```

Needs the `Reference_Warp_Tagger` venv and the six stitched frames. Tagging is cached to
`docs/phase0/.tagcache.npz`.
