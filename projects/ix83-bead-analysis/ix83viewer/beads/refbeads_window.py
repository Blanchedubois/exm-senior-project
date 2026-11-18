"""Reference-bead window: click in-focus single beads to measure the light of one bead.

    python3 -m ix83viewer beads-refs experiments/4Nov26.json
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QMainWindow, QPushButton, QSplitter,
    QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .experiment import Experiment
from .panels import AreaImage
from .refbeads import (
    ANNULUS_GAP_PX, ANNULUS_WIDTH_PX, MAX_RADIUS_PX, MIN_ILLUMINATION, OFF_CENTRE_FRACTION, BeadMeasurement, BeadPick,
    RefStore, measure, radial_profile, snap_to_peak, suggest_radius, summarise,
)

pg.setConfigOptions(imageAxisOrder="row-major")


def _later(fn):
    """Run fn after the current mouse event has finished.  Removing or rebuilding circles while
    Qt is still delivering that event to them crashes PySide6, so every edit goes through here."""
    QTimer.singleShot(0, fn)


def safe_gc(owner) -> None:
    """Turn off automatic garbage collection and collect on a timer from the event loop instead.
    Old circles hold reference cycles; if Python frees them in the middle of a Qt event, the
    process segfaults (seen on 9 Nov: SIGSEGV in QGraphicsItem::itemChange during a click)."""
    from pyqtgraph.util.garbage_collector import GarbageCollector

    owner._garbage_collector = GarbageCollector(interval=1.0)

GOOD_PEN = pg.mkPen("#ffffff", width=1.5)
FLAG_PEN = pg.mkPen("#ff5050", width=1.5)
SELECTED_PEN = pg.mkPen("#ffd000", width=2.5)
EXCLUDING_FLAGS = ("edge", "saturated", "crowded", "faint", "dim-light")
HELP = ("Click a bead to add it (the circle snaps to its peak and sizes itself). Drag a circle to move it, "
        "drag its handle to resize, right-click it to remove. White = used, red = flagged and left out "
        "of the average. Light is corrected for the uneven illumination; outside the dashed line the field "
        "is too dim (< 20% of the centre) to trust. Pick beads at a range of distances from the centre.")


class RefBeadWindow(QMainWindow):
    def __init__(self, exp: Experiment, areas: dict[str, list[AreaImage]], store: RefStore,
                 flat: np.ndarray | None = None):
        super().__init__()
        self.exp, self.store, self.flat = exp, store, flat
        self.areas = {a.folder: a for lst in areas.values() for a in lst}
        self.condition_of = {a.folder: a.condition.key for a in self.areas.values()}
        self.label_of = {c.key: c.label for c in exp.conditions}
        self.measurements: dict[str, list[BeadMeasurement]] = {}
        for folder in self.areas:
            self._remeasure(folder)
        self.folder: str | None = None
        self.rois: list[pg.CircleROI] = []
        self.rings: list = []
        self.selected: int | None = None
        self.setWindowTitle(f"Reference beads · {exp.name}")
        self._build()
        self._fill_tree()
        first = next(iter(self.areas))
        self.show_area(first)
        self.resize(1500, 900)

    # ---- layout ---------------------------------------------------------
    def _build(self):
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Area", "Beads"])
        self.tree.itemClicked.connect(self._tree_clicked)
        self.tree.setColumnWidth(0, 170)

        self.glw = pg.GraphicsLayoutWidget()
        self.vb = self.glw.addViewBox(lockAspect=True, invertY=True)
        self.img_item = pg.ImageItem()
        self.vb.addItem(self.img_item)
        self.hist = pg.HistogramLUTItem()
        self.hist.setImageItem(self.img_item)
        self.hist.gradient.setColorMap(pg.colormap.get("viridis"))
        self.glw.addItem(self.hist)
        self.centre_ring = pg.QtWidgets.QGraphicsEllipseItem()
        pen = QPen(QColor(255, 255, 255, 120))
        pen.setStyle(Qt.DashLine)
        pen.setCosmetic(True)
        self.centre_ring.setPen(pen)
        self.vb.addItem(self.centre_ring)
        self.isocurve = None
        if self.flat is not None:
            self.isocurve = pg.IsocurveItem(data=self.flat, level=MIN_ILLUMINATION,
                                            pen=pg.mkPen((255, 255, 255, 150), width=1, style=Qt.DashLine))
            self.vb.addItem(self.isocurve)
            self.centre_ring.setVisible(False)
        self.glw.scene().sigMouseClicked.connect(self._scene_clicked)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["#", "Corrected light", "Raw light", "Illum.", "r (px)", "Background",
                                              "SNR", "Flags"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._row_selected)
        remove = QPushButton("Remove selected")
        remove.clicked.connect(self._remove_selected)
        refit = QPushButton("Auto radius")
        refit.setToolTip("Re-centre on the peak and size the circle from the bead's profile")
        refit.clicked.connect(self._refit_selected)
        buttons = QHBoxLayout()
        buttons.addWidget(remove)
        buttons.addWidget(refit)

        self.profile = pg.PlotWidget()
        self.profile.setLabel("bottom", "radius (px)")
        self.profile.setLabel("left", "enclosed light (ADU)")
        self.profile.setMinimumHeight(180)
        self.profile_curve = self.profile.plot(pen=pg.mkPen("#3b82f6", width=2))
        self.profile_line = pg.InfiniteLine(angle=90, pen=pg.mkPen("#ffd000", width=1.5))
        self.profile.addItem(self.profile_line)

        self.summary = QTableWidget(0, 5)
        self.summary.setHorizontalHeaderLabels(["Hydrogel", "Beads (areas)", "Mean light", "SD", "SEM"])
        self.summary.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.summary.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.summary.horizontalHeader().setStretchLastSection(True)
        self.summary.verticalHeader().setVisible(False)
        self.table.verticalHeader().setVisible(False)

        right = QWidget()
        rl = QVBoxLayout(right)
        self.area_label = QLabel()
        self.area_label.setWordWrap(True)
        rl.addWidget(self.area_label)
        rl.addWidget(self.table, 3)
        rl.addLayout(buttons)
        rl.addWidget(QLabel("Enclosed light of the selected bead (it should level off inside the circle)"))
        rl.addWidget(self.profile, 2)
        rl.addWidget(QLabel("One bead's light, corrected for illumination (flagged beads left out)"))
        rl.addWidget(self.summary, 2)

        split = QSplitter()
        split.addWidget(self.tree)
        split.addWidget(self.glw)
        split.addWidget(right)
        split.setSizes([260, 800, 440])
        self.setCentralWidget(split)
        self.statusBar().showMessage(HELP)

    def _fill_tree(self):
        self.tree.clear()
        self.tree_items = {}
        for c in self.exp.conditions:
            parent = QTreeWidgetItem([c.label, ""])
            self.tree.addTopLevelItem(parent)
            for folder in c.areas:
                item = QTreeWidgetItem([f"Area {self.areas[folder].ds.name.rep}", ""])
                item.setData(0, Qt.UserRole, folder)
                item.setToolTip(0, folder)
                parent.addChild(item)
                self.tree_items[folder] = item
            parent.setExpanded(True)
        self._update_counts()

    def _update_counts(self):
        for folder, item in self.tree_items.items():
            ms = self.measurements.get(folder, [])
            used = sum(not self._excluded(m) for m in ms)
            item.setText(1, f"{used}" + (f" (+{len(ms) - used} flagged)" if len(ms) > used else ""))

    # ---- area display ----------------------------------------------------
    def _tree_clicked(self, item, _col):
        folder = item.data(0, Qt.UserRole)
        if folder:
            self.show_area(folder)

    def show_area(self, folder: str):
        self.folder = folder
        a = self.areas[folder]
        img = a.image
        self.img_item.setImage(img, autoLevels=False)
        lo, hi = np.percentile(img[::4, ::4], (0.5, 99.8))
        self.hist.setLevels(float(lo), float(hi))
        h, w = img.shape
        rad = OFF_CENTRE_FRACTION * w
        self.centre_ring.setRect(QRectF((w - 1) / 2 - rad, (h - 1) / 2 - rad, 2 * rad, 2 * rad))
        self.vb.autoRange(padding=0.01)
        self.area_label.setText(f"<b>{a.condition.label}</b> · {folder}<br>"
                                f"{a.ds.n_frames} frames × {a.ds.exposure_ms:g} ms, dark-subtracted mean")
        self.tree.setCurrentItem(self.tree_items[folder])
        self.selected = None
        self._redraw()

    def _redraw(self):
        for roi in self.rois:
            self.vb.removeItem(roi)
        for ring in self.rings:
            self.vb.removeItem(ring)
        self._disconnect_rois()
        self.rois, self.rings = [], []
        ms = self.measurements.get(self.folder, [])
        for i, m in enumerate(ms):
            p = m.pick
            pen = SELECTED_PEN if i == self.selected else (FLAG_PEN if self._excluded(m) else GOOD_PEN)
            roi = pg.CircleROI((p.x - p.r, p.y - p.r), (2 * p.r, 2 * p.r), pen=pen, removable=True,
                               movable=True, rotatable=False)
            roi.sigRegionChangeFinished.connect(lambda r, i=i: _later(lambda: self._roi_moved(i, r)))
            roi.sigRemoveRequested.connect(lambda r, i=i: _later(lambda: self.remove_bead(i)))
            roi.sigClicked.connect(lambda r, ev, i=i: self._select(i))
            roi.setAcceptedMouseButtons(Qt.LeftButton)
            self.vb.addItem(roi)
            self.rois.append(roi)
            outer = p.r + ANNULUS_GAP_PX + ANNULUS_WIDTH_PX
            ring = pg.QtWidgets.QGraphicsEllipseItem(p.x - outer, p.y - outer, 2 * outer, 2 * outer)
            rp = QPen(pen.color())
            rp.setStyle(Qt.DotLine)
            rp.setCosmetic(True)
            ring.setPen(rp)
            self.vb.addItem(ring)
            self.rings.append(ring)
        self._fill_table()
        self._fill_summary()
        self._show_profile()
        self._update_counts()

    def _fill_table(self):
        ms = self.measurements.get(self.folder, [])
        self.table.blockSignals(True)
        self.table.setRowCount(len(ms))
        for i, m in enumerate(ms):
            vals = [str(i + 1), f"{m.usable_light:,.0f}" if m.light_corrected is not None else "–",
                    f"{m.light:,.0f}", f"{m.illumination:.2f}" if m.illumination is not None else "–",
                    f"{m.pick.r:.0f}", f"{m.background:.1f}", f"{m.snr:.0f}", ", ".join(m.flags)]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if self._excluded(m):
                    item.setForeground(QColor("#d03030"))
                self.table.setItem(i, col, item)
        if self.selected is not None and self.selected < len(ms):
            self.table.selectRow(self.selected)
        self.table.blockSignals(False)

    def _fill_summary(self):
        s = summarise(self.measurements, self.condition_of, EXCLUDING_FLAGS)
        keys = [c.key for c in self.exp.conditions] + ["all"]
        self.summary.setRowCount(len(keys))
        for r, k in enumerate(keys):
            v = s.get(k)
            label = self.label_of.get(k, "All hydrogels")
            vals = ([label, f"{v.n_beads} ({v.n_areas})", f"{v.mean_light:,.0f}",
                     f"{v.sd_light:,.0f}" if v.n_beads > 1 else "–",
                     f"{v.sem_light:,.0f}" if v.n_beads > 1 else "–"] if v else [label, "0", "–", "–", "–"])
            for col, x in enumerate(vals):
                self.summary.setItem(r, col, QTableWidgetItem(x))

    def _show_profile(self):
        ms = self.measurements.get(self.folder, [])
        if self.selected is None or self.selected >= len(ms):
            self.profile_curve.setData([], [])
            return
        m = ms[self.selected]
        radii, _, cum = radial_profile(self.areas[self.folder].image, m.pick.x, m.pick.y, MAX_RADIUS_PX)
        self.profile_curve.setData(radii, cum)
        self.profile_line.setValue(m.pick.r)

    # ---- editing ---------------------------------------------------------
    def _scene_clicked(self, ev):
        if ev.button() != Qt.LeftButton or ev.double() or self.folder is None:
            return
        if not self.vb.sceneBoundingRect().contains(ev.scenePos()):
            return
        p = self.vb.mapSceneToView(ev.scenePos())
        x, y = p.x(), p.y()
        h, w = self.areas[self.folder].image.shape
        if not (0 <= x < w and 0 <= y < h):
            return
        for i, m in enumerate(self.measurements.get(self.folder, [])):
            if np.hypot(x - m.pick.x, y - m.pick.y) <= m.pick.r:
                self._select(i)
                return
        _later(lambda: self.add_bead_at(x, y))

    def add_bead_at(self, x: float, y: float) -> BeadMeasurement:
        img = self.areas[self.folder].image
        sx, sy = snap_to_peak(img, x, y)
        pick = BeadPick(round(sx, 1), round(sy, 1), suggest_radius(img, sx, sy))
        self.store.add(self.folder, pick)
        self._changed(select=len(self.store.picks[self.folder]) - 1)
        return self.measurements[self.folder][-1]

    def move_bead(self, index: int, x: float, y: float, r: float):
        r = float(np.clip(r, 2, MAX_RADIUS_PX * 2))
        self.store.replace(self.folder, index, BeadPick(round(x, 1), round(y, 1), round(r, 1)))
        self._changed(select=index)

    def remove_bead(self, index: int):
        self.store.remove(self.folder, index)
        self._changed(select=None)

    def _roi_moved(self, index: int, roi):
        pos, size = roi.pos(), roi.size()
        r = (size.x() + size.y()) / 4
        self.move_bead(index, pos.x() + r, pos.y() + r, r)

    def _remove_selected(self):
        if self.selected is not None:
            self.remove_bead(self.selected)

    def _refit_selected(self):
        if self.selected is None:
            return
        img = self.areas[self.folder].image
        p = self.store.picks[self.folder][self.selected]
        sx, sy = snap_to_peak(img, p.x, p.y)
        self.move_bead(self.selected, sx, sy, suggest_radius(img, sx, sy))

    def _select(self, index: int):
        self.selected = index
        for i, roi in enumerate(self.rois):
            m = self.measurements[self.folder][i]
            roi.setPen(SELECTED_PEN if i == index else (FLAG_PEN if self._excluded(m) else GOOD_PEN))
        self.table.blockSignals(True)
        self.table.selectRow(index)
        self.table.blockSignals(False)
        self._show_profile()

    def _row_selected(self):
        rows = self.table.selectionModel().selectedRows()
        if rows:
            self._select(rows[0].row())

    def _changed(self, select: int | None):
        self._remeasure(self.folder)
        self.selected = select
        self.store.save(self.measurements, self.condition_of)
        self._redraw()

    def _remeasure(self, folder: str):
        a = self.areas[folder]
        self.measurements[folder] = [measure(a.image, p, a.saturated_mask, self._illumination(p))
                                     for p in self.store.picks.get(folder, [])]

    def _illumination(self, p: BeadPick) -> float | None:
        if self.flat is None:
            return None
        h, w = self.flat.shape
        return float(self.flat[int(np.clip(round(p.y), 0, h - 1)), int(np.clip(round(p.x), 0, w - 1))])

    def _disconnect_rois(self):
        """Break the signal links so old circles hold no reference to the window (otherwise freeing
        a circle can free the window in the middle of Qt destroying it, and the process crashes)."""
        for roi in self.rois:
            for sig in (roi.sigRegionChangeFinished, roi.sigRemoveRequested, roi.sigClicked):
                try:
                    sig.disconnect()
                except (RuntimeError, TypeError):
                    pass

    def closeEvent(self, ev):
        self._disconnect_rois()
        for roi in self.rois:
            self.vb.removeItem(roi)
        self.rois = []
        try:
            self.glw.scene().sigMouseClicked.disconnect(self._scene_clicked)
        except (RuntimeError, TypeError):
            pass
        super().closeEvent(ev)

    @staticmethod
    def _excluded(m: BeadMeasurement) -> bool:
        return any(f in EXCLUDING_FLAGS for f in m.flags)


def run(exp: Experiment, store_path: str) -> int:
    import sys

    from PySide6.QtWidgets import QApplication

    from .panels import load_area_images

    import os

    from .flatfield import estimate, load, save

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("IX83 Bead Analysis")
    areas = load_area_images(exp)
    flat_tif = os.path.join(os.path.dirname(os.path.abspath(store_path)), "flatfield", "flat.tif")
    if not os.path.exists(flat_tif):
        ff = estimate({a.folder: a.image for lst in areas.values() for a in lst})
        save(ff, os.path.dirname(flat_tif), exp.name)
        print(f"Built the illumination map: {flat_tif}")
    win = RefBeadWindow(exp, areas, RefStore.load(store_path, exp.name), load(flat_tif))
    safe_gc(win)
    win.show()
    code = app.exec()
    win.close()
    win.deleteLater()
    app.processEvents()
    return code
