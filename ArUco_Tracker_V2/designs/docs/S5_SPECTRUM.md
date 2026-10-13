# S5 — The spectrum print and its analysis script

*2026-09-29. Builder `tools/build_spectrum.py`; analysis `designs/4_spectrum/analyse_spectrum.py`;
gate `tools/s5_gate.py`; records `designs/4_spectrum/verify.json`, `designs/docs/S5_gate.json`;
worked examples in `designs/4_spectrum/example/`.*

**Result: built, gated, and the analysis script returns the known answer.**

---

## 1. The print — `designs/4_spectrum/spectrum.stl`

750 × 750 × 2 µm, 36 tags (23 µm), 480 dashes, **9,244 dots in 25 boxes**. Tags, their ids and the
dashes are identical, feature for feature, to the three designs. Footprint 104,019 µm² (18.5 % —
the same as the Optimistic print, so about the same write time, 1.4 × the reference).

Each cell: **spacing (µm)** · dots in the box.

| dot ↓ / gap → | 2.875 | 3.375 | 3.875 | 4.375 | 4.875 |
|---|---|---|---|---|---|
| **2.125** *(reference dot)* | **5.000** · 713 — OPTIMISTIC | 5.500 · 560 | **6.000** · 468 — MEDIUM | 6.500 · 396 | **7.000** · 320 — CONSERVATIVE |
| **2.5** | 5.375 · 609 | 5.875 · 480 | 6.375 · 396 | 6.875 · 357 | 7.375 · 285 |
| **3.0** | 5.875 · 480 | 6.375 · 396 | 6.875 · 357 | 7.375 · 285 | 7.875 · 252 |
| **3.5** | 6.375 · 468 | 6.875 · 357 | 7.375 · 285 | 7.875 · 252 | 8.375 · 221 |
| **4.0** | 6.875 · 357 | 7.375 · 285 | 7.875 · 252 | 8.375 · 221 | **8.875** · 192 — SAFEST |

Top-left is the Optimistic pattern, the top row carries all three designs, bottom-right is the
safest pattern on the print. Columns step the **gap between dot edges** (spacing = gap + dot) —
decision D1, taken as the default.

**Build gate — all pass:** every box has its own size, spacing, count and clearances, exactly ·
every dot recovered from a render of the STL, all 36 tags decode, extent 750.00 µm · zero
overlaps · merged mesh manifold with the right volume · spec sheet and the 25-box table re-read
and checked against the rendered STL.

**No separate orientation mark.** The plan proposed an L-shaped datum outside the pattern. It is
dropped: the pattern fills the 750 µm envelope, so a datum would have to go outside it; and it is
not needed. Every node carries a unique tag, so every box is identified by the ids at its corners
whatever the rotation, and a mirrored image cannot be misread — mirrored tags do not decode
(tested in Phase C). By eye, the dense corner is top-left.

## 2. Files in the folder

```
designs/4_spectrum/
  spectrum.stl, spectrum_merged.stl     the print (box mesh / manifold mesh)
  spec_sheet.json                       common parameters + "boxes": the 25 patterns
  boxes.csv                             the same 25 rows, for a spreadsheet
  features.csv                          all 9,760 features, with dot / spacing / gap per dot
  reference_tags.json, ids.json         what the recognition pipeline loads
  verify.json, render.png               gate record, labelled render
  analyse_spectrum.py                   reads one image, reports per box
  example/                              four synthetic images and what the script says of each
```

## 3. The analysis script

```
python designs/4_spectrum/analyse_spectrum.py  IMAGE  [--um-per-px 0.51] [--out DIR]
```

One stitched image in, a 5 × 5 table, five heat-maps and one line out. Per box:

| column | meaning |
|---|---|
| `in_view`, `fully_in_view` | dots of the box inside the usable field; fully = at least 90 % of them |
| `recognised` | dots found **and identified** / dots in view |
| `merged` | dots estimated to lie in blobs too big or too long to be one dot — spacing too tight for the blur |
| `contrast` | dot peak minus the darkest tenth of the box, grey levels — is a bigger dot brighter? |
| `scatter_px` | RMS of the recognised dots about their box's fitted lattice — does a bigger dot sit steadier? |
| `blur_um` | blur (PSF FWHM) from Gaussian fits to the dots, printed size removed |

