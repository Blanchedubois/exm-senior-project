"""
gui.compare_common
==================
Shared pieces of the cross-image tabs (5 Pair, 6 Overlay, 7 Field, 8 Series):
the reference / compared image selector over the project's ACCEPTED images,
heat-map colour maps, and an ellipse helper.
"""
from __future__ import annotations
import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets, QtCore


def accepted(project):
    if project is None:
        return []
    return [e for e in sorted(project.images, key=lambda e: e.label)
            if e.pipeline.tagging is not None and e.pipeline.tagging.accepted]


class PairSelector(QtWidgets.QWidget):
    """Two combos: reference (default the project's Initial) and compared
    (default the next accepted image). Emits changed() on a user pick."""
    changed = QtCore.Signal()

    def __init__(self, project_fn, with_compare=True, parent=None):
        super().__init__(parent)
        self.project_fn = project_fn
        lay = QtWidgets.QGridLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        self.cmb_ref = QtWidgets.QComboBox(); self.cmb_cmp = QtWidgets.QComboBox()
        lay.addWidget(QtWidgets.QLabel("reference:"), 0, 0); lay.addWidget(self.cmb_ref, 0, 1)
        if with_compare:
            lay.addWidget(QtWidgets.QLabel("compared:"), 1, 0); lay.addWidget(self.cmb_cmp, 1, 1)
        else:
            self.cmb_cmp.hide()
        self._entries = []
        self.cmb_ref.activated.connect(lambda *_: self.changed.emit())
        self.cmb_cmp.activated.connect(lambda *_: self.changed.emit())

    def refresh(self):
        proj = self.project_fn()
        acc = accepted(proj)
        cur_r, cur_c = self.ref(), self.cmp()
        self._entries = acc
        for cmb in (self.cmb_ref, self.cmb_cmp):
            cmb.blockSignals(True); cmb.clear()
            for e in acc:
                cmb.addItem(f"{e.label:g}×  {'(initial)' if e.role == 'initial' else ''}  {e.name[:28]}")
            cmb.blockSignals(False)
        if not acc:
            return False
        init = proj.initial() if proj is not None else None
        r = cur_r if cur_r in acc else (init if init in acc else acc[0])
        self.cmb_ref.setCurrentIndex(acc.index(r))
        rest = [e for e in acc if e is not r]
        c = cur_c if (cur_c in acc and cur_c is not r) else (rest[0] if rest else r)
        self.cmb_cmp.setCurrentIndex(acc.index(c))
        return True

    def ref(self):
        i = self.cmb_ref.currentIndex()
        return self._entries[i] if 0 <= i < len(self._entries) else None

    def cmp(self):
        i = self.cmb_cmp.currentIndex()
        return self._entries[i] if 0 <= i < len(self._entries) else None

    def entries(self):
        return list(self._entries)


def cyclic_cmap():
    """A cyclic map for orientations (phi, mod 180)."""
    import colorsys
    pos = np.linspace(0, 1, 13)
    cols = [tuple(int(255 * c) for c in colorsys.hsv_to_rgb(p, 0.8, 0.95)) + (255,) for p in pos]
    return pg.ColorMap(pos, cols)


def ellipse(centre, cov, scale=1.0, n=24):
    """(n,2) outline of the 1-sigma ellipse of `cov` around `centre`, scaled."""
    w, v = np.linalg.eigh(np.asarray(cov, float))
    w = np.sqrt(np.maximum(w, 0)) * scale
    t = np.linspace(0, 2 * np.pi, n)
    circ = np.stack([np.cos(t) * w[0], np.sin(t) * w[1]], 1)
    return np.asarray(centre, float) + circ @ v.T
