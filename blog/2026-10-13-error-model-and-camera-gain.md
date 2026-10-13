# How each dot gets an error bar, and why the camera gain matters

*2026-10-13*

The port plan for the ArUco tagger is now written ([`ArUco_Reference_Tagger/docs/`](../ArUco_Reference_Tagger/docs/)). One decision in it deserves its own note, because it changes what the downstream distortion analysis can claim: every detected feature will carry a position uncertainty, and every ArUco tag a rotation uncertainty. This post explains where those numbers come from and what the camera gain has to do with it.

## Why an error per dot

The analysis wants to separate real gel deformation from measurement noise. A dot that has moved 0.3 px from where uniform expansion predicts is a distortion signal only if its position is known better than 0.3 px. Dim dots in a 6× frame are known far less well than bright dots in the reference frame, so a single global noise figure would either hide real distortion in the bright frames or invent it in the dim ones. Each dot therefore gets its own 2×2 covariance in every frame of reference it is reported in.

## The formula

A fluorescent dot imaged through the microscope is well described by a Gaussian spot of width σ (in pixels). Fitting its centre from N photons on a background of b photons per pixel has a well-known localisation precision, from Thompson, Larson and Webb (2002) with Mortensen's correction for least-squares fitting:

```
variance per axis  =  (σ² + 1/12) / N  +  8π σ⁴ b² / N²
```

The first term is the shot-noise limit: more photons, better centre. The 1/12 is pixelation. The second term is the penalty for background: a dot sitting on a bright, noisy floor is harder to centre, and the penalty grows fast with spot width. Both terms depend on the dot through σ, N and b, which the detector records for every dot when it refines its centre (the integrated signal above background, the background level, and the fitted width).

For the ArUco tags the route is different. Each corner is refined to sub-pixel precision and its uncertainty is estimated from the local image gradient structure (the Förstner estimate). The four corner covariances give the tag's centre covariance and, through the side vectors, the rotation uncertainty in degrees.

## Where the gain comes in

The formula needs N and b in photons. The camera reports intensities in analogue-to-digital units (ADU). The conversion is the camera gain, in electrons per ADU, which depends on the camera and its readout mode. With the gain known, the dot's recorded signal and background convert to photons and the formula gives an absolute error in pixels.

Without it, the pipeline uses a gain of 1. The resulting numbers are still correct **relative to each other**: a dot with four times the signal of its neighbour is known twice as well, whatever the true gain. But the absolute scale is off by the square root of the true gain, and the export flags every such row as `relative_err = true`.

So the gain is a metadata field on every image, alongside the objective, laser and exposure. We do not have it for the current camera yet. It is not a blocker, for the reason below, but if it turns up in the camera documentation, entering it upgrades every existing project on the next export.

## The second route, which needs no gain

The formula assumes an ideal Gaussian spot and ideal Poisson noise. Real dots are square, slightly undersampled, and resampled by the lens un-distortion. So the pipeline also calibrates the model empirically: given several exposures of a static sample (the proposal's control images of unexpanded gels), each dot is detected in every exposure and the scatter of its positions is measured directly. One scale factor per image is then fitted so that the formula's prediction matches the measured scatter in the median. That factor is stored with the project.

This empirical route gives absolute errors with no gain at all, and it also catches anything the formula misses. The plan's dummy-frame generator produces ten noise realisations of the same geometry precisely so this calibration can be tested before any real repeat images exist.

## Carrying the error through the pipeline

A position passes through several maps before it is exported: the lens un-distortion and deskew rotation, the alignment onto the initial image, and the fitted similarity back to design micrometres. Each map's Jacobian transforms the covariance. The alignment itself is fitted from the paired dots, so it has its own uncertainty, estimated by bootstrap over the pairs; that contribution is exported as a separate set of columns so the downstream script can include it or not.

The result, in every export table: `x, y, sxx, syy, sxy` per feature per frame, `rot_deg, rot_sigma_deg` per tag, and a `relative_err` flag that says whether the camera gain was known.

## Next

Phase 1 of the port: the headless ArUco recognition package, the command-line script to run it on a single image, and the dummy-frame generator.
