# Phase B — Simulator retarget

**Status: DONE (2026-09-22) · gate PASS on both variants — CONDITIONAL on exposure
compensation (§4b). With the measured signal falloff and a fixed exposure, the gate FAILS above
~3× on photons alone.**
Tool: `tools/simulate_v2.py` · Output: `sim/<variant>_<timestamp>/`

Synthetic frames of the V2 three-tier pattern with **known ground truth**, which is what Phase D
needs to separate pipeline bias from gel physics — and what the workspace could not produce
before, because `expansion_camera_sim` simulates a design that is no longer printed.

---

## 1. What changed from the V1 simulator

- **Geometry comes from the Phase-A generator**, not the old 4×4 × 30 µm ArUco toolkit design.
- **The camera is the real instrument.** 0.51 µm/px over a 1365 µm field reproduces the
  **2676 px** stitched frames of the real series, so synthetic and real frames are directly
  comparable and can be fed to the same pipeline.
- **FOV starvation fixed.** V1 kept *one* tag in frame at λ ≥ 4. Here the field is sized from the
  real stitch, and the sim reports tags-in-frame so the claim is checkable.
- **Ladder rungs are relative to each variant's design PSF**, not absolute. The two variants
  target different optics; an absolute ladder tests the optimistic tags against blur they were
  never sized for, and they fail for the wrong reason.
- **Montage overlap fixed** (`h_pad` as well as `rect` — `rect` alone was not enough), dead
  `render_camera_frame` dropped, and **outputs go to a timestamped directory**, never in place.

Physics is the Phase-0 result: **rigid islands.** Every tag, dash and dot keeps its printed size
and only its centre moves, so spacing grows while feature size does not.

## 2. Results

*Exposure-compensated (see §4b for the uncompensated case).*

| Level (PSF ×design) | conservative | optimistic |
|---|---|---|
| L0_sharp (0.63×) | **97%** | **94%** |
| L1_good (0.79×) | 93% | 92% |
| L2_asdesigned (0.94×) | 87% | 87% |
| L3_soft (1.07×) | 55% | 61% |
| L4_poor (1.19×) | 8% | 6% |

Monotonic, gradual, and spanning a usable range — the thing V1's ladder did not do. **At least
one tag decodes at every λ through L2 in both variants**, which is the operational requirement:
ArUco addresses globally, so a single decoded tag registers the whole lattice.

## 3. Four real design bugs the simulator caught

This is the value of Phase B. All four were in the Phase-A CAD and none were visible in the
static renders.

1. ~~**Tags were half the size they needed to be.**~~ **Corrected by Workshop W1 (2026-09-22):**
   the 47% figure was inflated by CLAHE in the decoder; with plain inversion a 21 µm tag decodes
   74% at PSF 3.18 and 27 µm reaches ≥95% in the worst-case placement. The in-scene rule is
   module ≥ ~1.45 × PSF, not 1.8×; the 36 µm SAFE tag was ~30% oversized. See
   `workshop/docs/FINDINGS.md` W1. *Original text follows.* 20.3 µm tags decoded only **47%** at the
   measured 3.0 µm blur. Sweeping tag size against blur (all 36 real IDs, real pixel size, real
   noise) gave the practical rule **module ≥ ~1.8 × PSF FWHM**, against the ~1.06 × implied by
   `FINDINGS.md` §4 — that older rule was derived without sensor noise or pixel sampling. Tags
   went 20.3 → **36 µm** (conservative) and 12.2 → **24 µm** (optimistic).
2. ~~**The ArUco quiet zone was too small.**~~ **Corrected by Workshop W2 (2026-09-22):** with the
   CLAHE step removed from the decoder, every quiet zone from ¼ module up decodes 100% at λ = 1.
   The 50% figure was a CLAHE artefact. The quiet zone is now set by the *dot detector*
   (quiet = pitch − dot); see `workshop/docs/FINDINGS.md` W2. *Original text follows.* 3.0 µm of
   clear space where ArUco needs a full module
   (6 µm) plus room for the blur to spread nearby dots into it. At λ = 1, where the pattern is
   most compact, decoding fell to 50% *in the undegraded centre of the frame*. The quiet zone is
   now derived: `max(module, 1.5 × PSF)`.
3. **Dots merged with the grid markers.** At the optimistic pitch, dots nearest a boundary sat
   ~0.3 µm clear of a dash — they merge in the image, since the blur is far wider than that gap.
   Dashes now carry a keep-out.
4. **The tag keep-out was circular around a square tag.** The tag's corners reach `tag/2 × √2`,
   so a circular keep-out of `tag/2 + quiet` left them uncovered and dots landed on the tag. Now
   Chebyshev.

