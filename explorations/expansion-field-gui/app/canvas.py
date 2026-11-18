"""app.canvas -- minimal pyqtgraph image view + markers overlay."""
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
        self._overlays = []
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.glw)

    def set_image(self, arr):
        first = self.img_item.image is None
        self.img_item.setImage(np.asarray(arr), autoLevels=True)
        if first and arr is not None:
            self.view.autoRange(padding=0.02)

    def clear_overlays(self):
        for it in self._overlays:
            self.view.removeItem(it)
        self._overlays = []

    def show_markers(self, markers_df):
        """tags green, dots amber."""
        self.clear_overlays()
        for typ, color, size in (("dot", (255, 190, 0), 4), ("tag", (0, 220, 0), 9)):
            sub = markers_df[markers_df["type"] == typ]
            if len(sub):
                it = pg.ScatterPlotItem(sub["img_x_px"].to_numpy(), sub["img_y_px"].to_numpy(),
                                        size=size, brush=pg.mkBrush(*color), pen=None)
                self.view.addItem(it); self._overlays.append(it)
