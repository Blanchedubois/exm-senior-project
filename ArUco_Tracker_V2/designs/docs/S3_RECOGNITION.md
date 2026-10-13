# S3 — What the microscope can recognise

*2026-09-29. Script `tools/s3_recognition.py`; data `S3_recognition.json`; log `S3_run.log`;
figures `S3_recognition.png` and `recognition.png` in each design folder.*

**Result.** All three designs were imaged through the camera model at twelve blurs (1.5 → 4.0 µm)
and six expansions (1 → 6×), two seeds each — 432 frames — and run through the production
recognition pipeline. Measured limits:

| | Optimistic (5 µm) | Medium (6 µm) | Conservative (7 µm) |
|---|---|---|---|
| **largest blur at which it is fully recognised** | **2.7 µm** | **3.1 µm** | **3.4 µm** |
| predicted in `01` (1.75× rule) | 1.91 µm | 2.69 µm | 3.39 µm |
| still usable (≥ 80 % in the worst frame) up to | 2.7 µm | 3.4 µm | 3.4 µm |
| 23 µm tags decode ≥ 95 % up to | 3.4 µm | 3.4 µm | 3.7 µm |
| frames that registered | 144 / 144 | 144 / 144 | 144 / 144 |
| dots given a *wrong* tag | 0 at every blur ≤ 3.7 µm | 0 | 0 |

"Fully recognised" = every frame registers, at least 90 % of the dots in the worst frame get
their correct tag, and at least 99 % of tagged dots are tagged correctly.

---

## 1. Three findings

### 1.1 The designs tolerate more blur than predicted — most of all Optimistic

The prediction in `01` used the separation rule with its safety margin (spacing ≥ 1.75 × the
imaged dot width). The pipeline itself separates dots down to about 1.45–1.6 ×:

