"""
app.reference_panel
==================
Renders the predefined reference grid (grid_metadata.json) as an on-screen
schematic so the user can visually compare it to the detected grid. Optionally
highlights which reference nodes were detected.
"""
from __future__ import annotations
import numpy as np
import pyqtgraph as pg


class ReferencePanel(pg.PlotWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAspectLocked(True)
        self.invertY(True)                          # match image (y down)
        self.setMenuEnabled(False)
        self.setTitle("Reference grid (grid_metadata.json)")
        self.getPlotItem().hideButtons()

    def set_reference(self, ref, grid=None):
        self.clear()
        idpos = {int(n["aruco_id"]): (n["x_um"], n["y_um"]) for n in ref.nodes}

        # box outlines
        segs = []
        for b in ref.boxes:
            c = b["corner_aruco_ids"]
            quad = [idpos[c["tl"]], idpos[c["tr"]], idpos[c["br"]], idpos[c["bl"]]]
            for k in range(4):
                segs += [quad[k], quad[(k + 1) % 4]]
        if segs:
            s = np.array(segs, float)
            self.plot(s[:, 0], s[:, 1], connect="pairs", pen=pg.mkPen((0, 160, 255, 120)))

        # nodes -- green if detected, grey otherwise
        detset = {nd.aruco_id for nd in grid.nodes if nd.status == "detected"} if grid else set()
        for n in ref.nodes:
            i = int(n["aruco_id"])
            on = i in detset if grid else False
            self.plot([n["x_um"]], [n["y_um"]], pen=None, symbol="o", symbolSize=9,
                      symbolBrush=(0, 220, 0) if on else (110, 110, 110))
            t = pg.TextItem(str(i), color=(220, 220, 220) if not grid or on else (110, 110, 110),
                            anchor=(0.5, -0.4))
            t.setPos(n["x_um"], n["y_um"])
            self.addItem(t)
        self.autoRange(padding=0.08)
