"""
app.stage4_points
================
Stage 4 GUI: detect + tag every dot and dash, mark centres (amber matched /
red missing), and export the feature table. Maths delegated to gridtrack.measure.
"""
from __future__ import annotations
import os
from PySide6 import QtWidgets

from gridtrack import measure, io
from gridtrack.types import MeasureParams


class Stage4Panel(QtWidgets.QWidget):
    def __init__(self, state, canvas, log, parent=None):
        super().__init__(parent)
        self.state = state
        self.canvas = canvas
        self.log = log

        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel("<b>Stage 4 — Track points</b>"))

        form = QtWidgets.QFormLayout()
        self.diameter = QtWidgets.QSpinBox(); self.diameter.setRange(3, 25)
        self.diameter.setSingleStep(2); self.diameter.setValue(9)
        self.minmass = QtWidgets.QDoubleSpinBox(); self.minmass.setRange(0, 5000)
        self.minmass.setValue(150); self.minmass.setSingleStep(25)
        self.ecc = QtWidgets.QDoubleSpinBox(); self.ecc.setRange(0.05, 1.0)
        self.ecc.setValue(0.35); self.ecc.setSingleStep(0.05)
        form.addRow("dot diameter (px)", self.diameter)
        form.addRow("min mass", self.minmass)
        form.addRow("max eccentricity", self.ecc)
        root.addLayout(form)

        self.chk_dashes = QtWidgets.QCheckBox("Detect dashes")
        self.chk_dashes.setChecked(True)
        root.addWidget(self.chk_dashes)

        self.b_run = QtWidgets.QPushButton("Detect && track")
        self.b_export = QtWidgets.QPushButton("Export features…")
        self.b_export.setEnabled(False)
        root.addWidget(self.b_run); root.addWidget(self.b_export)

        self.summary = QtWidgets.QLabel("—"); self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        self.table = QtWidgets.QTableView()
        root.addWidget(self.table, 1)

        self.b_run.clicked.connect(self.run)
        self.b_export.clicked.connect(self.export)

    def set_params(self, mp: MeasureParams):
        self.diameter.setValue(int(mp.diameter))
        self.minmass.setValue(float(mp.minmass))
        self.ecc.setValue(float(mp.ecc_max))
        self.chk_dashes.setChecked(bool(mp.detect_dashes))

    def read_params(self):
        return self._params()

    def _params(self):
        return MeasureParams(diameter=self.diameter.value(), minmass=self.minmass.value(),
                             ecc_max=self.ecc.value(), detect_dashes=self.chk_dashes.isChecked())

    def run(self):
        det = self.state.pipeline.detection
        grid = self.state.pipeline.grid
        ref = self.state.pipeline.reference
        if det is None or grid is None or ref is None:
            self.log("Stage 4: run Stages 2 and 3 first."); return
        self.log("Stage 4: detecting… (trackpy)")
        QtWidgets.QApplication.processEvents()
        feats = measure.detect_features(det.image, grid, ref, self._params())
        self.state.set_features(feats)

        self.canvas.set_image(det.image)
        self.canvas.draw_features(feats)
        self._show_table(feats)

        dots = feats[feats["type"] == "dot"]
        nm = int((dots["status"] == "matched").sum())
        nmiss = int((dots["status"] == "predicted_missing").sum())
        ndash = int((feats["type"] == "dash").sum())
        rate = 100.0 * nm / max(nm + nmiss, 1)
        self.summary.setText(
            f"dots matched <b>{nm}</b> / {nm + nmiss} ({rate:.1f}%)<br>"
            f"predicted-missing (out of view / occluded): {nmiss}<br>"
            f"dashes tagged: <b>{ndash}</b><br>"
            f"unmatched detections: {feats.attrs.get('n_dot_unmatched_detections', 0)}")
        self.b_export.setEnabled(True)
        self.log(f"Stage 4: {nm} dots matched ({rate:.1f}%), {ndash} dashes, "
                 f"{nmiss} missing recorded")

    def _show_table(self, feats):
        from PySide6 import QtGui, QtCore
        model = QtGui.QStandardItemModel()
        cols = list(feats.columns)
        model.setHorizontalHeaderLabels(cols)
        for _, row in feats.head(400).iterrows():        # cap view for responsiveness
            items = [QtGui.QStandardItem("" if _is_nan(row[c]) else _fmt(row[c])) for c in cols]
            model.appendRow(items)
        self.table.setModel(model)
        self.table.resizeColumnsToContents()

    def export(self):
        feats = self.state.pipeline.features
        if feats is None:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export features", "features.parquet", "Parquet (*.parquet);;CSV (*.csv)")
        if not path:
            return
        base = os.path.splitext(path)[0]
        try:
            feats.to_parquet(base + ".parquet")
        except Exception as e:
            self.log(f"(parquet failed: {e})")
        feats.to_csv(base + ".csv", index=False)
        # annotated image alongside
        det = self.state.pipeline.detection
        if det is not None:
            self._save_annotated(det.image, feats, base + "_annotated.png")
        self.log(f"Stage 4: exported {base}.parquet/.csv (+ annotated PNG)")

    def _save_annotated(self, img, feats, path):
        import cv2, numpy as np
        vis = cv2.cvtColor(io.to_uint8(img), cv2.COLOR_GRAY2BGR)
        dots = feats[feats["type"] == "dot"]
        for _, r in dots[dots["status"] == "matched"].iterrows():
            cv2.circle(vis, (int(r.img_x_px), int(r.img_y_px)), 2, (0, 190, 255), -1)
        for _, r in feats[feats["type"] == "dash"].iterrows():
            cv2.drawMarker(vis, (int(r.img_x_px), int(r.img_y_px)), (0, 140, 255),
                           cv2.MARKER_SQUARE, 6, 1)
        cv2.imwrite(path, vis)


def _is_nan(v):
    try:
        return v != v
    except Exception:
        return False


def _fmt(v):
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)
