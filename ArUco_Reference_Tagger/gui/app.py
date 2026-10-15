"""
gui.app
=======
ArUco Reference Tagger window. Ported from Reference_Warp_Tagger/gui/app.py and
grown one port phase at a time (docs/00_PORT_OVERVIEW.md):

  Phase 2  project sidebar · tab 1 (Correct optics) · metadata dock · log dock ·
           toolbar (Add images / Save + Open project / Save + Load session /
           Copy to all)
  Phase 3  tab 2 (Detect): ArUco decode, design-driven per-box dots, raw pass;
           auto-deskew from the tags; derived metadata
  Phase 4  tab 3 (Filter, per-box gates) · tab 4 (Tag, acceptance) · the
           sidebar's Run stages 2–4 / Run all pending (series gates)
  Phase 6  tabs 5–8: Pair, Overlay, Field, Series (any two accepted images)
  later    Export bundle

One AppState, one active image at a time. Per-image Stage-1 params live in the
`.rwsession.json` sidecar, per-image metadata in `.rwmeta.json`; both autosave on
selection change and project save.
"""
from __future__ import annotations
from PySide6 import QtWidgets, QtCore, QtGui   # import Qt before OpenCV (avoids plugin hijack)
import os

from rwtag import io
from rwtag import project as PJ
from .state import AppState
from .canvas import ImageCanvas
from .correct_panel import CorrectPanel
from .project_panel import ProjectSidebar
from .meta_panel import MetaPanel
from .detect_panel import DetectPanel
from .filter_panel import FilterPanel
from .tag_panel import TagPanel
from .pair_panel import PairPanel
from .overlay_panel import OverlayPanel
from .field_panel import FieldPanel
from .series_panel import SeriesPanel, SeriesStrip

IMG_FILTER = "Images (*.tif *.tiff *.ome.tif *.png *.jpg);;All files (*)"
IMG_EXTS = io.IMG_EXTS
_HERE = os.path.dirname(os.path.abspath(__file__))
_DUMMY = os.path.normpath(os.path.join(_HERE, "..", "..", "ArUco_Tracker_V2", "dummy"))


