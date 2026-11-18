# 01 — Design parameters for the three spacings

*Numbers computed with the production generator (`tools/aruco_grid.py`) on 2026-09-29; dot counts
are exact builds, not estimates. Frozen at the end of phase S0.*

---

## 1. The three designs, and the reference

| | **1 Optimistic** | **2 Medium** | **3 Conservative** | *reference (current print)* |
|---|---|---|---|---|
| dot (printed) | 2.125 µm square | 2.125 | 2.125 | 2.125 |
| **spacing, centre to centre** | **5.0 µm** | **6.0 µm** | **7.0 µm** | 8.0 µm |
| gap between dot edges | 2.875 µm | 3.875 | 4.875 | 5.875 |
| dots per box row | 29 | 24 | 20 | — |
| **dots in the print** | **17,825** | **11,700** | **8,000** | 6,420 |
| vs reference | 2.8 × | 1.8 × | 1.25 × | 1 × |
| ArUco tag | **23 µm** | **23 µm** | **23 µm** | (printed digits) |
| tag module (tag / 6) | 3.83 µm | 3.83 | 3.83 | — |
| box pitch, node to node | 145.4 µm | 145.4 | 145.4 | 150 |
| dashes | 480 | 480 | 480 | 600 |
| clearance dot ↔ tag, dot ↔ dash | 2.875 µm | 3.875 | 4.875 | — |
| areal fill | 18.5 % | 13.6 % | 10.6 % | 13.2 % |
| height | 2 µm | 2 | 2 | 2 |
| envelope | 750 × 750 µm | same | same | same |

**The three designs differ in the dot lattice and in nothing else** (your decision, 2026-09-29):
the tags, their positions and ids, and all 480 dashes are identical, feature for feature.

Common to all three: `DICT_4X4_50`, 23 µm tags, 36 of them on a 6 × 6 node lattice, the same 36 ids in the same
positions, tags rounded (0.20 µm necks across diagonal pinches, 0.30 µm fillets), dashes
8.125 × 2.125 µm, dot lattice centred in each box.

## 2. What the microscope must do for each — *predicted; phase S3 measures it*

The measured separation rule (Phase 0c, W5): two dots are recognised as two when their spacing is
at least **1.75 ×** the width of one dot *as imaged* — the printed 2.125 µm widened by the blur:

```
spacing  ≥  1.75 × √( dot² + PSF² )      ⇒      PSF_max = √( (spacing / 1.75)² − dot² )
```

| | Optimistic | Medium | Conservative | reference |
|---|---|---|---|---|
| largest blur it tolerates — predicted, 1.75× rule | 1.91 µm | 2.69 µm | 3.39 µm | 4.05 µm |
| **largest blur — measured in S3, from a 1× reference** | **2.7 µm** | **3.1 µm** | **3.4 µm** | — |
| … measured, if the first frame is at 1.5× | 3.1 µm | 3.4 µm | 3.4 µm | — |
| blur measured today (0b) | 2.7 – 3.2 µm | ← | ← | ← |
| blur expected after flattening focus (0b) | ~ 1.9 µm | ← | ← | ← |
| works on today's microscope, untouched? (S3) | only at the best end (2.7), or from a 1.5× reference | yes, without margin | **yes, with margin** | yes |
| works after the focus fix? | **yes, at the limit** | yes, with margin | yes, large margin | yes |
| spacing in camera pixels at 1× (0.51 µm/px) | 9.8 px | 11.8 px | 13.7 px | 15.7 px |
| … at 4× | 39 px | 47 px | 55 px | 63 px |

So the three are not three guesses at the same thing: each is the densest pattern for one state
of the microscope. **Conservative is printable and readable today. Optimistic is the pay-off for
fixing the focus. Medium is what survives a partial fix.**

## 3. The tag is 23 µm in every design — predicted cost (S3 measured: none)

> **S3 result:** the 23 µm tags decode 99 % at every blur up to 3.1 µm and 98–99 % at 3.4 µm, and
> all 432 test frames registered. The prediction below was pessimistic (it predates the detector's
> error correction). The tags do not limit any of the three designs. See `S3_RECOGNITION.md` §1.2.

You asked that the ArUco markers stay the same size and only the dot spacing change, so all three
designs (and the spectrum print) carry the optimistic design's 23 µm tag.

A tag has its own blur limit, separate from the dots'. Measured in W1: a module (one of the
tag's 6 × 6 cells, 3.83 µm here) must be at least 1.45 × the blur to decode ≥ 95 % of the time.

```
23 µm tag:  module 3.83 µm  →  decodes reliably up to a blur of 3.83 / 1.45 ≈ 2.6 µm
```

| | Optimistic | Medium | Conservative |
|---|---|---|---|
| blur the **dots** tolerate | 1.91 µm | 2.69 µm | 3.39 µm |
| blur the **tags** tolerate | ~2.6 µm | ~2.6 µm | ~2.6 µm |
| what limits the design | the dots | both, about equally | **the tags** |

So for Conservative the tags, not the dots, are now the first thing to fail as the blur grows:
at today's measured blur (2.7–3.2 µm) W1 found a 21 µm tag decoding 74 % of the time at 3.18 µm.
That is usually still enough — a frame needs one decoded tag to register and has 4 to 36 in view —
but it is margin given up, and at high expansion only four tags are in the frame. Phase S3
measures exactly this (tag decode rate and frames registered, per design, per blur), so the cost
will be a number rather than a prediction before anything is printed.

## 4. What is *not* changing

| | value | why it stays |
|---|---|---|
| dot size | 2.125 µm | the only size proven to stay anchored in this gel through 4.2× (your decision A) |
| envelope, height, box count | 750 µm, 2 µm, 5 × 5 | same Nanoscribe job, same stitch |
| three tiers | tags + dashes + dots | your earlier requirement |
| tag rounding | necks + fillets | tags must not come apart on expansion |
| exposure policy | ∝ λ² | W6: without it every design loses its dots by 3× |

## 5. Printability at a glance — *phase S4 checks it properly*

| | Optimistic | Medium | Conservative |
|---|---|---|---|
| smallest gap between any two features | 2.875 µm | 3.875 µm | 4.875 µm |
| smallest feature | 2.125 µm dot (tag necks 0.20 µm wide are bridges inside a solid, not free-standing) | same | same |
| laser write time vs the reference print (S4) | 1.40 × | 1.03 × | 0.80 × |

All gaps are far above the two-photon feature size, so none of the three is limited by the
printer. The limit is the microscope — which is why the fourth print exists.
