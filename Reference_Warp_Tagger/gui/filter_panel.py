"""
gui.filter_panel
================
Stage-3 control panel (third tab): quality-filter the Stage-2 dots & dashes, then
show the clean filtered marked image — surviving dots/dashes plus the box grid,
box numbers and glyph labels carried from Stage 2. Consumes the Stage-2
DetectResult (no re-detection); publishes a FilterResult for Stage 4.

Modelled on the old `stageui/stage_filter.py`, rewired to the new state/canvas.
"""
from __future__ import annotations
import os
import csv
from collections import defaultdict
import numpy as np
from PySide6 import QtWidgets

from rwtag.glyph import lattice as lt, dotfilter as gdf
from rwtag.glyph.types import FilterResult
from .widgets import SliderSpin

_DOT_COLOR = {"": (60, 230, 90), "too_close": (255, 60, 60),
              "on_glyph": (255, 160, 0), "off_lattice": (230, 80, 230)}
_DASH_COLOR = {"": (255, 60, 180), "off_grid": (255, 60, 60),
               "intersection": (80, 160, 255), "too_close": (255, 160, 0)}
_STATE_COLOR = {"confirmed": (60, 230, 90), "corrected": (255, 190, 0),
                "predicted": (80, 160, 255), "conflict": (255, 60, 60), "raw": (200, 200, 200)}


