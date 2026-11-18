"""app.image_list -- sidebar listing the initial + expansion images and status."""
from __future__ import annotations
import os
from PySide6 import QtWidgets, QtCore


class ImageList(QtWidgets.QListWidget):
    selectedPath = QtCore.Signal(str)

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self.setMaximumWidth(230)
        self.currentRowChanged.connect(self._emit)

    def refresh(self):
        self.blockSignals(True)
        self.clear()
        for p in self.project.all_paths():
            done = p in self.project.results
            role = "initial" if p == self.project.initial_path else "expansion"
            mark = "✓" if done else "·"
            it = QtWidgets.QListWidgetItem(f"{mark} [{role}] {os.path.basename(p)}")
            it.setData(QtCore.Qt.UserRole, p)
            self.addItem(it)
        self.blockSignals(False)

    def _emit(self, row):
        if 0 <= row < self.count():
            self.selectedPath.emit(self.item(row).data(QtCore.Qt.UserRole))
