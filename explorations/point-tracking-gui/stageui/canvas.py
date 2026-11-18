"""
app.canvas
==========
The image viewport (pyqtgraph): fast zoom/pan, a straightness reference grid
overlay, and pixel readout. Overlays for later stages (scatter points, labels,
grid lines) attach to `self.view` the same way.
"""
from __future__ import annotations
import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets

pg.setConfigOptions(imageAxisOrder="row-major", background="k", antialias=True)


class ImageCanvas(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.glw = pg.GraphicsLayoutWidget()
        self.view = self.glw.addViewBox(lockAspect=True, invertY=True)
        self.img_item = pg.ImageItem()
        self.view.addItem(self.img_item)

        # straightness reference grid (hidden until toggled) -- to judge distortion
        self.grid_item = pg.PlotCurveItem(pen=pg.mkPen((0, 200, 255, 120), width=1),
                                          connect="pairs")
        self.grid_item.setVisible(False)
        self.view.addItem(self.grid_item)

        self._overlays = []          # transient overlay items (points/labels/polys)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.glw)

    def set_image(self, arr: np.ndarray, autolevels=True):
        """Display a float/uint image (row-major). Keeps view on first load."""
        first = self.img_item.image is None
        self.img_item.setImage(np.asarray(arr), autoLevels=autolevels)
        if first and arr is not None:
            self.view.autoRange(padding=0.02)
            self._build_grid(arr.shape)

    def _build_grid(self, shape, n=12):
        h, w = shape[:2]
        segs = []
        for i in range(1, n):
            x = w * i / n
            segs += [[x, 0], [x, h]]
            y = h * i / n
            segs += [[0, y], [w, y]]
        pts = np.array(segs, float) if segs else np.zeros((0, 2))
        self.grid_item.setData(pts[:, 0], pts[:, 1])

    def show_grid(self, on: bool):
        self.grid_item.setVisible(on)

    # ---------------------------------------------------------------- overlays
    # Reusable across stages. Coordinates are (x=col, y=row) in image pixels.
    def clear_overlays(self):
        for it in self._overlays:
            self.view.removeItem(it)
        self._overlays = []

    def _add(self, item):
        self.view.addItem(item)
        self._overlays.append(item)
        return item

    def add_points(self, xy, color=(255, 190, 0), size=9, symbol="o"):
        xy = np.asarray(xy, float).reshape(-1, 2)
        if len(xy) == 0:
            return
        self._add(pg.ScatterPlotItem(xy[:, 0], xy[:, 1], size=size, symbol=symbol,
                                     brush=pg.mkBrush(*color), pen=pg.mkPen("k", width=0.5)))

    def add_polylines(self, quads, color=(0, 220, 0), width=2):
        """quads: list of (M,2) point arrays drawn as closed polygons."""
        segs = []
        for q in quads:
            q = np.asarray(q, float)
            for k in range(len(q)):
                segs += [q[k], q[(k + 1) % len(q)]]
        if segs:
            s = np.array(segs, float)
            self._add(pg.PlotCurveItem(s[:, 0], s[:, 1], connect="pairs",
                                       pen=pg.mkPen(color, width=width)))

    def add_labels(self, xy, texts, color=(0, 255, 120), anchor=(0.5, 1.3)):
        for (x, y), t in zip(np.asarray(xy, float).reshape(-1, 2), texts):
            item = pg.TextItem(str(t), color=color, anchor=anchor)
            item.setPos(float(x), float(y))
            self._add(item)

    def draw_detection(self, corners: dict, centers: dict, ids, labels=True):
        """Green tag quads + amber centres + ID labels."""
        self.clear_overlays()
        ids = [int(i) for i in ids]
        self.add_polylines([corners[i] for i in ids], color=(0, 220, 0), width=2)
        self.add_points([centers[i] for i in ids], color=(255, 190, 0), size=8)
        if labels:
            self.add_labels([centers[i] for i in ids], ids, color=(0, 255, 120))

    def draw_grid(self, grid, labels=True, only_inbounds=True):
        """Grid lines between neighbouring nodes; amber detected nodes, red
        predicted-missing nodes; ID + (i,j) labels on detected nodes."""
        self.clear_overlays()
        h, w = (self.img_item.image.shape[:2] if self.img_item.image is not None
                else (10 ** 9, 10 ** 9))
        by_ij = {(n.node_i, n.node_j): n for n in grid.nodes}

        segs = []
        for n in grid.nodes:
            for di, dj in ((1, 0), (0, 1)):
                m = by_ij.get((n.node_i + di, n.node_j + dj))
                if m is not None:
                    segs += [n.img_xy_px, m.img_xy_px]
        if segs:
            s = np.array(segs, float)
            self._add(pg.PlotCurveItem(s[:, 0], s[:, 1], connect="pairs",
                                       pen=pg.mkPen((0, 180, 255, 140), width=1)))

        det = [n for n in grid.nodes if n.status == "detected"]
        pred = [n for n in grid.nodes if n.status == "predicted"]
        if only_inbounds:
            pred = [n for n in pred if 0 <= n.img_xy_px[0] < w and 0 <= n.img_xy_px[1] < h]
        self.add_points([n.img_xy_px for n in det], color=(255, 190, 0), size=9)
        self.add_points([n.img_xy_px for n in pred], color=(255, 60, 60), size=10, symbol="x")
        if labels:
            self.add_labels([n.img_xy_px for n in det],
                            [f"{n.aruco_id} ({n.node_i},{n.node_j})" for n in det],
                            color=(0, 255, 120))

    def draw_features(self, feats):
        """Amber matched dots, orange dashes, bright-red filtered, faint predicted-
        missing (all clipped to the image)."""
        self.clear_overlays()
        h, w = (self.img_item.image.shape[:2] if self.img_item.image is not None
                else (10 ** 9, 10 ** 9))

        def xy(mask):
            a = feats[mask][["img_x_px", "img_y_px"]].to_numpy()
            if len(a):
                a = a[(a[:, 0] >= 0) & (a[:, 0] < w) & (a[:, 1] >= 0) & (a[:, 1] < h)]
            return a

        dot = feats["type"] == "dot"
        self.add_points(xy(dot & (feats["status"] == "matched")), color=(255, 190, 0), size=5)
        self.add_points(xy(feats["type"] == "dash"), color=(255, 110, 0), size=6, symbol="s")
        self.add_points(xy(dot & (feats["status"] == "filtered")), color=(255, 40, 40),
                        size=8, symbol="o")
        self.add_points(xy(dot & (feats["status"] == "predicted_missing")),
                        color=(150, 50, 50), size=6, symbol="x")
