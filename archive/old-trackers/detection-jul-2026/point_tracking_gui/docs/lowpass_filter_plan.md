# Implementation Plan — FFT Low-Pass Filter in Stage 1 (Shared Optics Correction)

> **Status: IMPLEMENTED.** `correct.lowpass` + `_lowpass_mask` in `gridtrack/correct.py` (applied last
> in `apply`), 4 new `CorrectionParams` fields, LP controls on both the `stageui` Stage-1 panel and the
> expansion app's Setup ("Shared optics correction") panel with live write-through, and 5 headless
> tests (all green). Off by default (`lp_enable=False`) ⇒ zero behaviour change until switched on.

**Goal.** Add a **2-D Fourier low-pass filter** with a user-settable **cut-off frequency** to the
Stage-1 optics correction, so high-frequency camera noise / speckle can be suppressed before ArUco
detection and dot/dash localisation. It lives in the **Shared Optics Correction** (same for every
image, like vignette + lens) and is exposed on the Stage-1 panel and the expansion app's Setup panel.

This is a design doc to workshop first — see **Open questions** at the end.

---

## 1. Where it lives

`gridtrack/correct.py` is the single headless home for Stage-1 maths. It already does
`apply(img, p) = correct_distortion(correct_vignette(img, p), p)`. We add a third operation,
`lowpass(img, p)`, driven by new fields on `CorrectionParams` (so it travels in `project.json`,
session files, and the per-image pipeline automatically).

Because it is part of `CorrectionParams`, it is **shared across all images** by construction (Stage-1
optics), exactly as requested. The Verify view's Stage-1 panel already writes through to
`project.correction`, and the batch pipeline reads the same object — so no plumbing beyond the maths +
the sliders is required.

---

## 2. Parameters (added to `CorrectionParams`)

```python
# 2-D FFT low-pass (noise suppression), applied in Stage 1
lp_enable: bool = False          # off by default -> zero behaviour change until switched on
lp_cutoff: float = 0.50          # cut-off, in units chosen below (default = half-Nyquist)
lp_shape: str   = "gaussian"     # "gaussian" | "butterworth" | "ideal"
lp_order: int   = 2              # Butterworth roll-off order (ignored by gaussian/ideal)
```

- Defaults keep `apply()` **bit-identical to today** when `lp_enable=False`, so every existing test,
  the simulator round-trip, and saved projects are unaffected.
- `from_dict` already filters unknown keys, so old `project.json` files load fine (missing keys →
  defaults).

### Cut-off units — the key decision (see Open questions Q1)
The filter needs a cut-off radius in the frequency plane. Candidate ways to express it:

| Option | Slider reads | Pros | Cons |
|---|---|---|---|
| **A. Normalised (fraction of Nyquist)** | `0.0–1.0` (×0.5 cyc/px) | unit-free, always valid, no calibration needed | not physical |
| **B. Cycles per pixel** | `0.0–0.5` | direct FFT unit | still not physical |
| **C. Cycles per µm** | e.g. `0–4` | physical, microscope-native | needs px/µm (only known after Stage 3, or entered) |
| **D. Smallest resolved feature (µm)** | e.g. `0.25 µm` | intuitive "resolution" knob | needs px/µm; inverse feel |

**Recommendation: A (fraction of Nyquist)** as the stored/authoritative value — it is robust and needs
no calibration — with a **live read-out** of the µm-equivalent shown beside the slider *when* a px/µm
scale is available (the camera scale is known: `8 px/µm` in the sim; the app can carry it as a
Stage-1 "pixel size" field). If you'd rather dial the physical number directly, we store option C/D
and convert internally using an explicit `px_per_um` you set once in the optics section.

---

## 3. The maths (`correct.lowpass`)

```python
def lowpass(img, p):
    if not p.lp_enable or p.lp_cutoff >= 1.0 and p.lp_shape == "ideal":
        return img.astype(np.float32, copy=False)
    f = np.fft.fft2(_reflect_pad(img))               # pad to tame edge ringing
    fs = np.fft.fftshift(f)
    H = _filter_mask(f.shape, p)                      # radial transfer function in [0,1]
    out = np.fft.ifft2(np.fft.ifftshift(fs * H)).real
    return _unpad(out).astype(np.float32)
```

**Radial frequency grid.** Build normalised radius `D = sqrt(fx² + fy²)` using `np.fft.fftfreq`
(cycles/px), then `Dn = D / 0.5` (fraction of Nyquist). Cut-off `Dc = lp_cutoff` (in the same
normalised units after conversion from the chosen unit).

**Transfer functions** `H(D)`:
- **Gaussian** (recommended default — no ringing): `H = exp(-(D²)/(2·Dc²))`.
- **Butterworth** (adjustable sharpness): `H = 1 / (1 + (D/Dc)^(2·order))`.
- **Ideal** (sharpest, but ringing/Gibbs): `H = (D ≤ Dc)`.

