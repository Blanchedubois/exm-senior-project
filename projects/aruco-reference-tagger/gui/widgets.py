"""
gui.widgets
===========
Small reusable Qt widgets. `SliderSpin` and `Collapsible` are ported verbatim
from the Point-Tracking GUI; `Collapsible` gains an optional "shared across
series" checkbox in its header (the per-image vs shared control).
"""
from __future__ import annotations
from PySide6 import QtWidgets, QtCore


class SliderSpin(QtWidgets.QWidget):
    """A labelled float slider linked to a spin box. Emits valueChanged(float)."""
    valueChanged = QtCore.Signal(float)

    def __init__(self, label, lo, hi, value, step=0.01, decimals=3, parent=None):
        super().__init__(parent)
        self._lo, self._hi, self._step = lo, hi, step
        self._n = max(1, int(round((hi - lo) / step)))

        self.label = QtWidgets.QLabel(label)
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setRange(0, self._n)
        self.spin = QtWidgets.QDoubleSpinBox()
        self.spin.setRange(lo, hi)
        self.spin.setSingleStep(step)
        self.spin.setDecimals(decimals)

        lay = QtWidgets.QGridLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.label, 0, 0)
        lay.addWidget(self.spin, 0, 1)
        lay.addWidget(self.slider, 1, 0, 1, 2)

        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)
        self.set_value(value)

    def _to_slider(self, v):
        return int(round((v - self._lo) / self._step))

    def _from_slider(self, iv):
        v = self._lo + iv * self._step
        self.spin.blockSignals(True); self.spin.setValue(v); self.spin.blockSignals(False)
        self.valueChanged.emit(v)

    def _from_spin(self, v):
        self.slider.blockSignals(True); self.slider.setValue(self._to_slider(v)); self.slider.blockSignals(False)
        self.valueChanged.emit(v)

    def value(self) -> float:
        return self.spin.value()

    def set_value(self, v: float):
        self.spin.blockSignals(True); self.slider.blockSignals(True)
        self.spin.setValue(v); self.slider.setValue(self._to_slider(v))
        self.spin.blockSignals(False); self.slider.blockSignals(False)


class Collapsible(QtWidgets.QGroupBox):
    """A titled group box holding a vertical stack of widgets.

    If `shared_default` is not None the header shows a checkable box: checked =
    'shared across series' (the params persist as you open the next image);
    unchecked = 'per-image'. Emits `sharedToggled(bool)`."""
    sharedToggled = QtCore.Signal(bool)

    def __init__(self, title, shared_default=None, parent=None):
        super().__init__(title, parent)
        self._lay = QtWidgets.QVBoxLayout(self)
        self._lay.setSpacing(6)
        self._has_shared = shared_default is not None
        if self._has_shared:
            self.setCheckable(False)
            row = QtWidgets.QHBoxLayout()
            self.chk_shared = QtWidgets.QCheckBox("shared across series")
            self.chk_shared.setChecked(bool(shared_default))
            self.chk_shared.setToolTip(
                "Checked: these params persist as you open the next image "
                "(microscope optics).\nUnchecked: per-image (remembered per file).")
            self.chk_shared.toggled.connect(self.sharedToggled)
            row.addStretch(1); row.addWidget(self.chk_shared)
            _w = QtWidgets.QWidget(); _w.setLayout(row)
            self._lay.addWidget(_w)

    def add(self, w):
        self._lay.addWidget(w)
        return w

    def is_shared(self) -> bool:
        return self._has_shared and self.chk_shared.isChecked()

    def set_shared(self, on: bool):
        if self._has_shared:
            self.chk_shared.blockSignals(True)
            self.chk_shared.setChecked(bool(on))
            self.chk_shared.blockSignals(False)
