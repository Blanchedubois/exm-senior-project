"""Camera corrections applied before display or quantitative export.

The dark frame comes from a DarkCount acquisition (16Oct26: 1000 frames at
10 ms).  The Prime 95B is cooled to -15 C, so dark current over a 150-500 ms
exposure is negligible next to the ~100 ADU offset; a 10 ms dark frame is a
fair estimate of offset plus fixed-pattern noise for every exposure used.
"""

from __future__ import annotations

import numpy as np

from ..io.mm_dataset import MMDataset
from .projection import project


def build_dark_frame(dark: MMDataset, method: str = "median", use_cache: bool = True) -> np.ndarray:
    """Master dark frame (float32). Median rejects cosmic-ray / hot-pixel spikes."""
    if dark.name.kind != "dark":
        raise ValueError(f"{dark.label} does not look like a dark acquisition")
    return project(dark, method=method, use_cache=use_cache)


def subtract_dark(img: np.ndarray, dark: np.ndarray, clip: bool = True) -> np.ndarray:
    """img - dark as float32; clip negatives (read noise) to 0 by default."""
    if img.shape != dark.shape:
        raise ValueError(f"Shape mismatch: image {img.shape} vs dark {dark.shape}")
    out = img.astype(np.float32) - dark.astype(np.float32)
    if clip:
        np.maximum(out, 0, out=out)
    return out
