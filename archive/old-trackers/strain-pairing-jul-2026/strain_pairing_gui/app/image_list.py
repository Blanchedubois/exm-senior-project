"""app.image_list — sidebar of the initial + expansion images with editable labels."""
from __future__ import annotations
import os
from PySide6 import QtWidgets, QtCore


class ImageList(QtWidgets.QListWidget):
    selectedPath = QtCore.Signal(str)
    labelEdited = QtCore.Signal()

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self.setMaximumWidth(260)
        self.currentRowChanged.connect(self._emit)
        self.itemDoubleClicked.connect(self._edit_label)

    def refresh(self):
        self.blockSignals(True)
        self.clear()
        for e in self.project.entries():
            done = e.path in self.project.results
            mark = "✓" if done else "·"
            it = QtWidgets.QListWidgetItem(
                f"{mark} {e.label:g}×  [{e.role}]  {os.path.basename(e.path)}")
            it.setData(QtCore.Qt.UserRole, e.path)
            self.addItem(it)
        self.blockSignals(False)

    def _emit(self, row):
        if 0 <= row < self.count():
            self.selectedPath.emit(self.item(row).data(QtCore.Qt.UserRole))

    def _edit_label(self, item):
        path = item.data(QtCore.Qt.UserRole)
        e = self.project.entry_for(path)
        if e is None:
            return
        val, ok = QtWidgets.QInputDialog.getDouble(
            self, "Expansion label", f"Expansion factor for {os.path.basename(path)} (×):",
            e.label, 0.1, 50.0, 2)
        if ok:
            e.label = val
            if path in self.project.results:
                self.project.results[path].label = val
            self.refresh()
            self.labelEdited.emit()
