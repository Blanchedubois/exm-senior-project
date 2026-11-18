"""Display-only helpers: wavelength colours, lookup tables, auto-contrast.

Nothing here changes pixel values; it only decides how they are drawn.
"""

from __future__ import annotations

import numpy as np

# Colour presets: wavelength (nm) -> RGB in 0..1.
COLOR_PRESETS: dict[str, dict[int, tuple[float, float, float]]] = {
    # The user's requested mapping: longest wavelength red, shortest blue.
    "Spectral RGB (633 R / 561 G / 488 B)": {633: (1, 0, 0), 561: (0, 1, 0), 488: (0, 0, 1)},
    # Common biology convention; magenta keeps it colour-blind safe.
    "Biology (488 G / 561 R / 633 M)": {488: (0, 1, 0), 561: (1, 0, 0), 633: (1, 0, 1)},
    # Approximate perceived emission colour.
    "True colour": {488: (0, 1, 0.9), 561: (1, 0.9, 0), 633: (1, 0, 0)},
}
DEFAULT_PRESET = "Spectral RGB (633 R / 561 G / 488 B)"

# LUT choices offered next to the wavelength colour.  None = use wavelength.
LUT_NAMES = ("Wavelength colour", "Gray", "Inferno", "Viridis", "Magma")


def wavelength_color(wavelength_nm: int | None, preset: str = DEFAULT_PRESET) -> tuple[float, float, float]:
    """Colour for a wavelength; nearest known line, white if unknown."""
    table = COLOR_PRESETS[preset]
    if wavelength_nm is None:
        return (1.0, 1.0, 1.0)
    if wavelength_nm in table:
        return table[wavelength_nm]
    nearest = min(table, key=lambda w: abs(w - wavelength_nm))
    return table[nearest] if abs(nearest - wavelength_nm) <= 30 else (1.0, 1.0, 1.0)


def ramp_lut(color: tuple[float, float, float], n: int = 256) -> np.ndarray:
    """n x 3 uint8 lookup table running black -> color."""
    t = np.linspace(0.0, 1.0, n)[:, None]
    return np.round(t * np.asarray(color)[None, :] * 255).astype(np.uint8)


def auto_levels(img: np.ndarray, low_pct: float = 0.1, high_pct: float = 99.9, max_samples: int = 500_000) -> tuple[float, float]:
    """Percentile clip limits, like Micro-Manager's autostretch.

    Large images are subsampled on a regular grid for speed.
    """
    flat = img.ravel()
    if flat.size > max_samples:
        flat = flat[:: flat.size // max_samples]
    lo, hi = np.percentile(flat, (low_pct, high_pct))
    if hi <= lo:
        hi = lo + 1
    return float(lo), float(hi)


def nice_scale_length(target_um: float) -> float:
    """Largest 1/2/5 x 10^n value not above target_um (min 1e-3 um)."""
    if target_um <= 0:
        return 1.0
    exp = np.floor(np.log10(target_um))
    for m in (5, 2, 1):
        v = m * 10**exp
        if v <= target_um:
            return float(v)
    return float(10**exp)


def format_um(um: float) -> str:
    if um >= 1000:
        return f"{um / 1000:g} mm"
    return f"{um:g} µm"


def image_stats(img: np.ndarray, saturation: int = 65535) -> dict[str, float]:
    return {
        "min": float(img.min()),
        "max": float(img.max()),
        "mean": float(img.mean()),
        "median": float(np.median(img)),
        "saturated": int(np.count_nonzero(img >= saturation)),
    }