class FilterPanel(QtWidgets.QWidget):
    def __init__(self, state, canvas, log, parent=None):
        super().__init__(parent)
        self.state = state
        self.canvas = canvas
        self.log = log
        self._det = None
        self._drecs = self._hrecs = None
        self._dcounts = self._hcounts = None

        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel("<b>Stage 3 — Filter false positives</b>"))
        _intro = QtWidgets.QLabel(
            "<small>Drops spurious dots &amp; dashes from the Stage-2 detection, then shows the "
            "clean marked image. Run Stage 2 first.</small>")
        _intro.setWordWrap(True)
        root.addWidget(_intro)

        # ---- dots ----
        db = QtWidgets.QGroupBox("Dots"); dl = QtWidgets.QVBoxLayout(db)
        self.c_sep = QtWidgets.QCheckBox("Min separation (× dot pitch)"); self.c_sep.setChecked(True)
        self.s_sep = SliderSpin("min sep", 0.1, 1.0, 0.50, 0.05, 2)
        self.c_gly = QtWidgets.QCheckBox("Exclude dots on numbers/letters"); self.c_gly.setChecked(True)
        self.s_gly = SliderSpin("glyph radius (× glyph)", 0.3, 1.6, 0.80, 0.05, 2)
        self.c_dev = QtWidgets.QCheckBox("Max deviation from ideal (× dot pitch)"); self.c_dev.setChecked(True)
        self.s_dev = SliderSpin("max deviation", 0.05, 1.2, 0.60, 0.05, 2)
        for w in (self.c_sep, self.s_sep, self.c_gly, self.s_gly, self.c_dev, self.s_dev):
            dl.addWidget(w)
        root.addWidget(db)

        # ---- dashes ----
        hb = QtWidgets.QGroupBox("Dashes"); hl = QtWidgets.QVBoxLayout(hb)
        self.c_off = QtWidgets.QCheckBox("Too far from grid line (× box)"); self.c_off.setChecked(True)
        self.s_off = SliderSpin("max off-grid", 0.03, 0.4, 0.15, 0.01, 2)
        self.c_hsep = QtWidgets.QCheckBox("Too close to each other (× dash pitch)"); self.c_hsep.setChecked(True)
        self.s_hsep = SliderSpin("min sep", 0.1, 1.0, 0.50, 0.05, 2)
        self.c_cor = QtWidgets.QCheckBox("At a grid intersection (× box)"); self.c_cor.setChecked(True)
        self.s_cor = SliderSpin("corner radius", 0.02, 0.3, 0.10, 0.01, 2)
        for w in (self.c_off, self.s_off, self.c_hsep, self.s_hsep, self.c_cor, self.s_cor):
            hl.addWidget(w)
        root.addWidget(hb)

        self.b_run = QtWidgets.QPushButton("Filter")
        root.addWidget(self.b_run)

        vo = QtWidgets.QGroupBox("View"); vl = QtWidgets.QVBoxLayout(vo)
        self.chk_dots = QtWidgets.QCheckBox("Dots ●"); self.chk_dots.setChecked(True)
        self.chk_dash = QtWidgets.QCheckBox("Dashes ▲"); self.chk_dash.setChecked(True)
        self.chk_drop = QtWidgets.QCheckBox("Show dropped"); self.chk_drop.setChecked(True)
        self.chk_lab = QtWidgets.QCheckBox("Glyph labels"); self.chk_lab.setChecked(True)
        self.chk_num = QtWidgets.QCheckBox("Box numbers"); self.chk_num.setChecked(True)
        for w in (self.chk_dots, self.chk_dash, self.chk_drop, self.chk_lab, self.chk_num):
            vl.addWidget(w)
        root.addWidget(vo)

        self.b_export = QtWidgets.QPushButton("Export filtered CSVs…"); self.b_export.setEnabled(False)
        root.addWidget(self.b_export)
        self.summary = QtWidgets.QLabel("Run Stage 2, then Filter."); self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        root.addStretch(1)

        self.b_run.clicked.connect(self.run)
        self.b_export.clicked.connect(self.export)
        for c in (self.chk_dots, self.chk_dash, self.chk_drop, self.chk_lab, self.chk_num):
            c.toggled.connect(self._redraw)
        for s in (self.s_sep, self.s_gly, self.s_dev, self.s_off, self.s_hsep, self.s_cor):
            s.valueChanged.connect(self._refilter)
        for c in (self.c_sep, self.c_gly, self.c_dev, self.c_off, self.c_hsep, self.c_cor):
            c.toggled.connect(self._refilter)
        self.state.imageLoaded.connect(self._invalidate)
        self.state.detectionChanged.connect(self._invalidate)

    # ---------------------------------------------------------------- params
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

    # ---------------------------------------------------------------- run
    def _invalidate(self, *_):
        self._det = self._drecs = self._hrecs = None
        self.b_export.setEnabled(False)
        self.summary.setText("Run Stage 2 (Detect grid), then Filter.")

    def load_from_state(self):
        """Restore panel caches from the active image's stored FilterResult
        (project selection change) — or clear if that image has none."""
        fr = self.state.pipeline.features
        det = self.state.pipeline.detection
        if fr is None or det is None:
            self._invalidate()
            return
        self._det = det
        self._drecs, self._hrecs = fr.dot_recs, fr.dash_recs
        self._dcounts, self._hcounts = fr.dot_counts, fr.dash_counts
        self.b_export.setEnabled(True)
        self.summary.setText(
            f"Restored — dots kept {fr.dot_counts['kept']}/{len(fr.dot_recs)} · "
            f"dashes kept {fr.dash_counts['kept']}/{len(fr.dash_recs)}")

    def refresh_base_image(self):
        """On entering the tab, show the Stage-2 image (if any)."""
        det = self.state.pipeline.detection
        if det is None:
            self.summary.setText("No detection — run Stage 2 (Detect grid) first."); return
        h, w = det.u8.shape
        self.canvas.set_extent(w, h)
        if self._drecs is None:
            self.canvas.set_image(det.u8, levels=(0, 255))

    def run(self):
        det = self.state.pipeline.detection
        if det is None:
            self.log("Stage 3: run Stage 2 (Detect grid) first."); return
        self._det = det
        h, w = det.u8.shape; self.canvas.set_extent(w, h)
        self._refilter()

    def _refilter(self, *_):
        det = self._det
        if det is None:
            return
        # filter dashes against the fit-aligned grid when available (the raw dash grid
        # is only a coarse bootstrap; the fit tracks the true box boundaries).
        dash_grid = lt.grid_from_fit(det.fit) if det.fit is not None else det.grid
        self._drecs, self._dcounts = gdf.filter_dots(
            det.dots, det.basis, det.glyphs, det.glyph_h, self._dot_params())
        self._hrecs, self._hcounts = gdf.filter_dashes(
            det.dashes_all, dash_grid, self._dash_params())
        self.b_export.setEnabled(True)
        self._redraw()
        self._publish()
        dp = float(det.basis["pitch"])
        hp = dash_grid["box_pitch"] / self._dash_params().dashes_per_edge
        self.summary.setText(
            f"<b>Dots</b> {len(self._drecs)} · kept {self._dcounts['kept']} — "
            f"<span style='color:#ff3c3c'>close {self._dcounts['too_close']}</span>, "
            f"<span style='color:#ffa000'>on-glyph {self._dcounts['on_glyph']}</span>, "
            f"<span style='color:#e650e6'>off-lattice {self._dcounts['off_lattice']}</span><br>"
            f"<b>Dashes</b> {len(self._hrecs)} · kept {self._hcounts['kept']} — "
            f"<span style='color:#ff3c3c'>off-grid {self._hcounts['off_grid']}</span>, "
            f"<span style='color:#50a0ff'>intersection {self._hcounts['intersection']}</span>, "
            f"<span style='color:#ffa000'>close {self._hcounts['too_close']}</span><br>"
            f"<small>dot pitch ≈ {dp:.1f}px · dash pitch ≈ {hp:.1f}px</small>")
        self.log(f"Stage 3: dots kept {self._dcounts['kept']}/{len(self._drecs)}, "
                 f"dashes kept {self._hcounts['kept']}/{len(self._hrecs)}")

    # ---------------------------------------------------------------- draw
    def _marked_layer(self):
        """Box quads + box numbers + glyph labels carried from Stage 2."""
        det = self._det; grid = det.grid; H, W = det.u8.shape
        fit = det.fit
        corner = (lambda i, j: lt.fit_box_corner(fit, i, j)) if fit is not None \
            else (lambda i, j: lt.box_corner(grid, i, j))

        def inb(p):
            return -60 <= p[0] <= W + 60 and -60 <= p[1] <= H + 60
        quads = []
        for i in range(-2, 10):
            for j in range(-2, 10):
                corners = [corner(i, j), corner(i + 1, j), corner(i + 1, j + 1), corner(i, j + 1)]
                if any(inb(c) for c in corners):
                    quads.append(corners)
        labels_by_state = None
        box_numbers = None
        m = det.model
        if m and self.chk_lab.isChecked():
            by = defaultdict(list)
            for L in m.get("labels", []):
                by[L["state"]].append((L["x"], L["y"], L["text"]))
            labels_by_state = [(_STATE_COLOR.get(st, (200, 200, 200)), items) for st, items in by.items()]
        if m and m.get("registered") and det.fit is not None and self.chk_num.isChecked():
            fit = det.fit; box_numbers = []
            for node, N in m.get("node_num", {}).items():
                if N is None:
                    continue
                c = fit["O"] + (node[0] + 0.5) * fit["U"] + (node[1] + 0.5) * fit["V"]
                if inb(c):
                    box_numbers.append((float(c[0]), float(c[1]), str(N)))
        return quads, labels_by_state, box_numbers

    def _redraw(self, *_):
        if self._drecs is None:
            return
        det = self._det
        self.canvas.set_image(det.u8, levels=(0, 255))
        self.canvas.clear_overlays()
        # z-order matters: filtered points at the BOTTOM, then the grid / labels /
        # box numbers ON TOP so the thin grid lines aren't buried under the dots.
        drop = self.chk_drop.isChecked()
        if self.chk_dots.isChecked():
            self._draw_recs(self._drecs, _DOT_COLOR, "o", drop)
        if self.chk_dash.isChecked():
            self._draw_recs(self._hrecs, _DASH_COLOR, "t", drop)
        quads, labels_by_state, box_numbers = self._marked_layer()
        self.canvas.add_polylines(quads, color=(0, 200, 255), width=1.5)
        if labels_by_state:
            for color, items in labels_by_state:
                if items:
                    self.canvas.add_labels([(x, y) for x, y, _t in items],
                                           [t for _x, _y, t in items], color=color)
        if box_numbers:
            self.canvas.add_labels([(x, y) for x, y, _t in box_numbers],
                                   [t for _x, _y, t in box_numbers],
                                   color=(255, 230, 0), anchor=(0.5, 0.5), size=12)

    def _draw_recs(self, recs, colors, symbol, show_dropped):
        groups = defaultdict(list)
        for r in recs:
            if not r["keep"] and not show_dropped:
                continue
            groups[r["reason"]].append((r["x"], r["y"]))
        for reason, pts in groups.items():
            size = 3 if (reason == "" and symbol == "o") else (7 if reason == "" else 8)
            self.canvas.add_points(pts, color=colors.get(reason, (200, 200, 200)),
                                   size=size, symbol=symbol)

    # ---------------------------------------------------------------- publish
    def _publish(self):
        kept_dots = np.array([[r["x"], r["y"]] for r in self._drecs if r["keep"]], float)
        kept_dashes = np.array([[r["x"], r["y"]] for r in self._hrecs if r["keep"]], float)
        fr = FilterResult(
            dot_recs=self._drecs, dash_recs=self._hrecs,
            dot_counts=self._dcounts, dash_counts=self._hcounts,
            kept_dots=kept_dots, kept_dashes=kept_dashes,
            dot_params=self._dot_params().__dict__, dash_params=self._dash_params().__dict__)
        self.state.set_features(fr)

    # ---------------------------------------------------------------- export
    def export(self):
        if self._drecs is None:
            return
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Export filtered fiducials to folder")
        if not d:
            return
        self._write(os.path.join(d, "dots_filtered.csv"), self._drecs)
        self._write(os.path.join(d, "dashes_filtered.csv"), self._hrecs)
        self.log(f"Stage 3: exported filtered dots + dashes to {d}")
        self.summary.setText(self.summary.text() + f"<br>exported → {d}")

    @staticmethod
    def _write(path, recs):
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "x_px", "y_px", "keep", "reason"])
            for i, r in enumerate(recs):
                w.writerow([i, round(r["x"], 1), round(r["y"], 1), int(r["keep"]), r["reason"]])
