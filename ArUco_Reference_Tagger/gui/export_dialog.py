"""
gui.export_dialog
=================
The "Export bundle…" dialog (docs/07 §5): output folder, include raw images,
consecutive pairs, extra A <-> B pairs, and a preview of the rows each table
will hold (from a quick build with few bootstrap draws).
"""
from __future__ import annotations
from PySide6 import QtWidgets

from rwtag import export as EX


class ExportDialog(QtWidgets.QDialog):
    def __init__(self, parent, project, preview, folder):
        super().__init__(parent)
        self.setWindowTitle("Export bundle")
        self.resize(620, 560)
        self.preview = preview
        lay = QtWidgets.QVBoxLayout(self)

        row = QtWidgets.QHBoxLayout()
        self.ed_folder = QtWidgets.QLineEdit(folder)
        b = QtWidgets.QPushButton("Browse…"); b.clicked.connect(self._browse)
        row.addWidget(QtWidgets.QLabel("Write into")); row.addWidget(self.ed_folder, 1); row.addWidget(b)
        lay.addLayout(row)
        lay.addWidget(QtWidgets.QLabel(f"Folder name: <b>{preview.name}</b>"))

        self.chk_raw = QtWidgets.QCheckBox("Include the raw TIFFs (copies, can be large)")
        self.chk_cons = QtWidgets.QCheckBox("Also pair each image with the next one (consecutive pairs)")
        self.chk_pq = QtWidgets.QCheckBox("Also write Parquet copies of the tables"); self.chk_pq.setChecked(True)
        for c in (self.chk_raw, self.chk_cons, self.chk_pq):
            lay.addWidget(c)

        grp = QtWidgets.QGroupBox("Extra pairs (reference ↔ compared); every image is paired with the initial already")
        g = QtWidgets.QHBoxLayout(grp)
        acc = [im["image"] for im in preview.manifest["project"]["images"] if im["accepted"]]
        self.cmb_a = QtWidgets.QComboBox(); self.cmb_b = QtWidgets.QComboBox()
        self.cmb_a.addItems(acc); self.cmb_b.addItems(acc)
        if len(acc) > 2:
            self.cmb_a.setCurrentIndex(1); self.cmb_b.setCurrentIndex(2)
        elif len(acc) == 2:
            self.cmb_b.setCurrentIndex(1)
        add = QtWidgets.QPushButton("Add"); add.clicked.connect(self._add_pair)
        self.lst = QtWidgets.QListWidget(); self.lst.setMaximumHeight(70)
        g.addWidget(self.cmb_a); g.addWidget(QtWidgets.QLabel("↔")); g.addWidget(self.cmb_b); g.addWidget(add)
        lay.addWidget(grp); lay.addWidget(self.lst)

        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["table", "rows"])
        self.table.horizontalHeader().setStretchLastSection(True)
        counts = EX.row_counts(preview)
        self.table.setRowCount(len(counts))
        for i, (k, v) in enumerate(counts.items()):
            self.table.setItem(i, 0, QtWidgets.QTableWidgetItem(k))
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(str(v)))
        self.table.resizeColumnsToContents()
        lay.addWidget(self.table, 1)
        rej = preview.rejected
        self.lbl_rej = QtWidgets.QLabel(
            "Rejected (listed in rejected.json, absent from the tables): "
            + (", ".join(f"{r['image']} ({r['reason']})" for r in rej) if rej else "none"))
        self.lbl_rej.setWordWrap(True)
        lay.addWidget(self.lbl_rej)

        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.button(QtWidgets.QDialogButtonBox.Ok).setText("Export")
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _browse(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Export into", self.ed_folder.text())
        if d:
            self.ed_folder.setText(d)

    def _add_pair(self):
        a, b = self.cmb_a.currentText(), self.cmb_b.currentText()
        if a and b and a != b:
            self.lst.addItem(f"{a} ↔ {b}")

    def folder(self):
        return self.ed_folder.text()

    def options(self) -> EX.ExportOptions:
        pairs = [tuple(self.lst.item(i).text().split(" ↔ ")) for i in range(self.lst.count())]
        return EX.ExportOptions(include_raw=self.chk_raw.isChecked(), consecutive_pairs=self.chk_cons.isChecked(),
                                extra_pairs=pairs, parquet=self.chk_pq.isChecked())
