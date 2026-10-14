"""
gui.project_panel
=================
The project sidebar: the ordered list of images (role · label · stage status)
plus project actions. Owns no processing — emits signals the MainWindow acts on.
"""
from __future__ import annotations
from PySide6 import QtWidgets, QtCore


def _status_glyphs(entry):
    s = entry.stage_status()
    return "".join("✓" if x else "·" for x in s)


def _row_text(e):
    mark = "●" if e.role == "initial" else "○"
    role = "initial" if e.role == "initial" else "expanded"
    optics = e.meta.optics_short()
    return (f"{mark} {e.label:g}× {role}" + (f"  ·  {optics}" if optics else "")
            + f"\n    {_status_glyphs(e)}  {e.name[:26]}")


class ProjectSidebar(QtWidgets.QWidget):
    entrySelected = QtCore.Signal(object)     # ImageEntry
    runOne = QtCore.Signal(object)            # ImageEntry
    runAll = QtCore.Signal()
    projectEdited = QtCore.Signal()           # roles/labels/list changed

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self._entries = []

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(QtWidgets.QLabel("<b>Project images</b>"))
        self.listw = QtWidgets.QListWidget()
        self.listw.currentRowChanged.connect(self._on_row)
        lay.addWidget(self.listw, 1)

        self.b_initial = QtWidgets.QPushButton("Set as initial")
        self.b_label = QtWidgets.QPushButton("Edit expected ×…")
        self.b_run = QtWidgets.QPushButton("Run stages 2–4")
        self.b_run_all = QtWidgets.QPushButton("Run all pending")
        self.b_remove = QtWidgets.QPushButton("Remove")
        for b in (self.b_initial, self.b_label, self.b_run, self.b_run_all, self.b_remove):
            lay.addWidget(b)
        for b in (self.b_run, self.b_run_all):                # the ArUco runner lands in port Phase 4
            b.setEnabled(False)
            b.setToolTip("Batch processing arrives with the Filter and Tag stages (port Phase 4).")
        self.hint = QtWidgets.QLabel("● = initial · ✓✓✓✓ = corrected · detected · filtered · tagged")
        self.hint.setStyleSheet("color:#999;"); self.hint.setWordWrap(True)
        lay.addWidget(self.hint)

        self.b_initial.clicked.connect(self._set_initial)
        self.b_label.clicked.connect(self._edit_label)
        self.b_run.clicked.connect(lambda: self.current() and self.runOne.emit(self.current()))
        self.b_run_all.clicked.connect(self.runAll)
        self.b_remove.clicked.connect(self._remove)

    # ---------------------------------------------------------------- helpers
    def current(self):
        r = self.listw.currentRow()
        return self._entries[r] if 0 <= r < len(self._entries) else None

    def refresh(self, keep_selection=True):
        cur = self.current()
        self._entries = sorted(self.project.images, key=lambda e: e.label)
        self.listw.blockSignals(True)
        self.listw.clear()
        for e in self._entries:
            self.listw.addItem(_row_text(e))
        self.listw.blockSignals(False)
        if keep_selection and cur in self._entries:
            self.listw.setCurrentRow(self._entries.index(cur))

    def refresh_status(self):
        """Update only the status glyphs (cheap, keeps selection & signals quiet)."""
        for i, e in enumerate(self._entries):
            item = self.listw.item(i)
            if item is not None:
                item.setText(_row_text(e))

    def select(self, entry):
        if entry in self._entries:
            self.listw.setCurrentRow(self._entries.index(entry))

    # ---------------------------------------------------------------- slots
    def _on_row(self, row):
        if 0 <= row < len(self._entries):
            self.entrySelected.emit(self._entries[row])

    def _set_initial(self):
        e = self.current()
        if e is None:
            return
        self.project.set_initial(e)
        self.refresh()
        self.projectEdited.emit()

    def _edit_label(self):
        e = self.current()
        if e is None:
            return
        v, ok = QtWidgets.QInputDialog.getDouble(
            self, "Expected expansion", f"Expected × for {e.name}:", e.label, 0.1, 100.0, 2)
        if ok:
            e.label = float(v)
            e.meta.set("expansion_expected", e.label, "user")
            e.save_meta()
            self.project.refresh_roles()
            self.refresh()
            self.projectEdited.emit()

    def _remove(self):
        e = self.current()
        if e is None:
            return
        if QtWidgets.QMessageBox.question(
                self, "Remove image", f"Remove {e.name} from the project?") \
                != QtWidgets.QMessageBox.Yes:
            return
        self.project.remove(e)
        self.refresh(keep_selection=False)
        self.projectEdited.emit()
        if self._entries:
            self.listw.setCurrentRow(0)
