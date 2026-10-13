"""
gui.summary_panel
=================
Phase-E tab (8 · Summary) with four toggleable views:

  1. Trend        — measured vs expected expansion (mean ± σ, identity line).
  2. Histogram    — per-dot local-expansion distributions of ALL expanded images,
                    overlaid + colour-coded, dashed line at each expected λ.
  3. Box+jitter — expansion:    one box-and-whisker per image (per-dot local
                    linear expansion) with ALL raw points jittered in the box.
  4. Box+jitter — warp residual: same construction for the per-dot similarity
                    residual (px) — each image's non-uniform warpage.

The expected factor of every image is recorded in the project and every export.
"""
from __future__ import annotations
import os
import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets, QtCore

from rwtag import pairing as PR

_PALETTE = [(0, 200, 255), (255, 190, 0), (60, 230, 90), (255, 60, 180),
            (170, 120, 255), (255, 120, 60), (120, 220, 220), (220, 220, 120)]

MODES = ["Trend (mean ± σ)", "Histogram — expansion",
         "Box + jitter — expansion", "Box + jitter — warp residual (px)"]


class SummaryPanel(QtWidgets.QWidget):
    def __init__(self, state, plotw, log, project_fn, parent=None):
        super().__init__(parent)
        self.state = state
        self.plotw = plotw
        self.log = log
        self.project_fn = project_fn
        self._rows = None
        self._dists = None
        self._legend = None

        self.plotw.showGrid(x=True, y=True, alpha=0.25)

        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel("<b>8 — Summary (measured vs expected)</b>"))
        _intro = QtWidgets.QLabel(
            "<small>Average measured expansion per expanded image, its per-dot "
            "distribution, and the warp-residual distribution (distance from each "
            "image's best-fit uniform expansion — pure warpage, px).</small>")
        _intro.setWordWrap(True)
        root.addWidget(_intro)

        vrow = QtWidgets.QHBoxLayout()
        vrow.addWidget(QtWidgets.QLabel("view:"))
        self.viewcombo = QtWidgets.QComboBox()
        self.viewcombo.addItems(MODES)
        vrow.addWidget(self.viewcombo, 1)
        _vw = QtWidgets.QWidget(); _vw.setLayout(vrow)
        root.addWidget(_vw)

        self.b_refresh = QtWidgets.QPushButton("Refresh")
        root.addWidget(self.b_refresh)

        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["image ×", "expected", "measured", "± σ", "n", "rms px"])
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setMinimumHeight(200)
        root.addWidget(self.table, 1)

        self.summary = QtWidgets.QLabel("Tag the images (Run all pending), then Refresh.")
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        self.b_export = QtWidgets.QPushButton("Export summary CSV…")
        self.b_export_dist = QtWidgets.QPushButton("Export distributions CSV…")
        self.b_export_png = QtWidgets.QPushButton("Export plot PNG…")
        for b in (self.b_export, self.b_export_dist, self.b_export_png):
            b.setEnabled(False)
            root.addWidget(b)
        root.addStretch(1)

        self.b_refresh.clicked.connect(self.refresh)
        self.viewcombo.currentIndexChanged.connect(lambda *_: self._plot())
        self.b_export.clicked.connect(self.export_csv)
        self.b_export_dist.clicked.connect(self.export_dist_csv)
        self.b_export_png.clicked.connect(self.export_png)
        self.state.taggingChanged.connect(
            lambda *_: (setattr(self, "_rows", None), setattr(self, "_dists", None)))

    # ---------------------------------------------------------------- data
    def refresh(self):
        proj = self.project_fn()
        init = proj.initial()
        if init is None or init.pipeline.tagging is None:
            self.summary.setText("Tag the <b>initial</b> image first."); return
        expanded = [(f"{e.label:g}× ({e.name[:24]})", e.label,
                     e.pipeline.tagging.tags if e.pipeline.tagging else None)
                    for e in proj.expanded()]
        if not expanded:
            self.summary.setText("Add and tag at least one expanded image."); return
        self._init = init
        self._rows = PR.expansion_rows(init.pipeline.tagging.tags, init.label, expanded)
        self._dists = PR.expansion_distributions(init.pipeline.tagging.tags,
                                                 init.label, expanded)
        self._fill_table()
        self._plot()
        ok = [r for r in self._rows if np.isfinite(r["measured"])]
        self.summary.setText(
            f"<b>{len(ok)}</b>/{len(self._rows)} expanded image(s) measured · "
            f"initial = {init.label:g}×.<br>"
            "<small>expected factors recorded per image; warp residual = distance from "
            "the best-fit uniform expansion (px).</small>")
        for b in (self.b_export, self.b_export_dist, self.b_export_png):
            b.setEnabled(bool(ok))
        for r in self._rows:
            m = ("%.3f±%.3f" % (r["measured"], r["sigma"])
                 if np.isfinite(r["measured"]) else r["status"])
            self.log(f"Summary: {r['name']} expected {r['expected']:.3f} -> {m}")

    def _fill_table(self):
        rows = self._rows or []
        rms_by = {d["label"]: d["rms"] for d in (self._dists or [])}
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            rms = rms_by.get(r["label"])
            vals = [f"{r['label']:g}×", f"{r['expected']:.3f}",
                    (f"{r['measured']:.3f}" if np.isfinite(r["measured"]) else "—"),
                    (f"{r['sigma']:.3f}" if np.isfinite(r["sigma"]) else "—"),
                    str(r["n"]),
                    (f"{rms:.1f}" if rms is not None and np.isfinite(rms) else "—")]
            for c, v in enumerate(vals):
                item = QtWidgets.QTableWidgetItem(v)
                if not np.isfinite(r["measured"]):
                    item.setForeground(pg.mkBrush(150, 150, 150))
                self.table.setItem(i, c, item)

    # ---------------------------------------------------------------- plotting
    def _clear_plot(self):
        self.plotw.clear()
        if self._legend is not None:
            try:
                self._legend.scene().removeItem(self._legend)
            except Exception:
                pass
            self._legend = None

    def _plot(self, *_):
        if self._rows is None:
            return
        self._clear_plot()
        mode = self.viewcombo.currentIndex()
        self.plotw.setTitle(["measured vs expected expansion",
                             "per-dot expansion distributions",
                             "expansion vs expected — box + jittered raw dots",
                             "warp residual — box + jittered raw dots"][mode])
        if mode == 0:
            self._plot_trend()
        elif mode == 1:
            self._plot_hist()
        elif mode == 2:
            self._plot_box(quantity="lin")
        else:
            self._plot_box(quantity="resid")

    def _plot_trend(self):
        self.plotw.setLabel("bottom", "expected expansion (vs initial)")
        self.plotw.setLabel("left", "measured expansion (vs initial)")
        rows = [r for r in (self._rows or []) if np.isfinite(r["measured"])]
        if not rows:
            return
        xs = np.array([1.0] + [r["expected"] for r in rows])
        ys = np.array([1.0] + [r["measured"] for r in rows])
        er = np.array([0.0] + [r["sigma"] for r in rows])
        lo = min(xs.min(), np.nanmin(ys - er)) * 0.95
        hi = max(xs.max(), np.nanmax(ys + er)) * 1.05
        self.plotw.plot([lo, hi], [lo, hi],
                        pen=pg.mkPen((255, 60, 60), width=2, style=QtCore.Qt.DashLine))
        self.plotw.addItem(pg.ErrorBarItem(x=xs, y=ys, height=2 * er,
                                           beam=0.012 * (hi - lo),
                                           pen=pg.mkPen((0, 200, 255), width=1.5)))
        self.plotw.plot(xs, ys, pen=None, symbol="o", symbolSize=10,
                        symbolBrush=(0, 200, 255), symbolPen=pg.mkPen("w", width=0.5))
        for r in rows:
            t = pg.TextItem(f"{r['label']:g}×", color=(255, 230, 0), anchor=(0.5, 1.4))
            t.setPos(r["expected"], r["measured"])
            self.plotw.addItem(t)

    def _plot_hist(self):
        self.plotw.setLabel("bottom", "per-dot local linear expansion (vs initial)")
        self.plotw.setLabel("left", "count")
        dists = self._dists or []
        if not dists:
            return
        self._legend = self.plotw.addLegend(offset=(10, 10))
        allv = np.concatenate([d["lin"] for d in dists if len(d["lin"])])
        lo, hi = np.percentile(allv, 0.5), np.percentile(allv, 99.5)
        pad = 0.05 * (hi - lo)
        edges = np.linspace(lo - pad, hi + pad, 61)
        for k, d in enumerate(dists):
            col = _PALETTE[k % len(_PALETTE)]
            counts, _ = np.histogram(d["lin"], bins=edges)
            self.plotw.plot(edges, counts.astype(float), stepMode="center",
                            fillLevel=0, brush=(*col, 70), pen=pg.mkPen(col, width=1.6),
                            name=f"{d['label']:g}×  (n={len(d['lin'])})")
            self.plotw.addItem(pg.InfiniteLine(
                pos=d["expected"], angle=90,
                pen=pg.mkPen(col, width=1.2, style=QtCore.Qt.DashLine)))

    def _plot_box(self, quantity="lin"):
        """Box-and-whisker (Q1/median/Q3, 1.5·IQR whiskers with caps) + ALL raw
        points jittered inside the box width; outliers slightly larger."""
        is_lin = quantity == "lin"
        self.plotw.setLabel("bottom", "expected expansion (vs initial)")
        self.plotw.setLabel("left",
                            "per-dot local linear expansion" if is_lin
                            else "per-dot warp residual (px)")
        dists = self._dists or []
        groups = [(d["expected"], d[quantity], _PALETTE[k % len(_PALETTE)], d["label"])
                  for k, d in enumerate(dists) if len(d[quantity]) >= 5]
        if not groups:
            return
        xs = [g[0] for g in groups]
        span = (max(xs) - min(xs)) or 1.0
        w = 0.06 * span

        if is_lin:                                    # identity line for the expansion view
            lo, hi = min(xs) - 2 * w, max(xs) + 2 * w
            self.plotw.plot([lo, hi], [lo, hi],
                            pen=pg.mkPen((255, 60, 60), width=2, style=QtCore.Qt.DashLine))

        for gi, (x0, vals, col, label) in enumerate(groups):
            v = np.asarray(vals, float)
            q1, med, q3 = np.percentile(v, [25, 50, 75])
            iqr = q3 - q1
            in_lo = v[v >= q1 - 1.5 * iqr].min()
            in_hi = v[v <= q3 + 1.5 * iqr].max()
            out = v[(v < in_lo) | (v > in_hi)]
            # jittered raw points (deterministic)
            rng = np.random.default_rng(hash(label) % (2 ** 32))
            jx = x0 + rng.uniform(-0.4 * w, 0.4 * w, len(v))
            self.plotw.plot(jx, v, pen=None, symbol="o", symbolSize=3,
                            symbolBrush=(*col, 60), symbolPen=None)
            if len(out):
                jo = x0 + rng.uniform(-0.4 * w, 0.4 * w, len(out))
                self.plotw.plot(jo, out, pen=None, symbol="o", symbolSize=6,
                                symbolBrush=None, symbolPen=pg.mkPen(col, width=1.2))
            pen = pg.mkPen(col, width=2)
            hw = 0.5 * w
            # box, median, whiskers, caps
            self.plotw.plot([x0 - hw, x0 + hw, x0 + hw, x0 - hw, x0 - hw],
                            [q1, q1, q3, q3, q1], pen=pen)
            self.plotw.plot([x0 - hw, x0 + hw], [med, med],
                            pen=pg.mkPen("w", width=2.4))
            for y0, y1 in ((q3, in_hi), (q1, in_lo)):
                self.plotw.plot([x0, x0], [y0, y1], pen=pen)
            for yc in (in_hi, in_lo):
                self.plotw.plot([x0 - 0.55 * hw, x0 + 0.55 * hw], [yc, yc], pen=pen)
            t = pg.TextItem(f"{label:g}×", color=(255, 230, 0), anchor=(0.5, -0.35))
            t.setPos(x0, in_hi)
            self.plotw.addItem(t)

    # ---------------------------------------------------------------- export
    def export_csv(self):
        if not self._rows:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export expansion summary", "expansion_summary.csv", "CSV (*.csv)")
        if path:
            PR.write_summary_csv(self._rows, path, self._init.label, self._init.name)
            self.log(f"Summary: CSV → {path}")

    def export_dist_csv(self):
        if not self._dists:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export per-dot distributions", "distributions.csv", "CSV (*.csv)")
        if path:
            PR.write_distributions_csv(self._dists, path, self._init.label)
            self.log(f"Summary: distributions CSV → {path}")

    def export_png(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export plot PNG", "expansion_summary.png", "PNG (*.png)")
        if not path:
            return
        from pyqtgraph.exporters import ImageExporter
        ImageExporter(self.plotw.plotItem).export(path)
        self.log(f"Summary: plot PNG → {path}")
