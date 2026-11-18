"""
app.widgets
===========
Small reusable Qt widgets used across GUI stages.
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
    """A titled group box that holds a vertical stack of widgets."""
    def __init__(self, title, parent=None):
        super().__init__(title, parent)
        self._lay = QtWidgets.QVBoxLayout(self)
        self._lay.setSpacing(6)

    def add(self, w):
        self._lay.addWidget(w)
        return w
