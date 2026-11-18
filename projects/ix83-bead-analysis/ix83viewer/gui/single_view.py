"""Single-channel view: image, frame/projection controls, histogram + intensity colour bar."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QSlider, QSpinBox,
    QVBoxLayout, QWidget,
)

from ..core.display import LUT_NAMES
from ..core.settings_store import SettingsStore
from ..io.mm_dataset import MMDataset
from .adjustable import AdjustableChannel
from .common import MODES, load_image
from .scale_bar import MicronScaleBar
from .workers import LatestOnlyLoader


class SingleChannelView(QWidget, AdjustableChannel):
    """Shows one acquisition. Emits image_changed(shown_image) after each load."""

    image_changed = Signal(object)
    status = Signal(str)
    edited = Signal(object, object, object, str)  # target, before, after, kind (for undo)
    adjusted = Signal()  # settings, levels or image changed
    analysis_changed = Signal()
    analysis_layout_changed = Signal()

    def __init__(self, store: SettingsStore | None = None, parent=None):
        super().__init__(parent)
        self.ds: MMDataset | None = None
        self.dark_folder: str | None = None
        self.raw: np.ndarray | None = None
        self.shown: np.ndarray | None = None
        self.loader = LatestOnlyLoader(self)
        self.pre_expansion = False
        self.restore_range = None  # [[x0, x1], [y0, y1]] to apply instead of fitting (sessions)
        self._build_ui()
        self.loader.busy_changed.connect(lambda b: self.busy_label.setText("Loading…" if b else ""))
        self._init_adjustable(store if store is not None else SettingsStore())

    # ---- UI ------------------------------------------------------------
    def _build_ui(self):
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(MODES)
        self.mode_combo.setToolTip("Show a single frame, or combine all frames of the stack")
        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_spin = QSpinBox()
        self.frame_total = QLabel("/ 0")
        self.time_label = QLabel("")
        self.busy_label = QLabel("")
        self.busy_label.setStyleSheet("color: #c80;")

        top = QHBoxLayout()
        top.addWidget(QLabel("Show"))
        top.addWidget(self.mode_combo)
        top.addSpacing(12)
        top.addWidget(QLabel("Frame"))
        top.addWidget(self.frame_slider, 1)
        top.addWidget(self.frame_spin)
        top.addWidget(self.frame_total)
        top.addWidget(self.time_label)
        top.addWidget(self.busy_label)

        self.canvas = pg.GraphicsLayoutWidget()
        self.vb = self.canvas.addViewBox(row=0, col=0, lockAspect=True, invertY=True, enableMenu=False)
        self.img_item = pg.ImageItem()
        self.vb.addItem(self.img_item)
        self.hist = pg.HistogramLUTItem(image=self.img_item, fillHistogram=True)
        self.hist.axis.setLabel("Intensity (ADU)")
        self.hist.axis.enableAutoSIPrefix(False)
        self.canvas.addItem(self.hist, row=0, col=1)
        self.scale_bar = MicronScaleBar(self.vb)

        self.lut_combo = QComboBox()
        self.lut_combo.addItems(LUT_NAMES)
        self.auto_btn = QPushButton("Auto contrast")
        self.auto_btn.setToolTip("Clip the darkest 0.1% and brightest 0.1% of pixels")
        self.scale_check = QCheckBox("Scale bar")
        self.scale_check.setChecked(True)
        self.px_spin = QDoubleSpinBox()
        self.px_spin.setDecimals(4)
        self.px_spin.setRange(0.001, 100)
        self.px_spin.setSingleStep(0.01)
        self.px_spin.setSuffix(" µm/px")
        self.px_spin.setToolTip("Pixel size at the sample. Default: 11 µm camera pixel / objective magnification")
        self.readout = QLabel("")
        self.readout.setMinimumWidth(320)
        self.readout.setTextInteractionFlags(Qt.TextSelectableByMouse)

        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("LUT"))
        bottom.addWidget(self.lut_combo)
        bottom.addWidget(self.auto_btn)
        bottom.addWidget(self.scale_check)
        bottom.addWidget(self.px_spin)
        bottom.addStretch(1)
        bottom.addWidget(self.readout)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(top)
        lay.addWidget(self.canvas, 1)
        lay.addLayout(bottom)

        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        self.frame_slider.valueChanged.connect(self.frame_spin.setValue)
        self.frame_spin.valueChanged.connect(self.frame_slider.setValue)
        self.frame_spin.valueChanged.connect(lambda _: self.reload())
        self.lut_combo.currentTextChanged.connect(self._on_lut)
        self.auto_btn.clicked.connect(self.auto_contrast)
        self.scale_check.toggled.connect(self.scale_bar.set_enabled)
        self.px_spin.valueChanged.connect(self._on_pixel_size)
        self.canvas.scene().sigMouseMoved.connect(self._on_mouse)
        self._set_frame_controls(0)

    # ---- public API ----------------------------------------------------
    def set_dataset(self, ds: MMDataset):
        self.show_bg_roi(False)
        self.ds = ds
        self._load_settings_for_ds()
        self.px_spin.blockSignals(True)
        self.px_spin.setValue(ds.pixel_size_um or 0.001)
        self.px_spin.blockSignals(False)
        self.scale_bar.set_pixel_size(ds.pixel_size_um)
        self.scale_bar.set_expansion(ds.expansion_factor if self.pre_expansion else None)
        self._set_frame_controls(ds.n_frames)
        self.reload(new_levels=True)

    def set_dark_folder(self, folder: str | None):
        self.dark_folder = folder

    def set_color_preset(self, preset: str):
        self.color_preset = preset
        self.apply_style()

    def current_mode(self) -> str:
        return self.mode_combo.currentText()

    def set_pre_expansion(self, on: bool):
        self.pre_expansion = on
        self.scale_bar.set_expansion(self.ds.expansion_factor if (on and self.ds) else None)

    def analysis_channels(self):
        return [self] if self.shown is not None else []

    def analysis_vbs(self):
        return [self.vb]

    def reload(self, new_levels: bool = False):
        if self.ds is None:
            return
        ds, mode, frame = self.ds, self.mode_combo.currentText(), self.frame_spin.value()
        dark, proc = self.dark_folder, self.settings.processing
        if new_levels:
            self._levels_pending = True
        self.frame_slider.setEnabled(mode == "Frame")
        self.frame_spin.setEnabled(mode == "Frame")
        self._show_time(frame if mode == "Frame" else None)
        self.loader.request(
            lambda: load_image(ds, mode, frame, dark, proc),
            lambda res: self._on_loaded(ds, res),
            lambda msg: self.status.emit(f"Load failed: {msg.splitlines()[0]}"),
        )

    # ---- internals -----------------------------------------------------
    def _on_lut(self, name):
        self.lut_name = name
        self.apply_style()

    def _on_loaded(self, ds, result):
        if ds is not self.ds:
            return
        first_or_resized = self.shown is None or self.shown.shape != result[1].shape
        self.raw, self.shown = result
        self.img_item.setImage(self.shown, autoLevels=False)
        self._after_load()  # restores remembered levels for this acquisition/mode/processing
        if self.restore_range is not None:
            from .session import set_view
            set_view(self.vb, self.restore_range)
            self.restore_range = None
        elif first_or_resized:  # otherwise keep the zoom, e.g. when flipping between channels
            self.vb.autoRange(padding=0.01)
        self.scale_bar.refresh()
        self.image_changed.emit(self.shown)
        self.analysis_changed.emit()

    def _on_mode_changed(self, _):
        self.reload(new_levels=True)

    def _set_frame_controls(self, n):
        for w in (self.frame_slider, self.frame_spin):
            w.blockSignals(True)
            w.setRange(0, max(0, n - 1))
            w.setValue(0)
            w.blockSignals(False)
        self.frame_total.setText(f"/ {max(0, n - 1)}")

    def _show_time(self, frame):
        if frame is None or not self.ds or frame >= len(self.ds.frames):
            self.time_label.setText(f"{self.ds.n_frames} frames combined" if self.ds and frame is None else "")
            return
        t = self.ds.frames[frame].elapsed_ms
        self.time_label.setText(f"t = {t / 1000:.1f} s" if t is not None else "")

    def _on_pixel_size(self, value):
        if self.ds is not None:
            self.ds.pixel_size_override_um = value
        self.scale_bar.set_pixel_size(value)

    def _on_mouse(self, scene_pos):
        if self.shown is None or not self.vb.sceneBoundingRect().contains(scene_pos):
            self.readout.setText("")
            return
        p = self.img_item.mapFromScene(scene_pos)
        x, y = int(np.floor(p.x())), int(np.floor(p.y()))
        h, w = self.shown.shape
        if not (0 <= x < w and 0 <= y < h):
            self.readout.setText("")
            return
        v = self.shown[y, x]
        text = f"x {x}, y {y}   {v:,.1f} ADU"
        if self.shown is not self.raw:
            text += f" (raw {self.raw[y, x]:,.1f})"
        if self.px_spin.value():
            px = self.px_spin.value()
            text += f"   ({x * px:.1f}, {y * px:.1f}) µm"
        self.readout.setText(text)
