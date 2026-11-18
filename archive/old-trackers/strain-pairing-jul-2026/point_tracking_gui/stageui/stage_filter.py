"""
stageui.stage_filter
===================
Stage 4 — filter the tracking fiducials.
  DOTS: drop dots too close to a neighbour (× dot pitch = box/18.75), on a
        number/letter, or too far off their ideal lattice node.
  DASHES: drop dashes too far from a grid line, too close to each other
        (× dash pitch = box/dashes-per-edge), or at a grid intersection.
Shows kept vs dropped by reason (dots = circles, dashes = triangles) and exports
both filtered sets.
"""
from __future__ import annotations
import os
import csv
import numpy as np
from PySide6 import QtWidgets

from gridtrack import io
from glyphtrack import lattice as lt
from glyphtrack import reader as gr
from glyphtrack import gridmodel as gm
from glyphtrack import results as gres
from glyphtrack import dotfilter as gdf
from glyphtrack.classifier import GlyphClassifier
from .widgets import SliderSpin

_MODEL = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reference", "glyph_knn.yml")
_DOT_COLOR = {"": (60, 230, 90), "too_close": (255, 60, 60),
              "on_glyph": (255, 160, 0), "off_lattice": (230, 80, 230)}
_DASH_COLOR = {"": (255, 60, 180), "off_grid": (255, 60, 60),
               "intersection": (80, 160, 255), "too_close": (255, 160, 0)}


