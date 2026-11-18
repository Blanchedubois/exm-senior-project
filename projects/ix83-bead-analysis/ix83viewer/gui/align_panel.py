"""Alignment controls for the side-by-side view.

One row per channel: select it (it becomes the layer that arrow keys nudge and
that Blink/Difference compare against the reference), edit dx/dy, lock it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QPushButton, QRadioButton, QVBoxLayout, QWidget,
)

from ..core.offsets import Offset
from .channel_panel import MERGE_MODES
from .common import text_color

MAX_OFFSET_PX = 100.0


def describe(offset: Offset) -> str:
    if offset.source == "auto":
        return f"auto · confidence {offset.confidence:.0f}" if offset.confidence else "auto"
    return {"none": "no offset", "calibration": "from calibration", "manual": "manual"}.get(offset.source, offset.source)


class _Row:
    def __init__(self, panel, is_reference: bool):
        self.panel = panel
        name = str(panel.wavelength_nm) if panel.wavelength_nm else panel.ds.label[:10]
        self.radio = QRadioButton(name)
        self.dx = _spin()
        self.dy = _spin()
        self.lock = QCheckBox()
        self.lock.setToolTip("Locked channels are skipped by Auto-align and nudging")
        self.status = QLabel("reference" if is_reference else "")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #888; font-size: 11px;")
        for w in (self.radio, self.dx, self.dy, self.lock):
            w.setEnabled(not is_reference)
        self.radio.setStyleSheet(f"color: {text_color(panel.color)}; font-weight: 600;")


def _spin() -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(-MAX_OFFSET_PX, MAX_OFFSET_PX)
    s.setDecimals(2)
    s.setSingleStep(0.1)
    s.setKeyboardTracking(False)
    s.setMinimumWidth(70)
    return s


class AlignPanel(QGroupBox):
    reference_changed = Signal(object)  # panel
    selected_changed = Signal(object)  # panel or None
    offset_edited = Signal(object, float, float)  # panel, dy, dx
    auto_clicked = Signal()
    reset_auto_clicked = Signal()
    zero_clicked = Signal()
    calibrate_clicked = Signal()
    mode_changed = Signal(str)
    aligned_panels_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__("Alignment", parent)
        self.rows: dict[object, _Row] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        self.ref_combo = QComboBox()
        self.ref_combo.setToolTip("Other channels are moved to line up with this one")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(MERGE_MODES)
        self.mode_combo.setToolTip("Blink and Difference compare the reference with the selected channel")
        self.auto_btn = QPushButton("Auto-align")
        self.auto_btn.setToolTip("Estimate each unlocked channel's offset from the displayed images\n"
                                 "(Mean gives the best signal).  Uncertain results are not applied.")
        self.uncertain_check = QCheckBox("Apply uncertain results")
        self.reset_btn = QPushButton("Reset to auto")
        self.zero_btn = QPushButton("Zero")
        self.cal_btn = QPushButton("Save as calibration")
        self.cal_btn.setToolTip("Reuse the selected channel's offset for every field of view taken\n"
                                "with this objective (best measured on multi-colour beads)")
        self.aligned_check = QCheckBox("Show channel panels aligned")
        self.aligned_check.setChecked(True)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        help_text = QLabel("Select a channel, then use the arrow keys to nudge it by 1 px, "
                           "or Shift+arrow keys for 0.1 px. Offsets are saved automatically.")
        help_text.setWordWrap(True)
        help_text.setStyleSheet("color: #888; font-size: 11px;")

        self.rows_host = QWidget()
        self.rows_grid = QGridLayout(self.rows_host)
        self.rows_grid.setContentsMargins(0, 0, 0, 0)

        top = QGridLayout()
        top.addWidget(QLabel("Reference"), 0, 0)
        top.addWidget(self.ref_combo, 0, 1)
        top.addWidget(QLabel("Merged view"), 1, 0)
        top.addWidget(self.mode_combo, 1, 1)
        buttons = QHBoxLayout()
        buttons.addWidget(self.reset_btn)
        buttons.addWidget(self.zero_btn)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.rows_host)
        lay.addWidget(self.auto_btn)
        lay.addWidget(self.uncertain_check)
        lay.addLayout(buttons)
        lay.addWidget(self.cal_btn)
        lay.addWidget(self.aligned_check)
        lay.addWidget(help_text)
        lay.addWidget(self.message)
        lay.addStretch(1)

        self.ref_combo.currentIndexChanged.connect(
            lambda i: self.reference_changed.emit(self.ref_combo.itemData(i)) if i >= 0 else None)
        self.mode_combo.currentTextChanged.connect(self.mode_changed.emit)
        self.auto_btn.clicked.connect(self.auto_clicked.emit)
        self.reset_btn.clicked.connect(self.reset_auto_clicked.emit)
        self.zero_btn.clicked.connect(self.zero_clicked.emit)
        self.cal_btn.clicked.connect(self.calibrate_clicked.emit)
        self.aligned_check.toggled.connect(self.aligned_panels_toggled.emit)
        self._group.buttonToggled.connect(lambda *_: self.selected_changed.emit(self.selected()))

    # ---- building ------------------------------------------------------
    def set_panels(self, panels, reference):
        self.ref_combo.blockSignals(True)
        self.ref_combo.clear()
        for p in panels:
            self.ref_combo.addItem(f"{p.wavelength_nm} nm" if p.wavelength_nm else p.ds.label, p)
        self.ref_combo.setCurrentIndex(panels.index(reference))
        self.ref_combo.blockSignals(False)
        self._build_rows(panels, reference)

    def set_reference(self, panels, reference):
        self._build_rows(panels, reference)

    def _build_rows(self, panels, reference):
        previous = self.selected()
        while self.rows_grid.count():
            w = self.rows_grid.takeAt(0).widget()
            if w:
                w.setParent(None)  # detach now; deleteLater alone leaves it drawn until the next loop
                w.deleteLater()
        for b in self._group.buttons():
            self._group.removeButton(b)
        self.rows = {}
        for col, text in enumerate(("nm", "dx (px)", "dy (px)", "Lock")):
            h = QLabel(text)
            h.setStyleSheet("color: #888;")
            self.rows_grid.addWidget(h, 0, col)
        for i, p in enumerate(panels):
            row = _Row(p, p is reference)
            r = 1 + 2 * i
            self.rows_grid.addWidget(row.radio, r, 0)
            self.rows_grid.addWidget(row.dx, r, 1)
            self.rows_grid.addWidget(row.dy, r, 2)
            self.rows_grid.addWidget(row.lock, r, 3, Qt.AlignCenter)
            self.rows_grid.addWidget(row.status, r + 1, 0, 1, 4)
            self._group.addButton(row.radio)
            row.dx.valueChanged.connect(lambda _, row=row: self._edited(row))
            row.dy.valueChanged.connect(lambda _, row=row: self._edited(row))
            self.rows[p] = row
        movable = [p for p in panels if p is not reference]
        pick = previous if previous in movable else (movable[0] if movable else None)
        if pick is not None:
            self.rows[pick].radio.setChecked(True)
        self.selected_changed.emit(self.selected())

    # ---- state ---------------------------------------------------------
    def selected(self):
        for p, row in self.rows.items():
            if row.radio.isChecked():
                return p
        return None

    def is_locked(self, panel) -> bool:
        row = self.rows.get(panel)
        return bool(row and row.lock.isChecked())

    def show_offset(self, panel, offset: Offset, note: str | None = None, tooltip: str = ""):
        row = self.rows.get(panel)
        if row is None or not row.dx.isEnabled():
            return
        for spin, v in ((row.dx, offset.dx), (row.dy, offset.dy)):
            spin.blockSignals(True)
            spin.setValue(v)
            spin.blockSignals(False)
        row.status.setText(note or describe(offset))
        row.status.setToolTip(tooltip)
        row.status.setStyleSheet(("color: #d08000;" if note and note.startswith("⚠") else "color: #888;")
                                 + " font-size: 11px;")

    def _edited(self, row: _Row):
        self.offset_edited.emit(row.panel, row.dy.value(), row.dx.value())
