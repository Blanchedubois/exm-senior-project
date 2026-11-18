"""
app.stage2_address
==================
Stage 2 GUI: detect ArUco tags on the corrected image, orient the image upright,
and list the tag numbers. All maths is delegated to gridtrack.address.
"""
from __future__ import annotations
from PySide6 import QtWidgets, QtCore

from gridtrack import address
from gridtrack.types import CorrectionParams

DICT_NAME = "DICT_6X6_1000"


class Stage2Panel(QtWidgets.QWidget):
    def __init__(self, state, canvas, log, parent=None):
        super().__init__(parent)
        self.state = state
        self.canvas = canvas
        self.log = log

        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel("<b>Stage 2 — Address + orient</b>"))

        self.chk_invert = QtWidgets.QCheckBox("Invert (fluorescence: bright tags)")
        self.chk_invert.setChecked(True)
        self.chk_labels = QtWidgets.QCheckBox("Show ID labels")
        self.chk_labels.setChecked(True)
        root.addWidget(self.chk_invert)
        root.addWidget(self.chk_labels)

        self.b_detect = QtWidgets.QPushButton("Detect && orient")
        root.addWidget(self.b_detect)

        self.summary = QtWidgets.QLabel("—")
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        root.addWidget(QtWidgets.QLabel("Detected IDs:"))
        self.id_list = QtWidgets.QListWidget()
        self.id_list.setMaximumHeight(280)
        root.addWidget(self.id_list)
        root.addStretch(1)

        self.b_detect.clicked.connect(self.run)
        self.chk_labels.toggled.connect(self._relabel)

    def run(self):
        img = self.state.working_image()
        if img is None:
            self.log("Stage 2: load an image first."); return
        p = self.state.correction
        p.invert = self.chk_invert.isChecked()
        det = address.detect_and_orient(img, DICT_NAME, p)
        self.state.set_detection(det)

        # show the oriented image + overlays
        self.canvas.set_image(det.image)
        self.canvas.draw_detection(det.corners, det.centers, det.ids,
                                   labels=self.chk_labels.isChecked())

        n = len(det.ids)
        self.summary.setText(
            f"<b>{n}</b> tags decoded<br>"
            f"global rotation removed: <b>{det.theta_deg:+.2f}°</b><br>"
            f"residual tilt (upright check): {det.residual_deg:+.2f}°")
        self.id_list.clear()
        self.id_list.addItems([str(int(i)) for i in det.ids])
        self.log(f"Stage 2: {n} tags decoded; oriented by {det.theta_deg:+.2f}° "
                 f"(residual {det.residual_deg:+.2f}°)")

    def _relabel(self, *_):
        det = self.state.pipeline.detection
        if det is not None:
            self.canvas.draw_detection(det.corners, det.centers, det.ids,
                                       labels=self.chk_labels.isChecked())