**Edge handling.** FFT assumes periodicity; a non-periodic frame produces wrap-around ringing at the
borders. Mitigate with a **reflect-pad** (e.g. 32 px) before the transform and crop after. (Cheap and
effective; alternative is a Hann window, but that dims the borders.)

**DC preservation.** All three `H` pass `D=0` at gain 1, so mean brightness is preserved — important
so downstream vignette/threshold behaviour is unchanged in the low-frequency band.

**Cost.** `fft2` on a ~1600² frame is ~30–80 ms — fine on the main thread with the existing 40 ms
slider debounce. `rfft2/irfft2` (real transform) halves it if needed.

---

## 4. Order in the Stage-1 pipeline

`apply()` currently: **vignette → distortion**. Where does low-pass go?

- **Recommendation: last — vignette → distortion → low-pass.** Rationale: vignette *division*
  amplifies corner noise, and the distortion `remap` (INTER_LINEAR) slightly resamples; running the
  low-pass on the final geometrically-true, flat image is the cleanest "denoise just before
  detection". 
- Alternative: **first** (raw → low-pass → vignette → distortion), i.e. treat it as a sensor
  pre-filter. Slightly more physical (noise is added at the sensor) but the remap then re-mixes
  frequencies a little.

Difference is minor in practice; I'll default to **last** unless you prefer first (Q3).

---

## 5. GUI

**Stage-1 panel (`stageui/stage1_correct.py`)** — add a `Collapsible("Low-pass (FFT denoise)")`:
- `Enable` checkbox (`lp_enable`).
- `cut-off` `SliderSpin` (range per the chosen unit) + a small µm-equivalent read-out label.
- `shape` combo (gaussian / butterworth / ideal) and an `order` spin (enabled only for butterworth).
- Wire into the existing debounce → `_recompute()` so the preview updates live; `_params()` writes the
  four fields into `state.correction`. `set_correction()` syncs the new widgets too.
- Optional (nice-to-have): a **"show FFT magnitude"** toggle that swaps the canvas / a small inset to
  the log-magnitude spectrum with the cut-off ring drawn — makes the cut-off visually meaningful.
  (Deferred unless you want it.)

**Expansion app Setup panel (`app/setup_panel.py`)** — it mirrors the shared correction sliders, so
add the same four controls there and extend `_pull_correction()`. (Both edit the one
`project.correction`, so Verify and Setup stay consistent.)

---

## 6. Persistence & compatibility
- `project.json` (expansion app) and `session.json` (point app) serialise `CorrectionParams` wholesale
  → the new fields persist automatically.
- Old files load unchanged (defaults fill the missing keys; `lp_enable=False` ⇒ no behavioural change).

---

## 7. Tests (headless, `point_tracking_gui/tests/`)
- **DC/flat pass-through:** a constant image is unchanged (gain 1 at D=0).
- **Attenuation:** synthesise two sine gratings — one below, one above the cut-off — assert the
  above-cut-off amplitude is strongly reduced and the below-cut-off one is ~preserved (per shape).
- **No-op when disabled:** `apply()` with `lp_enable=False` equals today's `apply()` exactly.
- **Shape monotonicity:** `H` is monotone-decreasing in D for each shape; ideal is a hard step.
- **Edge ringing bounded:** with reflect-pad, border artefacts on a step image stay under a threshold.

---

## 8. Risks / notes
- **Over-smoothing hurts localisation.** Too low a cut-off blurs dots/dashes and biases centroids.
  Default `lp_enable=False`; recommend Gaussian with a conservative cut-off. The Stage-4 dot-diameter
  is the natural guide (don't cut below the dot's fundamental).
- **Ringing** from the ideal filter can create phantom peaks trackpy might latch onto — hence Gaussian
  default and the reflect-pad.
- **Interaction with CLAHE/invert (Stage 2).** Low-pass runs in Stage 1, before the Stage-2
  invert/CLAHE preprocessing, so ordering is well-defined.
- **Not literally "optics".** It's a denoise pre-filter placed in the optics section per your request;
  documented as such so it isn't mistaken for a physical flat-field.

---

## Decisions (locked in)
1. **Cut-off units — Fraction of Nyquist** (0.0–1.0). Stored as the authoritative value; a µm-equiv
   read-out is shown when a pixel-size is available. No px/µm field required.
2. **Filter shape default — Gaussian.** The combo still offers Butterworth (with order) and Ideal.
3. **Pipeline order — last** (vignette → distortion → low-pass). [my recommended default; not
   contested]
4. **FFT spectrum view — skipped** for now (corrected-image preview only). [my recommended default]
