"""
app.stage3_grid
==============
Stage 3 GUI: map the detected tags onto the grid_metadata.json reference, show
the reference schematic, label IDs on the image, and draw the grid (amber
detected nodes, red predicted-missing nodes). Maths delegated to gridtrack.reference.
"""
from __future__ import annotations
import os
from PySide6 import QtWidgets

from gridtrack import reference
from .reference_panel import ReferencePanel

# default reference: prefer the copy bundled in this standalone app; fall back to
# the shared toolkit metadata if this tree is ever run next to the main project.
_HERE = os.path.dirname(__file__)
DEFAULT_META = next(
    (p for p in (
        os.path.normpath(os.path.join(_HERE, "..", "reference", "grid_metadata.json")),
        os.path.normpath(os.path.join(_HERE, "..", "..", "hydrogel_marker_analysis",
                                      "toolkit", "grid_metadata.json")),
    ) if os.path.exists(p)),
    os.path.normpath(os.path.join(_HERE, "..", "reference", "grid_metadata.json")))


class Stage3Panel(QtWidgets.QWidget):
    def __init__(self, state, canvas, log, parent=None):
        super().__init__(parent)
        self.state = state
        self.canvas = canvas
        self.log = log

        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel("<b>Stage 3 — Map grid</b>"))

        row = QtWidgets.QHBoxLayout()
        self.model = QtWidgets.QComboBox()
        self.model.addItems(["similarity", "affine", "homography"])
        row.addWidget(QtWidgets.QLabel("transform")); row.addWidget(self.model)
        root.addLayout(row)

        row2 = QtWidgets.QHBoxLayout()
        self.thresh = QtWidgets.QDoubleSpinBox()
        self.thresh.setRange(0.5, 20.0); self.thresh.setValue(4.0); self.thresh.setSingleStep(0.5)
        row2.addWidget(QtWidgets.QLabel("RANSAC px")); row2.addWidget(self.thresh)
        root.addLayout(row2)

        self.chk_labels = QtWidgets.QCheckBox("Show ID (i,j) labels")
        self.chk_labels.setChecked(True)
        root.addWidget(self.chk_labels)

        self.b_ref = QtWidgets.QPushButton("Load reference…")
        self.b_map = QtWidgets.QPushButton("Map grid")
        root.addWidget(self.b_ref); root.addWidget(self.b_map)

        self.summary = QtWidgets.QLabel("—"); self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        self.ref_panel = ReferencePanel()
        self.ref_panel.setMinimumHeight(240)
        root.addWidget(self.ref_panel, 1)

        # auto-load the default reference if present
        self._reference = None
        if os.path.exists(DEFAULT_META):
            self._load_reference(DEFAULT_META)

        self.b_ref.clicked.connect(self._pick_reference)
        self.b_map.clicked.connect(self.run)
        self.chk_labels.toggled.connect(self._relabel)

    # ------------------------------------------------------------ param binding
    def set_params(self, transform_model: str, ransac_px: float):
        i = self.model.findText(transform_model)
        if i >= 0:
            self.model.setCurrentIndex(i)
        self.thresh.setValue(ransac_px)

    def read_params(self):
        return self.model.currentText(), self.thresh.value()

    def _load_reference(self, path):
        self._reference = reference.load(path)
        self.state.pipeline.reference = self._reference
        self.ref_panel.set_reference(self._reference)
        self.log(f"Stage 3: reference loaded ({len(self._reference.nodes)} nodes, "
                 f"{len(self._reference.boxes)} boxes) from {os.path.basename(path)}")

    def _pick_reference(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load grid_metadata.json", "", "JSON (*.json)")
        if path:
            self._load_reference(path)

    def run(self):
        det = self.state.pipeline.detection
        if det is None:
            self.log("Stage 3: run Stage 2 (detect & orient) first."); return
        if self._reference is None:
            self.log("Stage 3: load a reference (grid_metadata.json) first."); return
        # detect dots so the few-tag tiers (1/2 markers) can measure the local
        # spacing and region-grow can follow the warp (also refines the global tier)
        from gridtrack import measure
        from gridtrack.types import MeasureParams
        try:
            dots_xy = measure.detect_dots(det.image, MeasureParams())[["x", "y"]].to_numpy()
        except Exception:
            dots_xy = None
        try:
            grid = reference.map_grid(det, self._reference,
                                      model=self.model.currentText(),
                                      ransac_thresh=self.thresh.value(), dots_xy=dots_xy)
        except Exception as e:
            self.log(f"Stage 3: mapping failed — {e}"); return
        if grid.method == "unanchored":
            self.log("Stage 3: no ArUco marker in view — cannot assign absolute IDs.")
        self.state.set_grid(grid)

        self.canvas.set_image(det.image)
        self.canvas.draw_grid(grid, labels=self.chk_labels.isChecked())
        self.ref_panel.set_reference(self._reference, grid)

        n_pred = grid.n_total - grid.n_detected
        lam = "" if grid.lambda_local != grid.lambda_local else \
            f"local expansion λ: <b>{grid.lambda_local:.2f}</b><br>"
        self.summary.setText(
            f"method: <b>{grid.method}</b> ({grid.n_detected} tag"
            f"{'s' if grid.n_detected != 1 else ''} in view)<br>"
            f"{lam}scale: <b>{grid.px_per_um:.2f}</b> px/µm<br>"
            f"fit residual (RMS): {grid.rms_residual_px:.2f} px<br>"
            f"boxes solved: {len(grid.box_homographies)}"
            f"{' (region-grown)' if grid.box_confidence else ''}")
        self.log(f"Stage 3: method={grid.method}, {grid.n_detected} tag(s), "
                 f"λ≈{grid.lambda_local:.2f}, {grid.px_per_um:.2f} px/µm, "
                 f"{len(grid.box_homographies)} boxes solved")

    def _relabel(self, *_):
        grid = self.state.pipeline.grid
        if grid is not None:
            self.canvas.draw_grid(grid, labels=self.chk_labels.isChecked())