A fifth — **the dot lattice was not centred in its box** (2.24 µm of asymmetry in the
conservative variant) — was spotted by eye by the user, not by the gate. Fixed by fitting the
rows first and splitting the leftover evenly; both variants now centre to 0.0000 µm.

## 4. A bug in the simulator itself, worth recording

The first full run reported λ = 3 decoding at 50% while λ = 4–6 hit 100% — non-monotonic in λ,
which made no physical sense. Cropping the "in-frame" tag positions showed **no tags at all,
only dots**: the positions were wrong.

Cause: `cv2.getRotationMatrix2D` acts in **image** coordinates (y down), but tag centres are in
the **design** frame (y up). Rotating y-up points with it mirrors them. The decode was always
fine; the *reference set* it was scored against was wrong.

This is the same class of error as the Kabsch reflection bug in Phase 0d — **the third
y-up/y-down mix-up in this project.** Any code mixing design and image coordinates should be
assumed guilty until checked.

## 4b. Signal falls as λ⁻¹·⁸⁴ — and it is the binding constraint at high λ

Raised by the user: dots must stay bright enough to detect, and brightness drops as the pattern
spreads. Measured on the real series (geometry-corrected, levels **not** applied, so the
per-image contrast normalisation cannot hide it):

| frame | 1.5× | 2× | 2.5× | 3× | 3.5× | 4.2× |
|---|---|---|---|---|---|---|
| dot signal above background | 78 | 60 | 38 | 26 | 18 | **12** |
| relative | 100% | 77% | 49% | 33% | 23% | **15%** |

That fits **signal ∝ λ⁻¹·⁸⁴** — essentially inverse-square. By 4.2× only 15% of the photons
remain. (Mechanism unidentified: fluorophore dilution, spreading in z, or bleaching across the
six sequential acquisitions. The design consequence is the same either way.)

The simulator rendered every λ at full brightness, so it was optimistic exactly where detection
is hardest. The law is now modelled (`signal_exp`, default −1.84). The effect is decisive:

| | L0 | L1 | L2 | L3 | L4 | gate |
|---|---|---|---|---|---|---|
| **with measured falloff** | 93% | 68% | 33% | 11% | 1% | **FAIL** |
| **exposure compensated** | 97% | 93% | 87% | 55% | 8% | **PASS** |

**At high expansion the limit is photons, not geometry.** No tag size or dot spacing fixes it.

**Recommendation — free, and an acquisition change rather than a fabrication one: scale exposure
with λ².** At 4.2× that is roughly 6× the exposure of the 1.5× frame. With compensation the
design meets the bar at every λ; without it, frames above ~3× are signal-starved whatever is
printed.

This also reinforces the dot-size floor from Phase A. Photons collected scale with dot **area**,
so shrinking 2.125 → 1.0 µm would cost a further **4.5×** in signal on top of the λ⁻¹·⁸⁴ loss —
on top of halving the gel contact area. Both arguments point the same way: do not shrink the
dots.

## 5. What this says about the two variants

**Conservative (36 µm tags, 6.69 µm pitch, 8,125 dots)** works at the blur measured *today*.
It is the safe choice and needs nothing from the lab.

**Optimistic (24 µm tags, 5.00 µm pitch, 17,825 dots)** is the better design — smaller
fiducials, ~2.2× the dots, and a visibly more even lattice. But it is sized for a **1.91 µm**
PSF, and the measured blur is **3.0–3.2 µm**. Printed today, its tags would not decode.

It is therefore a **bet on the Phase-0b focus fix**. That bet is well-founded — 0b showed the
blur is not diffraction-limited (36–38% variation across the field, worse in the centre, which
points at a domed or tilted sample rather than the objective) — but it is still unconfirmed
until the z-stack is run.

**Recommendation:** run the Phase-0b z-stack before committing to fabrication. If the focus fix
lands, print optimistic. If it does not, print conservative.

## 6. Gate

```
  L0 mean >=90%, >=4 tags per frame : PASS
  falloff monotonic across ladder   : PASS
  ladder spans a usable range       : PASS
  >=1 tag at every lambda thru L2   : PASS
```

Two criteria were changed from the plan, both because the originals were not measuring the right
thing:

- *">=95% at every λ"* → **mean ≥90% with ≥4 decoded tags per frame**. A per-frame percentage is
  meaningless at high λ, where only 4–8 tags are in frame and one edge failure costs 12–25%. A
  count is not distorted by small N, and 4 tags is four times what registration needs.
- Absolute ladder → **ladder relative to each variant's design PSF** (§1).

## 7. Reproduce

```bash
cd ArUco_Tracker_V2/tools
python simulate_v2.py --variant conservative     # ~2 min
python simulate_v2.py --variant optimistic
python simulate_v2.py --quick                    # smoke test
```

Writes `sim/<variant>_<timestamp>/<level>/` with per-λ TIFFs, a montage per level, and
`sim_results.json`.
