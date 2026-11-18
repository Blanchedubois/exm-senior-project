"""Additive colour merge of single-channel images (display only).

Each channel is scaled to 0..1 by its own (low, high) display levels, tinted
by its colour, and the tints are summed and clipped, the same way Fiji's
"Composite" mode works.  Each layer can carry a (dy, dx) offset that is
applied before merging (see core/registration.py for the convention).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .registration import apply_shift


@dataclass
class Layer:
    image: np.ndarray
    levels: tuple[float, float]
    color: tuple[float, float, float]
    offset: tuple[float, float] = (0.0, 0.0)  # (dy, dx)


def normalize(img: np.ndarray, levels: tuple[float, float]) -> np.ndarray:
    lo, hi = levels
    span = hi - lo if hi > lo else 1.0
    out = (img.astype(np.float32) - lo) / span
    return np.clip(out, 0.0, 1.0, out=out)


def composite(layers: list[Layer]) -> np.ndarray:
    """H x W x 3 float32 RGB in 0..1. Layers must share a shape."""
    if not layers:
        raise ValueError("No layers to merge")
    shape = layers[0].image.shape
    rgb = np.zeros((*shape, 3), np.float32)
    for layer in layers:
        if layer.image.shape != shape:
            raise ValueError(f"Shape mismatch: {layer.image.shape} vs {shape}")
        n = apply_shift(normalize(layer.image, layer.levels), *layer.offset)
        for c in range(3):
            if layer.color[c]:
                rgb[..., c] += n * layer.color[c]
    return np.clip(rgb, 0.0, 1.0, out=rgb)
