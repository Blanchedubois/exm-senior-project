"""
gui.field_panel
===============
Phase-D tab (7 · Field): the displacement / strain field of each Expanded image
vs the Initial, from the paired dots in the rigidly-aligned (unscaled) frame.
Vector field (quiver) + heat map (local linear expansion or |displacement|),
toggleable per expanded image; CSV export.
"""
from __future__ import annotations
import os
import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets, QtCore

from rwtag import pairing as PR
from rwtag.refwarp import tagframe as TF
from .widgets import SliderSpin


class FieldPanel(QtWidgets.QWidget):
    def __init__(self, state, canvas, log, project_fn, parent=None):
        super().__init__(parent)
        self.state = state
        self.canvas = canvas
        self.log = log
        self.project_fn = project_fn
        self._field = None
        self._align = None
        self._init_entry = None
        self._exp_entry = None

        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel("<b>7 — Field (displacement &amp; strain)</b>"))
        _intro = QtWidgets.QLabel(
            "<small>Per paired dot: displacement u = aligned expanded − initial (scale "
            "untouched) and the local linear expansion from its neighbours. Drawn over the "
            "initial image.</small>")
        _intro.setWordWrap(True)
        root.addWidget(_intro)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("expanded:"))
        self.expcombo = QtWidgets.QComboBox(); row.addWidget(self.expcombo, 1)
        _rw = QtWidgets.QWidget(); _rw.setLayout(row)
        root.addWidget(_rw)

        vg = QtWidgets.QGroupBox("Vectors"); vl = QtWidgets.QVBoxLayout(vg)
        self.chk_vec = QtWidgets.QCheckBox("Show vector field"); self.chk_vec.setChecked(True)
        self.s_scale = SliderSpin("arrow scale (×)", 0.05, 3.0, 1.0, 0.05, 2)
        self.spin_dec = QtWidgets.QSpinBox(); self.spin_dec.setRange(1, 30); self.spin_dec.setValue(4)
        dec_row = QtWidgets.QHBoxLayout()
        dec_row.addWidget(QtWidgets.QLabel("draw every Nth")); dec_row.addWidget(self.spin_dec)
        _dw = QtWidgets.QWidget(); _dw.setLayout(dec_row)
        for w in (self.chk_vec, self.s_scale, _dw):
            vl.addWidget(w)
        root.addWidget(vg)

        hg = QtWidgets.QGroupBox("Heat map"); hl = QtWidgets.QVBoxLayout(hg)
        self.chk_heat = QtWidgets.QCheckBox("Show heat map"); self.chk_heat.setChecked(True)
        qrow = QtWidgets.QHBoxLayout()
        self.qty = QtWidgets.QComboBox()
        self.qty.addItems(["local linear expansion", "displacement |u| (px)"])
        qrow.addWidget(QtWidgets.QLabel("quantity")); qrow.addWidget(self.qty, 1)
        _qw = QtWidgets.QWidget(); _qw.setLayout(qrow)
        self.s_alpha = SliderSpin("heat opacity", 0.0, 1.0, 0.55, 0.05, 2)
        self.lbl_range = QtWidgets.QLabel("—"); self.lbl_range.setStyleSheet("color:#999;")
        for w in (self.chk_heat, _qw, self.s_alpha, self.lbl_range):
            hl.addWidget(w)
        root.addWidget(hg)

        self.chk_img = QtWidgets.QCheckBox("Show initial image"); self.chk_img.setChecked(True)
        root.addWidget(self.chk_img)

        self.summary = QtWidgets.QLabel("Tag the initial + an expanded image, then open this tab.")
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        self.b_export = QtWidgets.QPushButton("Export field CSV…")
        self.b_export_all = QtWidgets.QPushButton("Export ALL field CSVs…")
        for b in (self.b_export, self.b_export_all):
            b.setEnabled(False)
            root.addWidget(b)
        root.addStretch(1)

        self.expcombo.currentIndexChanged.connect(lambda *_: self._recompute())
        for w in (self.chk_vec, self.chk_heat, self.chk_img):
            w.toggled.connect(lambda *_: self._draw())
        self.qty.currentIndexChanged.connect(lambda *_: self._draw())
        self.s_scale.valueChanged.connect(lambda *_: self._draw())
        self.s_alpha.valueChanged.connect(lambda *_: self._draw())
        self.spin_dec.valueChanged.connect(lambda *_: self._draw())
        self.b_export.clicked.connect(self.export_csv)
        self.b_export_all.clicked.connect(self.export_all)
        self.state.taggingChanged.connect(lambda *_: setattr(self, "_field", None))

    # ---------------------------------------------------------------- data
    def _tagged(self):
        proj = self.project_fn()
        init = proj.initial()
        if init is None or init.pipeline.tagging is None:
            return None, []
        return init, [e for e in proj.expanded() if e.pipeline.tagging is not None]

    def refresh(self):
        init, exp = self._tagged()
        cur = self.expcombo.currentText()
        self.expcombo.blockSignals(True)
        self.expcombo.clear()
        self.expcombo.addItems([f"{e.label:g}×" for e in exp])
        i = self.expcombo.findText(cur)
        if i >= 0:
            self.expcombo.setCurrentIndex(i)
        self.expcombo.blockSignals(False)
        if init is None or not exp:
            self.summary.setText("Tag the initial and ≥1 expanded image first."); return
        self._recompute()

    def _compute_for(self, init, e):
        """(pairs, align, field) for one expanded entry (best common box)."""
        pairs = PR.pair_tags(init.pipeline.tagging.tags, e.pipeline.tagging.tags)
        boxes = PR.common_boxes(pairs)
        if not boxes:
            return None, None, None
        N = boxes[0][0]
        c0 = TF.warped_box_centers(init.pipeline.tagging.warp, None)[N]
        c1 = TF.warped_box_centers(e.pipeline.tagging.warp, None)[N]
        align = PR.rigid_align(pairs, N, c0, c1)
        if not align.get("ok"):
            return pairs, align, None
        return pairs, align, PR.displacement_field(pairs, align)

    def _recompute(self):
        init, exp = self._tagged()
        if init is None or not exp:
            return
        idx = max(0, self.expcombo.currentIndex())
        if idx >= len(exp):
            return
        e = exp[idx]
        self._init_entry, self._exp_entry = init, e
        _pairs, self._align, self._field = self._compute_for(init, e)
        if self._field is None:
            self.summary.setText("No usable field (no common box / alignment failed)."); return
        st = PR.field_stats(self._field)
        expct = e.label / init.label
        self.summary.setText(
            f"<b>{st['n']}</b> paired dots · aligned about <b>B{self._align['box']}</b><br>"
            f"local expansion: <b>{st['lin_mean']:.3f} ± {st['lin_sigma']:.3f}</b> "
            f"(expected {expct:.3f})<br>"
            f"|u|: median {st['umag_median']:.0f}px · p90 {st['umag_p90']:.0f}px")
        for b in (self.b_export, self.b_export_all):
            b.setEnabled(True)
        self.log(f"Field: {init.label:g}×→{e.label:g}× — lin {st['lin_mean']:.3f}"
                 f"±{st['lin_sigma']:.3f} (exp {expct:.3f}), n={st['n']}")
        self._draw()

    # ---------------------------------------------------------------- draw
    def _draw(self, *_):
        f = self._field
        if f is None or self._init_entry is None:
            return
        det = self._init_entry.pipeline.detection
        H, W = det.u8.shape
        self.canvas.set_extent(W, H)
        if self.chk_img.isChecked():
            self.canvas.set_image(det.u8, levels=(0, 255))
        else:
            self.canvas.set_image(np.zeros((8, 8), np.uint8), levels=(0, 255))
        self.canvas.clear_overlays()

        if self.chk_heat.isChecked():
            vals = f["lin"] if self.qty.currentIndex() == 0 else f["umag"]
            grid, (gw, gh) = PR.heat_grid(f["P0"], vals, (H, W))
            ok = np.isfinite(grid)
            if ok.any():
                lo, hi = np.nanpercentile(grid, 2), np.nanpercentile(grid, 98)
                hi = hi if hi > lo else lo + 1e-6
                t = np.clip((grid - lo) / (hi - lo), 0, 1)
                cmap = pg.colormap.get("viridis")
                rgba = cmap.map(t.filled(0) if hasattr(t, "filled") else np.nan_to_num(t),
                                mode="byte").reshape(*grid.shape, 4)
                rgba[..., 3] = np.where(ok, int(self.s_alpha.value() * 255), 0)
                item = pg.ImageItem(rgba)
                item.setRect(QtCore.QRectF(0, 0, gw, gh))
                self.canvas._add(item)
                unit = "" if self.qty.currentIndex() == 0 else " px"
                self.lbl_range.setText(f"heat range: {lo:.3f} → {hi:.3f}{unit} (viridis)")
                self.canvas.show_colorbar(cmap, lo, hi, label=self.qty.currentText())
        else:
            self.lbl_range.setText("—")
            self.canvas.hide_colorbar()

        if self.chk_vec.isChecked():
            dec = max(1, self.spin_dec.value())
            sc = self.s_scale.value()
            P0 = f["P0"][::dec]; U = f["U"][::dec] * sc
            tips = P0 + U
            segs = np.empty((2 * len(P0), 2))
            segs[0::2] = P0; segs[1::2] = tips
            self.canvas._add(pg.PlotCurveItem(segs[:, 0], segs[:, 1], connect="pairs",
                                              pen=pg.mkPen((255, 190, 0, 200), width=1.2)))
            self.canvas.add_points(tips, color=(255, 120, 0), size=4)

    # ---------------------------------------------------------------- export
    def export_csv(self):
        if self._field is None:
            return
        name = f"field_{self._exp_entry.label:g}x.csv"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export field CSV", name,
                                                        "CSV (*.csv)")
        if path:
            PR.write_field_csv(self._field, path, self._init_entry.label,
                               self._exp_entry.label, self._align)
            self.log(f"Field: CSV → {path}")

    def export_all(self):
        init, exp = self._tagged()
        if init is None or not exp:
            return
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Folder for field CSVs")
        if not d:
            return
        n = 0
        for e in exp:
            _p, align, field = self._compute_for(init, e)
            if field is not None:
                PR.write_field_csv(field, os.path.join(d, f"field_{e.label:g}x.csv"),
                                   init.label, e.label, align)
                n += 1
        self.log(f"Field: {n} field CSV(s) → {d}")
