"""
gui.filter_panel
================
Stage-3 tab (3 · Filter). Ported from Reference_Warp_Tagger/gui/filter_panel.py:
live sliders over the dot and dash quality gates, dropped points coloured by
reason, the box outlines carried from Stage 2. Changes: the glyph gate became
the tag quiet-zone gate, the lattice and separation gates are per box, an
`edge` reason shows Stage 2's exact un-distortion test, and a per-box table
counts what each gate removed. Publishes a FilterResult for Stage 4.
"""
from __future__ import annotations
import os
import csv
from collections import defaultdict
import numpy as np
from PySide6 import QtWidgets

from rwtag import dotfilter as DF
from rwtag.aruco.detect import predicted_px
from .widgets import SliderSpin

_DOT_COLOR = {"": (60, 230, 90), "edge": (255, 60, 60), "near_tag": (255, 160, 0),
              "too_close": (255, 0, 255), "off_lattice": (0, 160, 255)}
_DASH_COLOR = {"": (255, 60, 180), "edge": (255, 60, 60), "off_grid": (200, 200, 200),
               "intersection": (80, 160, 255), "too_close": (255, 160, 0)}


class FilterPanel(QtWidgets.QWidget):
    def __init__(self, state, canvas, log, design_fn, parent=None):
        super().__init__(parent)
        self.state, self.canvas, self.log, self.design_fn = state, canvas, log, design_fn
        self._det = None
        self._fr = None

        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel("<b>Stage 3 — Filter</b>"))
        intro = QtWidgets.QLabel("<small>Drops doubtful dots and dashes from the Stage-2 detection, live. "
                                 "Each gate works per box, with that box's own pitch and lattice. Dropped "
                                 "points are kept in the export with their reason.</small>")
        intro.setWordWrap(True); root.addWidget(intro)

        db = QtWidgets.QGroupBox("Dots"); dl = QtWidgets.QVBoxLayout(db)
        self.c_edge = QtWidgets.QCheckBox("No real raw source (lens edge)"); self.c_edge.setChecked(True)
        self.c_tag = QtWidgets.QCheckBox("Inside a tag's quiet zone"); self.c_tag.setChecked(True)
        self.s_tag = SliderSpin("quiet zone (× tag side)", 0.0, 1.0, 0.25, 0.05, 2)
        self.c_sep = QtWidgets.QCheckBox("Too close to a neighbour (× box pitch)"); self.c_sep.setChecked(True)
        self.s_sep = SliderSpin("min separation", 0.1, 1.0, 0.50, 0.05, 2)
        self.c_dev = QtWidgets.QCheckBox("Off the box lattice (× box pitch)"); self.c_dev.setChecked(True)
        self.s_dev = SliderSpin("max deviation", 0.05, 1.2, 0.60, 0.05, 2)
        for w in (self.c_edge, self.c_tag, self.s_tag, self.c_sep, self.s_sep, self.c_dev, self.s_dev):
            dl.addWidget(w)
        root.addWidget(db)

        hb = QtWidgets.QGroupBox("Dashes"); hl = QtWidgets.QVBoxLayout(hb)
        self.c_hedge = QtWidgets.QCheckBox("No real raw source (lens edge)"); self.c_hedge.setChecked(True)
        self.c_off = QtWidgets.QCheckBox("Too far from a grid line (× box)"); self.c_off.setChecked(True)
        self.s_off = SliderSpin("max off-grid", 0.03, 0.4, 0.15, 0.01, 2)
        self.c_hsep = QtWidgets.QCheckBox("Too close to each other (× dash pitch)"); self.c_hsep.setChecked(True)
        self.s_hsep = SliderSpin("min separation", 0.1, 1.0, 0.50, 0.05, 2)
        self.c_cor = QtWidgets.QCheckBox("At a grid intersection (× box)"); self.c_cor.setChecked(True)
        self.s_cor = SliderSpin("corner radius", 0.02, 0.3, 0.10, 0.01, 2)
        for w in (self.c_hedge, self.c_off, self.s_off, self.c_hsep, self.s_hsep, self.c_cor, self.s_cor):
            hl.addWidget(w)
        root.addWidget(hb)

        self.b_run = QtWidgets.QPushButton("Filter")
        root.addWidget(self.b_run)

        vo = QtWidgets.QGroupBox("View"); vl = QtWidgets.QVBoxLayout(vo)
        self.chk_dots = QtWidgets.QCheckBox("Dots ●"); self.chk_dots.setChecked(True)
        self.chk_dash = QtWidgets.QCheckBox("Dashes ▲"); self.chk_dash.setChecked(True)
        self.chk_drop = QtWidgets.QCheckBox("Show dropped (coloured by reason)"); self.chk_drop.setChecked(True)
        self.chk_box = QtWidgets.QCheckBox("Box outlines + numbers"); self.chk_box.setChecked(True)
        for w in (self.chk_dots, self.chk_dash, self.chk_drop, self.chk_box):
            vl.addWidget(w)
        legend = QtWidgets.QLabel(
            "<small><span style='color:#3ce65a'>kept</span> · <span style='color:#ff3c3c'>edge</span> · "
            "<span style='color:#ffa000'>quiet zone</span> · <span style='color:#ff00ff'>too close</span> · "
            "<span style='color:#00a0ff'>off lattice</span></small>")
        vl.addWidget(legend)
        root.addWidget(vo)

        self.summary = QtWidgets.QLabel("Run Stage 2, then Filter."); self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self.table = QtWidgets.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["box", "found", "kept", "edge", "quiet", "close", "off lat."])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setMinimumHeight(200)
        root.addWidget(self.table, 1)
        self.b_export = QtWidgets.QPushButton("Export filtered CSVs…"); self.b_export.setEnabled(False)
        root.addWidget(self.b_export)

        self.b_run.clicked.connect(self.run)
        self.b_export.clicked.connect(self.export)
        for c in (self.chk_dots, self.chk_dash, self.chk_drop, self.chk_box):
            c.toggled.connect(self._redraw)
        for s in (self.s_tag, self.s_sep, self.s_dev, self.s_off, self.s_hsep, self.s_cor):
            s.valueChanged.connect(self._refilter)
        for c in (self.c_edge, self.c_tag, self.c_sep, self.c_dev, self.c_hedge, self.c_off, self.c_hsep, self.c_cor):
            c.toggled.connect(self._refilter)
        self.state.imageLoaded.connect(self._invalidate)
        self.state.detectionChanged.connect(self._invalidate)

    # ---------------------------------------------------------------- params
    def dot_params(self):
        return DF.DotFilterParams(edge_enable=self.c_edge.isChecked(), tag_enable=self.c_tag.isChecked(),
                                  tag_margin_frac=self.s_tag.value(), min_sep_enable=self.c_sep.isChecked(),
                                  min_sep_frac=self.s_sep.value(), dev_enable=self.c_dev.isChecked(),
                                  max_dev_frac=self.s_dev.value())

    def set_params(self, dp, hp):
        """Restore the widgets from stored settings (project open)."""
        self.c_edge.setChecked(dp.edge_enable); self.c_tag.setChecked(dp.tag_enable); self.s_tag.setValue(dp.tag_margin_frac)
        self.c_sep.setChecked(dp.min_sep_enable); self.s_sep.setValue(dp.min_sep_frac)
        self.c_dev.setChecked(dp.dev_enable); self.s_dev.setValue(dp.max_dev_frac)
        self.c_hedge.setChecked(hp.edge_enable); self.c_off.setChecked(hp.offgrid_enable); self.s_off.setValue(hp.max_offgrid_frac)
        self.c_hsep.setChecked(hp.minsep_enable); self.s_hsep.setValue(hp.min_sep_frac)
        self.c_cor.setChecked(hp.corner_enable); self.s_cor.setValue(hp.corner_radius_frac)

    def dash_params(self):
        d = self.design_fn()
        return DF.DashFilterParams(edge_enable=self.c_hedge.isChecked(), offgrid_enable=self.c_off.isChecked(),
                                   max_offgrid_frac=self.s_off.value(), minsep_enable=self.c_hsep.isChecked(),
                                   min_sep_frac=self.s_hsep.value(), corner_enable=self.c_cor.isChecked(),
                                   corner_radius_frac=self.s_cor.value(),
                                   dashes_per_edge=(d.dashes_per_edge if d is not None else 10))

    # ---------------------------------------------------------------- state
    def _invalidate(self, *_):
        self._det = self._fr = None
        self.b_export.setEnabled(False)
        self.table.setRowCount(0)
        self.summary.setText("Run Stage 2 (Detect), then Filter.")

    def load_from_state(self):
        det, fr = self.state.pipeline.detection, self.state.pipeline.features
        if det is None or fr is None:
            self._invalidate(); return
        self._det, self._fr = det, fr
        self.b_export.setEnabled(True)
        self._fill()

    def refresh_base_image(self):
        det = self.state.pipeline.detection
        if det is None:
            self.summary.setText("No detection — run Stage 2 (Detect) first."); return
        h, w = det.u8.shape
        self.canvas.set_extent(w, h)
        if self._fr is None:
            self.canvas.clear_overlays(); self.canvas.set_image(det.u8, levels=(0, 255))
        else:
            self._redraw()

    def run(self):
        det = self.state.pipeline.detection
        if det is None or not det.model.get("registered"):
            self.log("Stage 3: run Stage 2 (Detect) first — the frame must be registered."); return None
        self._det = det
        h, w = det.u8.shape; self.canvas.set_extent(w, h)
        self._refilter()
        return self._fr

    def _refilter(self, *_):
        det = self._det
        if det is None:
            return
        self._fr = DF.filter_frame(det, self.dot_params(), self.dash_params(), self.design_fn())
        self.state.set_features(self._fr)
        self.b_export.setEnabled(True)
        self._fill()

    def _fill(self):
        fr, det = self._fr, self._det
        dc, hc = fr.dot_counts, fr.dash_counts
        self.summary.setText(
            f"<b>Dots</b> {len(fr.dot_recs)} · kept <b>{dc['kept']}</b> — edge {dc['edge']}, quiet zone "
            f"{dc['near_tag']}, too close {dc['too_close']}, off lattice {dc['off_lattice']}<br>"
            f"<b>Dashes</b> {len(fr.dash_recs)} · kept <b>{hc['kept']}</b> — edge {hc['edge']}, off grid "
            f"{hc['off_grid']}, intersection {hc['intersection']}, too close {hc['too_close']}")
        by = defaultdict(lambda: defaultdict(int))
        for r in fr.dot_recs:
            by[r["box"]]["found"] += 1
            by[r["box"]][r["reason"] or "kept"] += 1
        rows = sorted(N for N in by if N)
        self.table.setRowCount(len(rows))
        for i, N in enumerate(rows):
            c = by[N]
            for j, v in enumerate([N, c["found"], c["kept"], c["edge"], c["near_tag"], c["too_close"], c["off_lattice"]]):
                self.table.setItem(i, j, QtWidgets.QTableWidgetItem(str(v)))
        self.log(f"Stage 3: dots kept {dc['kept']}/{len(fr.dot_recs)}, dashes kept {hc['kept']}/{len(fr.dash_recs)}")
        self._redraw()

    def _redraw(self, *_):
        fr, det = self._fr, self._det
        if fr is None or det is None:
            return
        self.canvas.set_image(det.u8, levels=(0, 255))
        self.canvas.clear_overlays()
        drop = self.chk_drop.isChecked()
        if self.chk_dots.isChecked():
            self._draw_recs(fr.dot_recs, _DOT_COLOR, "o", drop)
        if self.chk_dash.isChecked():
            self._draw_recs(fr.dash_recs, _DASH_COLOR, "t", drop)
        design = self.design_fn()
        if self.chk_box.isChecked() and design is not None:
            h, w = det.u8.shape
            quads, centres, labels = [], [], []
            for b in design.boxes:
                c = predicted_px([[b.x0_um, b.y0_um], [b.x0_um + b.side_um, b.y0_um],
                                  [b.x0_um + b.side_um, b.y0_um + b.side_um], [b.x0_um, b.y0_um + b.side_um]], det)
                if ((c[:, 0] > -50) & (c[:, 0] < w + 50) & (c[:, 1] > -50) & (c[:, 1] < h + 50)).any():
                    quads.append(c); centres.append(c.mean(0)); labels.append(str(b.N))
            self.canvas.add_polylines(quads, color=(0, 200, 255), width=1)
            self.canvas.add_labels(centres, labels, color=(255, 230, 0), anchor=(0.5, 0.5), size=12)
        tags = [t for t in det.tags.values()]
        if tags:
            self.canvas.add_polylines([t.corners_px for t in tags], color=(60, 230, 90), width=1.5)

    def _draw_recs(self, recs, colors, symbol, show_dropped):
        groups = defaultdict(list)
        for r in recs:
            if r["keep"] or show_dropped:
                groups[r["reason"]].append((r["x"], r["y"]))
        for reason, pts in groups.items():
            size = (3 if symbol == "o" else 7) if reason == "" else (6 if symbol == "o" else 9)
            self.canvas.add_points(pts, color=colors.get(reason, (200, 200, 200)), size=size, symbol=symbol)

    # ---------------------------------------------------------------- export
    def export(self):
        if self._fr is None:
            return
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Export filtered dots and dashes to folder")
        if d:
            self.write(d)

    def write(self, folder):
        for name, recs in (("dots_filtered.csv", self._fr.dot_recs), ("dashes_filtered.csv", self._fr.dash_recs)):
            with open(os.path.join(folder, name), "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["index", "x_px", "y_px", "box", "keep", "reason"])
                for r in recs:
                    w.writerow([r["i"], round(r["x"], 3), round(r["y"], 3), r.get("box", ""), int(r["keep"]), r["reason"]])
        self.log(f"Stage 3: exported filtered dots + dashes to {folder}")
