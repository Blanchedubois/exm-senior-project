"""
gui.tag_panel
=============
Stage-4 control panel (fourth tab): reference-warp tagging.

Tags the CURRENT frame (Stage-1 corrected image + Stage-2 registration + Stage-3
filtered points) by warping the STL reference onto it; hover any marker to read
its tag; filter by kind/box; overlay the TPS-warped reference grid ("the grid
following the dashes"). A Series group batch-processes the sibling expansion
frames headlessly (sidecar-driven, coreg rescue for high expansion) and shows the
measured-vs-expected strain. Exports tagged / pairing CSVs.
"""
from __future__ import annotations
import os
import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets, QtCore

from rwtag.refwarp import tagframe as TF, series as S, strain as ST, io_csv

KIND_COLOR = {"dot": (255, 190, 0), "dash": (255, 60, 180),
              "num": (40, 200, 255), "let": (60, 230, 90), "node": (255, 70, 70)}
KIND_SIZE = {"dot": 4, "dash": 7, "num": 9, "let": 9, "node": 10}
KIND_ALPHA = {"dot": 150, "dash": 200, "num": 220, "let": 220, "node": 230}
_MODEL = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reference", "glyph_knn.yml")


class TagPanel(QtWidgets.QWidget):
    def __init__(self, state, canvas, log, parent=None):
        super().__init__(parent)
        self.state = state
        self.canvas = canvas
        self.log = log
        self._series = None            # list[SeriesFrame] after Process series

        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel("<b>Stage 4 — Reference-warp tagging</b>"))
        _intro = QtWidgets.QLabel(
            "<small>Warps the tagged STL reference onto the processed image and gives every "
            "filtered point its unique design tag. Hover a marker to read its tag.</small>")
        _intro.setWordWrap(True)
        root.addWidget(_intro)

        self.b_tag = QtWidgets.QPushButton("Tag current frame")
        root.addWidget(self.b_tag)
        self.summary = QtWidgets.QLabel("Run Stages 1–3, then Tag current frame.")
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        # view controls
        vo = QtWidgets.QGroupBox("View"); vl = QtWidgets.QVBoxLayout(vo)
        row = QtWidgets.QHBoxLayout()
        self.kindcombo = QtWidgets.QComboBox()
        self.kindcombo.addItems(["all", "dot", "dash", "num", "let"])
        self.boxcombo = QtWidgets.QComboBox(); self.boxcombo.addItem("all")
        row.addWidget(QtWidgets.QLabel("kind:")); row.addWidget(self.kindcombo, 1)
        row.addWidget(QtWidgets.QLabel("box:")); row.addWidget(self.boxcombo, 1)
        _rw = QtWidgets.QWidget(); _rw.setLayout(row); vl.addWidget(_rw)
        self.chk_grid = QtWidgets.QCheckBox("Warped reference grid"); self.chk_grid.setChecked(True)
        self.chk_nums = QtWidgets.QCheckBox("Box numbers"); self.chk_nums.setChecked(True)
        self.chk_resid = QtWidgets.QCheckBox("Colour by residual (QC)")
        vl.addWidget(self.chk_grid); vl.addWidget(self.chk_nums); vl.addWidget(self.chk_resid)
        self.readout = QtWidgets.QLabel("hover a point to read its tag")
        self.readout.setStyleSheet("color:#8cf; font-weight:bold;")
        self.readout.setWordWrap(True)
        vl.addWidget(self.readout)
        root.addWidget(vo)

        self.b_export_tagged = QtWidgets.QPushButton("Export tagged CSV…")
        self.b_export_tagged.setEnabled(False)
        root.addWidget(self.b_export_tagged)

        # series group
        sg = QtWidgets.QGroupBox("Series (all expansions in this folder)")
        sl = QtWidgets.QVBoxLayout(sg)
        self.serieslist = QtWidgets.QListWidget(); self.serieslist.setMaximumHeight(130)
        sl.addWidget(self.serieslist)
        self.b_series = QtWidgets.QPushButton("Process series")
        self.b_export_pair = QtWidgets.QPushButton("Export pairing CSV…")
        self.b_export_all = QtWidgets.QPushButton("Export all tagged CSVs…")
        self.b_export_pair.setEnabled(False); self.b_export_all.setEnabled(False)
        for w in (self.b_series, self.b_export_pair, self.b_export_all):
            sl.addWidget(w)
        root.addWidget(sg)

        # strain group
        st = QtWidgets.QGroupBox("Strain (measured vs expected expansion)")
        stl = QtWidgets.QVBoxLayout(st)
        self.straintable = QtWidgets.QTableWidget(0, 4)
        self.straintable.setHorizontalHeaderLabels(["×", "measured", "± σ", "expected"])
        self.straintable.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.straintable.verticalHeader().setVisible(False)
        self.straintable.setMaximumHeight(150)
        stl.addWidget(self.straintable)
        self.trend = pg.PlotWidget(title="measured vs expected")
        self.trend.showGrid(x=True, y=True, alpha=0.2)
        self.trend.setMaximumHeight(180)
        stl.addWidget(self.trend)
        root.addWidget(st)
        root.addStretch(1)

        # wiring
        self.b_tag.clicked.connect(self.tag_current)
        self.b_series.clicked.connect(self.process_series)
        self.b_export_tagged.clicked.connect(self.export_tagged)
        self.b_export_pair.clicked.connect(self.export_pairing)
        self.b_export_all.clicked.connect(self.export_all_tagged)
        self.kindcombo.currentIndexChanged.connect(self._redraw)
        self.boxcombo.currentIndexChanged.connect(self._redraw)
        for c in (self.chk_grid, self.chk_nums, self.chk_resid):
            c.toggled.connect(self._redraw)
        self.canvas.tagHovered.connect(
            lambda t: self.readout.setText(t or "hover a point to read its tag"))
        self.state.imageLoaded.connect(self._invalidate)
        self.state.detectionChanged.connect(self._invalidate_tags)

    # ---------------------------------------------------------------- helpers
    def _invalidate(self, *_):
        self.state.pipeline.tagging = None
        self.b_export_tagged.setEnabled(False)
        self.summary.setText("New image — run Stages 1–3, then Tag current frame.")
        self._fill_series_list()

    def _invalidate_tags(self, *_):
        self.state.pipeline.tagging = None
        self.b_export_tagged.setEnabled(False)

    def load_from_state(self):
        """Restore the panel from the active image's stored TagResult (project
        selection change)."""
        tr = self.state.pipeline.tagging
        self.b_export_tagged.setEnabled(tr is not None)
        self._fill_series_list()
        if tr is None:
            self.summary.setText("Run Stages 1–3, then Tag current frame.")
            return
        boxes = sorted({int(t.split("|")[1][1:]) for t in tr.tags if t.startswith("dot|")})
        self.boxcombo.blockSignals(True); self.boxcombo.clear()
        self.boxcombo.addItem("all"); self.boxcombo.addItems([str(b) for b in boxes])
        self.boxcombo.blockSignals(False)
        self.summary.setText(
            f"Restored — <b>{len(tr.tags)}</b> tags · resid "
            f"<b>{tr.warp['per_det_median']:.1f}px</b> · matched "
            f"<b>{tr.warp['matched_frac']:.0%}</b>")

    def refresh_base_image(self):
        det = self.state.pipeline.detection
        if det is None:
            return
        h, w = det.u8.shape
        self.canvas.set_extent(w, h)
        self.canvas.set_image(det.u8, levels=(0, 255))
        self._fill_series_list()
        if self.state.pipeline.tagging is not None:
            self._redraw()

    def _fill_series_list(self):
        self.serieslist.clear()
        src = self.state.pipeline.source_path
        if not src:
            return
        for path, lab in S.find_series(os.path.dirname(src)):
            item = QtWidgets.QListWidgetItem(f"{lab:g}×  ·  {os.path.basename(path)[:34]}")
            self.serieslist.addItem(item)

    # ---------------------------------------------------------------- tagging
    def tag_current(self):
        det = self.state.pipeline.detection
        filt = self.state.pipeline.features
        if det is None or not (det.model and det.model.get("registered")):
            self.summary.setText("Need a solved Stage-2 grid — run Detect/Read/Solve first.")
            self.log("Stage 4: no registered detection."); return
        a = det.basis["angle_deg"] % 90
        tilt = min(a, 90 - a)
        if tilt > 8:
            self.summary.setText(
                f"<b>Frame is tilted ~{tilt:.0f}°</b> — glyph reads (and so the registration) "
                "are unreliable on tilted frames. Use <b>Auto-deskew</b> in Stage 2, then "
                "re-run Stages 2–3 and tag again.")
            self.log(f"Stage 4: frame tilted {tilt:.0f}° — deskew first."); return
        if filt is None:
            self.log("Stage 4: no Stage-3 filter — tagging raw detections instead.")
        self.log("Stage 4: fitting warp + tagging…"); QtWidgets.QApplication.processEvents()
        tr = TF.tag_frame(det, filt)
        if tr is None:
            self.summary.setText("Warp fit failed — check the Stage-2 registration.")
            self.log("Stage 4: warp fit failed."); return
        self.state.set_tagging(tr)
        self.b_export_tagged.setEnabled(True)
        boxes = sorted({int(t.split("|")[1][1:]) for t in tr.tags if t.startswith("dot|")})
        self.boxcombo.blockSignals(True); self.boxcombo.clear()
        self.boxcombo.addItem("all"); self.boxcombo.addItems([str(b) for b in boxes])
        self.boxcombo.blockSignals(False)
        pc = tr.per_category
        self.summary.setText(
            f"<b>{len(tr.tags)}</b> tags · warp <b>{tr.warp['kind']}</b> · "
            f"median resid <b>{tr.warp['per_det_median']:.1f}px</b> · "
            f"matched <b>{tr.warp['matched_frac']:.0%}</b><br>"
            f"dots {pc['dot']['n']} · dashes {pc['dash']['n']} · glyphs {pc['glyph']['n']}<br>"
            "<small>letters/corner-dots rarely match on real prints (faint in print — known "
            "data limit, not an error).</small>")
        self.log(f"Stage 4: {len(tr.tags)} tags, resid {tr.warp['per_det_median']:.1f}px, "
                 f"matched {tr.warp['matched_frac']:.0%}")
        self._redraw()

    def _redraw(self, *_):
        tr = self.state.pipeline.tagging
        det = self.state.pipeline.detection
        if tr is None or det is None:
            return
        self.canvas.set_image(det.u8, levels=(0, 255))
        self.canvas.clear_overlays()
        kind_f = self.kindcombo.currentText()
        box_f = self.boxcombo.currentText()
        # residual QC colouring: green (0) -> red (>= pitch/2), per-point (I4)
        by_resid = self.chk_resid.isChecked() and tr.residuals
        rmax = 0.5 * float(det.basis["pitch"]) if by_resid else 1.0
        entries = []
        for tag, (x, y) in tr.tags.items():
            k = tag.split("|")[0]
            if kind_f != "all" and k != kind_f:
                continue
            if box_f != "all" and f"|B{box_f}|" not in tag:
                continue
            if by_resid:
                t = min(tr.residuals.get(tag, 0.0) / max(rmax, 1e-6), 1.0)
                color = (int(60 + 195 * t), int(230 - 170 * t), 60, 220)
            else:
                color = KIND_COLOR.get(k, (200, 200, 200)) + (KIND_ALPHA.get(k, 200),)
            entries.append((f"{tag}  ({tr.residuals.get(tag, 0):.1f}px)" if by_resid else tag,
                            x, y, color, KIND_SIZE.get(k, 6)))
        self.canvas.draw_hover_points(entries)
        if self.chk_grid.isChecked():
            segs = TF.warped_grid_segments(tr.warp)
            self.canvas.add_polylines([s for s in segs], color=(0, 220, 255), width=1.6)
        if self.chk_nums.isChecked():
            centers = TF.warped_box_centers(tr.warp, tr.tags)
            if centers:
                self.canvas.add_labels([xy for xy in centers.values()],
                                       [str(N) for N in centers],
                                       color=(255, 230, 0), anchor=(0.5, 0.5), size=12)

    # ---------------------------------------------------------------- series
    def process_series(self):
        src = self.state.pipeline.source_path
        if not src:
            self.log("Stage 4: open an image first."); return
        frames = S.find_series(os.path.dirname(src))
        if len(frames) < 2:
            self.log("Stage 4: need ≥2 labelled frames (e.g. '1.5X…') in the folder."); return
        from rwtag.glyph import detect as D
        clf = D.load_classifier(_MODEL)
        self.serieslist.clear()
        self.log(f"Stage 4: processing {len(frames)} frames…")
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            def prog(k, n, f):
                s = (f"{f.label:g}× — OK · {f.source} · {f.n_tags} tags" if f.ok
                     else f"{f.label:g}× — REJECTED: {f.reason}")
                self.serieslist.addItem(s)
                self.log(f"  [{k}/{n}] {s}")
                QtWidgets.QApplication.processEvents()
            self._series = S.process_series(frames, clf, progress=prog)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        ok = [f for f in self._series if f.ok]
        self.b_export_pair.setEnabled(len(ok) >= 2)
        self.b_export_all.setEnabled(len(ok) >= 1)
        self.log(f"Stage 4: series done — {len(ok)}/{len(self._series)} accepted.")
        self._fill_strain()

    def _fill_strain(self):
        ok = [f for f in (self._series or []) if f.ok]
        self.straintable.setRowCount(0)
        self.trend.clear()
        if len(ok) < 2:
            return
        init = min(ok, key=lambda f: f.label)
        rows = [f for f in ok if f is not init]
        self.straintable.setRowCount(len(rows))
        xs, ys, er = [1.0], [1.0], [0.0]
        for i, f in enumerate(rows):
            r = ST.strain(init.tags, f.tags, init.label, f.label)
            for c, v in enumerate([f"{f.label:g}", f"{r['mean']:.3f}",
                                   f"{r['sigma']:.3f}", f"{r['expected']:.3f}"]):
                self.straintable.setItem(i, c, QtWidgets.QTableWidgetItem(v))
            if np.isfinite(r["mean"]):
                xs.append(r["expected"]); ys.append(r["mean"]); er.append(r["sigma"])
        xs, ys, er = np.array(xs), np.array(ys), np.array(er)
        lo, hi = min(xs.min(), ys.min()) * 0.95, max(xs.max(), ys.max()) * 1.05
        self.trend.plot([lo, hi], [lo, hi],
                        pen=pg.mkPen((255, 60, 60), width=2, style=QtCore.Qt.DashLine))
        self.trend.addItem(pg.ErrorBarItem(x=xs, y=ys, height=2 * er,
                                           beam=0.01 * (hi - lo), pen=pg.mkPen((0, 200, 255))))
        self.trend.plot(xs, ys, pen=None, symbol="o", symbolSize=8, symbolBrush=(0, 200, 255))

    # ---------------------------------------------------------------- exports
    def export_tagged(self):
        tr = self.state.pipeline.tagging
        if tr is None:
            return
        base = os.path.splitext(os.path.basename(self.state.pipeline.source_path or "frame"))[0]
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export tagged CSV", base + "_tagged.csv", "CSV (*.csv)")
        if path:
            io_csv.write_tagged(tr.tags, path)
            self.log(f"Stage 4: tagged CSV → {path}")

    def export_pairing(self):
        if not self._series:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export pairing CSV", "pairing.csv", "CSV (*.csv)")
        if path:
            io_csv.write_pairing(self._series, path)
            self.log(f"Stage 4: pairing CSV → {path}")

    def export_all_tagged(self):
        if not self._series:
            return
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Folder for tagged CSVs")
        if d:
            n = 0
            for f in self._series:
                if f.ok and f.tags:
                    io_csv.write_tagged(f.tags, os.path.join(d, f"{f.label:g}x_tagged.csv"))
                    n += 1
            self.log(f"Stage 4: {n} tagged CSVs → {d}")
