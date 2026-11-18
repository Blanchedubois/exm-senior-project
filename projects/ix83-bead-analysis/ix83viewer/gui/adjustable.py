"""Shared behaviour of anything that shows one adjustable channel
(the single-channel view and each side-by-side ChannelPanel).

The host class must provide: ds, shown, hist (HistogramLUTItem), img_item,
vb, dark_folder, current_mode(), reload(new_levels), and the Qt signals
`edited(target, before, after, kind)` and `adjusted()`.  It calls
_init_adjustable(store) once and _after_load() whenever a new image is shown.

Every user change is reported through `edited` with before/after Snapshots,
which the view turns into undoable commands (gui/undo.py).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QTimer

from ..core.adjust import ChannelSettings, tone_curve
from ..core.analysis import clipping_overlay
from ..core.display import DEFAULT_PRESET, auto_levels, wavelength_color
from ..core.settings_store import LevelStore, SettingsStore

_ROI_PEN = pg.mkPen((255, 200, 0), width=2)
_DEFAULT_ROI = 120  # px, side of a new background region


@dataclass(frozen=True)
class Snapshot:
    settings: ChannelSettings
    levels: tuple[float, float] | None


class AdjustableChannel:
    # ---- setup ---------------------------------------------------------
    def _init_adjustable(self, store: SettingsStore):
        self.store = store
        self.settings = ChannelSettings()
        self.lut_name = "Wavelength colour"
        self.color_preset = DEFAULT_PRESET
        self._quiet = False  # programmatic level changes are not user edits
        self._last: Snapshot | None = None
        self._levels_override: tuple[float, float] | None = None
        self._levels_pending = False
        self._awaiting_image = False  # processing changed; levels come with the new image
        self._data_range: tuple[float, float] | None = None
        self.bg_roi: pg.RectROI | None = None
        self.show_clipping = False
        self.overlay_item = pg.ImageItem()
        self.overlay_item.setZValue(15)
        self.overlay_item.setVisible(False)
        self.vb.addItem(self.overlay_item)
        self.hist.sigLevelsChanged.connect(self._on_hist_levels)

    def _load_settings_for_ds(self):
        """Call when self.ds changes."""
        self.settings = self.store.get(self.ds)
        self._last = None
        self.apply_style()

    # ---- identity and colour -------------------------------------------
    @property
    def wavelength_nm(self) -> int | None:
        return self.ds.wavelength_nm if self.ds else None

    @property
    def name(self) -> str:
        return str(self.wavelength_nm) if self.wavelength_nm else (self.ds.label if self.ds else "")

    @property
    def color(self) -> tuple[float, float, float]:
        return self.settings.color or wavelength_color(self.wavelength_nm, self.color_preset)

    def colormap(self, lut_name: str | None = None) -> pg.ColorMap:
        """LUT for this channel with gamma and invert baked in, so the
        histogram's colour bar shows the true intensity -> colour mapping."""
        name = lut_name or self.lut_name
        if name == "Wavelength colour":
            r, g, b = self.color
            base = pg.ColorMap([0.0, 1.0], [(0, 0, 0), (int(r * 255), int(g * 255), int(b * 255))])
        elif name == "Gray":
            base = pg.ColorMap([0.0, 1.0], [(0, 0, 0), (255, 255, 255)])
        else:
            base = pg.colormap.get(name.lower())
        t = np.linspace(0.0, 1.0, 64)
        colors = base.map(tone_curve(t, self.settings.gamma, self.settings.invert), mode="byte")
        return pg.ColorMap(t, colors)

    def lut_table(self, gray: bool = False) -> np.ndarray:
        """256 x 3/4 uint8 table for the merged layer (always wavelength colour, or gray)."""
        return self.colormap("Gray" if gray else "Wavelength colour").getLookupTable(nPts=256, alpha=False)

    def apply_style(self):
        self.hist.gradient.setColorMap(self.colormap())
        self.hist.gradient.showTicks(False)  # 64 stops would draw 64 drag handles
        self.adjusted.emit()

    # ---- levels --------------------------------------------------------
    def level_key(self) -> str | None:
        if self.ds is None:
            return None
        return LevelStore.key(self.ds, self.current_mode(), self.settings.processing)

    def levels(self) -> tuple[float, float]:
        return tuple(float(v) for v in self.hist.getLevels())

    def set_levels(self, lo: float, hi: float):
        self.hist.setLevels(lo, hi)  # recorded by _on_hist_levels

    def auto_contrast(self):
        if self.shown is not None:
            self.set_levels(*auto_levels(self.shown))

    def data_range(self) -> tuple[float, float]:
        if self._data_range is None and self.shown is not None:
            self._data_range = auto_levels(self.shown, 0.01, 99.99)
        return self._data_range or (0.0, 1.0)

    def _set_levels_quietly(self, levels):
        self._quiet = True
        try:
            self.hist.setLevels(*levels)
        finally:
            self._quiet = False

    def _on_hist_levels(self):
        key = self.level_key()
        if self.shown is None or key is None:
            return
        self.store.levels[key] = self.levels()
        schedule_save(self.store)
        self.update_overlay()
        if not self._quiet:
            self._record("levels")
        self.adjusted.emit()

    # ---- settings ------------------------------------------------------
    def snapshot(self) -> Snapshot:
        """levels None = "whatever is stored for these settings, else auto"."""
        if self.shown is None or self._awaiting_image:
            return Snapshot(self.settings, None)
        return Snapshot(self.settings, self.levels())

    def set_settings(self, new: ChannelSettings, kind: str = "settings",
                     levels: tuple[float, float] | None = None):
        """User change of settings (recorded for undo)."""
        if new == self.settings and levels is None:
            return
        self._apply(new, levels)
        self._record(kind)

    def apply_snapshot(self, snap: Snapshot):
        """Undo/redo: restore without recording."""
        self._apply(snap.settings, snap.levels)
        self._last = snap

    def _apply(self, new: ChannelSettings, levels):
        old = self.settings
        self.settings = new
        self.store.set(self.ds, new)
        schedule_save(self.store)
        self._sync_roi()
        if new.processing != old.processing:
            self._levels_override = levels
            self._awaiting_image = True
            self.apply_style()
            self.reload(new_levels=True)  # levels follow in _after_load
        else:
            self.apply_style()
            if levels is not None:
                self._set_levels_quietly(levels)
                self.store.levels[self.level_key()] = tuple(levels)

    def _record(self, kind: str):
        after = self.snapshot()
        before = self._last
        self._last = after
        if before is not None and before != after:
            self.edited.emit(self, before, after, kind)

    # ---- image arrival -------------------------------------------------
    def _after_load(self):
        """Host calls this after setting self.shown for a new image."""
        self._data_range = None
        if self._levels_pending:
            self._levels_pending = False
            levels = self._levels_override or self.store.levels.get(self.level_key()) or auto_levels(self.shown)
            self._levels_override = None
            self._awaiting_image = False
            self._set_levels_quietly(levels)
            self.store.levels[self.level_key()] = tuple(levels)
            self._last = self.snapshot()
        elif self._last is None:
            self._last = self.snapshot()
        self.update_overlay()
        self.adjusted.emit()

    # ---- saturation / clipping overlay ----------------------------------
    def set_clipping_overlay(self, on: bool):
        self.show_clipping = on
        self.update_overlay()

    def update_overlay(self):
        if not self.show_clipping or self.shown is None:
            self.overlay_item.setVisible(False)
            return
        rgba = clipping_overlay(self.shown, getattr(self, "raw", None), self.levels())
        self.overlay_item.setImage(rgba, levels=(0, 255), autoLevels=False)
        self.overlay_item.setPos(self.img_item.pos())
        self.overlay_item.setVisible(True)

    # ---- background region (Processing.background == "region") --------
    def show_bg_roi(self, on: bool):
        if on and self.bg_roi is None:
            x, y, w, h = self.settings.processing.roi or self._default_roi()
            dy, dx = getattr(self, "display_offset", (0.0, 0.0))
            self.bg_roi = pg.RectROI((x + dx, y + dy), (w, h), pen=_ROI_PEN, removable=False)
            self.bg_roi.setZValue(20)
            self.vb.addItem(self.bg_roi)
            self.bg_roi.sigRegionChangeFinished.connect(self._on_roi_moved)
        elif not on and self.bg_roi is not None:
            self.vb.removeItem(self.bg_roi)
            self.bg_roi = None

    def current_roi_rect(self) -> tuple[int, int, int, int]:
        if self.bg_roi is None:
            return self.settings.processing.roi or self._default_roi()
        dy, dx = getattr(self, "display_offset", (0.0, 0.0))
        pos, size = self.bg_roi.pos(), self.bg_roi.size()
        return (int(round(pos.x() - dx)), int(round(pos.y() - dy)),
                max(1, int(round(size.x()))), max(1, int(round(size.y()))))

    def _default_roi(self):
        h, w = self.shown.shape if self.shown is not None else (512, 512)
        return (w // 2 - _DEFAULT_ROI // 2, h // 2 - _DEFAULT_ROI // 2, _DEFAULT_ROI, _DEFAULT_ROI)

    def _on_roi_moved(self):
        p = self.settings.processing
        if p.background == "region":
            self.set_settings(self.settings.with_(processing=replace(p, roi=self.current_roi_rect())), "region")

    def _sync_roi(self):
        if self.bg_roi is not None and self.settings.processing.roi:
            x, y, w, h = self.settings.processing.roi
            dy, dx = getattr(self, "display_offset", (0.0, 0.0))
            self.bg_roi.blockSignals(True)
            self.bg_roi.setPos((x + dx, y + dy))
            self.bg_roi.setSize((w, h))
            self.bg_roi.blockSignals(False)


# ---- debounced persistence -------------------------------------------
_save_timers: dict[int, QTimer] = {}


def schedule_save(store: SettingsStore, delay_ms: int = 800):
    """Write display.json shortly after the last change (slider drags fire often)."""
    t = _save_timers.get(id(store))
    if t is None:
        t = QTimer()
        t.setSingleShot(True)
        t.timeout.connect(store.save)
        _save_timers[id(store)] = t
    t.start(delay_ms)
