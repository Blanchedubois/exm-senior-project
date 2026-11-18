"""Optional per-channel processing applied to a projection before display.

Order: dark-frame subtraction -> background subtraction -> denoise.
Unlike display settings, these change pixel values, so they are recorded
(Processing.key() is part of the contrast-memory key, and Phase 5 writes it
into export sidecars).  Negative values after subtraction are clipped to 0.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from scipy import ndimage
from skimage.restoration import rolling_ball

from .corrections import subtract_dark

BACKGROUNDS = ("none", "percentile", "region", "rolling_ball")
BACKGROUND_LABELS = {
    "none": "None",
    "percentile": "Constant: percentile",
    "region": "Constant: region",
    "rolling_ball": "Rolling ball",
}
DENOISERS = ("none", "gaussian", "median")
DENOISE_LABELS = {"none": "None", "gaussian": "Gaussian", "median": "Median"}

# Rolling ball runs on a block-averaged copy: ~0.06 s instead of minutes at
# full size, and the averaging stops the ball from riding on noise minima.
ROLLING_BALL_DOWNSAMPLE = 4


@dataclass(frozen=True)
class Processing:
    dark: bool = False
    background: str = "none"
    bg_param: float = 50.0  # percentile (%) or rolling-ball radius (px)
    roi: tuple[int, int, int, int] | None = None  # x, y, w, h for "region"
    denoise: str = "none"
    denoise_param: float = 1.0  # Gaussian sigma or median size (px)

    @property
    def is_identity(self) -> bool:
        return not self.dark and self.background == "none" and self.denoise == "none"

    def key(self) -> str:
        """Short stable text identifying the pixel-changing steps."""
        parts = []
        if self.dark:
            parts.append("dark")
        if self.background == "region" and self.roi:
            parts.append("bg=region" + ",".join(map(str, self.roi)))
        elif self.background in ("percentile", "rolling_ball"):
            parts.append(f"bg={self.background}{self.bg_param:g}")
        if self.denoise != "none":
            parts.append(f"dn={self.denoise}{self.denoise_param:g}")
        return "+".join(parts) or "raw"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Processing":
        d = dict(d)
        if d.get("roi") is not None:
            d["roi"] = tuple(int(v) for v in d["roi"])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def background_image(img: np.ndarray, p: Processing) -> np.ndarray | float:
    if p.background == "percentile":
        return float(np.percentile(img, p.bg_param))
    if p.background == "region":
        if not p.roi:
            return 0.0
        x, y, w, h = p.roi
        patch = img[max(0, y):y + h, max(0, x):x + w]
        return float(np.median(patch)) if patch.size else 0.0
    if p.background == "rolling_ball":
        f = ROLLING_BALL_DOWNSAMPLE
        h, w = img.shape
        hh, ww = h // f * f, w // f * f
        small = img[:hh, :ww].reshape(hh // f, f, ww // f, f).mean(axis=(1, 3))
        bg_small = rolling_ball(small, radius=max(1.0, p.bg_param / f))
        return ndimage.zoom(bg_small, (h / bg_small.shape[0], w / bg_small.shape[1]), order=1).astype(np.float32)
    return 0.0


def denoise(img: np.ndarray, p: Processing) -> np.ndarray:
    if p.denoise == "gaussian":
        return ndimage.gaussian_filter(img, p.denoise_param)
    if p.denoise == "median":
        return ndimage.median_filter(img, max(1, int(round(p.denoise_param))))
    return img


def apply_processing(img: np.ndarray, p: Processing, dark: np.ndarray | None = None) -> np.ndarray:
    """Return the processed image (float32), or img itself when nothing applies."""
    if p.is_identity or (p.background == "none" and p.denoise == "none" and dark is None):
        return img
    out = img.astype(np.float32)
    if p.dark and dark is not None and dark.shape == out.shape:
        out = subtract_dark(out, dark)
    if p.background != "none":
        out = out - background_image(out, p)
        np.maximum(out, 0, out=out)
    return denoise(out, p).astype(np.float32, copy=False)
