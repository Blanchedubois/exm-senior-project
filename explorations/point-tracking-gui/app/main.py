"""
app.main
========
Standalone Point-Tracking GUI: a thin shell (toolbar + log) around the shared
`stageui.StageWorkspace`. The 5-stage tuner itself lives in `stageui/` so the
expansion app can embed the identical UI.
"""
from __future__ import annotations
from PySide6 import QtWidgets, QtCore   # import Qt before OpenCV (avoids plugin hijack)
import os

from gridtrack import io
from stageui.workspace import StageWorkspace


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Point-Tracking GUI — hydrogel marker grid")
        self.resize(1280, 820)

        # log dock (create early: stage panels call log() in __init__)
        self.logbox = QtWidgets.QPlainTextEdit(readOnly=True, maximumBlockCount=500)
        dock = QtWidgets.QDockWidget("Log", self)
        dock.setWidget(self.logbox)
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea, dock)

        tb = self.addToolBar("main")
        tb.addAction("Open TIFF…", self.open_tiff)
        tb.addAction("Save session…", self.save_session)
        tb.addSeparator()

        self.workspace = StageWorkspace(log_fn=self.log)
        self.state = self.workspace.state
        self.setCentralWidget(self.workspace)
        self.log("Ready. Open a TIFF to begin (Stage 1).")

    # ---------------------------------------------------------------- actions
    def log(self, msg: str):
        self.logbox.appendPlainText(str(msg))

    def open_tiff(self, *_):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open image", "", "Images (*.tif *.tiff *.png *.jpg);;All files (*)")
        if not path:
            return
        try:
            img = io.load_tiff(path)
        except Exception as e:                       # pragma: no cover
            QtWidgets.QMessageBox.critical(self, "Load failed", str(e)); return
        self.state.set_raw(path, img)
        self.log(f"loaded {os.path.basename(path)}  {img.shape[1]}x{img.shape[0]}  "
                 f"[{img.min():.0f}, {img.max():.0f}]")

    def save_session(self, *_):
        if self.state.pipeline.source_path is None:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save session", "session.json",
                                                        "JSON (*.json)")
        if path:
            io.save_session(path, self.state.pipeline.source_path, self.state.correction)
            self.log(f"saved session -> {os.path.basename(path)}")


def main():
    import sys
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
