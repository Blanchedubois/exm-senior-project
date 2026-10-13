"""
rwtag — Reference-Warp Tagger, headless core.

Stage 1: microscope-optics correction (vignette, lens distortion, FFT low-pass,
deskew rotation) plus a per-image contrast/threshold (levels) remap. NO Qt and
NO GUI imports live in this package, so it stays unit-testable and embeddable.
"""
from __future__ import annotations

from .types import CorrectionParams, LevelsParams, PipelineState
from . import correct, io

__all__ = ["CorrectionParams", "LevelsParams", "PipelineState", "correct", "io"]
