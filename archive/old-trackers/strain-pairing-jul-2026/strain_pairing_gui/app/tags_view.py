"""
app.tags_view
=============
Tag inspector: pick a processed image and see every canonical tag laid over the
image. Points are coloured by kind; hover a point to read its tag, click a table
row (or a point) to highlight and label it. Filter by box number / kind to cut
the clutter, or toggle labels on all visible points.
"""
from __future__ import annotations
import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets, QtCore

from gridtrack import io as gio, correct
from gridtrack.types import CorrectionParams

pg.setConfigOptions(imageAxisOrder="row-major", background="k", antialias=True)

# per-kind marker colour + size (dots are dense, so kept small & translucent so
# the microscope image stays visible underneath)
KIND_COLOR = {"dot": (255, 190, 0), "dash": (255, 60, 180),
              "digit": (40, 200, 255), "letter": (60, 230, 90)}
KIND_SIZE = {"dot": 4, "dash": 7, "digit": 9, "letter": 9}
KIND_ALPHA = {"dot": 150, "dash": 200, "digit": 220, "letter": 220}
LABEL_CAP = 120          # only paint tag labels when this few are visible (else clutter)


class TagsView(QtWidgets.QWidget):
    def __init__(self, project, log, parent=None):
        super().__init__(parent)
        self.project = project
        self.log = log
        self._pts = []            # tagged PointRecords currently listed
        self._vis = []            # subset actually drawn (after box/kind filter)

        root = QtWidgets.QVBoxLayout(self)
        bar = QtWidgets.QHBoxLayout()
        self.combo = QtWidgets.QComboBox()
        self.boxcombo = QtWidgets.QComboBox()
        self.kindcombo = QtWidgets.QComboBox()
        self.kindcombo.addItems(["all", "dot", "dash", "digit", "letter"])
        self.chk_labels = QtWidgets.QCheckBox("Tag labels")
        self.chk_img = QtWidgets.QCheckBox("Image"); self.chk_img.setChecked(True)
        for lbl, wdg in (("image:", self.combo), ("box:", self.boxcombo),
                         ("kind:", self.kindcombo)):
            bar.addWidget(QtWidgets.QLabel(lbl)); bar.addWidget(wdg)
        bar.addWidget(self.chk_labels); bar.addWidget(self.chk_img)
        bar.addStretch(1)
        self.readout = QtWidgets.QLabel("hover a point to read its tag")
        self.readout.setStyleSheet("color:#8cf; font-weight:bold;")
        bar.addWidget(self.readout)
        root.addLayout(bar)

        self.glw = pg.GraphicsLayoutWidget()
        self.vb = self.glw.addViewBox(lockAspect=True, invertY=True)
        self.img_item = pg.ImageItem(); self.vb.addItem(self.img_item)
        self.scatter = pg.ScatterPlotItem(pen=None, hoverable=True, hoverSize=13,
                                          hoverPen=pg.mkPen("w", width=2))
        self.vb.addItem(self.scatter)
        self.sel = pg.ScatterPlotItem(pen=pg.mkPen("w", width=2), brush=None,
                                      size=20, symbol="o")           # click highlight
        self.vb.addItem(self.sel)
        self._labelitems = []
        self._sellabel = pg.TextItem("", color=(255, 255, 255), anchor=(0.5, 1.4))
        self.vb.addItem(self._sellabel)

        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["tag", "kind", "box", "char", "px"])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 150)

        split = QtWidgets.QSplitter()
        split.addWidget(self.glw); split.addWidget(self.table)
        split.setStretchFactor(0, 3); split.setStretchFactor(1, 1)
        root.addWidget(split, 1)
        self.count = QtWidgets.QLabel("—")
        root.addWidget(self.count)

        self.combo.currentIndexChanged.connect(self._on_image)
        self.boxcombo.currentIndexChanged.connect(self._redraw)
        self.kindcombo.currentIndexChanged.connect(self._redraw)
        self.chk_labels.toggled.connect(self._redraw)
        self.chk_img.toggled.connect(self._redraw)
        self.scatter.sigHovered.connect(self._on_hover)
        self.scatter.sigClicked.connect(self._on_pick)
        self.table.itemSelectionChanged.connect(self._on_row)

    # ------------------------------------------------------------------ data
    def refresh_images(self):
        """Populate the image chooser from the project's processed images."""
        self.combo.blockSignals(True); self.combo.clear()
        self._entries = [e for e in self.project.entries()
                         if e.path in self.project.results]
        for e in self._entries:
            role = "initial" if e.role == "initial" else "exp"
            self.combo.addItem(f"{e.label:g}× ({role})")
        self.combo.blockSignals(False)
        if self._entries:
            self.combo.setCurrentIndex(0)
            self._on_image()

    def _cur_table(self):
        if not getattr(self, "_entries", None):
            return None
        i = self.combo.currentIndex()
        if not (0 <= i < len(self._entries)):
            return None
        return self.project.results.get(self._entries[i].path)

    def _on_image(self, *_):
        t = self._cur_table()
        self._pts = [p for p in (t.points if t else []) if p.tag]
        boxes = sorted(set(p.box_number for p in self._pts))
        self.boxcombo.blockSignals(True); self.boxcombo.clear()
        self.boxcombo.addItem("all")
        for b in boxes:
            self.boxcombo.addItem(str(b))
        self.boxcombo.blockSignals(False)
        self._bg = self._bg_image(t) if t else None
        self._redraw()

    def _bg_image(self, t):
        e = self._entries[self.combo.currentIndex()]
        try:
            img = gio.load_tiff(e.path)
            return gio.to_uint8(correct.apply(img, CorrectionParams(rotate_deg=t.deskew_deg)))
        except Exception:
            return None

    # ------------------------------------------------------------------ draw
    def _filtered(self):
        box = self.boxcombo.currentText()
        kind = self.kindcombo.currentText()
        out = []
        for p in self._pts:
            if box != "all" and str(p.box_number) != box:
                continue
            if kind != "all" and p.type != kind:
                continue
            out.append(p)
        return out

    def _redraw(self, *_):
        self.img_item.setImage(self._bg) if (self.chk_img.isChecked() and
                                             getattr(self, "_bg", None) is not None) \
            else self.img_item.clear()
        self.sel.clear(); self._sellabel.setText("")
        for it in self._labelitems:
            self.vb.removeItem(it)
        self._labelitems = []

        self._vis = self._filtered()
        if self._vis:
            xs = np.array([p.x for p in self._vis]); ys = np.array([p.y for p in self._vis])
            brushes = [pg.mkBrush(*KIND_COLOR.get(p.type, (200, 200, 200)),
                                  KIND_ALPHA.get(p.type, 200)) for p in self._vis]
            sizes = [KIND_SIZE.get(p.type, 6) for p in self._vis]
            self.scatter.setData(x=xs, y=ys, size=sizes, brush=brushes, pen=None,
                                 data=list(range(len(self._vis))))
        else:
            self.scatter.clear()

        # Labels are opt-in and only when sparse — 195 stacked dot tags are an
        # unreadable blob. Hover a point (readout) or click it to read its tag.
        if self.chk_labels.isChecked() and 0 < len(self._vis) <= LABEL_CAP:
            for p in self._vis:
                it = pg.TextItem(p.tag, color=(230, 230, 120), anchor=(0, 1.1))
                it.setPos(p.x, p.y); self.vb.addItem(it); self._labelitems.append(it)
        self.vb.autoRange(padding=0.02)

        self._fill_table()
        note = ("" if not self.chk_labels.isChecked() or len(self._vis) <= LABEL_CAP
                else f"  · labels hidden (> {LABEL_CAP}; filter to a box or zoom)")
        self.count.setText(f"{len(self._vis)} tagged points shown / {len(self._pts)} in image "
                           f"· hover a point to read its tag{note}")

    def _fill_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._vis))
        for r, p in enumerate(self._vis):
            vals = [p.tag, p.type, str(p.box_number), p.char or "",
                    f"{p.x:.0f},{p.y:.0f}"]
            for c, v in enumerate(vals):
                self.table.setItem(r, c, QtWidgets.QTableWidgetItem(v))
        self.table.blockSignals(False)

    # ------------------------------------------------------------------ interaction
    def _highlight(self, idx):
        if not (0 <= idx < len(self._vis)):
            return
        p = self._vis[idx]
        self.sel.setData(x=[p.x], y=[p.y])
        self._sellabel.setText(p.tag); self._sellabel.setPos(p.x, p.y)
        self.readout.setText(p.tag)

    def _on_hover(self, _scatter, points):
        if len(points):
            idx = points[0].data()
            if idx is not None and 0 <= idx < len(self._vis):
                self.readout.setText(self._vis[idx].tag)

    def _on_pick(self, _scatter, points):
        if len(points):
            idx = points[0].data()
            if idx is not None:
                self.table.blockSignals(True)
                self.table.selectRow(idx); self.table.blockSignals(False)
                self._highlight(idx)

    def _on_row(self):
        rows = self.table.selectionModel().selectedRows()
        if rows:
            self._highlight(rows[0].row())
