"""
refwarp.app
===========
Standalone GUI for the reference-warp tagging system. Add a series of expansion
images (each labelled with its factor), Process all (detect -> warp reference ->
tag by proximity, auto-aligning the hard frames), then:
  - Tags tab  : any image with its warped-reference tags overlaid; hover to read a
                tag; filter by box / kind; the image stays visible under translucent marks.
  - Strain tab: measured vs expected expansion per frame (table + trend plot).
Export the wide pairing CSV or per-image tagged CSVs.
"""
from __future__ import annotations
import os
import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets, QtCore

from .session import TagSession
from . import strain as st, io_csv

pg.setConfigOptions(imageAxisOrder="row-major", background="k", antialias=True)

KIND_COLOR = {"dot": (255, 190, 0), "dash": (255, 60, 180),
              "num": (40, 200, 255), "let": (60, 230, 90), "node": (255, 70, 70)}
KIND_SIZE = {"dot": 4, "dash": 7, "num": 9, "let": 9, "node": 10}
KIND_ALPHA = {"dot": 150, "dash": 200, "num": 220, "let": 220, "node": 230}
IMG_FILTER = "Images (*.tif *.tiff *.ome.tif *.png *.jpg);;All files (*)"


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, model_path):
        super().__init__()
        self.setWindowTitle("Reference-Warp Tagging")
        self.resize(1360, 860)
        self.session = TagSession(model_path)

        self.log_box = QtWidgets.QPlainTextEdit(readOnly=True, maximumBlockCount=500)
        dock = QtWidgets.QDockWidget("Log", self)
        dock.setWidget(self.log_box); self.addDockWidget(QtCore.Qt.BottomDockWidgetArea, dock)

        tb = self.addToolBar("main")
        tb.addAction("Add images…", self.add_images)
        tb.addAction("Process all", self.process_all)
        tb.addSeparator()
        tb.addAction("Export pairing CSV…", self.export_pairing)
        tb.addAction("Export tagged CSVs…", self.export_tagged)

        self.image_list = QtWidgets.QListWidget(); self.image_list.setMaximumWidth(220)
        self.image_list.currentRowChanged.connect(lambda *_: (self._draw(), self._draw_grid()))

        # Tags tab
        self.tags_page = QtWidgets.QWidget(); tl = QtWidgets.QVBoxLayout(self.tags_page)
        bar = QtWidgets.QHBoxLayout()
        self.boxcombo = QtWidgets.QComboBox(); self.kindcombo = QtWidgets.QComboBox()
        self.kindcombo.addItems(["all", "dot", "dash", "num", "let", "node"])
        self.chk_img = QtWidgets.QCheckBox("Image"); self.chk_img.setChecked(True)
        for lbl, w in (("box:", self.boxcombo), ("kind:", self.kindcombo)):
            bar.addWidget(QtWidgets.QLabel(lbl)); bar.addWidget(w)
        bar.addWidget(self.chk_img); bar.addStretch(1)
        self.readout = QtWidgets.QLabel("hover a point to read its tag")
        self.readout.setStyleSheet("color:#8cf; font-weight:bold;"); bar.addWidget(self.readout)
        tl.addLayout(bar)
        self.glw = pg.GraphicsLayoutWidget(); self.vb = self.glw.addViewBox(lockAspect=True, invertY=True)
        self.img_item = pg.ImageItem(); self.vb.addItem(self.img_item)
        self.scatter = pg.ScatterPlotItem(pen=None, hoverable=True, hoverSize=15,
                                          hoverPen=pg.mkPen("w", width=2)); self.vb.addItem(self.scatter)
        self.scatter.sigHovered.connect(self._hover)
        self._hovertip = pg.TextItem("", color=(10, 10, 10), anchor=(0.5, 1.5),
                                     fill=pg.mkBrush(255, 235, 120, 235),
                                     border=pg.mkPen(0, 0, 0))
        self._hovertip.setZValue(200); self.vb.addItem(self._hovertip); self._hovertip.hide()
        tl.addWidget(self.glw)
        self.count = QtWidgets.QLabel("—"); tl.addWidget(self.count)
        self.boxcombo.currentIndexChanged.connect(self._draw)
        self.kindcombo.currentIndexChanged.connect(self._draw)
        self.chk_img.toggled.connect(self._draw)

        # Strain tab
        self.strain_page = QtWidgets.QWidget(); sl = QtWidgets.QVBoxLayout(self.strain_page)
        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["exp ×", "measured", "± σ", "expected", "n pairs", "registration"])
        self.table.setMaximumHeight(220); sl.addWidget(self.table)
        self.trend = pg.PlotWidget(title="measured vs expected expansion")
        self.trend.showGrid(x=True, y=True, alpha=0.2)
        self.trend.setLabel("bottom", "expected"); self.trend.setLabel("left", "measured")
        sl.addWidget(self.trend)

        # Grid tab: the warped reference box-grid over the image (the frame the tags live in)
        self.grid_page = QtWidgets.QWidget(); gl = QtWidgets.QVBoxLayout(self.grid_page)
        gbar = QtWidgets.QHBoxLayout()
        self.chk_gimg = QtWidgets.QCheckBox("Image"); self.chk_gimg.setChecked(True)
        self.chk_gdash = QtWidgets.QCheckBox("Detected dashes"); self.chk_gdash.setChecked(True)
        self.chk_glab = QtWidgets.QCheckBox("Box numbers"); self.chk_glab.setChecked(True)
        for w in (self.chk_gimg, self.chk_gdash, self.chk_glab):
            gbar.addWidget(w)
        gbar.addStretch(1); gl.addLayout(gbar)
        self.ggl = pg.GraphicsLayoutWidget()
        self.gvb = self.ggl.addViewBox(lockAspect=True, invertY=True)
        self.gimg = pg.ImageItem(); self.gvb.addItem(self.gimg)
        self.gridlines = pg.PlotCurveItem(pen=pg.mkPen((0, 220, 255), width=1.6), connect="pairs")
        self.gvb.addItem(self.gridlines)
        self.gdash = pg.ScatterPlotItem(pen=None, brush=pg.mkBrush(255, 60, 180, 220), size=6)
        self.gvb.addItem(self.gdash)
        gl.addWidget(self.ggl)
        self._glabels = []
        for w in (self.chk_gimg, self.chk_gdash, self.chk_glab):
            w.toggled.connect(self._draw_grid)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self.grid_page, "Grid")
        self.tabs.addTab(self.tags_page, "Tags")
        self.tabs.addTab(self.strain_page, "Strain")
        self.tabs.currentChanged.connect(lambda *_: (self._draw(), self._draw_grid()))
        split = QtWidgets.QSplitter(); split.addWidget(self.image_list); split.addWidget(self.tabs)
        split.setStretchFactor(1, 1); self.setCentralWidget(split)
        self._vis = []
        self.log("Add expansion images (label each), then Process all.")

    # ---------------------------------------------------------------- helpers
    def log(self, m): self.log_box.appendPlainText(str(m))

    def _frames_ok(self):
        return [f for f in sorted(self.session.frames, key=lambda f: f.label) if f.ok]

    def _cur_frame(self):
        fr = self._frames_ok(); r = self.image_list.currentRow()
        return fr[r] if 0 <= r < len(fr) else None

    # ---------------------------------------------------------------- actions
    def add_images(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Expansion images", "", IMG_FILTER)
        for p in paths:
            v, ok = QtWidgets.QInputDialog.getDouble(
                self, "Expansion factor", f"Factor for {os.path.basename(p)} (×):", 1.5, 0.1, 50, 2)
            if ok:
                self.session.add(p, v)
        self.log(f"added {len(paths)} image(s); total {len(self.session.frames)}")

    def process_all(self):
        if not self.session.frames:
            self.log("Add images first."); return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            self.session.process(progress=lambda k, n, f: self.log(
                f"  [{k}/{n}] {f.label:g}× — {'OK' if f.ok else 'FAILED'} · {f.source} · "
                f"{f.confidence} · {len(f.tags) if f.tags else 0} tags"))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.image_list.clear()
        for f in self._frames_ok():
            self.image_list.addItem(f"{f.label:g}×  ·  {f.source}\n    {f.confidence}")
        if self.image_list.count():
            self.image_list.setCurrentRow(0)
        self._fill_strain()
        self.log("Done. See Tags and Strain tabs.")

    def _fill_strain(self):
        fr = self._frames_ok()
        init = min(fr, key=lambda f: f.label) if fr else None
        rows = [f for f in fr if f is not init]
        self.table.setRowCount(len(rows))
        self.trend.clear()
        xs, ys, er = [1.0], [1.0], [0.0]
        for i, f in enumerate(rows):
            r = st.strain(init.tags, f.tags, init.label, f.label)
            for c, v in enumerate([f"{f.label:g}", f"{r['mean']:.3f}", f"{r['sigma']:.3f}",
                                   f"{r['expected']:.3f}", str(r["n"]),
                                   f"{f.source} · {f.confidence}"]):
                self.table.setItem(i, c, QtWidgets.QTableWidgetItem(v))
            if np.isfinite(r["mean"]):
                xs.append(r["expected"]); ys.append(r["mean"]); er.append(r["sigma"])
        xs, ys, er = np.array(xs), np.array(ys), np.array(er)
        lo, hi = min(xs.min(), ys.min()) * 0.95, max(xs.max(), ys.max()) * 1.05
        self.trend.plot([lo, hi], [lo, hi], pen=pg.mkPen((255, 60, 60), width=2,
                        style=QtCore.Qt.DashLine))
        self.trend.addItem(pg.ErrorBarItem(x=xs, y=ys, height=2 * er, beam=0.01 * (hi - lo),
                           pen=pg.mkPen((0, 200, 255))))
        self.trend.plot(xs, ys, pen=None, symbol="o", symbolSize=9, symbolBrush=(0, 200, 255))

    # ---------------------------------------------------------------- draw
    def _draw_grid(self, *_):
        """Warped reference box-grid (box boundaries + numbers) over the image — the
        frame the tags live in. The grid comes from the dot-fit warp, so it tracks the
        box boundaries (where the dashes are) even when few dashes are detected."""
        from . import warp as W
        f = self._cur_frame()
        if f is None or f.warp is None:
            return
        self.gimg.setImage(f.d["u8"]) if self.chk_gimg.isChecked() else self.gimg.clear()
        D = f.d["dots"]; mg = 12.0 * float(f.d["basis"]["pitch"])   # clip grid to imaged region
        lo, hi = D.min(0) - mg, D.max(0) + mg
        segs = []                                        # warp the 6 V + 6 H grid lines
        for c in range(6):
            for line in ([[c * 150, t] for t in np.linspace(0, 750, 200)],
                         [[t, c * 150] for t in np.linspace(0, 750, 200)]):
                P = W.warp_points(np.array(line, float), f.warp)
                for k in range(len(P) - 1):
                    mid = 0.5 * (P[k] + P[k + 1])
                    if lo[0] <= mid[0] <= hi[0] and lo[1] <= mid[1] <= hi[1]:
                        segs += [P[k], P[k + 1]]
        S = np.array(segs, float).reshape(-1, 2) if segs else np.zeros((0, 2))
        self.gridlines.setData(S[:, 0], S[:, 1])
        dd = f.d.get("dashes")
        if self.chk_gdash.isChecked() and dd is not None and len(dd):
            # show only the dashes that lie ON the grid (within ~1 dot pitch) — at high
            # expansion detect_dashes returns scattered junk that isn't on any boundary.
            from scipy.spatial import cKDTree
            gpts = S.reshape(-1, 2)
            dist, _ = cKDTree(gpts).query(np.asarray(dd, float))
            keep = dd[dist < 1.5 * float(f.d["basis"]["pitch"])]
            self.gdash.setData(keep[:, 0], keep[:, 1]) if len(keep) else self.gdash.clear()
        else:
            self.gdash.clear()
        for it in self._glabels:
            self.gvb.removeItem(it)
        self._glabels = []
        if self.chk_glab.isChecked():
            boxes = sorted(set(int(t.split("|")[1][1:]) for t in f.tags if t.startswith("dot|")))
            for N in boxes:
                col, row = (N - 1) // 5, (N - 1) % 5
                c = W.warp_points(np.array([[(col + 0.5) * 150, (row + 0.5) * 150]]), f.warp)[0]
                it = pg.TextItem(str(N), color=(255, 230, 0), anchor=(0.5, 0.5))
                it.setPos(float(c[0]), float(c[1])); self.gvb.addItem(it); self._glabels.append(it)
        self.gvb.autoRange(padding=0.02)

    def _draw(self, *_):
        f = self._cur_frame()
        if f is None:
            return
        self._hovertip.hide()
        boxes = sorted(set(t.split("|")[1][1:] for t in f.tags if t.startswith("dot|")),
                       key=lambda s: int(s))
        if self.boxcombo.count() != len(boxes) + 1:
            self.boxcombo.blockSignals(True); self.boxcombo.clear()
            self.boxcombo.addItem("all"); self.boxcombo.addItems(boxes)
            self.boxcombo.blockSignals(False)
        self.img_item.setImage(f.d["u8"]) if self.chk_img.isChecked() else self.img_item.clear()
        box = self.boxcombo.currentText(); kind = self.kindcombo.currentText()
        vis = []
        for tag, (x, y) in f.tags.items():
            k = tag.split("|")[0]
            if kind != "all" and k != kind:
                continue
            if box != "all" and not (tag.startswith(f"dot|B{box}|") or tag.startswith(f"num|B{box}|")
                                     or tag.startswith(f"let|B{box}|")):
                continue
            vis.append((tag, x, y, k))
        self._vis = vis
        if vis:
            xs = np.array([v[1] for v in vis]); ys = np.array([v[2] for v in vis])
            br = [pg.mkBrush(*KIND_COLOR.get(v[3], (200, 200, 200)), KIND_ALPHA.get(v[3], 200)) for v in vis]
            sz = [KIND_SIZE.get(v[3], 6) for v in vis]
            self.scatter.setData(x=xs, y=ys, size=sz, brush=br, pen=None, data=list(range(len(vis))))
        else:
            self.scatter.clear()
        self.vb.autoRange(padding=0.02)
        self.count.setText(f"{len(vis)} tags shown / {len(f.tags)} in image · hover to read a tag")

    def _hover(self, _s, pts):
        if len(pts):
            i = pts[0].data()
            if i is not None and 0 <= i < len(self._vis):
                tag, x, y, _k = self._vis[i]
                self.readout.setText(tag)
                self._hovertip.setText(tag); self._hovertip.setPos(float(x), float(y))
                self._hovertip.show()
                return
        self._hovertip.hide()

    def export_pairing(self):
        if not self._frames_ok():
            self.log("Process first."); return
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Pairing CSV", "pairing.csv", "CSV (*.csv)")
        if p:
            io_csv.write_pairing(self.session, p); self.log(f"pairing CSV → {p}")

    def export_tagged(self):
        if not self._frames_ok():
            self.log("Process first."); return
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Folder for tagged CSVs")
        if d:
            for f in self._frames_ok():
                io_csv.write_tagged(f, os.path.join(d, f"{f.label:g}x_tagged.csv"))
            self.log(f"tagged CSVs → {d}")


def main():
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    model = os.path.join(root, "reference", "glyph_knn.yml")
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow(model); w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
