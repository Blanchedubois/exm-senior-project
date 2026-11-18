<!-- Draft section for the 4 Nov Magnify kit blog post. Goes into the post's analysis section.
     Figures to copy into blog/images/ when the post is written:
     outputs/4Nov26/flatfield/flat.png        -> 2026-11-XX-magnify-illumination-map.png
     outputs/4Nov26/flatfield/bead_check.png  -> 2026-11-XX-magnify-bead-check.png -->

## Correcting for uneven illumination

The 10× field isn't evenly lit. The centre gets the most light, and the corners get only about a tenth of it. The same bead looks 5–10× dimmer near a corner than in the middle. That matters here because the density estimate divides total light by the light of one bead. Both depend on where in the field the light comes from.

### Step 1: a map from the background glow

The first idea was to draw lines out from the centre of the field and watch how the brightness between beads falls off. The automatic version of that idea uses every direction at once.

For each of the 12 areas, the beads and their blur discs are removed with a rolling low percentile (the 20th percentile in a 124 px window). That leaves the background glow of the gel and the out-of-focus haze. Every area's glow is lit by the same light, so the median across all 12 areas gives the shape of the illumination. It's smoothed and scaled so the brightest point is 1. The brightest point is close to the centre of the image, at (706, 718) px.

![Illumination map](images/2026-11-XX-magnify-illumination-map.png)

*Left: the illumination map used for the correction. Right: how the background falls off with distance from the brightest point. The grey dots are each area's background, the dark dots are their median, the blue dots are the smoothed glow map, and the orange dots are the map actually used (step 2). Below 0.2 of the centre's light, the correction isn't trusted.*

### Step 2: checking the map against beads

A good map should make every bead equally bright once corrected, wherever it sits in the field. I circled 52 single, in-focus reference beads by hand across all 12 areas and checked them against the map.

![Bead check](images/2026-11-XX-magnify-bead-check.png)

*Each dot is a reference bead, shown as its light divided by its hydrogel's average. Left: raw. Middle: divided by the glow map. Right: divided by the glow map raised to the power 1.94.*

The glow map on its own only did half the job. Raw bead light rose steeply with illumination (Spearman ρ = 0.75), and dividing by the glow map left a clear trend (ρ = 0.46). The background glow falls off more gently than the light an in-focus bead receives. A likely reason is that the glow is mostly out-of-focus light, which is spread sideways, so its fall-off is blurred and flatter than the true illumination. Changing the shape of the map (a polynomial fit, a smooth elliptical spot, the raw median) didn't change this.

So the map keeps the shape of the glow but is made steeper. The steepness is fitted from the beads: bead light ∝ glow^γ, with a separate brightness level for each hydrogel. The fit gives **γ = 1.94 (95% interval 1.48–2.41, bootstrapped over the 51 beads used in the fit)**. After dividing by glow^1.94, the trend is gone (ρ = 0.11) and the spread between beads drops from 64% to 44%. The remaining spread is mostly real variation between beads.

There's a catch. γ is fitted from the same beads it's checked against, so the flat right-hand panel is flat by construction. It isn't an independent test. The confidence interval on γ is the honest measure of how well the correction is known.

### Step 3: only using the well-lit middle

With γ ≈ 2, less than half the field (47%) gets at least 20% of the centre's light. Outside that, the correction multiplies the signal by 5 or more, which amplifies any error in the map. So:

- **Reference beads** outside the 20% contour are left out of the single-bead average.
- **Total light** is summed only inside the 20% contour. It's the same region for every image, 1.13 mm² of gel.

Using the same region for both the 1× and 11× images means most of any remaining error in the map cancels when the two densities are compared. Repeating the whole analysis at both ends of the γ interval moves the implied expansion by at most about 0.35×.

### What would do this properly

This correction is built from the sample images themselves, which is why it needed calibrating. The standard fix is a flat-field image: one image of a uniform fluorescent slide at 561 nm, taken at the same settings. That's on the list for the next session.
