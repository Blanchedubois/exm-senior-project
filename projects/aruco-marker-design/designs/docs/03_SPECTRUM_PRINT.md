# 03 — The spectrum print (design 4)

*One 750 × 750 µm print whose 25 boxes are 25 different dot patterns, so a single print and a
single image series show which spacing and which dot size this microscope and this gel can
actually use. Built in phase S5.*

---

## 1. Layout

Spacing widens **left → right**, dot size grows **top → bottom**. Optimistic is the top-left box,
the most conservative pattern is the bottom-right.

```
                 spacing  ─────────────────────────────────────────►
                 col 1        col 2        col 3        col 4        col 5
            ┌────────────┬────────────┬────────────┬────────────┬────────────┐
 size  row1 │ OPTIMISTIC │            │   MEDIUM   │            │CONSERVATIVE│  dot 2.125 (reference)
   │        ├────────────┼────────────┼────────────┼────────────┼────────────┤
   │   row2 │            │            │            │            │            │  dot 2.5
   │        ├────────────┼────────────┼────────────┼────────────┼────────────┤
   │   row3 │            │            │            │            │            │  dot 3.0
   │        ├────────────┼────────────┼────────────┼────────────┼────────────┤
   │   row4 │            │            │            │            │            │  dot 3.5
   ▼        ├────────────┼────────────┼────────────┼────────────┼────────────┤
       row5 │            │            │            │            │  SAFEST    │  dot 4.0
            └────────────┴────────────┴────────────┴────────────┴────────────┘
```

The top row **is** designs 1, 2 and 3 (columns 1, 3, 5) with two intermediate spacings between
them, so the spectrum print tests the three designs themselves, not stand-ins for them.

Tags (23 µm, one unique id at each of the 36 nodes) and dashes are exactly those of the three
designs. Each box is identified by the four tags at its corners, so the analysis never depends on
knowing where in the image a box is. (An L-shaped datum was proposed here and dropped in S5: the
pattern fills the envelope, and the unique tags already make a rotated image unambiguous and a
mirrored one undecodable.)

## 2. What "spacing" means here — decision D1

There are two ways to step the spacing when the dot size also changes:

**(a) gap between dot edges — the default.** Columns are gaps of 2.875 → 4.875 µm; the
centre-to-centre pitch is `gap + dot`.

**(b) centre-to-centre pitch.** Columns are pitches 5.0 → 7.0 µm whatever the dot size.

The top row is the same in both. They differ below it, and the difference matters:

| bottom-right box | (a) gap | (b) pitch |
|---|---|---|
| dot / pitch / gap | 4.0 / 8.875 / 4.875 µm | 4.0 / 7.0 / 3.0 µm |
| largest blur it tolerates | **3.1 µm** | **0 — not resolvable at any blur** |

With (b), a big dot at a fixed pitch leaves a smaller gap, and the blur closes it: the
bottom-right box would be the *hardest* on the print, and 9 of the 25 boxes could never resolve
under the measured 1.75× rule. With (a), every column tolerates roughly the same blur in every
row, so reading down a column isolates the effect of **dot size** and reading along a row
isolates **spacing** — which is what a test matrix is for. **Default: (a).** Say so if you want (b).

## 3. The 25 boxes (default D1 = gap, D4 sizes)

Each cell: **pitch (µm)** · largest tolerated blur (µm PSF FWHM) · approx. dots in the box.

