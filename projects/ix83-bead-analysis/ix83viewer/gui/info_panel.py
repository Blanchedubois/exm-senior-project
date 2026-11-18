"""Right panel: acquisition metadata, warnings, and statistics for the shown image."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDoubleSpinBox, QFormLayout, QGroupBox, QLabel, QVBoxLayout, QWidget

from ..core.display import image_stats
from ..io.mm_dataset import MMDataset


def _value_label() -> QLabel:
    lab = QLabel("—")
    lab.setWordWrap(True)
    lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lab


class InfoPanel(QWidget):
    expansion_changed = Signal(object)  # the MMDataset whose factor was edited

    META_FIELDS = ("Wavelength", "Frames", "Exposure", "Objective", "Pixel size",
                   "Stage XYZ", "Started", "Comment", "Folder")
    STAT_FIELDS = ("Min", "Median", "Mean", "Max", "Saturated")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.meta = {k: _value_label() for k in self.META_FIELDS}
        self.stats = {k: _value_label() for k in self.STAT_FIELDS}
        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet("color: #d08000;")

        self.ds = None
        self.expansion = QDoubleSpinBox()
        self.expansion.setRange(0.0, 100.0)
        self.expansion.setDecimals(2)
        self.expansion.setSingleStep(0.1)
        self.expansion.setSpecialValueText("none")
        self.expansion.setSuffix(" ×")
        self.expansion.setToolTip("Gel expansion factor, read from the folder name (e.g. 3.0x).\n"
                                  "Edit it if the name is wrong; used by View ▸ Pre-expansion scale bars.")
        self.expansion.valueChanged.connect(self._on_expansion)
        meta_box = QGroupBox("Acquisition")
        f = QFormLayout(meta_box)
        for k, lab in self.meta.items():
            f.addRow(k, lab)
            if k == "Wavelength":
                f.addRow("Expansion", self.expansion)
        stats_box = QGroupBox("Shown image (ADU)")
        f2 = QFormLayout(stats_box)
        for k, lab in self.stats.items():
            f2.addRow(k, lab)

        lay = QVBoxLayout(self)
        lay.addWidget(meta_box)
        lay.addWidget(self.warn)
        lay.addWidget(stats_box)
        lay.addStretch(1)

    def set_dataset(self, d: MMDataset):
        x, y, z = d.stage_xyz_um
        intended = d.summary.get("IntendedDimensions", {}).get("time")
        frames = f"{d.n_frames}" + (f" of {intended}" if intended and intended != d.n_frames else "")
        px = d.pixel_size_um
        values = {
            "Wavelength": f"{d.wavelength_nm} nm" if d.wavelength_nm else d.name.kind,
            "Frames": frames,
            "Exposure": f"{d.exposure_ms:g} ms" if d.exposure_ms else "—",
            "Objective": d.objective or "—",
            "Pixel size": (f"{px:.4g} µm (metadata: {d.reported_pixel_size_um})" if px else "—"),
            "Stage XYZ": f"{x:.1f}, {y:.1f}, {z:.1f} µm" if x is not None else "—",
            "Started": d.start_time or "—",
            "Comment": d.comment or "—",
            "Folder": os.path.join(os.path.basename(os.path.dirname(d.folder)), os.path.basename(d.folder)),
        }
        self.ds = d
        self.expansion.blockSignals(True)
        self.expansion.setValue(d.expansion_factor or 0.0)
        self.expansion.blockSignals(False)
        for k, v in values.items():
            self.meta[k].setText(v)
        self.meta["Folder"].setToolTip(d.folder)
        self.warn.setText("\n".join("⚠ " + w for w in d.warnings))
        for lab in self.stats.values():
            lab.setText("—")

    def _on_expansion(self, value):
        if self.ds is not None:
            self.ds.expansion_override = value or None
            self.expansion_changed.emit(self.ds)

    def set_image(self, img):
        s = image_stats(img)
        self.stats["Min"].setText(f"{s['min']:,.1f}")
        self.stats["Median"].setText(f"{s['median']:,.1f}")
        self.stats["Mean"].setText(f"{s['mean']:,.1f}")
        self.stats["Max"].setText(f"{s['max']:,.1f}")
        self.stats["Saturated"].setText(f"{s['saturated']:,} px")
