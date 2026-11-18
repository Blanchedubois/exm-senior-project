"""
gui.series_panel
================
Tab 8 · Series (new; replaces V1's Summary tab). One thumbnail per accepted
image, each the chosen map of that image against the reference, side by side on
ONE colour scale, so the progression with expansion is visible at a glance.
A visual check of the series, not its analysis.
"""
from __future__ import annotations
import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets, QtCore

from rwtag import pairing as PR
from .compare_common import PairSelector
from .field_panel import compute

STRIP_QUANTITIES = [
    ("|u| after similarity alignment (distortion)", "umag", "px"),
    ("deviation from design (includes print error)", "dev1_mag", "px"),
    ("anisotropy λ1/λ2 − 1", "anisotropy", ""),
    ("local linear expansion ÷ uniform expansion", "lin_rel", ""),
    ("local warping (affine misfit)", "resid_rms", "px"),
]


class SeriesStrip(QtWidgets.QWidget):
    """The thumbnail strip (the tab's 'canvas')."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.glw = pg.GraphicsLayoutWidget()
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.addWidget(self.glw)
        self.views = []

    def show_maps(self, maps, lo, hi, cmap, label):
        """maps = [(title, grid, (W, H), ref_u8 or None)]."""
        self.glw.clear(); self.views = []
        cols = min(3, max(1, len(maps)))
        for i, (title, grid, (gw, gh), u8) in enumerate(maps):
            vb = self.glw.addViewBox(row=2 * (i // cols) + 1, col=i % cols, lockAspect=True, invertY=True)
            self.glw.addLabel(title, row=2 * (i // cols), col=i % cols)
            if u8 is not None:
                bg = pg.ImageItem(u8); bg.setLevels((0, 255)); bg.setRect(QtCore.QRectF(0, 0, gw, gh)); vb.addItem(bg)
            ok = np.isfinite(grid)
            t = np.clip((np.nan_to_num(grid) - lo) / max(hi - lo, 1e-12), 0, 1)
            rgba = cmap.map(t, mode="byte").reshape(*grid.shape, 4)
            rgba[..., 3] = np.where(ok, 230, 0)
            it = pg.ImageItem(rgba); it.setRect(QtCore.QRectF(0, 0, gw, gh)); vb.addItem(it)
            vb.autoRange(padding=0.02)
            self.views.append(vb)
        if maps:
            cb = pg.ColorBarItem(values=(float(lo), float(hi)), colorMap=cmap, interactive=False, width=16)
            cb.getAxis("right").setLabel(label)
            self.glw.addItem(cb, row=1, col=cols, rowspan=max(1, 2 * ((len(maps) - 1) // cols) + 1))


class SeriesPanel(QtWidgets.QWidget):
    def __init__(self, state, strip: SeriesStrip, log, project_fn, design_fn, parent=None):
        super().__init__(parent)
        self.state, self.strip, self.log, self.project_fn, self.design_fn = state, strip, log, project_fn, design_fn
        self._maps = None
        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel("<b>8 — Series</b>"))
        intro = QtWidgets.QLabel("<small>Every accepted image against the reference, one map each, on one colour "
                                 "scale. <i>Deviation from design</i> includes the print's own placement error; "
                                 "the other maps compare with the reference image, which cancels it.</small>")
        intro.setWordWrap(True); root.addWidget(intro)
        self.sel = PairSelector(project_fn, with_compare=False); root.addWidget(self.sel)
        self.cmb_q = QtWidgets.QComboBox(); self.cmb_q.addItems([q[0] for q in STRIP_QUANTITIES])
        root.addWidget(self.cmb_q)
        self.chk_img = QtWidgets.QCheckBox("Reference image underneath"); self.chk_img.setChecked(True)
        root.addWidget(self.chk_img)
        self.b_go = QtWidgets.QPushButton("Compute strip"); root.addWidget(self.b_go)
        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["image ×", "paired dots", "uniform λ ratio", "median", "p90"])
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        root.addWidget(self.table, 1)
        self.b_png = QtWidgets.QPushButton("Export strip PNG…"); self.b_png.setEnabled(False); root.addWidget(self.b_png)
        self.b_go.clicked.connect(self.compute)
        self.cmb_q.currentIndexChanged.connect(lambda *_: self.compute() if self._maps is not None else None)
        self.chk_img.toggled.connect(lambda *_: self.compute() if self._maps is not None else None)
        self.b_png.clicked.connect(self.export_png)

    def refresh(self):
        self.sel.refresh()

    def compute(self):
        ref, design = self.sel.ref(), self.design_fn()
        others = [e for e in self.sel.entries() if e is not ref]
        if ref is None or not others or design is None:
            self.log("Series: tag at least two images."); return None
        label, key, unit = STRIP_QUANTITIES[self.cmb_q.currentIndex()]
        H, W = ref.pipeline.detection.u8.shape
        maps, rows, allv = [], [], []
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            for e in others:
                _p, _a, sim, f = compute(ref, e, design, "similarity")
                if f is None:
                    continue
                v = f["lin"] / sim["expansion"] if key == "lin_rel" else f.get(key)
                if v is None:
                    continue
                grid, ext = PR.heat_grid(f["P0"], v, (H, W))
                maps.append((f"{e.label:g}×", grid, ext, ref.pipeline.detection.u8 if self.chk_img.isChecked() else None))
                fin = v[np.isfinite(v)]; allv.append(fin)
                rows.append((e.label, f["n"], sim["expansion"], np.median(fin) if len(fin) else np.nan,
                             np.percentile(fin, 90) if len(fin) else np.nan))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        if not maps:
            return None
        pooled = np.concatenate(allv)
        lo, hi = np.percentile(pooled, 2), np.percentile(pooled, 98)
        self.strip.show_maps(maps, lo, hi if hi > lo else lo + 1e-6, pg.colormap.get("viridis"),
                             f"{label} ({unit})" if unit else label)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, val in enumerate([f"{r[0]:g}", str(r[1]), f"{r[2]:.4f}", f"{r[3]:.4g}", f"{r[4]:.4g}"]):
                self.table.setItem(i, j, QtWidgets.QTableWidgetItem(val))
        self._maps = maps
        self.b_png.setEnabled(True)
        self.log(f"Series: {len(maps)} map(s) of '{label}' vs {ref.label:g}×, common scale {lo:.4g}–{hi:.4g}")
        return maps

    def export_png(self, path=None):
        if self._maps is None:
            return None
        if path is None:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export strip PNG", "series_strip.png", "PNG (*.png)")
            if not path:
                return None
        from pyqtgraph.exporters import ImageExporter
        ImageExporter(self.strip.glw.ci).export(path)
        self.log(f"Series: PNG → {path}")
        return path
