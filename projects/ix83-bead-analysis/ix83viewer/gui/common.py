"""Pieces shared by the single-channel and side-by-side views."""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import pyqtgraph as pg

from ..core.corrections import build_dark_frame
from ..core.processing import Processing, apply_processing
from ..core.projection import project
from ..io.mm_dataset import MMDataset

pg.setConfigOptions(imageAxisOrder="row-major")

MODES = ("Frame", "Mean", "Max", "Median", "Min", "Sum")


def text_color(rgb) -> str:
    """CSS colour for a channel name: the channel colour, lightened in dark
    mode (pure blue is unreadable on dark grey) and darkened in light mode
    (pure green or yellow is unreadable on white)."""
    from PySide6.QtWidgets import QApplication

    r, g, b = rgb
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    app = QApplication.instance()
    dark = app is not None and app.palette().window().color().lightness() < 128
    if dark and luminance < 0.5:
        a = 0.55 - luminance  # blend towards white
        r, g, b = (c + (1 - c) * a for c in (r, g, b))
    elif not dark and luminance > 0.6:
        r, g, b = (c * 0.6 for c in (r, g, b))
    return f"rgb({int(r * 255)},{int(g * 255)},{int(b * 255)})"


@lru_cache(maxsize=2)
def dark_frame(dark_folder: str) -> np.ndarray:
    return build_dark_frame(MMDataset.open(dark_folder))


def load_image(ds: MMDataset, mode: str, frame: int, dark_folder: str | None,
               processing: Processing | None = None):
    """Runs on a worker thread. Returns (raw, shown); shown has processing applied."""
    frame = min(frame, ds.n_frames - 1)
    raw = project(ds, mode.lower(), frame=frame)
    p = processing or Processing()
    dark = dark_frame(dark_folder) if (p.dark and dark_folder) else None
    return raw, apply_processing(raw, p, dark)
