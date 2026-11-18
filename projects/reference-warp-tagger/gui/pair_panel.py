"""
gui.pair_panel
==============
Phase-B tab (5 · Pair): pair the Initial image's tagged features with each
Expanded image's by shared reference tag. Shows the paired dots over the INITIAL
image, the full pair table (both frames' positions), counts, and CSV exports.
"""
from __future__ import annotations
import os
from PySide6 import QtWidgets

from rwtag import pairing as PR
from rwtag.refwarp import io_csv


class PairPanel(QtWidgets.QWidget):
    def __init__(self, state, canvas, log, project_fn, parent=None):
        super().__init__(parent)
        self.state = state
        self.canvas = canvas
        self.log = log
        self.project_fn = project_fn           # -> rwtag.project.Project
        self._pairs = None
        self._init_entry = None
        self._exp_entry = None

        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel("<b>5 — Pair (initial ↔ expanded)</b>"))
        _intro = QtWidgets.QLabel(
            "<small>Joins the two frames' tags: every point present in BOTH images, with its "
            "position in each. Tag both images first (stages 1–4).</small>")
        _intro.setWordWrap(True)
        root.addWidget(_intro)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("expanded:"))
        self.expcombo = QtWidgets.QComboBox()
        row.addWidget(self.expcombo, 1)
        _rw = QtWidgets.QWidget(); _rw.setLayout(row)
        root.addWidget(_rw)

        self.chk_unpaired = QtWidgets.QCheckBox("Show unpaired initial dots (grey)")
        self.chk_unpaired.setChecked(True)
        root.addWidget(self.chk_unpaired)

        self.summary = QtWidgets.QLabel("Tag the initial and ≥1 expanded image, then pair.")
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["tag", "x_init", "y_init", "x_exp", "y_exp"])
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setMinimumHeight(260)
        root.addWidget(self.table, 1)

        self.b_export = QtWidgets.QPushButton("Export these pairs CSV…")
        self.b_export_all = QtWidgets.QPushButton("Export ALL pair CSVs…")
        self.b_export_wide = QtWidgets.QPushButton("Export wide pairing CSV…")
        for b in (self.b_export, self.b_export_all, self.b_export_wide):
            b.setEnabled(False)
            root.addWidget(b)

        self.expcombo.currentIndexChanged.connect(lambda *_: self._recompute())
        self.chk_unpaired.toggled.connect(lambda *_: self._draw())
        self.b_export.clicked.connect(self.export_current)
        self.b_export_all.clicked.connect(self.export_all)
        self.b_export_wide.clicked.connect(self.export_wide)
        self.state.taggingChanged.connect(lambda *_: self._stale())

    # ---------------------------------------------------------------- helpers
    def _tagged(self):
        """(initial_entry, [expanded entries with tags]) — only tagged images."""
        proj = self.project_fn()
        init = proj.initial()
        if init is None or init.pipeline.tagging is None:
            return None, []
        exp = [e for e in proj.expanded() if e.pipeline.tagging is not None]
        return init, exp

    def _stale(self):
        self._pairs = None

    def refresh(self):
        """Called on tab entry: rebuild the expanded combo and (re)pair."""
        init, exp = self._tagged()
        cur = self.expcombo.currentText()
        self.expcombo.blockSignals(True)
        self.expcombo.clear()
        self.expcombo.addItems([f"{e.label:g}×" for e in exp])
        i = self.expcombo.findText(cur)
        if i >= 0:
            self.expcombo.setCurrentIndex(i)
        self.expcombo.blockSignals(False)
        if init is None:
            self.summary.setText("Tag the <b>initial</b> image first (stages 1–4)."); return
        if not exp:
            self.summary.setText("Tag at least one <b>expanded</b> image (or Run all pending)."); return
        self._recompute()

    def _recompute(self):
        init, exp = self._tagged()
        if init is None or not exp:
            return
        idx = max(0, self.expcombo.currentIndex())
        if idx >= len(exp):
            return
        e = exp[idx]
        self._init_entry, self._exp_entry = init, e
        self._pairs = PR.pair_tags(init.pipeline.tagging.tags, e.pipeline.tagging.tags)
        c = PR.pair_counts(init.pipeline.tagging.tags, e.pipeline.tagging.tags, self._pairs)
        self.summary.setText(
            f"<b>{c['n_pairs']}</b> paired tags ({init.label:g}× ↔ {e.label:g}×)<br>"
            f"dots: initial {c['n_dot_init']} · expanded {c['n_dot_exp']} · "
            f"paired <b>{c['n_dot_pairs']}</b> ({c['dot_pair_frac']:.0%})<br>"
            f"<small>by category: {c['by_category']}</small>")
        self._fill_table()
        self._draw()
        for b in (self.b_export, self.b_export_all, self.b_export_wide):
            b.setEnabled(True)
        self.log(f"Pair: {init.label:g}×↔{e.label:g}× — {c['n_pairs']} pairs "
                 f"({c['n_dot_pairs']} dots, {c['dot_pair_frac']:.0%})")

    def _fill_table(self):
        pairs = self._pairs or {}
        tags = sorted(pairs)
        self.table.setRowCount(len(tags))
        for r, t in enumerate(tags):
            xi, yi, xe, ye = pairs[t]
            for col, v in enumerate([t, f"{xi:.1f}", f"{yi:.1f}", f"{xe:.1f}", f"{ye:.1f}"]):
                self.table.setItem(r, col, QtWidgets.QTableWidgetItem(v))

    def _draw(self, *_):
        if self._init_entry is None or self._pairs is None:
            return
        det = self._init_entry.pipeline.detection
        tags0 = self._init_entry.pipeline.tagging.tags
        if det is not None:
            h, w = det.u8.shape
            self.canvas.set_extent(w, h)
            self.canvas.set_image(det.u8, levels=(0, 255))
        self.canvas.clear_overlays()
        paired_dots = [(xi, yi) for t, (xi, yi, _xe, _ye) in self._pairs.items()
                       if PR.category(t) == "dot"]
        if self.chk_unpaired.isChecked():
            unpaired = [xy for t, xy in tags0.items()
                        if PR.category(t) == "dot" and t not in self._pairs]
            self.canvas.add_points(unpaired, color=(140, 140, 140), size=3)
        self.canvas.add_points(paired_dots, color=(60, 230, 90), size=4)

    # ---------------------------------------------------------------- export
    def export_current(self):
        if not self._pairs:
            return
        name = f"pairs_{self._exp_entry.label:g}x.csv"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export pairs CSV", name,
                                                        "CSV (*.csv)")
        if path:
            PR.write_pairs_csv(self._pairs, path, self._init_entry.label, self._exp_entry.label)
            self.log(f"Pair: pairs CSV → {path}")

    def export_all(self):
        init, exp = self._tagged()
        if init is None or not exp:
            return
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Folder for pair CSVs")
        if not d:
            return
        for e in exp:
            pairs = PR.pair_tags(init.pipeline.tagging.tags, e.pipeline.tagging.tags)
            PR.write_pairs_csv(pairs, os.path.join(d, f"pairs_{e.label:g}x.csv"),
                               init.label, e.label)
        self.log(f"Pair: {len(exp)} pair CSV(s) → {d}")

    def export_wide(self):
        init, exp = self._tagged()
        if init is None:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export wide pairing CSV",
                                                        "pairing.csv", "CSV (*.csv)")
        if not path:
            return

        class _F:                                     # io_csv.write_pairing shim
            def __init__(self, e):
                self.label, self.tags, self.ok = e.label, e.pipeline.tagging.tags, True
        io_csv.write_pairing([_F(e) for e in [init] + exp], path)
        self.log(f"Pair: wide pairing CSV → {path}")
