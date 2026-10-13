"""
gui.canvas
==========
The image viewport (pyqtgraph): fast zoom/pan, a straightness reference grid
overlay, a cursor pixel/value readout, and generic overlay helpers.

Ported from the Point-Tracking GUI and trimmed to Stage-1 needs. The generic
overlay helpers (add_points/add_polylines/add_labels/clear_overlays) are kept
even though Stage 1 doesn't use them -- stages 2-4 draw dots, dashes, box quads
and box numbers through exactly these, so porting them now avoids a rewrite.
"""
from __future__ import annotations
import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets, QtCore

pg.setConfigOptions(imageAxisOrder="row-major", background="k", antialias=True)


class ImageCanvas(QtWidgets.QWidget):
    clicked = QtCore.Signal(float, float)          # image-pixel coords, only in pick mode
    cursorMoved = QtCore.Signal(float, float, float)   # x, y, value (NaN if out of bounds)
    tagHovered = QtCore.Signal(str)                # label of the hovered tag point (or "")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.glw = pg.GraphicsLayoutWidget()
        self.view = self.glw.addViewBox(lockAspect=True, invertY=True)
        self.img_item = pg.ImageItem()
        self.view.addItem(self.img_item)
        self._pick = False
        self.view.scene().sigMouseClicked.connect(self._on_scene_click)
        self.view.scene().sigMouseMoved.connect(self._on_scene_move)

        # straightness reference grid (hidden until toggled) -- to judge distortion
        self.grid_item = pg.PlotCurveItem(pen=pg.mkPen((0, 200, 255, 120), width=1),
                                          connect="pairs")
        self.grid_item.setVisible(False)
        self.view.addItem(self.grid_item)

        self._overlays = []          # transient overlay items (points/labels/polys)
        self._extent = None          # (W, H) logical extent in view coords
        self._disp = None            # the array currently displayed (for cursor readout)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.glw)

    def set_extent(self, w: float, h: float):
        """Pin the logical view extent (the rectangle the image occupies) to W x H,
        independent of the displayed array's pixel dimensions. This lets a fast
        low-res *preview* and the sharp full-res image share the exact same
        rectangle, so swapping between them refines blur->sharp with NO jump."""
        self._extent = (float(w), float(h))
        self._build_grid((h, w))          # keep the straightness grid sized to the frame

    def set_image(self, arr: np.ndarray, autolevels=False, levels=None):
        """Display a float/uint image (row-major). The image is stretched to the
        pinned extent (see set_extent), so preview/full swaps never move the view.
        `levels`=(lo,hi) sets an explicit display range; `autolevels` lets
        pyqtgraph pick. One of the two should be used."""
        arr = np.asarray(arr)
        first = self.img_item.image is None
        h, w = arr.shape[:2]
        ext = self._extent or (w, h)
        self.img_item.setImage(arr, autoLevels=autolevels)
        self.img_item.setRect(QtCore.QRectF(0.0, 0.0, ext[0], ext[1]))
        if levels is not None:
            self.img_item.setLevels(levels)
        self._disp = arr
        if first:
            self.view.autoRange(padding=0.02)
            self._build_grid((ext[1], ext[0]))

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

    # ---------------------------------------------------------------- cursor
    def _on_scene_move(self, pos):
        try:
            p = self.view.mapSceneToView(pos)
            x, y = float(p.x()), float(p.y())
        except Exception:
            return
        val = float("nan")
        im = self._disp
        if im is not None:
            ew, eh = self._extent or (im.shape[1], im.shape[0])
            # map view coords (in extent units) -> array index (handles preview scale)
            xi = int(round(x / ew * im.shape[1])) if ew else -1
            yi = int(round(y / eh * im.shape[0])) if eh else -1
            if 0 <= yi < im.shape[0] and 0 <= xi < im.shape[1]:
                px = im[yi, xi]
                val = float(np.mean(px)) if np.ndim(px) else float(px)   # RGB -> mean
        self.cursorMoved.emit(x, y, val)

    # ---------------------------------------------------------------- picking
    def set_pick(self, on: bool):
        self._pick = bool(on)

    def _on_scene_click(self, ev):
        if not self._pick:
            return
        try:
            p = self.view.mapSceneToView(ev.scenePos())
            self.clicked.emit(float(p.x()), float(p.y()))
        except Exception:
            pass

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

    def add_labels(self, xy, texts, color=(0, 255, 120), anchor=(0.5, 1.3), size=None):
        from PySide6 import QtGui
        font = None
        if size:
            font = QtGui.QFont(); font.setPointSize(int(size)); font.setBold(True)
        for (x, y), t in zip(np.asarray(xy, float).reshape(-1, 2), texts):
            item = pg.TextItem(str(t), color=color, anchor=anchor)
            if font is not None:
                item.setFont(font)
            item.setPos(float(x), float(y))
            self._add(item)

    # ------------------------------------------------------------ Stage-2 overlay
    def draw_glyph_grid(self, dots=None, box_quads=None, num_pts=None, letter_pts=None,
                        dash_pts=None, labels_by_state=None, box_numbers=None,
                        show_dots=True):
        """Composite Stage-2 overlay: fine dots (amber), box boundaries (cyan quads),
        fiducial slots (numbers = amber cross, letters = green diamond), on-grid dash
        centres (pink triangles), per-slot glyph labels coloured by state, and box
        numbers at box centres."""
        self.clear_overlays()
        if show_dots and dots is not None and len(dots):
            self.add_points(dots, color=(255, 190, 0), size=3)
        if box_quads:
            self.add_polylines(box_quads, color=(0, 200, 255), width=1)
        if dash_pts is not None and len(dash_pts):
            self.add_points(dash_pts, color=(255, 60, 180), size=8, symbol="t")
        if num_pts is not None and len(num_pts):
            self.add_points(num_pts, color=(255, 200, 40), size=10, symbol="+")
        if letter_pts is not None and len(letter_pts):
            self.add_points(letter_pts, color=(60, 230, 90), size=11, symbol="d")
        if labels_by_state:
            for color, items in labels_by_state:      # [( (r,g,b), [(x,y,text), ...] ), ...]
                if items:
                    self.add_labels([(x, y) for x, y, _t in items],
                                    [t for _x, _y, t in items], color=color)
        if box_numbers:                                # [(x, y, "N"), ...] at box centres
            self.add_labels([(x, y) for x, y, _t in box_numbers],
                            [t for _x, _y, t in box_numbers],
                            color=(255, 230, 0), anchor=(0.5, 0.5), size=12)

    # ------------------------------------------------------------ colorbar
    def show_colorbar(self, cmap, lo, hi, label=""):
        """Show a colour-scale legend beside the image (for heat-map overlays).
        Purely a legend — non-interactive; values are the overlay's display range."""
        self.hide_colorbar()
        self._colorbar = pg.ColorBarItem(values=(float(lo), float(hi)),
                                         colorMap=cmap, interactive=False, width=18)
        if label:
            self._colorbar.getAxis("right").setLabel(label)
        self.glw.addItem(self._colorbar, row=0, col=1)

    def hide_colorbar(self):
        cb = getattr(self, "_colorbar", None)
        if cb is not None:
            try:
                self.glw.removeItem(cb)
            except Exception:
                pass
            self._colorbar = None

    # ------------------------------------------------------------ Stage-4 tags
    def draw_hover_points(self, entries):
        """Hoverable tag markers. `entries` = [(label, x, y, (r,g,b,a), size), ...].
        Hovering a point shows its label in a tooltip and emits tagHovered(label)."""
        if getattr(self, "_tag_scatter", None) is None:
            self._tag_scatter = pg.ScatterPlotItem(pen=None, hoverable=True, hoverSize=15,
                                                   hoverPen=pg.mkPen("w", width=2))
            self._tag_scatter.sigHovered.connect(self._on_tag_hover)
            self._tag_tip = pg.TextItem("", color=(10, 10, 10), anchor=(0.5, 1.5),
                                        fill=pg.mkBrush(255, 235, 120, 235),
                                        border=pg.mkPen(0, 0, 0))
            self._tag_tip.setZValue(200)
            self.view.addItem(self._tag_scatter)
            self.view.addItem(self._tag_tip)
            self._tag_tip.hide()
        self._tag_entries = list(entries)
        if entries:
            xs = np.array([e[1] for e in entries]); ys = np.array([e[2] for e in entries])
            brushes = [pg.mkBrush(*e[3]) for e in entries]
            sizes = [e[4] for e in entries]
            self._tag_scatter.setData(x=xs, y=ys, brush=brushes, size=sizes, pen=None,
                                      data=list(range(len(entries))))
        else:
            self._tag_scatter.clear()
        self._tag_tip.hide()

    def clear_hover_points(self):
        if getattr(self, "_tag_scatter", None) is not None:
            self._tag_scatter.clear()
            self._tag_tip.hide()
        self._tag_entries = []

    def _on_tag_hover(self, _s, pts):
        entries = getattr(self, "_tag_entries", [])
        if len(pts):
            i = pts[0].data()
            if i is not None and 0 <= i < len(entries):
                label, x, y, _b, _sz = entries[i]
                self._tag_tip.setText(label)
                self._tag_tip.setPos(float(x), float(y))
                self._tag_tip.show()
                self.tagHovered.emit(label)
                return
        if getattr(self, "_tag_tip", None) is not None:
            self._tag_tip.hide()
        self.tagHovered.emit("")