| | spacing ÷ imaged dot width at the measured limit |
|---|---|
| Optimistic, 2.7 µm blur | 1.46 |
| Medium, 3.1 µm blur | 1.60 |
| Conservative, 3.4 µm blur | 1.75 (the ladder's next step, 3.7, fails) |

So the 1.75 × rule is a safe design rule, not the cliff. The cliff is steep, though: Optimistic
goes from 98 % of its dots at 2.7 µm to 76 % at 2.9 µm and 27 % at 3.1 µm.

### 1.2 Keeping the tags at 23 µm costs nothing in the range that matters

Predicted tag limit was ~2.6 µm. Measured: **99 % of in-frame tags decode at every blur up to
3.1 µm, 98–99 % at 3.4 µm**, in all three designs, and every one of the 432 frames registered —
even at 4.0 µm, where 83 % of tags still decode and the worst frame has 3. The earlier, more
pessimistic figure (W1) was measured before the detector's error correction was switched on
(`errorCorrectionRate = 1.0`, W3). **The tags are not the limiting feature of any design**; the
dots are. Your decision to keep one tag size is sound.

(The 94 % "worst frame" in the figure is the 1.5× frame, where two of the 36 tags sit inside the
excluded band at the edge of the field and are deliberately ignored — not a decode failure.)

### 1.3 The blur limit is set by the *least expanded* frame

Blur is fixed in the image; the dots move apart as the gel expands. So a design fails first in
its densest frame and recovers as it expands (Optimistic at 3.4 µm blur: 11 % at 1×, 56 % at
1.5×, 90 % at 2×, 94 % at 3×). The limit therefore depends on where the series starts:

| largest blur fully recognised, if the first frame is at … | Optimistic | Medium | Conservative |
|---|---|---|---|
| 1× (unexpanded reference) | 2.7 µm | 3.1 µm | 3.4 µm |
| 1.5× | 3.1 µm | 3.4 µm | 3.4 µm |
| 2× or more | 3.4 µm | 3.4 µm | 3.4 µm |

The existing series starts at the frame labelled 1.5× (1.97× if the metadata pixel size is the
true one). **If the reference state you image is already expanded by ~1.5× or more, Optimistic is
readable across the whole range of blur measured today.** If you need an unexpanded reference,
it is not.

Beyond 2× every design sits at 94–97 %: the remaining few percent are dots lost at the edge of
the field and beside tags, the same in all three, not a spacing effect.

## 2. Against the microscope as it is

Blur measured on the real series: **2.7 µm** (edge method) to **3.2 µm** (dot method), and it
varies by 36–38 % across the field (0b), so part of every frame is worse than the average.

| | Optimistic | Medium | Conservative |
|---|---|---|---|
| at 2.7 µm, from 1× | 98 % — passes, at the edge of the cliff | 99.8 % | 99.8 % |
| at 3.1 µm, from 1× | **27 % — fails** | 97 % | 99 % |
| at 3.4 µm, from 1× | 11 % | 81 % — marginal | 94 % |
| at 3.1 µm, from 1.5× | 94 % | 98 % | 99 % |
| after the focus fix (~1.9 µm) | 100 % | 100 % | 100 % |
| dots | 17,825 | 11,700 | 8,000 |

Reading it:

- **Conservative** is recognised across today's whole blur range from an unexpanded reference,
  with margin. It carries 1.25 × the reference print's dots.
- **Medium** is recognised across today's range (97 % at 3.1 µm) but has no margin above it: the
  worse parts of a field with 36 % variation would drop toward 80 %. It carries 1.8 ×.
- **Optimistic** needs either the focus fix or a reference that is already expanded ~1.5×. With
  either, it carries 2.8 × the dots.

## 3. What this test cannot tell you

1. **The blur is modelled as a Gaussian, the same everywhere in the field.** The real one has
   wider tails and varies across the field. Expect real limits somewhat below these — which is
   why the 1.75 × rule keeps its margin in the design documents, and why the measured figures are
   recorded in the spec sheets *next to* the predicted ones rather than replacing them.
2. **The pixel size is still the metadata value (0.510 µm/px).** If the true value is 0.381, every
   blur figure in µm on the real microscope is 25 % smaller than quoted and all three designs gain margin.
3. **Exposure is assumed to rise as λ².** Without it no design survives past 3× (W6).
4. **Anchoring and print fidelity are not simulated.** Whether 5 µm-spaced dots print cleanly and
   stay put in the gel is for S4 and the spectrum print.

The spectrum print (S5) is the measurement that replaces this one: the same three spacings,
side by side, on the real gel and the real microscope.

## 4. Numbers

Dots recognised in the worst frame / mean tag decode, by blur:

| blur (µm) | Optimistic | Medium | Conservative |
|---|---|---|---|
| 1.5 | 95.8 % / 99 % | 95.6 % / 99 % | 95.3 % / 99 % |
| 1.9 | 95.8 % / 99 % | 95.6 % / 99 % | 95.2 % / 99 % |
| 2.3 | 95.7 % / 99 % | 95.5 % / 99 % | 95.2 % / 99 % |
| 2.5 | 95.7 % / 99 % | 95.5 % / 99 % | 95.0 % / 99 % |
| 2.7 | 95.6 % / 99 % | 95.3 % / 99 % | 95.1 % / 99 % |
| 2.9 | **75.7 %** / 99 % | 95.1 % / 99 % | 94.9 % / 99 % |
| 3.1 | 26.9 % / 99 % | 95.0 % / 99 % | 94.8 % / 99 % |
| 3.4 | 11.0 % / 98 % | **80.7 %** / 99 % | 93.5 % / 99 % |
| 3.7 | 0.2 % / 92 % | 27.2 % / 90 % | **70.9 %** / 96 % |
| 4.0 | 0.0 % / 83 % | 1.1 % / 83 % | 26.4 % / 83 % |

(Below the cliff the worst frame is one of the expanded frames at ~95 %; at and above it the
worst frame is the 1× frame.)

The measured limits are written into each design's `spec_sheet.json`
(`optics_assumed.psf_fwhm_max_measured` and the `recognition_measured` block).