| dot ↓ / gap → | **2.875** | **3.375** | **3.875** | **4.375** | **4.875** |
|---|---|---|---|---|---|
| **2.125** | **5.000** · 1.91 · 713 *(= optimistic)* | 5.500 · 2.32 · 560 | **6.000** · 2.69 · 468 *(= medium)* | 6.500 · 3.05 · 396 | **7.000** · 3.39 · 320 *(= conservative)* |
| **2.5** | 5.375 · 1.78 · 609 | 5.875 · 2.24 · 480 | 6.375 · 2.65 · 396 | 6.875 · 3.03 · 357 | 7.375 · 3.39 · 285 |
| **3.0** | 5.875 · 1.51 · 480 | 6.375 · 2.07 · 396 | 6.875 · 2.54 · 357 | 7.375 · 2.96 · 285 | 7.875 · 3.35 · 252 |
| **3.5** | 6.375 · 1.01 · 468 | 6.875 · 1.78 · 357 | 7.375 · 2.35 · 285 | 7.875 · 2.83 · 252 | 8.375 · 3.26 · 221 |
| **4.0** | 6.875 · — · 357 | 7.375 · 1.33 · 285 | 7.875 · 2.06 · 252 | 8.375 · 2.63 · 221 | **8.875** · 3.12 · 192 *(safest)* |

(— : not resolvable at any blur under the 1.75× rule; printed anyway, as the known-bad corner
that shows the test is sensitive. Dot counts are exact, from the S1 build with 23 µm tags.)

**9,244 dots** in total. Every box holds 192–713, enough for a recognised fraction to ±2–3 %.

**Reading the result.** At today's blur (~2.7–3.2 µm) the prediction is that only the two
right-hand columns resolve. After a focus fix to ~1.9 µm, everything from column 1 (top rows)
rightwards should. The first column in which the top-row box resolves tells you which of
designs 1 / 2 / 3 to print; the rows tell you whether a bigger dot tracks better or is brighter
on the real gel — the question of "3+ µm" that simulation cannot answer.

## 4. Spec sheet additions

`spec_sheet.json` carries the common parameters (envelope, grid, tags, dashes, frame, detector
settings) exactly as in `02_SPEC_SHEET_FORMAT.md`, and replaces the single `"dots"` block by a
list of 25:

```json
"boxes": [
  { "box": 5,  "col": 0, "row": 4, "position": "top-left", "label": "OPTIMISTIC",
    "corner_tag_ids": [ .. 4 ids .. ],
    "dot": 2.125, "gap": 2.875, "pitch": 5.0,
    "per_row": 27, "count": 681, "phase_in_box": 3.4,
    "psf_fwhm_max_predicted": 1.91,
    "expected_at_expansion_1": { "dot_pitch_px": 9.80, "dot_fwhm_px": 5.6 } },
  ...
]
```

plus `boxes.csv` (the same, one row per box) and `features.csv` with `dot_um`, `pitch_um`,
`gap_um` on every dot row. Box numbering follows the existing rule (`N = col*5 + row + 1`, from
the bottom-left), so "top-left" is box 5 and "bottom-right" is box 21; the sheet states both the
number and the position in words.

## 5. The analysis script (`designs/4_spectrum/analyse_spectrum.py`, phase S5)

Input: one image of the print (any expansion) + the spec sheet. Output: a 5 × 5 table and a
heat-map, per box —

| quantity | meaning |
|---|---|
| recognised fraction | dots found and correctly identified / dots printed in that box |
| merged fraction | pairs of neighbours detected as one blob — the signature of spacing too tight for the blur |
| brightness | median dot signal above background — does a bigger dot help? |
| position scatter | RMS of dots about their fitted lattice — does a bigger dot sit more steadily? |
| measured blur | dot width in the image, de-convolved by the printed size |

and one line: **the tightest spacing that is ≥ 95 % recognised at the reference dot size** —
which names the design to print.

S5's gate runs this script on synthetic images of the spectrum print at three known blurs and
checks that it returns the known answer. **Done — see `S5_SPECTRUM.md`.** Two rules were added in
the building: boxes cut by the edge of the field are reported but not judged, and the frame's
blur is taken from the reference-size boxes.

## 6. Relation to the earlier coupon

`cad/coupon_phase6.stl` (Rev D) asked the same questions with ladders of small patches. The
spectrum print supersedes it for the spacing and size questions — full boxes instead of 70 µm
patches, 25 combinations instead of 10, and the three candidate designs themselves in the top
row. The coupon's two stiffening fields (does a tag pinch the gel?) are not reproduced here;
that test stays on the coupon if you still want it.
