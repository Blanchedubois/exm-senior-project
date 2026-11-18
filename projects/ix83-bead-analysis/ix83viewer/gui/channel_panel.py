"""One tile of the side-by-side view: a channel (or the merged image) with its own contrast."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..core.settings_store import SettingsStore
from ..io.mm_dataset import MMDataset
from .adjustable import AdjustableChannel
from .common import load_image, text_color
from .scale_bar import MicronScaleBar
from .workers import LatestOnlyLoader

HIST_HEIGHT = 80  # px for the histogram / colour-bar strip under each tile
_CURSOR_PEN = pg.mkPen((255, 255, 255, 110), width=1, style=Qt.DashLine)


class _Tile(QWidget):
    """Header row + image canvas + scale bar + crosshair; base for both tile kinds."""

    hovered = Signal(object)  # (x, y) in view (reference-image) pixels, or None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.header = QHBoxLayout()
        self.header.setContentsMargins(2, 0, 2, 0)
        self.canvas = pg.GraphicsLayoutWidget()
        self.canvas.ci.setContentsMargins(0, 0, 0, 0)
        self.vb = self.canvas.addViewBox(row=0, col=0, lockAspect=True, invertY=True, enableMenu=False)
        self.img_item = pg.ImageItem()
        self.vb.addItem(self.img_item)
        self.scale_bar = MicronScaleBar(self.vb)
        self.vline = pg.InfiniteLine(angle=90, pen=_CURSOR_PEN, movable=False)
        self.hline = pg.InfiniteLine(angle=0, pen=_CURSOR_PEN, movable=False)
        for line in (self.vline, self.hline):
            line.setVisible(False)
            self.vb.addItem(line, ignoreBounds=True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addLayout(self.header)
        lay.addWidget(self.canvas, 1)
        self.canvas.scene().sigMouseMoved.connect(self._on_mouse)

    def set_cursor(self, xy):
        for line in (self.vline, self.hline):
            line.setVisible(xy is not None)
        if xy is not None:
            self.vline.setPos(xy[0] + 0.5)
            self.hline.setPos(xy[1] + 0.5)

    def _on_mouse(self, scene_pos):
        if not self.vb.sceneBoundingRect().contains(scene_pos):
            self.hovered.emit(None)
            return
        p = self.vb.mapSceneToView(scene_pos)
        self.hovered.emit((int(np.floor(p.x())), int(np.floor(p.y()))))

    def leaveEvent(self, e):
        self.hovered.emit(None)
        super().leaveEvent(e)


class ChannelPanel(_Tile, AdjustableChannel):
    """Shows one wavelength; a combo picks which replicate acquisition to use."""

    image_changed = Signal()
    merge_toggled = Signal()
    dataset_changed = Signal()
    failed = Signal(str)
    edited = Signal(object, object, object, str)  # target, before, after, kind (for undo)
    adjusted = Signal()  # settings, levels or image changed

    def __init__(self, datasets: list[MMDataset], store: SettingsStore, parent=None):
        super().__init__(parent)
        self.datasets = datasets
        self.ds: MMDataset = _default_replicate(datasets)
        self.raw: np.ndarray | None = None
        self.shown: np.ndarray | None = None
        self.dark_folder: str | None = None
        self.display_offset = (0.0, 0.0)  # (dy, dx) the image is drawn shifted by
        self._req: tuple | None = None  # (mode, frame) last requested
        self.loader = LatestOnlyLoader(self)

        self.title = QLabel()
        self.title.setStyleSheet("font-weight: 600;")
        self.combo = QComboBox()
        for i, d in enumerate(datasets):
            self.combo.addItem(f"{d.label}  ({d.n_frames} fr)", d)
            self.combo.setItemData(i, d.label, Qt.ToolTipRole)
        self.combo.setCurrentIndex(datasets.index(self.ds))
        self.combo.setEnabled(len(datasets) > 1)
        # The replicate drop-down may shrink to almost nothing so three panels
        # plus the merge fit on a laptop screen; the full name is in its tooltip.
        self.combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(3)
        self.combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.combo.setMinimumWidth(40)
        self.merge_check = QCheckBox("Merge")
        self.merge_check.setChecked(True)
        self.merge_check.setToolTip("Include this channel in the merged image")
        self.note = QLabel()
        self.note.setStyleSheet("color: #d08000;")
        self.header.addWidget(self.title)
        self.header.addWidget(self.combo, 1)
        self.header.addWidget(self.note)
        self.header.addWidget(self.merge_check)

        self.hist = pg.HistogramLUTItem(image=self.img_item, orientation="horizontal")
        self.hist.axis.enableAutoSIPrefix(False)
        self.canvas.addItem(self.hist, row=1, col=0)
        self.canvas.ci.layout.setRowMaximumHeight(1, HIST_HEIGHT)  # leave the height to the image

        self.combo.currentIndexChanged.connect(self._on_replicate)
        self.merge_check.toggled.connect(lambda _: self.merge_toggled.emit())
        self.loader.busy_changed.connect(lambda b: self.title.setText(self._title() + (" …" if b else "")))
        self.title.setText(self._title())
        self.combo.setToolTip(self.ds.label)
        self.scale_bar.set_pixel_size(self.ds.pixel_size_um)
        self._init_adjustable(store)
        self._load_settings_for_ds()

    @property
    def in_merge(self) -> bool:
        return self.merge_check.isChecked() and self.shown is not None

    def current_mode(self) -> str:
        return self._req[0] if self._req else "Mean"

    def set_style(self, lut_name: str, preset: str):
        self.lut_name, self.color_preset = lut_name, preset
        self.apply_style()

    def apply_style(self):
        super().apply_style()
        self.title.setStyleSheet(f"font-weight: 600; color: {text_color(self.color)};"
                                 if self.lut_name == "Wavelength colour" else "font-weight: 600;")

    def load(self, mode: str, frame: int, dark_folder: str | None, new_levels: bool = False):
        self._req = (mode, frame)
        self.dark_folder = dark_folder
        self.reload(new_levels)

    def reload(self, new_levels: bool = False):
        if self._req is None:
            return
        mode, frame = self._req
        if new_levels:
            self._levels_pending = True
        ds, dark, proc = self.ds, self.dark_folder, self.settings.processing
        clamped = min(frame, ds.n_frames - 1)
        self.note.setText(f"last frame = {clamped}" if mode == "Frame" and frame > clamped else "")
        self.loader.request(lambda: load_image(ds, mode, frame, dark, proc),
                            lambda res: self._on_loaded(ds, res),
                            lambda msg: self.failed.emit(f"{ds.label}: {msg.splitlines()[0]}"))

    def set_display_offset(self, dy: float, dx: float):
        """Draw the image translated (no resampling): used to show it aligned."""
        self.display_offset = (dy, dx)
        self.img_item.setPos(dx, dy)
        self.overlay_item.setPos(dx, dy)
        self._sync_roi()

    def value_at(self, x: int, y: int):
        """Value under view pixel (x, y), undoing the display offset."""
        if self.shown is None:
            return None
        dy, dx = self.display_offset
        ix, iy = int(np.floor(x + 0.5 - dx)), int(np.floor(y + 0.5 - dy))
        h, w = self.shown.shape
        return float(self.shown[iy, ix]) if 0 <= ix < w and 0 <= iy < h else None

    # ---- internals -----------------------------------------------------
    def _title(self) -> str:
        return f"{self.wavelength_nm} nm" if self.wavelength_nm else self.ds.label

    def _on_loaded(self, ds, result):
        if ds is not self.ds:
            return
        self.raw, self.shown = result
        self.img_item.setImage(self.shown, autoLevels=False)
        self._after_load()
        self.image_changed.emit()

    def _on_replicate(self, index):
        self.show_bg_roi(False)
        self.ds = self.combo.itemData(index)
        self.combo.setToolTip(self.ds.label)
        self.scale_bar.set_pixel_size(self.ds.pixel_size_um)
        self.title.setText(self._title())
        self._load_settings_for_ds()
        self.reload(new_levels=True)
        self.dataset_changed.emit()


MERGE_MODES = ("Overlay", "Blink", "Difference")
BLINK_MS = 500


class MergedPanel(_Tile):
    """Live merge built from one ImageItem per channel, added together by Qt
    (CompositionMode_Plus).  Moving a layer is just setPos, so nudging and
    blinking need no recomputation.

    Modes:
      Overlay    every channel with Merge ticked, in its wavelength colour
      Blink      reference and the selected channel alternate every 0.5 s
      Difference |reference - selected| in gray; aligned structure goes dark
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.vb.removeItem(self.img_item)  # layers replace the single image
        title = QLabel("Merged")
        title.setStyleSheet("font-weight: 600;")
        self.note = QLabel()
        self.note.setStyleSheet("color: #888;")
        self.header.addWidget(title)
        self.header.addWidget(self.note, 1)
        self.canvas.addLabel("Contrast follows each channel's levels", row=1, col=0, color="#888", size="8pt")
        self.canvas.ci.layout.setRowMaximumHeight(1, HIST_HEIGHT)
        self.layers: dict[ChannelPanel, pg.ImageItem] = {}
        self.mode = "Overlay"
        self.reference: ChannelPanel | None = None
        self.moving: ChannelPanel | None = None
        self._offsets: dict[ChannelPanel, tuple[float, float]] = {}
        self._blink_on_ref = True
        self._blink = QTimer(self, interval=BLINK_MS)
        self._blink.timeout.connect(self._on_blink)

    def set_panels(self, panels: list[ChannelPanel]):
        for item in self.layers.values():
            self.vb.removeItem(item)
        self.layers = {}
        for p in panels:
            item = pg.ImageItem()
            item.setCompositionMode(QPainter.CompositionMode_Plus)
            self.vb.addItem(item)
            self.layers[p] = item
        self.refresh()

    def set_mode(self, mode: str, reference: ChannelPanel | None, moving: ChannelPanel | None):
        self.mode, self.reference, self.moving = mode, reference, moving
        if mode == "Blink" and reference and moving:
            self._blink.start()
        else:
            self._blink.stop()
        self.refresh()

    def refresh(self, offsets: dict | None = None):
        """Re-read every channel's image, levels and colour. offsets: panel -> (dy, dx)."""
        if offsets is not None:
            self._offsets = dict(offsets)
        pair_mode = self.mode in ("Blink", "Difference") and self.reference and self.moving
        for p, item in self.layers.items():
            if p.shown is None:
                item.setVisible(False)
                continue
            gray = self.mode == "Difference"
            item.setImage(p.shown, levels=p.levels(), lut=p.lut_table(gray), autoLevels=False)
            item.setOpacity(p.settings.opacity)
            dy, dx = self._offsets.get(p, (0.0, 0.0))
            item.setPos(dx, dy)
            item.setCompositionMode(QPainter.CompositionMode_Difference
                                    if gray and p is self.moving else QPainter.CompositionMode_Plus)
            if pair_mode:
                item.setZValue(1 if p is self.moving else 0)
                item.setVisible(p is self.reference or p is self.moving)
            else:
                item.setZValue(0)
                item.setVisible(p.merge_check.isChecked())
        if pair_mode and self.mode == "Blink":
            self._apply_blink()
        self.note.setText(self._describe())

    def set_offset(self, panel: ChannelPanel, dy: float, dx: float):
        self._offsets[panel] = (dy, dx)
        if panel in self.layers:
            self.layers[panel].setPos(dx, dy)

    def _describe(self) -> str:
        name = lambda p: str(p.wavelength_nm or p.ds.label)  # noqa: E731
        if self.mode == "Blink" and self.reference and self.moving:
            shown = self.reference if self._blink_on_ref else self.moving
            return f"blink {name(self.reference)} ↔ {name(self.moving)}  (showing {name(shown)})"
        if self.mode == "Difference" and self.reference and self.moving:
            return f"|{name(self.reference)} − {name(self.moving)}|  dark = matched"
        names = [name(p) for p in self.layers if p.merge_check.isChecked() and p.shown is not None]
        return " + ".join(names) if names else "nothing to merge"

    def _on_blink(self):
        self._blink_on_ref = not self._blink_on_ref
        self._apply_blink()
        self.note.setText(self._describe())

    def _apply_blink(self):
        for p, item in self.layers.items():
            if p is self.reference:
                item.setVisible(self._blink_on_ref and p.shown is not None)
            elif p is self.moving:
                item.setVisible(not self._blink_on_ref and p.shown is not None)


def _default_replicate(datasets: list[MMDataset]) -> MMDataset:
    """Most frames wins (the truncated 561-400ms_1 loses to _2); ties keep name order."""
    return max(datasets, key=lambda d: d.n_frames)
