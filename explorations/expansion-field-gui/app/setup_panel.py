"""
app.setup_panel
==============
Shared processing setup: the Stage-1 optics correction (same microscope for all
images) + the batch "Run all" that processes every image and writes CSVs.
"""
from __future__ import annotations
import os
from PySide6 import QtWidgets
from .widgets import SliderSpin
from .worker import BatchWorker


class SetupPanel(QtWidgets.QWidget):
    def __init__(self, project, log, on_progress, parent=None):
        super().__init__(parent)
        self.project = project
        self.log = log
        self.on_progress = on_progress
        self.pre_run = None          # optional hook: flush per-image params before batch

        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel("<b>Shared optics correction</b><br>"
                                        "<small>(same microscope for every image)</small>"))
        c = project.correction
        self.s_strength = SliderSpin("vignette strength", 0.0, 1.0, c.vig_strength, 0.01)
        self.s_power = SliderSpin("vignette power", 0.5, 5.0, c.vig_power, 0.05)
        self.s_k1 = SliderSpin("lens k1 (barrel<0)", -0.30, 0.30, c.k1, 0.005, 4)
        self.s_k2 = SliderSpin("lens k2", -0.10, 0.10, c.k2, 0.002, 4)
        for w in (self.s_strength, self.s_power, self.s_k1, self.s_k2):
            root.addWidget(w)

        # --- 2-D FFT low-pass denoise (shared, applied last in Stage 1) ---
        lpbox = QtWidgets.QGroupBox("Low-pass (FFT denoise)")
        lpl = QtWidgets.QVBoxLayout(lpbox)
        self.chk_lp = QtWidgets.QCheckBox("Enable"); self.chk_lp.setChecked(c.lp_enable)
        lpl.addWidget(self.chk_lp)
        self.s_lp_cut = SliderSpin("cut-off (× Nyquist)", 0.02, 1.0, c.lp_cutoff, 0.02, 3)
        lpl.addWidget(self.s_lp_cut)
        row = QtWidgets.QHBoxLayout()
        self.cmb_lp_shape = QtWidgets.QComboBox()
        self.cmb_lp_shape.addItems(["gaussian", "butterworth", "ideal"])
        self.cmb_lp_shape.setCurrentText(c.lp_shape)
        self.spin_lp_order = QtWidgets.QSpinBox(); self.spin_lp_order.setRange(1, 8)
        self.spin_lp_order.setValue(c.lp_order)
        self.spin_lp_order.setEnabled(c.lp_shape == "butterworth")
        row.addWidget(QtWidgets.QLabel("shape")); row.addWidget(self.cmb_lp_shape, 1)
        row.addWidget(QtWidgets.QLabel("order")); row.addWidget(self.spin_lp_order)
        lpl.addLayout(row)
        root.addWidget(lpbox)

        # live write-through: any optics control updates project.correction immediately,
        # so the Verify tab and the batch always read the same shared object
        for s in (self.s_strength, self.s_power, self.s_k1, self.s_k2, self.s_lp_cut):
            s.valueChanged.connect(lambda *_: self._pull_correction())
        self.chk_lp.toggled.connect(lambda *_: self._pull_correction())
        self.cmb_lp_shape.currentTextChanged.connect(self._on_lp_shape)
        self.spin_lp_order.valueChanged.connect(lambda *_: self._pull_correction())

        root.addSpacing(8)
        self.out_label = QtWidgets.QLabel("output: <i>not set</i>")
        self.out_label.setWordWrap(True)
        root.addWidget(self.out_label)

        self.b_run = QtWidgets.QPushButton("Run all (stages 1–5 → CSVs)")
        root.addWidget(self.b_run)
        self.progress = QtWidgets.QProgressBar()
        root.addWidget(self.progress)
        root.addStretch(1)

        self.b_run.clicked.connect(self.run_all)

    def _on_lp_shape(self, name):
        self.spin_lp_order.setEnabled(name == "butterworth")
        self._pull_correction()

    def _pull_correction(self):
        c = self.project.correction
        c.vig_strength = self.s_strength.value()
        c.vig_power = self.s_power.value()
        c.k1 = self.s_k1.value()
        c.k2 = self.s_k2.value()
        c.lp_enable = self.chk_lp.isChecked()
        c.lp_cutoff = self.s_lp_cut.value()
        c.lp_shape = self.cmb_lp_shape.currentText()
        c.lp_order = self.spin_lp_order.value()

    def push_from_project(self):
        """Sync the sliders/controls FROM project.correction (e.g. after the Verify
        tab edited the shared optics, or after Open-project)."""
        c = self.project.correction
        for s, v in ((self.s_strength, c.vig_strength), (self.s_power, c.vig_power),
                     (self.s_k1, c.k1), (self.s_k2, c.k2), (self.s_lp_cut, c.lp_cutoff)):
            s.set_value(v)
        self.chk_lp.blockSignals(True); self.chk_lp.setChecked(c.lp_enable)
        self.chk_lp.blockSignals(False)
        self.cmb_lp_shape.blockSignals(True); self.cmb_lp_shape.setCurrentText(c.lp_shape)
        self.cmb_lp_shape.blockSignals(False)
        self.spin_lp_order.blockSignals(True); self.spin_lp_order.setValue(c.lp_order)
        self.spin_lp_order.blockSignals(False)
        self.spin_lp_order.setEnabled(c.lp_shape == "butterworth")

    def refresh(self):
        self.out_label.setText(f"output: {self.project.out_dir or '<i>not set</i>'}")

    def run_all(self):
        if not self.project.all_paths():
            self.log("Add an initial image (and expansions) first."); return
        if not self.project.out_dir:
            self.log("Set an output directory first (toolbar)."); return
        if self.pre_run:
            self.pre_run()          # flush current Verify image's tuned params
        self._pull_correction()
        self.progress.setRange(0, len(self.project.all_paths())); self.progress.setValue(0)
        self.b_run.setEnabled(False)
        self.log("Running all images…")
        self._worker = BatchWorker(self.project)       # off the GUI thread -> stays responsive
        self._worker.progressed.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, k, n, path):
        res = self.project.results.get(path)
        if res is not None:
            ndots = int((res.markers["type"] == "dot").sum())
            self.log(f"  [{k}/{n}] {os.path.basename(path)}: {res.grid.n_detected} tags, "
                     f"{ndots} dots  ({res.grid.px_per_um:.2f} px/µm)")
        self.progress.setValue(k)
        self.on_progress(path)

    def _on_done(self):
        self.b_run.setEnabled(True)
        self.log(f"Done. CSVs written under {self.project.out_dir}")

    def _on_failed(self, msg):
        self.b_run.setEnabled(True)
        self.log(f"Run failed: {msg}")
