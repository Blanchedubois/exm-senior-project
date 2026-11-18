"""Per-channel cosmetic settings and the brightness/contrast <-> levels maths.

Levels (black, white) are the single source of truth for brightness and
contrast; the B/C sliders are another view of them, as in ImageJ:
  brightness B in [-100, 100] moves the window centre across the data range
  (higher = brighter image), contrast C in [-100, 100] narrows (C > 0) or
  widens (C < 0) the window on a log scale (C = 50 -> window = range / 10).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np

from .processing import Processing

GAMMA_MIN, GAMMA_MAX = 0.2, 5.0


@dataclass(frozen=True)
class ChannelSettings:
    processing: Processing = field(default_factory=Processing)
    gamma: float = 1.0
    invert: bool = False
    color: tuple[float, float, float] | None = None  # None = wavelength colour
    opacity: float = 1.0  # weight in the merged image

    def with_(self, **kw) -> "ChannelSettings":
        return replace(self, **kw)

    def to_dict(self) -> dict:
        return {"processing": self.processing.to_dict(), "gamma": self.gamma, "invert": self.invert,
                "color": list(self.color) if self.color else None, "opacity": self.opacity}

    @classmethod
    def from_dict(cls, d: dict) -> "ChannelSettings":
        return cls(
            processing=Processing.from_dict(d.get("processing", {})),
            gamma=float(d.get("gamma", 1.0)),
            invert=bool(d.get("invert", False)),
            color=tuple(d["color"]) if d.get("color") else None,
            opacity=float(d.get("opacity", 1.0)),
        )


def bc_from_levels(levels: tuple[float, float], data_range: tuple[float, float]) -> tuple[float, float]:
    lo, hi = levels
    dmin, dmax = data_range
    span = max(dmax - dmin, 1e-9)
    width = max(hi - lo, 1e-9)
    b = (dmin + span / 2 - (lo + hi) / 2) / (span / 2) * 100
    c = -50 * math.log10(width / span)
    return _clamp(b, -100, 100), _clamp(c, -100, 100)


def levels_from_bc(b: float, c: float, data_range: tuple[float, float]) -> tuple[float, float]:
    dmin, dmax = data_range
    span = max(dmax - dmin, 1e-9)
    centre = dmin + span / 2 - (b / 100) * (span / 2)
    width = span * 10 ** (-c / 50)
    return centre - width / 2, centre + width / 2


def tone_curve(t: np.ndarray, gamma: float = 1.0, invert: bool = False) -> np.ndarray:
    """Map normalised intensity t in [0, 1] through gamma, optionally inverted."""
    out = np.clip(t, 0, 1) ** gamma
    return 1 - out if invert else out


def gamma_to_slider(gamma: float) -> int:
    """Slider -100..100 on a log scale: 0 -> 1.0, +-100 -> 5.0 / 0.2."""
    return int(round(100 * math.log(gamma) / math.log(GAMMA_MAX)))


def slider_to_gamma(v: int) -> float:
    return round(GAMMA_MAX ** (v / 100), 3)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))