and for the frame: tags decoded, expansion, handedness, blur (taken from the reference-size boxes —
the estimate reads up to 40 % high on the largest dots, whose flat top is not a Gaussian), and

> *tightest spacing recognised at the 2.125 µm dot: 6 µm (97 %) → print MEDIUM*

— the tightest reference-size spacing that is ≥ 95 % recognised with every wider one recognised
too, and the design that corresponds to it.

**Image the print with all of it in view** — at 0.51 µm/px and a 1365 µm field, that is any
expansion up to about 1.6 ×. Boxes cut by the edge of the field are reported (marked `*`) but not
judged, because the field edge loses dots for reasons unrelated to spacing; if the boxes that
would decide are cut off, the script says *inconclusive* rather than guessing.

## 4. Analysis gate — does the script return the known answer?

Synthetic images of the spectrum print through the camera model, Stage-1 corrected; the script
sees the image and the spec sheet, the gate holds the truth.

| injected blur, expansion | script recommends | truth recommends | worst box, script − truth | blur measured | expansion measured |
|---|---|---|---|---|---|
| 1.9 µm, 1 × | OPTIMISTIC (5.0 µm, 100 %) | same | 0.000 | 2.08 µm | 0.999 |
| 2.7 µm, 1 × | OPTIMISTIC (5.0 µm, 99 %) | same | 0.000 | 2.67 µm | 0.999 |
| 3.4 µm, 1 × | CONSERVATIVE (7.0 µm, 96 %) | same | 0.000 | 3.23 µm | 0.999 |
| 3.1 µm, 2 × (print only partly in view) | inconclusive — deciding boxes cut off | same | 0.006 | 2.74 µm | 1.996 |

Every dot the script counts as recognised carries its correct identity: script and truth agree to
within 0.6 % in every box of every image. Blur is measured to within 5–12 %, expansion to 0.2 %.
These agree with S3: Optimistic recognised to 2.7 µm, Conservative the survivor at 3.4 µm.

## 5. What the synthetic spectrum already suggests about dot size

At 3.4 µm blur, 1 ×, recognised fraction by box:

| dot ↓ / gap → | 2.875 | 3.375 | 3.875 | 4.375 | 4.875 |
|---|---|---|---|---|---|
| 2.125 | 22 % | 52 % | 82 % | 93 % | 96 % |
| 2.5 | 87 % | 96 % | 98 % | 100 % | 100 % |
| 3.0 | **97 %** | 99 % | 99 % | 100 % | 100 % |
| 3.5 | 97 % | 100 % | 100 % | 100 % | 100 % |
| 4.0 | 48 % | 90 % | 99 % | 100 % | 100 % |

Compare patterns of nearly **equal density**: a 3.0 µm dot at 5.875 µm spacing is 97 % recognised;
the reference 2.125 µm dot at 6.0 µm spacing is 82 %. The larger dot is brighter (contrast 125 vs
76 grey levels at this blur), and at high blur a good part of what the small dot loses is
contrast, not merging. Your instinct that a dot of about 3 µm reads better is supported — *in
simulation, at high blur*. At 1.9 and 2.7 µm blur every box is 99–100 % and size makes no
difference. At 4.0 µm the tightest gap fails again: the dots are so wide that they merge.

This is exactly what the print is for. Simulation cannot say whether a 3 µm dot stays anchored,
prints cleanly, or shadows the gel beneath it; the rows of the spectrum print will. If the real
image shows the same pattern, a fourth design — 3.0 µm dots at about 5.9 µm — becomes worth
building, and it is one line in the generator.

## 6. In the lab (L1)

1. Print `spectrum.stl` (or `spectrum_merged.stl`), same process as the reference.
2. Image it before expansion, or at the first expansion state, with the **whole print in view**;
   then at each later state if you want the trend.
3. `python analyse_spectrum.py <image>` — read the line, keep the `_spectrum.png`.
4. Print the design it names (`designs/1_…`, `2_…` or `3_…`).

If the blur it reports is well below 2.7 µm, the focus fix has worked; if it names Conservative
at a blur above 3 µm, Medium and Optimistic are waiting on the focus.