def _stage_page(canvas, panel):
    """A stage tab: [ large canvas | scrollable control panel ]."""
    scroll = QtWidgets.QScrollArea(); scroll.setWidgetResizable(True)
    scroll.setWidget(panel)
    scroll.setMinimumWidth(360); scroll.setMaximumWidth(480)
    scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
    split = QtWidgets.QSplitter()
    split.addWidget(canvas); split.addWidget(scroll)
    split.setStretchFactor(0, 1); split.setStretchFactor(1, 0)
    split.setSizes([960, 380])
    return split


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ArUco Reference Tagger")
        self.resize(1480, 900)
        self._open_dir = _DUMMY if os.path.isdir(_DUMMY) else os.path.expanduser("~")

        # log dock first: panels log during init
        self.logbox = QtWidgets.QPlainTextEdit(readOnly=True, maximumBlockCount=1000)
        dock = QtWidgets.QDockWidget("Log", self)
        dock.setObjectName("log"); dock.setWidget(self.logbox)
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea, dock)

        tb = self.addToolBar("main"); tb.setObjectName("toolbar")
        tb.addAction("Add images…", self.add_images)
        tb.addAction("Save project", self.save_project)
        tb.addAction("Open project…", self.open_project)
        tb.addSeparator()
        tb.addAction("Save session…", self.save_session)
        tb.addAction("Load session…", self.load_session)
        tb.addAction("Copy to all…", self.copy_to_all)
        tb.addSeparator()
        tb.addAction("Export bundle…", self.export_bundle_dialog)

        self.state = AppState()
        self.project = PJ.Project()
        self.current_entry = None

        # tab 1 — Stage 1
        self.canvas = ImageCanvas()
        self.panel = CorrectPanel(self.state, self.canvas, self.log)
        # tab 2 — Stage 2 (own canvas so overlays do not bleed into the editor)
        self.canvas2 = ImageCanvas()
        self.detect = DetectPanel(self.state, self.canvas2, self.log, lambda: self.project,
                                  lambda: self.current_entry)
        self.detect.deskewApplied.connect(self._on_deskew)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(_stage_page(self.canvas, self.panel), "1 · Correct optics")
        self.tabs.addTab(_stage_page(self.canvas2, self.detect), "2 · Detect")
        # tabs 3, 4 — Stages 3-4
        self.canvas3 = ImageCanvas()
        self.filter = FilterPanel(self.state, self.canvas3, self.log, lambda: self.detect.design)
        self.canvas4 = ImageCanvas()
        self.tagger = TagPanel(self.state, self.canvas4, self.log, lambda: self.detect.design, lambda: self.project)
        self.tagger.runAllRequested.connect(self.run_all_pending)
        self.tabs.addTab(_stage_page(self.canvas3, self.filter), "3 · Filter")
        self.tabs.addTab(_stage_page(self.canvas4, self.tagger), "4 · Tag")
        # tabs 5–8 — cross-image views (any two accepted images)
        design_fn = lambda: self.detect.design
        self.canvas5 = ImageCanvas(); self.pair = PairPanel(self.state, self.canvas5, self.log, lambda: self.project)
        self.canvas6 = ImageCanvas(); self.overlay = OverlayPanel(self.state, self.canvas6, self.log, lambda: self.project, design_fn)
        self.canvas7 = ImageCanvas(); self.field = FieldPanel(self.state, self.canvas7, self.log, lambda: self.project, design_fn)
        self.strip = SeriesStrip(); self.series = SeriesPanel(self.state, self.strip, self.log, lambda: self.project, design_fn)
        self.tabs.addTab(_stage_page(self.canvas5, self.pair), "5 · Pair")
        self.tabs.addTab(_stage_page(self.canvas6, self.overlay), "6 · Overlay")
        self.tabs.addTab(_stage_page(self.canvas7, self.field), "7 · Field")
        self.tabs.addTab(_stage_page(self.strip, self.series), "8 · Series")
        self.tabs.currentChanged.connect(self._on_tab)
        self.panel.b_deskew.clicked.connect(self.detect.run_deskew)

        # sidebar
        self.sidebar = ProjectSidebar(self.project)
        self.sidebar.setMinimumWidth(200); self.sidebar.setMaximumWidth(280)
        self.sidebar.entrySelected.connect(self.select_entry)
        self.sidebar.projectEdited.connect(self._on_project_edited)
        self.sidebar.runOne.connect(self.run_stages_for)
        self.sidebar.runAll.connect(self.run_all_pending)

        # metadata dock (right)
        self.meta = MetaPanel()
        self.meta_dock = QtWidgets.QDockWidget("Metadata", self)
        self.meta_dock.setObjectName("metadata"); self.meta_dock.setWidget(self.meta)
        self.meta_dock.setMinimumWidth(330)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.meta_dock)
        self.meta.metaEdited.connect(self._on_meta_edited)
        self.meta.applyToAll.connect(self._apply_meta_to_all)

        outer = QtWidgets.QSplitter()
        outer.addWidget(self.sidebar); outer.addWidget(self.tabs)
        outer.setStretchFactor(0, 0); outer.setStretchFactor(1, 1)
        outer.setSizes([220, 1100])
        self.setCentralWidget(outer)
        self.resizeDocks([dock], [130], QtCore.Qt.Vertical)

        self.readout = QtWidgets.QLabel("—")
        self.statusBar().addPermanentWidget(self.readout)
        for c in (self.canvas, self.canvas2, self.canvas3, self.canvas4, self.canvas5, self.canvas6, self.canvas7):
            c.cursorMoved.connect(self._on_cursor)
        for sig in (self.state.featuresChanged, self.state.taggingChanged):
            sig.connect(self.sidebar.refresh_status)
        self.state.correctionChanged.connect(self.sidebar.refresh_status)
        self.state.detectionChanged.connect(self._on_detection)
        self.state.metaChanged.connect(self.meta.refresh)
        self.state.metaChanged.connect(self.detect.show_noise)

        self._install_shortcuts()
        self.log("Ready. Add images to build the project (expansion labels parse from '1.5X…' "
                 "names; metadata auto-fills from the TIFF header where present).")

    # ---------------------------------------------------------------- infra
    def log(self, msg):
        self.logbox.appendPlainText(str(msg))

    def _install_shortcuts(self):
        for key, fn in (("B", lambda: self.panel.chk_before.toggle()),
                        ("G", lambda: self.panel.chk_grid.toggle()),
                        ("R", self.panel._reset)):
            sc = QtGui.QShortcut(QtGui.QKeySequence(key), self)
            sc.activated.connect(fn)

    def _on_cursor(self, x, y, val):
        self.readout.setText("—" if val != val else f"(x={x:.0f}, y={y:.0f})  value={val:.0f}")

    def _on_tab(self, idx):
        if idx == 1:
            self.detect.refresh_base_image()
        elif idx == 2:
            self.filter.refresh_base_image()
        elif idx == 3:
            self.tagger.refresh_base_image()
        elif idx == 4:
            self.pair.refresh()
        elif idx == 5:
            self.overlay.refresh()
        elif idx == 6:
            self.field.refresh()
        elif idx == 7:
            self.series.refresh()

    def _on_detection(self):
        det = self.state.pipeline.detection
        ok = det is not None and det.model is not None and det.model.get("registered", False)
        self.panel.b_deskew.setEnabled(bool(ok))
        self.sidebar.refresh_status()
        self.meta.refresh()

    def _on_deskew(self, deg):
        """Stage 2's auto-deskew wrote a rotation: sync the Stage-1 slider and
        re-render synchronously so the corrected frame is fresh before re-detect."""
        self.panel.s_rot.set_value(deg)
        self.panel.read_correction()
        self.panel._recompute_full()
        if self.current_entry is not None:
            self.current_entry.save_sidecar(self.panel.shared_flags())
        self.log(f"Stage 1 rotation set to {deg:+.2f}° from the ArUco tags.")

    def _on_project_edited(self):
        self.sidebar.refresh_status()
        self.meta.refresh()

    def _on_meta_edited(self, name):
        if self.current_entry is not None and name == "expansion_expected" \
                and self.current_entry.meta.expansion_expected:
            self.current_entry.label = float(self.current_entry.meta.expansion_expected)
            self.project.refresh_roles()
            self.sidebar.refresh()
        self.sidebar.refresh_status()
        self.state.metaChanged.emit()

    def _apply_meta_to_all(self):
        if self.current_entry is None:
            return
        n = self.project.apply_meta_groups_to_all(self.current_entry)
        self.sidebar.refresh_status()
        self.log(f"metadata: optics + camera of {self.current_entry.name} copied to {n} other image(s)")

    # ---------------------------------------------------------------- project
    def add_images(self, *_):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Add images to project", self._open_dir, IMG_FILTER)
        self.add_paths(paths)

    def add_paths(self, paths, ask_label=True):
        """Add image files to the project (also the headless/test entry point)."""
        added = None
        for p in paths:
            if any(os.path.abspath(p) == e.path for e in self.project.images):
                continue
            lab = io.parse_label(p)
            if lab is None:
                if not ask_label:
                    lab = 1.0
                else:
                    lab, ok = QtWidgets.QInputDialog.getDouble(
                        self, "Expected expansion", f"Expected × for {os.path.basename(p)}:",
                        1.0, 0.1, 100.0, 2)
                    if not ok:
                        continue
            added = self.project.add(p, lab)
            self._open_dir = os.path.dirname(p)
            n = len([s for s in added.meta.sources.values() if s == "header"])
            self.log(f"added {added.name}: {lab:g}×, {n} metadata value(s) from the file header")
        if added is None:
            return None
        if not self.project.folder:
            self.project.folder = os.path.dirname(added.path)
        if not self.project.design_folder and self.detect.design is not None:
            self.project.design_folder = self.detect.design.folder
        self.sidebar.refresh()
        self.log(f"project: {len(self.project.images)} image(s); initial = {self.project.initial().label:g}×")
        if self.current_entry is None:
            self.sidebar.select(self.project.initial())
            if self.current_entry is None:                 # offscreen/no-signal fallback
                self.select_entry(self.project.initial())
            self.meta_dock.raise_()
        return added

    def _store_current(self):
        prev = self.current_entry
        if prev is not None and prev.pipeline.raw_image is not None:
            self.panel.read_correction(); self.panel.read_levels()
            prev.save_sidecar(self.panel.shared_flags())
            prev.save_meta()

    def select_entry(self, entry):
        if entry is None or entry is self.current_entry:
            return
        prev = self.current_entry
        self._store_current()
        if prev is not None:
            prev.unload_images()                           # bound memory
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            try:
                entry.ensure_loaded()
            except Exception as e:                         # pragma: no cover
                QtWidgets.QApplication.restoreOverrideCursor()
                QtWidgets.QMessageBox.critical(self, "Load failed", str(e)); return
            self.current_entry = entry
            self.state.activate(entry.pipeline)
            self.panel.sync_from_state()
            self.panel._on_image_loaded()
            self.meta.set_entry(entry)
            self.detect.load_from_state()
            self.filter.load_from_state()
            self.tagger.load_from_state()
            self._on_detection()
            self._on_tab(self.tabs.currentIndex())
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.sidebar.refresh_status()
        img = entry.pipeline.raw_image
        self.log(f"selected {entry.name}  {img.shape[1]}x{img.shape[0]}  "
                 f"[{img.min():.0f}, {img.max():.0f}]  ·  {entry.label:g}× {entry.role}")

    def save_project(self, *_):
        if not self.project.images:
            self.log("Project is empty."); return None
        self._store_current()
        path = self.project.save()
        self.log(f"project saved -> {path}")
        return path

    def open_project(self, *_):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open project", self._open_dir, "Project (*.rwproj.json);;All files (*)")
        if path:
            self.open_project_path(path)

    def open_project_path(self, path):
        self._store_current()
        self.project = PJ.Project.load(path)
        self.current_entry = None
        self.sidebar.project = self.project
        self.sidebar.refresh(keep_selection=False)
        if self.project.design_folder and os.path.exists(self.project.design_folder):
            self.detect.set_design_folder(self.project.design_folder)
        if self.project.settings:
            ap, dp, hp = self.project.stage_params()
            self.detect.set_params(ap); self.filter.set_params(dp, hp)
        self._open_dir = self.project.folder
        self.log(f"project opened: {os.path.basename(path)} · {len(self.project.images)} image(s)")
        if self.project.images:
            self.sidebar.select(self.project.initial())
            if self.current_entry is None:
                self.select_entry(self.project.initial())

    # ---------------------------------------------------------------- batch
    def run_stages_for(self, entry):
        """Stages 2-4 for one image with ITS Stage-1 tuning and the current Detect /
        Filter settings, validated against the images already accepted."""
        if entry is None or self.detect.design is None:
            return None
        if entry is self.current_entry:
            self._store_current()
        accepted = [e for e in sorted(self.project.images, key=lambda e: e.label)
                    if e is not entry and e.pipeline.tagging is not None and e.pipeline.tagging.accepted]
        self.log(f"running stages 2–4 for {entry.name} …"); QtWidgets.QApplication.processEvents()
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            ok, msg = PJ.run_stages_validated(entry, accepted, self.detect.design, self.detect.params(),
                                              self.filter.dot_params(), self.filter.dash_params(),
                                              keep_images=(entry is self.current_entry), calib=self.project.noise)
            self.project.store_settings(self.detect.params(), self.filter.dot_params(), self.filter.dash_params())
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.log(f"  {entry.label:g}× — {'OK · ' + msg if ok else msg}")
        if entry is self.current_entry:
            self.state.activate(entry.pipeline)
            self.detect.load_from_state(); self.filter.load_from_state(); self.tagger.load_from_state()
            self._on_detection()
            self._on_tab(self.tabs.currentIndex())
        self.tagger.fill_series()
        self.sidebar.refresh_status()
        return ok

    def run_all_pending(self):
        """Every image without an accepted tagging, in ascending expansion, so the
        lowest accepted frame becomes the baseline."""
        pend = [e for e in sorted(self.project.images, key=lambda e: e.label)
                if e.pipeline.tagging is None or not e.pipeline.tagging.accepted]
        if not pend:
            self.log("Run all: nothing pending."); return
        for e in pend:
            self.run_stages_for(e)
            QtWidgets.QApplication.processEvents()
        n = sum(1 for e in self.project.images if e.pipeline.tagging is not None and e.pipeline.tagging.accepted)
        self.log(f"Run all: {n}/{len(self.project.images)} image(s) accepted.")

    # ---------------------------------------------------------------- export (Phase 7)
    def export_bundle(self, parent, options=None, name=None):
        """Headless half of the Export action: build + write the bundle of the
        current project. Returns (folder, bundle) or (None, None)."""
        from rwtag import export as EX
        if self.detect.design is None or not self.project.images:
            self.log("Export: load images and a design first."); return None, None
        self._store_current()
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            folder, b = EX.export_project(self.project, self.detect.design, parent, options, name)
        except ValueError as ex:
            self.log(f"Export failed: {ex}"); return None, None
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        import hashlib
        with open(os.path.join(folder, "manifest.json"), "rb") as f:
            mh = hashlib.sha256(f.read()).hexdigest()[:12]
        n = EX.row_counts(b)
        self.log(f"Export -> {folder}  ·  manifest sha256 {mh}…  ·  {len(n)} tables, "
                 f"{n.get('features_corr.csv', 0)} feature rows, {len(b.rejected)} image(s) rejected")
        return folder, b

    def export_bundle_dialog(self, *_):
        from rwtag import export as EX
        from .export_dialog import ExportDialog
        if self.detect.design is None or not self.project.images:
            self.log("Export: load images and a design first."); return None
        self._store_current()
        try:
            preview = EX.build_bundle(self.project, self.detect.design, EX.ExportOptions(n_boot=20))
        except ValueError as ex:
            self.log(f"Export: {ex}"); return None
        dlg = ExportDialog(self, self.project, preview, self.project.folder or self._open_dir)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return None
        folder, _b = self.export_bundle(dlg.folder(), dlg.options())
        return folder

    # ---------------------------------------------------------------- sessions
    def save_session(self, *_):
        if self.state.pipeline.source_path is None:
            self.log("Open an image first."); return
        default = io.sidecar_path(self.state.pipeline.source_path)
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save session", default, "JSON (*.json)")
        if not path:
            return
        io.save_session(path, self.state.pipeline.source_path,
                        self.panel.read_correction(), self.panel.read_levels(), self.panel.shared_flags())
        self.log(f"saved session -> {os.path.basename(path)}")

    def load_session(self, *_):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load session", self._open_dir,
                                                        "JSON (*.json);;All files (*)")
        if not path:
            return
        _src, corr, lv, flags = io.load_session(path)
        for f in corr.__dataclass_fields__:
            setattr(self.state.correction, f, getattr(corr, f))
        for f in lv.__dataclass_fields__:
            setattr(self.state.levels, f, getattr(lv, f))
        self.panel.set_shared_flags(flags)
        self.panel.sync_from_state()
        if self.state.pipeline.raw_image is not None:
            self.panel._recompute_full()
        self.log(f"loaded session <- {os.path.basename(path)}")

    def copy_to_all(self, *_):
        """Write the current Stage-1 correction as the sidecar of every project image
        (V1 wrote every image in the folder; the project is the better scope)."""
        if self.current_entry is None:
            self.log("Open an image first."); return
        others = [e for e in self.project.images]
        msg = (f"Write the current correction as the Stage-1 session of all {len(others)} "
               "project image(s)?\n\nExisting sessions will be overwritten.")
        if QtWidgets.QMessageBox.question(self, "Copy to all", msg) != QtWidgets.QMessageBox.Yes:
            self.log("Copy to all: cancelled."); return
        corr, lv, flags = self.panel.read_correction(), self.panel.read_levels(), self.panel.shared_flags()
        for e in others:
            io.save_session(io.sidecar_path(e.path), e.path, corr, lv, flags)
            if e is not self.current_entry:
                e.unload_images(); e._sidecar_loaded = False
                for f in corr.__dataclass_fields__:
                    setattr(e.pipeline.correction, f, getattr(corr, f))
                for f in lv.__dataclass_fields__:
                    setattr(e.pipeline.levels, f, getattr(lv, f))
        self.log(f"copied the correction to {len(others)} project image(s)")


def main():
    import sys
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow(); w.show()
    proj = [a for a in sys.argv[1:] if a.endswith(".rwproj.json") and os.path.exists(a)]
    if proj:                                   # python run.py path/to/project.rwproj.json
        w.open_project_path(os.path.abspath(proj[0]))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
