# ACF / CCF simulation on the 'optimistic' fiducial grid (2026-10-29)

Simulated pre (1x) and post (4x) images of the real grid (reference_tags.json: 17,825 dots, 480 dashes, 36 ArUco tags) at 0.51 um/px, PSF FWHM 1.91 um, rigid islands, shot + read noise.
Pre: print jitter 0.08 um, stage rotation 0.6 deg. Post: lambda = 4.0, rotation 4.0 deg, gel jitter 0.4 um, three lagging patches (12-15 % less expansion, sigma 28-40 um), kinematic lag model.
Scripts: exm_sim.py, exm_analysis.py, check_tags.py.

## Results
| Global pre->post | ACF (dot lattice) | ArUco tag centres | Truth |
|---|---|---|---|
| scale | 4.0064 | 3.9788 | 3.9735 |
| anisotropy | 1.0018 | 1.0007 | 1.0005 |
| rotation (deg) | +3.398 | +3.392 | +3.399 |

- ACF needs no alignment or correspondence and nails rotation, but its scale follows the bulk (unaffected) gel (true bulk median 4.004), not the area mean: +0.8 % bias when lagging patches are present.
- ACF peak height post/pre falls with lag beyond ~5 dot spacings: signature of nonuniform expansion.
- CCF after ACF-only correction fails: up to 27 px residual (pitch 9.8 px); global CCF picks the wrong dot-lattice cell; 100 % of windows off by a cell.
- CCF after tag-centre affine: global CCF peak 0.200 vs next 0.175. Windowed CCF (64 px, step 24): naive 11 % of windows off by a cell; lattice-aware 0.9 px rms, 0.8 % off. Local expansion from plane-fit gradients: r = 0.955 vs truth, rms 0.021.
