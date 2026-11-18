"""app.worker -- run the (slow) per-image batch off the GUI thread."""
from __future__ import annotations
from PySide6 import QtCore


class BatchWorker(QtCore.QThread):
    progressed = QtCore.Signal(int, int, str)     # k, n, path (result is in project.results[path])
    done = QtCore.Signal()
    failed = QtCore.Signal(str)

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project

    def run(self):
        try:
            self.project.process_all(
                progress=lambda k, n, p, r: self.progressed.emit(k, n, p))
            self.done.emit()
        except Exception as e:                        # pragma: no cover
            self.failed.emit(str(e))
