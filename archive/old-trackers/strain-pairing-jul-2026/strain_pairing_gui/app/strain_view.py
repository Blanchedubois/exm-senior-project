"""
app.strain_view
==============
Strain analysis: choose the expansion and the CENTRE box, view the per-point
expansion heatmap / displacement vectors, the distribution (mean ± σ), a
measured-vs-expected trend graph (with the expected y=x line), and a table.
Exports per-point + summary CSVs.
"""
from __future__ import annotations
import os
import csv
import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets, QtCore

from gridtrack import io as gio, correct
from gridtrack.types import CorrectionParams

pg.setConfigOptions(imageAxisOrder="row-major", background="k", antialias=True)


class StrainView(QtWidgets.QWidget):
    def __init__(self, project, log, parent=None):
        super().__init__(parent)
        self.project = project
        self.log = log
        self._fields = {}                 # e -> StrainField (stats are ref-box-independent)
        self._ref_box = None

        root = QtWidgets.QVBoxLayout(self)
        bar = QtWidgets.QHBoxLayout()
        self.combo = QtWidgets.QComboBox()
        self.refbox = QtWidgets.QComboBox()
        self.mode = QtWidgets.QComboBox(); self.mode.addItems(["Heatmap", "Vectors", "Both"])
        self.vscale = QtWidgets.QDoubleSpinBox(); self.vscale.setRange(0.2, 20.0)
        self.vscale.setValue(3.0); self.vscale.setSingleStep(0.5)
        self.chk_img = QtWidgets.QCheckBox("Image"); self.chk_img.setChecked(True)
        self.b_go = QtWidgets.QPushButton("Compute strain")
        self.b_exp = QtWidgets.QPushButton("Export…")
        for lbl, wdg in (("expansion:", self.combo), ("centre box:", self.refbox),
                         ("view:", self.mode), ("vec×", self.vscale)):
            bar.addWidget(QtWidgets.QLabel(lbl)); bar.addWidget(wdg)
        bar.addWidget(self.chk_img); bar.addStretch(1)
        bar.addWidget(self.b_go); bar.addWidget(self.b_exp)
        root.addLayout(bar)

        self.glw = pg.GraphicsLayoutWidget()
        self.vb = self.glw.addViewBox(lockAspect=True, invertY=True)
        self.img_item = pg.ImageItem(); self.vb.addItem(self.img_item)
        self.scatter = pg.ScatterPlotItem(pen=None); self.vb.addItem(self.scatter)
        self.vectors = pg.PlotCurveItem(connect="pairs", pen=pg.mkPen((0, 220, 255, 160)))
        self.vb.addItem(self.vectors)

        self.hist = pg.PlotWidget(title="per-point linear expansion")
        self.hist.setMaximumHeight(180); self.hist.showGrid(x=True, y=False, alpha=0.2)
        self.trend = pg.PlotWidget(title="measured vs expected expansion")
        self.trend.setMaximumHeight(220); self.trend.showGrid(x=True, y=True, alpha=0.2)
        self.trend.setLabel("bottom", "expected (label ratio)")
        self.trend.setLabel("left", "measured linear")
        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["exp ×", "measured", "± σ", "expected", "Δ", "n"])
        self.table.setMaximumHeight(150)

        split = QtWidgets.QSplitter()
        left = QtWidgets.QWidget(); ll = QtWidgets.QVBoxLayout(left); ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.glw)
        right = QtWidgets.QWidget(); rl = QtWidgets.QVBoxLayout(right); rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.hist); rl.addWidget(self.trend); rl.addWidget(self.table)
        split.addWidget(left); split.addWidget(right)
        split.setStretchFactor(0, 3); split.setStretchFactor(1, 2)
        root.addWidget(split, 1)
        self.summary = QtWidgets.QLabel("—"); self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        self.b_go.clicked.connect(self.compute)
        self.b_exp.clicked.connect(self.export)
        self.combo.currentIndexChanged.connect(self._recompute_current)
        self.refbox.currentIndexChanged.connect(self._on_refbox)
        self.mode.currentIndexChanged.connect(self._draw)
        self.vscale.valueChanged.connect(self._draw)
        self.chk_img.toggled.connect(self._draw)

    # ------------------------------------------------------------------ compute
    def refresh_combo(self):
        self.combo.blockSignals(True); self.combo.clear()
        for e in self.project.expansions:
            self.combo.addItem(f"{e.label:g}×")
        self.combo.blockSignals(False)

    def compute(self):
        if getattr(self.project, "pairing", None) is None:
            self.summary.setText("Pair to initial first (toolbar)."); return
        self.refresh_combo()
        self.log("Strain: computing all expansions…")
        QtWidgets.QApplication.processEvents()
        self._fields = {e: self.project.strain(e)
                        for e in range(len(self.project.pairing.expansions))}
        self._fill_table(); self._draw_trend()
        self._recompute_current()

    def _boxes_with_pairs(self, sf):
        p = self.project.pairing
        return sorted(set(p.initial.points[i].box_number for i in _paired(p, sf.e)
                          if p.initial.points[i].type == "dot"))

    def _populate_refbox(self, boxes):
        self.refbox.blockSignals(True); self.refbox.clear()
        self.refbox.addItem("auto")
        for b in boxes:
            self.refbox.addItem(str(b))
        # keep the current selection if still valid
        idx = self.refbox.findText("auto" if self._ref_box is None else str(self._ref_box))
        self.refbox.setCurrentIndex(idx if idx >= 0 else 0)
        self.refbox.blockSignals(False)

    def _on_refbox(self):
        txt = self.refbox.currentText()
        self._ref_box = None if txt == "auto" else int(txt)
        self._recompute_current()

    def _recompute_current(self, *_):
        if not self._fields:
            return
        ei = self.combo.currentIndex()
        if ei < 0:
            return
        self._fields[ei] = self.project.strain(ei, ref_box=self._ref_box)
        self._populate_refbox(self._boxes_with_pairs(self._fields[ei]))
        self._draw()

    def _bg_image(self):
        e = self.project.initial
        t = self.project.results.get(e.path)
        try:
            img = gio.load_tiff(e.path)
            return gio.to_uint8(correct.apply(img, CorrectionParams(rotate_deg=t.deskew_deg)))
        except Exception:
            return None

    def _draw(self, *_):
        if not self._fields:
            return
        ei = self.combo.currentIndex()
        sf = self._fields.get(ei)
        if sf is None or sf.lin is None:
            self.scatter.clear(); self.vectors.clear()
            self.summary.setText("not enough paired points for this expansion "
                                 "(frames may not overlap — see the log)."); return
        bg = self._bg_image() if self.chk_img.isChecked() else None
        self.img_item.setImage(bg) if bg is not None else self.img_item.clear()

        lin = sf.lin; ok = np.isfinite(lin)
        P = sf.P0[ok]; L = lin[ok]
        vmin, vmax = np.percentile(L, [5, 95]) if len(L) else (0.8, 1.2)
        heat = self.mode.currentText() in ("Heatmap", "Both")
        vec = self.mode.currentText() in ("Vectors", "Both")
        if heat and len(P):
            cmap = pg.colormap.get("viridis")
            cols = cmap.map(np.clip((L - vmin) / (vmax - vmin + 1e-9), 0, 1), mode="byte")
            self.scatter.setData(x=P[:, 0], y=P[:, 1], size=6,
                                 brush=[pg.mkBrush(*c) for c in cols])
        else:
            self.scatter.clear()
        if vec and sf.disp is not None:
            sc = self.vscale.value(); a = sf.P0; b = sf.P0 + sf.disp * sc
            xs = np.empty(2 * len(a)); ys = np.empty(2 * len(a))
            xs[0::2] = a[:, 0]; xs[1::2] = b[:, 0]; ys[0::2] = a[:, 1]; ys[1::2] = b[:, 1]
            self.vectors.setData(x=xs, y=ys)
        else:
            self.vectors.clear()
        self.vb.autoRange(padding=0.02)
        self._draw_hist(sf, L)
        st = sf.stats()
        self.summary.setText(
            f"<b>{sf.label_init:g}× → {sf.label_exp:g}×</b> · centre box {sf.ref_box} · "
            f"{st['n']} points<br>measured linear expansion "
            f"<b>{st['mean']:.3f} ± {st['sigma']:.3f}</b> (median {st['median']:.3f}, "
            f"global-fit {sf.global_scale:.3f}) · expected <b>{sf.expected:.3f}</b>")

    def _draw_hist(self, sf, L):
        self.hist.clear()
        if len(L) < 3:
            return
        counts, edges = np.histogram(L, bins=48)
        self.hist.plot(edges, counts, stepMode="center", fillLevel=0,
                       brush=(90, 140, 255, 150), pen=pg.mkPen((150, 180, 255)))
        st = sf.stats()
        self.hist.addItem(pg.InfiniteLine(st["mean"], angle=90,
                                          pen=pg.mkPen((255, 210, 0), width=2)))
        self.hist.addItem(pg.InfiniteLine(sf.expected, angle=90,
                          pen=pg.mkPen((255, 60, 60), width=2, style=QtCore.Qt.DashLine)))

    def _draw_trend(self):
        self.trend.clear()
        xs, ys, err = [1.0], [1.0], [0.0]         # the initial vs itself = (1, 1)
        for e in range(len(self.project.pairing.expansions)):
            sf = self._fields.get(e); st = sf.stats() if sf else {"mean": float("nan")}
            if sf and np.isfinite(st["mean"]):
                xs.append(sf.expected); ys.append(st["mean"]); err.append(st["sigma"])
        xs, ys, err = np.array(xs), np.array(ys), np.array(err)
        lo = min(xs.min(), ys.min()) * 0.96; hi = max(xs.max(), ys.max()) * 1.04
        self.trend.plot([lo, hi], [lo, hi], pen=pg.mkPen((255, 60, 60), width=2,
                        style=QtCore.Qt.DashLine), name="expected")   # y = x
        self.trend.addItem(pg.ErrorBarItem(x=xs, y=ys, height=2 * err,
                           beam=0.01 * (hi - lo), pen=pg.mkPen((0, 200, 255))))
        self.trend.plot(xs, ys, pen=None, symbol="o", symbolSize=8,
                        symbolBrush=(0, 200, 255))

    def _fill_table(self):
        exps = self.project.pairing.expansions
        self.table.setRowCount(len(exps))
        for e, t in enumerate(exps):
            sf = self._fields.get(e); st = sf.stats() if sf else {"mean": float("nan"),
                                                                  "sigma": float("nan"), "n": 0}
            exp = sf.expected if sf else float("nan")
            delta = abs(st["mean"] - exp) if np.isfinite(st["mean"]) else float("nan")
            for c, v in enumerate([f"{t.label:g}", f"{st['mean']:.3f}", f"{st['sigma']:.3f}",
                                   f"{exp:.3f}", f"{delta:.3f}", str(st["n"])]):
                self.table.setItem(e, c, QtWidgets.QTableWidgetItem(v))

    # ------------------------------------------------------------------ export
    def export(self):
        if not self._fields:
            self.log("Compute strain first."); return
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Export strain to folder")
        if not d:
            return
        with open(os.path.join(d, "expansion_summary.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["expansion_x", "measured_linear", "sigma", "expected",
                        "abs_error", "n_points", "centre_box"])
            for e, t in enumerate(self.project.pairing.expansions):
                sf = self._fields[e]; st = sf.stats()
                w.writerow([t.label, round(st["mean"], 4), round(st["sigma"], 4),
                            round(sf.expected, 4),
                            round(abs(st["mean"] - sf.expected), 4) if np.isfinite(st["mean"]) else "",
                            st["n"], sf.ref_box])
        for e, t in enumerate(self.project.pairing.expansions):
            sf = self._fields[e]
            if sf.lin is None:
                continue
            with open(os.path.join(d, f"strain_{t.label:g}x.csv"), "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["init_x", "init_y", "exp_x", "exp_y", "type",
                            "J_areal", "linear", "disp_x", "disp_y"])
                for i in range(sf.n_pairs):
                    dx, dy = (sf.disp[i] if sf.disp is not None else (0, 0))
                    w.writerow([round(sf.P0[i, 0], 1), round(sf.P0[i, 1], 1),
                                round(sf.P1[i, 0], 1), round(sf.P1[i, 1], 1), sf.types[i],
                                round(sf.J[i], 4), round(sf.lin[i], 4),
                                round(float(dx), 2), round(float(dy), 2)])
        self.summary.setText(self.summary.text() + f"<br>exported → {d}")
        self.log(f"Strain: exported summary + per-point CSVs to {d}")


def _paired(pairing, e):
    return [i for i, ip in enumerate(pairing.initial.points) if pairing.matches[e][i] is not None]
