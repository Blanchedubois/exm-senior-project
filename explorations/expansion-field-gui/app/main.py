"""
app.main
========
Expansion-Field GUI (Phase 0-1): add an initial image + expansion images, set the
shared optics correction, and batch-run stages 1-5 (writing per-stage CSVs).
Pairing (Phase 3) and the field view (Phase 4) slot in as further tabs later.
"""
from __future__ import annotations
from PySide6 import QtWidgets, QtCore   # import Qt BEFORE OpenCV (avoids plugin hijack)
import os

import fieldkit  # noqa: F401  (ensures the gridtrack path is set via fieldkit.__init__)
from fieldkit.project import ExpansionProject
from gridtrack import io as gio, correct
from .canvas import ImageCanvas
from .image_list import ImageList
from .setup_panel import SetupPanel
from .pairing_panel import PairingPanel
from .field_view import FieldView
from .verify_view import VerifyView

IMG_FILTER = "Images (*.tif *.tiff *.png *.jpg);;All files (*)"


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Expansion-Field GUI — pair initial ↔ expansions")
        self.resize(1200, 780)
        self.project = ExpansionProject()

        self.logbox = QtWidgets.QPlainTextEdit(readOnly=True, maximumBlockCount=1000)
        dock = QtWidgets.QDockWidget("Log", self)
        dock.setWidget(self.logbox)
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea, dock)

        tb = self.addToolBar("main")
        tb.addAction("Add initial image…", self.add_initial)
        tb.addAction("Add expansion images…", self.add_expansions)
        tb.addAction("Set output dir…", self.set_out_dir)
        tb.addSeparator()
        tb.addAction("Save project…", self.save_project)
        tb.addAction("Open project…", self.open_project)
        tb.addSeparator()

        self.image_list = ImageList(self.project)

        # centre: tabbed view (Image | Verify | Field)
        self.canvas = ImageCanvas()
        self.verify = VerifyView(self.project, self.log, self._cycle_image)
        self.field_view = FieldView()
        self.view_tabs = QtWidgets.QTabWidget()
        self.view_tabs.addTab(self.canvas, "Image")
        self.view_tabs.addTab(self.verify, "Verify")
        self.view_tabs.addTab(self.field_view, "Field")

        # right: tabbed controls (Setup | Pairing)
        self.setup = SetupPanel(self.project, self.log, self._on_processed)
        self.setup.pre_run = self.verify.flush   # capture current image's tuned params
        self.pairing = PairingPanel(self.project, self.log, self._show_field)
        self.ctrl_tabs = QtWidgets.QTabWidget()
        self.ctrl_tabs.addTab(self.setup, "Setup")
        self.ctrl_tabs.addTab(self.pairing, "Pairing")
        self.ctrl_tabs.setMinimumWidth(320)
        # reflect any shared-optics edits made in the Verify tab when Setup is shown
        self.ctrl_tabs.currentChanged.connect(
            lambda i: self.setup.push_from_project() if self.ctrl_tabs.widget(i) is self.setup else None)

        split = QtWidgets.QSplitter()
        split.addWidget(self.image_list)
        split.addWidget(self.view_tabs)
        split.addWidget(self.ctrl_tabs)
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)

        self.image_list.selectedPath.connect(self.show_image)
        self.image_list.selectedPath.connect(self.verify.on_select)
        self.log("Add an initial image, then expansion images. Set an output dir, then Run all.")

    def _cycle_image(self, delta):
        n = self.image_list.count()
        if n:
            self.image_list.setCurrentRow((self.image_list.currentRow() + delta) % n)

    # ---------------------------------------------------------------- actions
    def log(self, msg):
        self.logbox.appendPlainText(str(msg))

    def add_initial(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Initial image", "", IMG_FILTER)
        if path:
            self.project.set_initial(path)
            self.image_list.refresh()
            self.image_list.setCurrentRow(0)              # select -> displays it
            self.view_tabs.setCurrentWidget(self.canvas)  # show the Image tab
            self.show_image(path)
            self.log(f"initial: {os.path.basename(path)}  {self._dims(path)}")

    def add_expansions(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Expansion images", "", IMG_FILTER)
        if paths:
            self.project.add_expansions(paths)
            self.image_list.refresh()
            if self.image_list.currentRow() < 0:
                self.image_list.setCurrentRow(0)
            self.view_tabs.setCurrentWidget(self.canvas)
            self.show_image(paths[0])
            self.log(f"added {len(paths)} expansion image(s)")

    def _dims(self, path):
        try:
            img = gio.load_tiff(path)
            return f"{img.shape[1]}x{img.shape[0]}"
        except Exception:
            return ""

    def set_out_dir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Output directory")
        if d:
            self.project.out_dir = d
            self.setup.refresh()
            self.log(f"output dir: {d}")

    def save_project(self):
        if not self.project.out_dir:
            self.log("Set an output directory first."); return
        self.verify.flush()               # capture current image's tuned per-image params
        self.setup._pull_correction()
        self.project.save_project_json()
        self.log(f"project saved -> {self.project.out_dir}/project.json")

    def open_project(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Open project output directory")
        if not d or not os.path.exists(os.path.join(d, "project.json")):
            if d:
                self.log("no project.json in that directory")
            return
        self.project = ExpansionProject.load_project_json(d)
        # rebind panels to the new project
        self.image_list.project = self.project
        self.setup.project = self.project
        self.pairing.project = self.project
        self.verify.rebind_project(self.project)
        self.setup.push_from_project()
        self.setup.refresh(); self.image_list.refresh()
        self.log(f"project opened from {d} — click 'Run all' to reprocess")

    def show_image(self, path):
        try:
            img = gio.load_tiff(path)
            self.canvas.set_image(gio.to_uint8(correct.apply(img, self.project.correction)))
        except Exception as e:                              # pragma: no cover
            self.log(f"preview failed: {e}"); return
        res = self.project.results.get(path)
        if res is not None:
            self.canvas.set_image(gio.to_uint8(res.detection.image))
            self.canvas.show_markers(res.markers)

    def _on_processed(self, path):
        self.image_list.refresh()

    def _show_field(self, pairing_result, mode, scale, density=1, show_heatmap=True):
        init = self.project.results.get(self.project.initial_path)
        if init is None:
            return None
        summary = self.field_view.set_field(
            gio.to_uint8(init.detection.image), pairing_result.field,
            mode=mode, scale=scale, density=density, show_heatmap=show_heatmap)
        self.view_tabs.setCurrentWidget(self.field_view)
        return summary


def main():
    import sys
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow(); w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
