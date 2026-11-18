"""
stageui.stage_results
====================
Stage 3 — Final grid / Results. Runs the whole pipeline on the current
(Stage-1-corrected, deskewed) image and shows the definitive result: one big box
number per box + the A/B/C/D letters + box boundaries. Every fill dot is tagged
to its box (recorded, shown only faintly on request). Exports CSVs.
"""
from __future__ import annotations
import os
from PySide6 import QtWidgets

from gridtrack import io
from glyphtrack import lattice as lt
from glyphtrack import reader as gr
from glyphtrack import gridmodel as gm
from glyphtrack import results as gres
from glyphtrack.classifier import GlyphClassifier

_MODEL = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reference", "glyph_knn.yml")


class ResultsPanel(QtWidgets.QWidget):
    def __init__(self, state, canvas, log, parent=None):
        super().__init__(parent)
        self.state = state
        self.canvas = canvas
        self.log = log
        self._clf = None
        self._result = None

        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel("<b>Final grid — results</b>"))
        root.addWidget(QtWidgets.QLabel(
            "<small>The solved 5×5 grid: one number per box + A/B/C/D. Every dot is tagged "
            "to its box (recorded for export).</small>"))

        self.b_run = QtWidgets.QPushButton("Compute final grid")
        root.addWidget(self.b_run)
        self.chk_dots = QtWidgets.QCheckBox("Show tagged dots (faint)")
        self.chk_dashes = QtWidgets.QCheckBox("Show tagged dashes (pink ▲)")
        self.chk_dashes.setChecked(True)
        self.chk_letters = QtWidgets.QCheckBox("Show letters"); self.chk_letters.setChecked(True)
        root.addWidget(self.chk_letters); root.addWidget(self.chk_dots); root.addWidget(self.chk_dashes)
        self.b_export = QtWidgets.QPushButton("Export CSV…"); self.b_export.setEnabled(False)
        root.addWidget(self.b_export)

        self.summary = QtWidgets.QLabel("—"); self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["box (i,j)", "number", "col,row"])
        root.addWidget(self.table, 1)

        self.b_run.clicked.connect(self.run)
        self.b_export.clicked.connect(self.export)
        self.chk_dots.toggled.connect(self._redraw)
        self.chk_letters.toggled.connect(self._redraw)
        self.chk_dashes.toggled.connect(self._redraw)

    # ------------------------------------------------------------------ run
    def run(self):
        img = self.state.working_image()
        if img is None:
            self.log("Results: open an image first (and deskew in Stage 1)."); return
        if self._clf is None:
            if not os.path.exists(_MODEL):
                self.summary.setText("recognition model not found."); return
            self._clf = GlyphClassifier.load(_MODEL)
        self.log("Results: computing final grid…")
        QtWidgets.QApplication.processEvents()
        u8 = io.to_uint8(img)
        dots = lt.detect_dots(u8)
        if len(dots) < 30:
            self.summary.setText("too few dots — check Stage 1 / deskew."); return
        basis = lt.refine_basis(dots, lt.estimate_basis(dots))
        dashes_all = lt.detect_dashes(u8)
        grid = lt.fit_box_grid(basis, dashes_all)
        dashes, _ = lt.dashes_on_grid(dashes_all, grid)
        _coarse, fit = gr.read_glyphs(u8, self._clf, grid)
        reads = gr.read_slots(u8, self._clf, fit)
        model = gm.build_grid_model(reads, fit, dots=dots,
                                    manual=self.state.glyph_manual)
        result = gres.finalize(model, fit, dots, dashes=dashes)
        self._u8 = u8; self._fit = fit; self._grid = grid; self._result = result
        self.b_export.setEnabled(result.registered)
        self._redraw()
        self._fill_table(result)
        self.summary.setText(("<b>registered.</b> " if result.registered else "<b>not registered.</b> ")
                             + result.summary)
        self.log("Results: " + result.summary)

    def _redraw(self, *_):
        if self._result is None:
            return
        r = self._result
        self.canvas.set_image(self._u8)
        self.canvas.clear_overlays()
        # box boundaries
        H, W = self._u8.shape

        def inb(p):
            return -60 <= p[0] <= W + 60 and -60 <= p[1] <= H + 60
        quads = []
        for b in r.boxes:
            i, j = b.box_i, b.box_j
            cs = [lt.fslot_point(self._fit, i, j, c) for c in ((0, 0), (150, 0), (150, 150), (0, 150))]
            if any(inb(c) for c in cs):
                quads.append(cs)
        self.canvas.add_polylines(quads, color=(0, 150, 210), width=1)
        if self.chk_dots.isChecked():
            self.canvas.add_points([(d.x, d.y) for d in r.dots], color=(255, 40, 40), size=5)
        if self.chk_dashes.isChecked() and r.dashes:
            self.canvas.add_points([(d.x, d.y) for d in r.dashes], color=(255, 60, 180),
                                   size=8, symbol="t")
        if r.registered:
            self.canvas.add_labels([(b.cx, b.cy) for b in r.boxes],
                                   [str(b.number) for b in r.boxes],
                                   color=(255, 210, 40), anchor=(0.5, 0.5), size=20)
            if self.chk_letters.isChecked():
                lets = [L for L in r.labels if L["kind"] == "letter"]
                self.canvas.add_labels([(L["x"], L["y"]) for L in lets],
                                       [L["text"] for L in lets], color=(60, 230, 90), size=11)
        else:
            self.canvas.add_labels([(L["x"], L["y"]) for L in r.labels],
                                   [L["text"] for L in r.labels], color=(200, 200, 200))

    def _fill_table(self, r):
        self.table.setRowCount(len(r.boxes))
        for row, b in enumerate(sorted(r.boxes, key=lambda b: b.number)):
            self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(f"({b.box_i},{b.box_j})"))
            self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(str(b.number)))
            self.table.setItem(row, 2, QtWidgets.QTableWidgetItem(f"{b.col},{b.row}"))

    def export(self):
        if self._result is None or not self._result.registered:
            return
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Export results to folder")
        if not d:
            return
        self._result.write_csv(d)
        self.summary.setText(self.summary.text() + f"<br>exported boxes/glyphs/dots.csv → {d}")
        self.log(f"Results: exported CSVs to {d}")
