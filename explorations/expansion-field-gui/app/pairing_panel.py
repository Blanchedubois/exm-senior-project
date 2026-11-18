"""
app.pairing_panel
================
Phase-3 GUI: pair every expansion image to the initial, list the recovered
expansion factors, and show the selected expansion's displacement field.
"""
from __future__ import annotations
from PySide6 import QtWidgets, QtCore, QtGui


class PairingPanel(QtWidgets.QWidget):
    def __init__(self, project, log, show_field, parent=None):
        super().__init__(parent)
        self.project = project
        self.log = log
        self.show_field = show_field           # callback(pairing_result, mode, scale)

        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel("<b>Pairing — initial ↔ expansions</b>"))

        self.b_pair = QtWidgets.QPushButton("Run pairing (all expansions)")
        root.addWidget(self.b_pair)

        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["expansion", "λ", "rot°", "tags", "dots"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        root.addWidget(self.table, 1)

        row = QtWidgets.QHBoxLayout()
        self.mode = QtWidgets.QComboBox(); self.mode.addItems(["full", "residual", "J"])
        row.addWidget(QtWidgets.QLabel("field")); row.addWidget(self.mode)
        root.addLayout(row)
        row2 = QtWidgets.QHBoxLayout()
        self.scale = QtWidgets.QDoubleSpinBox(); self.scale.setRange(0.1, 50.0)
        self.scale.setValue(1.0); self.scale.setSingleStep(0.5)
        row2.addWidget(QtWidgets.QLabel("arrow ×")); row2.addWidget(self.scale)
        self.density = QtWidgets.QSpinBox(); self.density.setRange(1, 50); self.density.setValue(1)
        row2.addWidget(QtWidgets.QLabel("show every")); row2.addWidget(self.density)
        root.addLayout(row2)

        self.chk_heat = QtWidgets.QCheckBox("Magnitude heatmap"); self.chk_heat.setChecked(True)
        root.addWidget(self.chk_heat)

        self.summary = QtWidgets.QLabel("—"); self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        self.b_pair.clicked.connect(self.run)
        self.table.itemSelectionChanged.connect(self._show_selected)
        for w in (self.mode, ):
            w.currentTextChanged.connect(self._show_selected)
        for w in (self.scale, self.density):
            w.valueChanged.connect(self._show_selected)
        self.chk_heat.toggled.connect(self._show_selected)

    def run(self):
        if self.project.initial_path not in self.project.results:
            self.log("Pairing: run 'Run all' (stages 1–5) first."); return
        self.log("Pairing all expansions to the initial…")
        QtWidgets.QApplication.processEvents()
        try:
            self.project.pair_all(progress=lambda p, pr: self.log(
                f"  {pr.expansion_name}: λ={pr.lambda_rel:.3f}, rot={pr.rotation_deg:.2f}°, "
                f"{pr.n_tags} tags + {pr.n_dots} dots, RMS {pr.rms_px:.2f}px"))
        except Exception as e:
            self.log(f"Pairing failed: {e}"); return
        self._fill_table()
        self.log(f"Pairing done. CSVs under {self.project.out_dir}/pairing/")

    def _fill_table(self):
        prs = list(self.project.pairings.values())
        self.table.setRowCount(len(prs))
        self._by_row = prs
        for r, pr in enumerate(prs):
            for c, v in enumerate([pr.expansion_name, f"{pr.lambda_rel:.3f}",
                                   f"{pr.rotation_deg:.2f}", str(pr.n_tags), str(pr.n_dots)]):
                self.table.setItem(r, c, QtWidgets.QTableWidgetItem(v))
        if prs:
            self.table.selectRow(0)

    def _show_selected(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows or not hasattr(self, "_by_row"):
            return
        pr = self._by_row[rows[0].row()]
        s = self.show_field(pr, self.mode.currentText(), self.scale.value(),
                            self.density.value(), self.chk_heat.isChecked())
        if s:
            jtxt = (f"J (areal): median <b>{s['J_median']:.2f}</b> "
                    f"(≈ λ² = {pr.lambda_rel**2:.1f}), max {s['J_max']:.2f}<br>"
                    if "J_median" in s else "")
            self.summary.setText(
                f"λ = <b>{pr.lambda_rel:.3f}</b> &nbsp; paired: <b>{s['n_paired']}</b><br>"
                f"|u| full: median <b>{s['full_median_um']:.2f}</b>, "
                f"max {s['full_max_um']:.2f} µm<br>"
                f"|u| residual: median {s['resid_median_um']:.3f} µm<br>"
                f"{jtxt}"
                f"unpaired: {s['n_unpaired_initial']} init / {s['n_unpaired_expansion']} exp")
