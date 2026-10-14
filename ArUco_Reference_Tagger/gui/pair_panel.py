"""
gui.pair_panel
==============
Tab 5 · Pair. Ported from Reference_Warp_Tagger/gui/pair_panel.py: join two
images' tags and show every shared point in both frames. Changes: any two
accepted images can be paired (reference defaults to the Initial); positions
carry their 1-sigma; tags are drawn as squares; the wide pairing CSV moves to the
export bundle (port Phase 7).
"""
from __future__ import annotations
import os
import numpy as np
from PySide6 import QtWidgets

from rwtag import pairing as PR
from .compare_common import PairSelector


class PairPanel(QtWidgets.QWidget):
    MAX_ROWS = 20000

    def __init__(self, state, canvas, log, project_fn, parent=None):
        super().__init__(parent)
        self.state, self.canvas, self.log, self.project_fn = state, canvas, log, project_fn
        self._pairs = None
        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel("<b>5 — Pair</b>"))
        intro = QtWidgets.QLabel("<small>Joins two accepted images on tag identity: every feature present in "
                                 "both, with its position (± 1σ) in each. Drawn on the reference image.</small>")
        intro.setWordWrap(True); root.addWidget(intro)
        self.sel = PairSelector(project_fn); root.addWidget(self.sel)
        self.chk_unpaired = QtWidgets.QCheckBox("Show unpaired reference dots (grey)"); self.chk_unpaired.setChecked(True)
        root.addWidget(self.chk_unpaired)
        self.summary = QtWidgets.QLabel("Tag at least two images (stages 1–4)."); self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["tag", "reference x, y (px)", "± σ", "compared x, y (px)", "± σ"])
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setMinimumHeight(260)
        root.addWidget(self.table, 1)
        self.b_export = QtWidgets.QPushButton("Export these pairs CSV…"); self.b_export.setEnabled(False)
        root.addWidget(self.b_export)
        self.sel.changed.connect(self._recompute)
        self.chk_unpaired.toggled.connect(lambda *_: self._draw())
        self.b_export.clicked.connect(self.export_current)

    def refresh(self):
        if not self.sel.refresh() or len(self.sel.entries()) < 2:
            self.summary.setText("Tag at least two images (Run all pending) — rejected images are not offered.")
            self._pairs = None; self.table.setRowCount(0); return
        self._recompute()

    def _recompute(self):
        r, c = self.sel.ref(), self.sel.cmp()
        if r is None or c is None or r is c:
            return
        t0, t1 = r.pipeline.tagging, c.pipeline.tagging
        self._pairs = PR.pair_frames(t0, t1)
        n = PR.pair_counts(self._pairs, t0, t1)
        self.summary.setText(
            f"<b>{n['n_pairs']}</b> shared tags ({r.label:g}× ↔ {c.label:g}×)<br>"
            f"dots: reference {n['n_dot_ref']} · compared {n['n_dot_cmp']} · paired <b>{n['n_dot_pairs']}</b> "
            f"({n['dot_pair_frac']:.0%})<br><small>by kind: {n['by_category']}</small>")
        self._fill_table()
        self._draw()
        self.b_export.setEnabled(True)
        self.log(f"Pair: {r.label:g}×↔{c.label:g}× — {n['n_pairs']} pairs ({n['n_dot_pairs']} dots)")

    def _fill_table(self):
        p = self._pairs
        n = min(len(p.tags), self.MAX_ROWS)
        self.table.setRowCount(n)
        for i in range(n):
            s0 = np.sqrt(np.diag(p.C0[i])); s1 = np.sqrt(np.diag(p.C1[i]))
            vals = [p.tags[i], f"{p.P0[i, 0]:.2f}, {p.P0[i, 1]:.2f}", f"{s0[0]:.3f}, {s0[1]:.3f}",
                    f"{p.P1[i, 0]:.2f}, {p.P1[i, 1]:.2f}", f"{s1[0]:.3f}, {s1[1]:.3f}"]
            for j, v in enumerate(vals):
                self.table.setItem(i, j, QtWidgets.QTableWidgetItem(v))

    def _draw(self, *_):
        r = self.sel.ref()
        if r is None or self._pairs is None or r.pipeline.detection is None:
            return
        det = r.pipeline.detection
        h, w = det.u8.shape
        self.canvas.set_extent(w, h); self.canvas.set_image(det.u8, levels=(0, 255))
        self.canvas.clear_overlays()
        p = self._pairs
        dots = np.array([c == "dot" for c in p.cats])
        if self.chk_unpaired.isChecked():
            paired = set(p.tags)
            un = [xy for t, xy in r.pipeline.tagging.tags.items() if t.startswith("dot|") and t not in paired]
            self.canvas.add_points(un, color=(140, 140, 140), size=3)
        self.canvas.add_points(p.P0[dots], color=(60, 230, 90), size=4)
        self.canvas.add_points(p.P0[np.array([c == "dash" for c in p.cats])], color=(255, 60, 180), size=8, symbol="t")
        self.canvas.add_points(p.P0[np.array([c == "aruco" for c in p.cats])], color=(255, 230, 0), size=16, symbol="s")

    def export_current(self):
        if self._pairs is None:
            return
        name = f"pairs_{self._pairs.label0:g}x_{self._pairs.label1:g}x.csv"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export pairs CSV", name, "CSV (*.csv)")
        if path:
            PR.write_pairs_csv(self._pairs, path)
            self.log(f"Pair: CSV → {path}")