class DotFilterPanel(QtWidgets.QWidget):
    def __init__(self, state, canvas, log, parent=None):
        super().__init__(parent)
        self.state = state
        self.canvas = canvas
        self.log = log
        self._clf = None
        self._drecs = None            # dot filter records
        self._hrecs = None            # dash filter records
        self._dtags = None
        self._htags = None

        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel("<b>Filter fiducials</b>"))

        # ---- dots group ----
        db = QtWidgets.QGroupBox("Dots"); dl = QtWidgets.QVBoxLayout(db)
        self.c_sep = QtWidgets.QCheckBox("Min separation (× dot pitch)"); self.c_sep.setChecked(True)
        self.s_sep = SliderSpin("min sep", 0.1, 1.0, 0.55, 0.05, 2)
        self.c_gly = QtWidgets.QCheckBox("Exclude dots on numbers/letters"); self.c_gly.setChecked(True)
        self.s_gly = SliderSpin("glyph radius (× glyph)", 0.3, 1.6, 0.80, 0.05, 2)
        self.c_dev = QtWidgets.QCheckBox("Max deviation from ideal (× dot pitch)"); self.c_dev.setChecked(True)
        self.s_dev = SliderSpin("max deviation", 0.05, 1.0, 0.35, 0.05, 2)
        for w in (self.c_sep, self.s_sep, self.c_gly, self.s_gly, self.c_dev, self.s_dev):
            dl.addWidget(w)
        root.addWidget(db)

        # ---- dashes group ----
        hb = QtWidgets.QGroupBox("Dashes"); hl = QtWidgets.QVBoxLayout(hb)
        self.c_off = QtWidgets.QCheckBox("Too far from grid line (× box)"); self.c_off.setChecked(True)
        self.s_off = SliderSpin("max off-grid", 0.03, 0.4, 0.12, 0.01, 2)
        self.c_hsep = QtWidgets.QCheckBox("Too close to each other (× dash pitch)"); self.c_hsep.setChecked(True)
        self.s_hsep = SliderSpin("min sep", 0.1, 1.0, 0.50, 0.05, 2)
        self.c_cor = QtWidgets.QCheckBox("At a grid intersection (× box)"); self.c_cor.setChecked(True)
        self.s_cor = SliderSpin("corner radius", 0.02, 0.3, 0.10, 0.01, 2)
        for w in (self.c_off, self.s_off, self.c_hsep, self.s_hsep, self.c_cor, self.s_cor):
            hl.addWidget(w)
        root.addWidget(hb)

        self.b_run = QtWidgets.QPushButton("Filter")
        self.chk_dots = QtWidgets.QCheckBox("Show dots ●"); self.chk_dots.setChecked(True)
        self.chk_dash = QtWidgets.QCheckBox("Show dashes ▲"); self.chk_dash.setChecked(True)
        self.chk_drop = QtWidgets.QCheckBox("Show dropped"); self.chk_drop.setChecked(True)
        self.b_export = QtWidgets.QPushButton("Export filtered…"); self.b_export.setEnabled(False)
        for w in (self.b_run, self.chk_dots, self.chk_dash, self.chk_drop, self.b_export):
            root.addWidget(w)

        self.summary = QtWidgets.QLabel("—"); self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        root.addStretch(1)

        self.b_run.clicked.connect(self.run)
        self.b_export.clicked.connect(self.export)
        for c in (self.chk_dots, self.chk_dash, self.chk_drop):
            c.toggled.connect(self._redraw)
        for s in (self.s_sep, self.s_gly, self.s_dev, self.s_off, self.s_hsep, self.s_cor):
            s.valueChanged.connect(self._refilter)
        for c in (self.c_sep, self.c_gly, self.c_dev, self.c_off, self.c_hsep, self.c_cor):
            c.toggled.connect(self._refilter)

    # ------------------------------------------------------------------ params
    def _dot_params(self):
        return gdf.DotFilterParams(
            min_sep_enable=self.c_sep.isChecked(), min_sep_frac=self.s_sep.value(),
            glyph_enable=self.c_gly.isChecked(), glyph_radius_frac=self.s_gly.value(),
            dev_enable=self.c_dev.isChecked(), max_dev_frac=self.s_dev.value())

    def _dash_params(self):
        return gdf.DashFilterParams(
            offgrid_enable=self.c_off.isChecked(), max_offgrid_frac=self.s_off.value(),
            minsep_enable=self.c_hsep.isChecked(), min_sep_frac=self.s_hsep.value(),
            corner_enable=self.c_cor.isChecked(), corner_radius_frac=self.s_cor.value())

    # ------------------------------------------------------------------ run
    def run(self):
        img = self.state.working_image()
        if img is None:
            self.log("Filter: open an image first (and deskew in Stage 1)."); return
        if self._clf is None:
            if not os.path.exists(_MODEL):
                self.summary.setText("recognition model not found."); return
            self._clf = GlyphClassifier.load(_MODEL)
        self.log("Filter: computing dots, dashes + grid…")
        QtWidgets.QApplication.processEvents()
        u8 = io.to_uint8(img)
        dots = lt.detect_dots(u8)
        if len(dots) < 30:
            self.summary.setText("too few dots — check Stage 1 / deskew."); return
        basis = lt.refine_basis(dots, lt.estimate_basis(dots))
        dashes = lt.detect_dashes(u8)
        grid = lt.fit_box_grid(basis, dashes)
        crops, gpos = gr.detect_glyph_blobs(u8)
        glyph_h = float(np.median([c.shape[0] for c in crops]) / 1.4) if crops else 30.0
        dtags = htags = None
        try:                                              # optional box tags for export
            _c, fit = gr.read_glyphs(u8, self._clf, grid)
            reads = gr.read_slots(u8, self._clf, fit)
            model = gm.build_grid_model(reads, fit, dots=dots, manual=self.state.glyph_manual)
            if model["registered"]:
                res = gres.finalize(model, fit, dots, dashes=dashes)
                dtags, htags = res.dots, res.dashes
        except Exception as e:
            self.log(f"Filter: tagging skipped ({e})")
        self._u8 = u8; self._dots = dots; self._basis = basis; self._grid = grid
        self._dashes = dashes; self._gpos = gpos; self._glyph_h = glyph_h
        self._dtags = dtags; self._htags = htags
        self._refilter()

    def _refilter(self, *_):
        if getattr(self, "_dots", None) is None:
            return
        self._drecs, self._dcounts = gdf.filter_dots(
            self._dots, self._basis, self._gpos, self._glyph_h, self._dot_params())
        self._hrecs, self._hcounts = gdf.filter_dashes(
            self._dashes, self._grid, self._dash_params())
        self.b_export.setEnabled(True)
        self._redraw()
        dp = self._basis["pitch"]; hp = self._grid["box_pitch"] / self._dash_params().dashes_per_edge
        self.summary.setText(
            f"<b>Dots</b> {len(self._drecs)} · kept {self._dcounts['kept']} — "
            f"<span style='color:#ff3c3c'>close {self._dcounts['too_close']}</span>, "
            f"<span style='color:#ffa000'>on-glyph {self._dcounts['on_glyph']}</span>, "
            f"<span style='color:#e650e6'>off-lattice {self._dcounts['off_lattice']}</span><br>"
            f"<b>Dashes</b> {len(self._hrecs)} · kept {self._hcounts['kept']} — "
            f"<span style='color:#ff3c3c'>off-grid {self._hcounts['off_grid']}</span>, "
            f"<span style='color:#50a0ff'>intersection {self._hcounts['intersection']}</span>, "
            f"<span style='color:#ffa000'>close {self._hcounts['too_close']}</span><br>"
            f"<small>dot pitch ≈ {dp:.1f}px · dash pitch ≈ {hp:.1f}px (box/{self._dash_params().dashes_per_edge})</small>")
        self.log(f"Filter: dots kept {self._dcounts['kept']}/{len(self._drecs)}, "
                 f"dashes kept {self._hcounts['kept']}/{len(self._hrecs)}")

    def _redraw(self, *_):
        if self._drecs is None:
            return
        self.canvas.set_image(self._u8)
        self.canvas.clear_overlays()
        drop = self.chk_drop.isChecked()
        if self.chk_dots.isChecked():
            self._draw(self._drecs, _DOT_COLOR, "o", drop)
        if self.chk_dash.isChecked():
            self._draw(self._hrecs, _DASH_COLOR, "t", drop)

    def _draw(self, recs, colors, symbol, show_dropped):
        groups = {}
        for r in recs:
            if not r["keep"] and not show_dropped:
                continue
            groups.setdefault(r["reason"], []).append((r["x"], r["y"]))
        for reason, pts in groups.items():
            size = 3 if (reason == "" and symbol == "o") else (7 if reason == "" else 8)
            self.canvas.add_points(pts, color=colors.get(reason, (200, 200, 200)),
                                   size=size, symbol=symbol)

    # ------------------------------------------------------------------ export
    def export(self):
        if self._drecs is None:
            return
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Export filtered fiducials to folder")
        if not d:
            return
        self._write(os.path.join(d, "dots_filtered.csv"), self._drecs, self._dtags,
                    ["box_i", "box_j", "box_number", "local_fx", "local_fy"],
                    lambda t: [t.box_i, t.box_j, "" if t.box_number is None else t.box_number,
                               round(t.fx, 3), round(t.fy, 3)])
        self._write(os.path.join(d, "dashes_filtered.csv"), self._hrecs, self._htags,
                    ["box_i", "box_j", "edge", "box_number"],
                    lambda t: [t.box_i, t.box_j, t.edge, "" if t.box_number is None else t.box_number])
        self.summary.setText(self.summary.text() + f"<br>exported dots/dashes_filtered.csv → {d}")
        self.log(f"Filter: exported filtered dots + dashes to {d}")

    @staticmethod
    def _write(path, recs, tags, extra_cols, tag_row):
        tag_by = {(round(t.x, 1), round(t.y, 1)): t for t in tags} if tags else None
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "x_px", "y_px", "keep", "reason"] + extra_cols)
            for i, r in enumerate(recs):
                t = tag_by.get((round(r["x"], 1), round(r["y"], 1))) if tag_by else None
                row = [i, round(r["x"], 1), round(r["y"], 1), int(r["keep"]), r["reason"]]
                row += tag_row(t) if t is not None else [""] * len(extra_cols)
                w.writerow(row)
