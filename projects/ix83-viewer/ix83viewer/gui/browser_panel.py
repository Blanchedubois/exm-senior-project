"""Left panel: acquisitions grouped by field of view."""

from __future__ import annotations

import html

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QMenu, QTreeWidget, QTreeWidgetItem

from ..core.checks import make_thumbnail
from ..core.display import DEFAULT_PRESET, wavelength_color
from ..core.projection import cache_dir
from ..io.mm_dataset import MMDataset
from ..io.scan import FovSet, ScanResult, group_by_position

DS_ROLE = Qt.UserRole
SET_ROLE = Qt.UserRole + 1


class _ThumbWorker(QThread):
    """Renders frame-0 thumbnails one by one in the background."""
    ready = Signal(str, str)  # folder, png path

    def __init__(self, jobs):
        super().__init__()
        self.jobs = jobs  # [(MMDataset, colour)]

    def run(self):
        for ds, color in self.jobs:
            if self.isInterruptionRequested():
                return
            try:
                self.ready.emit(ds.folder, make_thumbnail(ds, cache_dir(), color))
            except Exception:  # a thumbnail is never worth an error dialog
                pass


def _swatch(rgb) -> QIcon:
    pm = QPixmap(12, 12)
    pm.fill(QColor.fromRgbF(*rgb))
    return QIcon(pm)


class BrowserPanel(QTreeWidget):
    """Click an acquisition -> dataset_selected; click a Set header -> set_selected.
    Select several acquisitions and right-click -> Show side by side."""

    dataset_selected = Signal(object)  # MMDataset
    set_selected = Signal(object)  # FovSet

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels(["Acquisition", "Frames", "Exp."])
        self.setColumnWidth(0, 270)
        self.setColumnWidth(1, 50)
        self.setUniformRowHeights(True)
        self.color_preset = DEFAULT_PRESET
        self._extra: list[MMDataset] = []
        self._scan: ScanResult | None = None
        self._thumbs: dict[str, str] = {}  # folder -> thumbnail png
        self._thumb_worker: _ThumbWorker | None = None
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.currentItemChanged.connect(self._on_current)

    def set_scan(self, scan: ScanResult):
        self._scan = scan
        self._extra = []
        self._rebuild()

    def add_dataset(self, ds: MMDataset):
        if all(d.folder != ds.folder for d in self._all()):
            self._extra.append(ds)
            self._rebuild()
        self.select(ds.folder)

    def set_color_preset(self, preset: str):
        if preset != self.color_preset:
            self._thumbs = {}  # thumbnails are tinted with the preset colour
        self.color_preset = preset
        self._rebuild()

    def select(self, folder: str):
        it = self._find(folder)
        if it:
            self.setCurrentItem(it)

    def datasets(self) -> list[MMDataset]:
        return self._all()

    # ---- internals -----------------------------------------------------
    def _all(self) -> list[MMDataset]:
        return (self._scan.datasets if self._scan else []) + self._extra

    def _rebuild(self):
        current = self.currentItem().data(0, DS_ROLE) if self.currentItem() else None
        self.blockSignals(True)
        self.clear()
        if self._scan:
            for s in group_by_position(self._scan.samples):
                x, y, _ = s.xyz_um
                wl = "/".join(map(str, s.wavelengths))
                top = QTreeWidgetItem([f"Set {s.label}  ·  {wl}  ·  ({x:.0f}, {y:.0f}) µm"])
                top.setData(0, SET_ROLE, s)
                top.setToolTip(0, ("\n".join(s.notes) or "All three wavelengths present")
                               + "\nClick to show side by side")
                if not s.is_complete:
                    top.setForeground(0, QColor("#888"))
                self.addTopLevelItem(top)
                for members in s.by_wavelength().values():
                    for d in members:
                        top.addChild(self._item(d))
                top.setExpanded(True)
            if self._scan.calibrations:
                cal = QTreeWidgetItem(["Calibration"])
                self.addTopLevelItem(cal)
                for d in self._scan.calibrations:
                    cal.addChild(self._item(d))
                cal.setExpanded(True)
        if self._extra:
            other = QTreeWidgetItem(["Added folders"])
            other.setData(0, SET_ROLE, FovSet(label="Added folders", members=list(self._extra)))
            other.setToolTip(0, "Click to show all added folders side by side")
            self.addTopLevelItem(other)
            for d in self._extra:
                other.addChild(self._item(d))
            other.setExpanded(True)
        self.blockSignals(False)
        if current is not None:
            self.select(current.folder)
        self._start_thumbnails()

    def _item(self, d: MMDataset) -> QTreeWidgetItem:
        exp = f"{d.exposure_ms:g} ms" if d.exposure_ms else ""
        it = QTreeWidgetItem([d.label, str(d.n_frames), exp])
        it.setData(0, DS_ROLE, d)
        it.setIcon(0, _swatch(wavelength_color(d.wavelength_nm, self.color_preset)))
        it.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
        if d.warnings:
            it.setForeground(0, QColor("#d08000"))
        it.setToolTip(0, self._tooltip(d))
        return it

    def _tooltip(self, d: MMDataset) -> str:
        parts = [f"<b>{html.escape(d.label)}</b>"]
        parts += [f"<span style='color:#d08000'>⚠ {html.escape(w)}</span>" for w in d.warnings]
        if d.folder in self._thumbs:
            parts.append(f"<img src='{html.escape(self._thumbs[d.folder])}'>")
        return "<br>".join(parts)

    def _start_thumbnails(self):
        if self._thumb_worker is not None and self._thumb_worker.isRunning():
            self._thumb_worker.requestInterruption()
            self._thumb_worker.wait(2000)
        jobs = [(d, wavelength_color(d.wavelength_nm, self.color_preset)) for d in self._all()
                if d.name.kind == "sample" and d.folder not in self._thumbs]
        if jobs:
            self._thumb_worker = _ThumbWorker(jobs)
            self._thumb_worker.ready.connect(self._on_thumb)
            self._thumb_worker.start()

    def _on_thumb(self, folder: str, path: str):
        self._thumbs[folder] = path
        it = self._find(folder)
        if it is not None:
            it.setToolTip(0, self._tooltip(it.data(0, DS_ROLE)))

    def _find(self, folder: str):
        for i in range(self.topLevelItemCount()):
            top = self.topLevelItem(i)
            for j in range(top.childCount()):
                d = top.child(j).data(0, DS_ROLE)
                if d is not None and d.folder == folder:
                    return top.child(j)
        return None

    def _on_current(self, item, _prev):
        if item is None:
            return
        d = item.data(0, DS_ROLE)
        if d is not None:
            self.dataset_selected.emit(d)
        elif item.data(0, SET_ROLE) is not None:
            self.set_selected.emit(item.data(0, SET_ROLE))

    def selected_datasets(self) -> list[MMDataset]:
        out = []
        for it in self.selectedItems():
            d = it.data(0, DS_ROLE)
            if d is not None and d not in out:
                out.append(d)
        return out

    def _context_menu(self, pos):
        chosen = self.selected_datasets()
        if len(chosen) < 2:
            return
        menu = QMenu(self)
        act = QAction(f"Show {len(chosen)} side by side", menu)
        act.triggered.connect(lambda: self.set_selected.emit(FovSet(label="Selection", members=chosen)))
        menu.addAction(act)
        menu.exec(self.viewport().mapToGlobal(pos))
