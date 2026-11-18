"""Channel-to-channel translation: estimate (auto-stack) and apply.

Convention: an offset (dy, dx) is the translation applied to the *moving*
image so it lines up with the reference (positive = move content down/right),
the same convention as skimage.registration.phase_cross_correlation and
scipy.ndimage.shift.

What the 16Oct26 data taught us (see IMPLEMENTATION_PLAN.md, Phase 3):
- Each channel labels different structures (561 nuclei, 488 cytoplasm,
  633 diffuse background), so cross-channel correlation is weak.
- Every image also carries static patterns that do not move with the sample:
  per-pixel camera noise, the field-stop edge, and debris in the light path.
  They pull estimates towards (0, 0); two *different* fields of view still
  peak at (0, 0) with confidence ~17.
Mitigations: a 3x3 median removes single-pixel patterns, a centre crop drops
the field-stop edge, a band-pass keeps cell-scale structure, and results
are only marked reliable above MIN_CONFIDENCE and within MAX_SHIFT_PX.
Offsets measured on multi-colour beads (all channels see the same points)
are the dependable route; see core/offsets.py for storing them as a
calibration.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage
from skimage.registration import phase_cross_correlation

CROP_FRACTION = 0.6  # keep the central 60% (drops the field-stop edge)
MEDIAN_SIZE = 3  # px; removes hot pixels / per-pixel fixed pattern
SMOOTH_SIGMA = 2.0  # px
BACKGROUND_SIGMA = 20.0  # px; removes background and illumination falloff
# Peak / std of the phase-correlation surface.  Different fields of view
# scored up to 17 on 16Oct26; same-field channel pairs 11-140.
MIN_CONFIDENCE = 20.0
# Chromatic offsets between channels on one microscope are a few pixels;
# anything larger is a false peak.
MAX_SHIFT_PX = 20.0


@dataclass(frozen=True)
class ShiftEstimate:
    dy: float
    dx: float
    confidence: float

    @property
    def reliable(self) -> bool:
        return (self.confidence >= MIN_CONFIDENCE
                and abs(self.dy) <= MAX_SHIFT_PX and abs(self.dx) <= MAX_SHIFT_PX)

    def describe(self) -> str:
        verdict = "reliable" if self.reliable else "uncertain"
        return f"({self.dx:+.2f}, {self.dy:+.2f}) px, confidence {self.confidence:.0f} ({verdict})"


def preprocess(img: np.ndarray, crop: float = CROP_FRACTION) -> np.ndarray:
    f = img.astype(np.float32)
    h, w = f.shape
    my, mx = int(h * (1 - crop) / 2), int(w * (1 - crop) / 2)
    f = f[my:h - my, mx:w - mx]
    f = ndimage.median_filter(f, MEDIAN_SIZE)
    f = ndimage.gaussian_filter(f, SMOOTH_SIGMA) - ndimage.gaussian_filter(f, BACKGROUND_SIGMA)
    f -= f.mean()
    window = np.outer(np.hanning(f.shape[0]), np.hanning(f.shape[1])).astype(np.float32)
    return f * window


def estimate_shift(reference: np.ndarray, moving: np.ndarray, upsample: int = 20,
                   crop: float = CROP_FRACTION) -> ShiftEstimate:
    """Sub-pixel translation to apply to `moving` so it matches `reference`."""
    if reference.shape != moving.shape:
        raise ValueError(f"Shape mismatch: {reference.shape} vs {moving.shape}")
    ref, mov = preprocess(reference, crop), preprocess(moving, crop)
    # Phase correlation finds the peak robustly but biases sub-pixel values
    # towards whole pixels (up to 0.25 px); plain correlation is accurate to
    # ~0.05 px but more easily fooled.  Use the plain value only when it agrees.
    robust, _, _ = phase_cross_correlation(ref, mov, upsample_factor=upsample, normalization="phase")
    fine, _, _ = phase_cross_correlation(ref, mov, upsample_factor=upsample, normalization=None)
    shift = fine if np.all(np.abs(fine - robust) <= 1.5) else robust
    return ShiftEstimate(dy=float(shift[0]), dx=float(shift[1]), confidence=_peak_confidence(ref, mov))


def _peak_confidence(ref: np.ndarray, mov: np.ndarray) -> float:
    cross = np.fft.fft2(ref) * np.conj(np.fft.fft2(mov))
    surface = np.fft.ifft2(cross / (np.abs(cross) + 1e-12)).real
    return float(surface.max() / (surface.std() + 1e-12))


def apply_shift(img: np.ndarray, dy: float, dx: float, order: int = 1, fill: float = 0.0) -> np.ndarray:
    """Translate img by (dy, dx); pixels shifted in from outside get `fill`.

    Whole-pixel shifts are exact copies (no interpolation).
    """
    if dy == 0 and dx == 0:
        return img
    if float(dy).is_integer() and float(dx).is_integer():
        out = np.full_like(img, fill)
        dy, dx = int(dy), int(dx)
        h, w = img.shape[:2]
        if abs(dy) >= h or abs(dx) >= w:
            return out
        ys, yd = (slice(0, h - dy), slice(dy, h)) if dy >= 0 else (slice(-dy, h), slice(0, h + dy))
        xs, xd = (slice(0, w - dx), slice(dx, w)) if dx >= 0 else (slice(-dx, w), slice(0, w + dx))
        out[yd, xd] = img[ys, xs]
        return out
    shift = (dy, dx) + (0,) * (img.ndim - 2)
    return ndimage.shift(img.astype(np.float32), shift, order=order, mode="constant", cval=fill)
