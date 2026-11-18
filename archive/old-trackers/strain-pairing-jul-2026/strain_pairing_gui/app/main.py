"""
app.main
========
Multi-image Pairing & Strain GUI (Phase 1). Add an initial expansion image + a
series of more-expanded images (each labelled with its expansion factor), process
each through the four glyph stages (embedded), and see the per-image point tables.
Pairing (Phase 2) and strain (Phases 3-4) slot in as further tabs.
"""
from __future__ import annotations
from PySide6 import QtWidgets, QtCore   # Qt before OpenCV
import os

import pairkit                          # noqa: F401 — puts the glyph core on sys.path
from pairkit.project import StrainProject
from gridtrack import io as gio
from stageui.workspace import StageWorkspace
from .image_list import ImageList
from .strain_view import StrainView
from .tags_view import TagsView

IMG_FILTER = "Images (*.tif *.tiff *.ome.tif *.png *.jpg);;All files (*)"


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pairing & Strain — glyph markers")
        self.resize(1360, 860)
        self.project = StrainProject()

        self.logbox = QtWidgets.QPlainTextEdit(readOnly=True, maximumBlockCount=1000)
        dock = QtWidgets.QDockWidget("Log", self)
        dock.setWidget(self.logbox)
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea, dock)

        tb = self.addToolBar("main")
        tb.addAction("Add initial image…", self.add_initial)
        tb.addAction("Add expansion images…", self.add_expansions)
        tb.addSeparator()
        tb.addAction("Process all", self.process_all)
        tb.addAction("Reprocess current", self.reprocess_current)
        tb.addAction("Auto-register current", self.auto_register_current)
        tb.addAction("Pair to initial", self.pair_all)
        tb.addAction("Export pairing CSV…", self.export_pairing)
        tb.addAction("Export tagged CSVs…", self.export_tagged)

        self.image_list = ImageList(self.project)

        self.workspace = StageWorkspace(log_fn=self.log)
        self.summary = QtWidgets.QTableWidget(0, 6)
        self.summary.setHorizontalHeaderLabels(
            ["image", "label ×", "registered", "dots", "dashes", "glyphs"])
        self.pairing_tab = QtWidgets.QTableWidget(0, 6)
        self.pairing_tab.setHorizontalHeaderLabels(
            ["expansion ×", "dots", "dashes", "numbers", "letters", "overall %"])
        self.tags_view = TagsView(self.project, self.log)
        self.strain_view = StrainView(self.project, self.log)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self.workspace, "Process (4 stages)")
        self.tabs.addTab(self.summary, "Point tables")
        self.tabs.addTab(self.tags_view, "Tags")
        self.tabs.addTab(self.pairing_tab, "Pairing")
        self.tabs.addTab(self.strain_view, "Strain")

        split = QtWidgets.QSplitter()
        split.addWidget(self.image_list)
        split.addWidget(self.tabs)
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)

        self.image_list.selectedPath.connect(self.show_image)
        self.log("Add an initial image (label its expansion), then expansion images. "
                 "Tune each in the 4 stages, or click Process all.")

    # ---------------------------------------------------------------- actions
    def log(self, msg):
        self.logbox.appendPlainText(str(msg))

    def _ask_label(self, path, default):
        v, ok = QtWidgets.QInputDialog.getDouble(
            self, "Expansion label", f"Expansion factor for {os.path.basename(path)} (×):",
            default, 0.1, 50.0, 2)
        return v if ok else None

    def add_initial(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Initial image", "", IMG_FILTER)
        if not path:
            return
        lab = self._ask_label(path, 1.0)
        if lab is None:
            return
        self.project.set_initial(path, lab)
        self.image_list.refresh()
        self.image_list.setCurrentRow(0)
        self.log(f"initial: {lab:g}×  {os.path.basename(path)}")

    def add_expansions(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Expansion images", "", IMG_FILTER)
        for path in paths:
            lab = self._ask_label(path, 2.0)
            if lab is not None:
                self.project.add_expansion(path, lab)
        self.image_list.refresh()
        self.log(f"added {len(paths)} expansion image(s)")

    def show_image(self, path):
        try:
            img = gio.load_tiff(path)
        except Exception as e:                              # pragma: no cover
            self.log(f"load failed: {e}"); return
        self._current = path
        # point the workspace's anchor store at THIS image's anchors, so clicking
        # "Set box number" in the glyph-grid stage writes per-image into the project
        self.workspace.state.glyph_manual = self.project.anchors(path)
        self.workspace.state.set_raw(path, img)
        self.tabs.setCurrentWidget(self.workspace)
        e = self.project.entry_for(path)
        self.log(f"loaded {e.label:g}× {os.path.basename(path)} — tune the 4 stages. "
                 f"If box numbers are misread (common at high expansion), use Stage 2 "
                 f"'Set box number' on one readable box, then click 'Reprocess current'.")

    def reprocess_current(self):
        """Re-run the shown image headlessly using its interactive deskew + manual
        box anchors, then refresh. Use after fixing a mis-registered high-expansion
        image with a Stage-2 box anchor."""
        path = getattr(self, "_current", None)
        if not path:
            self.log("Select an image first."); return
        c = self.workspace.state.correction
        if abs(getattr(c, "rotate_deg", 0.0)) > 1e-6:       # user set a deskew -> match it
            self.project.corrections[path] = c              # (so anchor nodes line up)
        else:
            self.project.corrections.pop(path, None)        # else let it auto-deskew
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            t = self.project.process_one(path)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self._fill_summary(); self.tags_view.refresh_images()
        boxes = sorted(set(p.box_number for p in t.points if p.type == "dot"))
        self.log(f"reprocessed {os.path.basename(path)}: registered={t.registered}, "
                 f"boxes {boxes}. Re-run 'Pair to initial'.")

    def auto_register_current(self):
        """Register the shown high-expansion image with NO manual anchor, by
        geometrically aligning it to an already-correct lower expansion and
        transferring box numbers (validated to a proper, non-mirrored fit)."""
        path = getattr(self, "_current", None)
        if not path:
            self.log("Select an image first."); return
        if not any(t.registered and self.project.entry_for(p).label
                   < self.project.entry_for(path).label
                   for p, t in self.project.results.items() if self.project.entry_for(p)):
            self.log("Auto-register needs a processed, correctly-registered LOWER "
                     "expansion first. Run 'Process all'."); return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            ok, ref, info = self.project.auto_register(path)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self._fill_summary(); self.tags_view.refresh_images()
        if ok:
            boxes = sorted(set(p.box_number for p in self.project.results[path].points
                               if p.type == "dot"))
            self.log(f"auto-registered {os.path.basename(path)} from the {ref:g}× reference "
                     f"({info['pairs']} matched dots) → boxes {boxes}. Re-run 'Pair to initial'.")
        else:
            self.log(f"auto-register couldn't find a proper alignment for "
                     f"{os.path.basename(path)} (too little overlap). Use Stage-2 "
                     f"'Set box number' + 'Reprocess current'.")

    def process_all(self):
        if not self.project.entries():
            self.log("Add images first."); return
        self.log("Processing all images through the 4 stages (headless)…")
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            self.project.process_all(progress=self._on_processed)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.image_list.refresh()
        self.tags_view.refresh_images()
        self.tabs.setCurrentWidget(self.summary)
        self.log("Done. See Point tables tab (and the Tags tab to inspect each tag).")

    def _on_processed(self, k, n, path, table):
        c = table.counts()
        self.log(f"  [{k}/{n}] {os.path.basename(path)}: registered={table.registered}, "
                 f"{c.get('dot',0)} dots, {c.get('dash',0)} dashes, "
                 f"{c.get('digit',0)+c.get('letter',0)} glyphs")
        self._fill_summary()
        QtWidgets.QApplication.processEvents()

    def pair_all(self):
        try:
            res = self.project.pair()
        except ValueError as e:
            self.log(f"Pairing: {e}"); return
        types = ["dot", "dash", "digit", "letter"]
        init_pts = self.project.results[self.project.initial.path].points
        self.pairing_tab.setRowCount(len(res.expansions))
        for e, t in enumerate(res.expansions):
            per = {ty: [0, 0] for ty in types}
            for i, p in enumerate(init_pts):
                if p.type in per:
                    per[p.type][1] += 1
                    per[p.type][0] += res.matches[e][i] is not None
            vals = [f"{t.label:g}"] + [f"{per[ty][0]}/{per[ty][1]}" for ty in types] \
                + [f"{100 * res.rate(e):.0f}%"]
            for col, v in enumerate(vals):
                self.pairing_tab.setItem(e, col, QtWidgets.QTableWidgetItem(v))
        self.tabs.setCurrentWidget(self.pairing_tab)
        self.strain_view.refresh_combo()
        self.log(f"Paired {len(res.expansions)} expansion(s) to the initial.")

    def export_pairing(self):
        if getattr(self.project, "pairing", None) is None:
            self.log("Pair to initial first."); return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export pairing CSV",
                                                        "pairing.csv", "CSV (*.csv)")
        if path:
            self.project.write_pairing_csv(path)
            self.log(f"pairing CSV -> {path}")

    def export_tagged(self):
        if not self.project.results:
            self.log("Process images first."); return
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Folder for tagged CSVs")
        if d:
            written = self.project.write_tagged_csvs(d)
            self.log(f"tagged CSVs -> {d} ({len(written)} file(s))")

    def _fill_summary(self):
        entries = self.project.entries()
        self.summary.setRowCount(len(entries))
        for r, e in enumerate(entries):
            t = self.project.results.get(e.path)
            c = t.counts() if t else {}
            vals = [os.path.basename(e.path), f"{e.label:g}",
                    "yes" if (t and t.registered) else "—",
                    str(c.get("dot", 0)), str(c.get("dash", 0)),
                    str(c.get("digit", 0) + c.get("letter", 0))]
            for col, v in enumerate(vals):
                self.summary.setItem(r, col, QtWidgets.QTableWidgetItem(v))


def main():
    import sys
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow(); w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
