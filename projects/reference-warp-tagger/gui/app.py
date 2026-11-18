"""
gui.app
=======
Reference-Warp Tagger window: a toolbar (Open / Save / Load / Copy to all /
Export marked image) + log around a tabbed workspace. Tab 1 is the Stage-1 optics
editor; Tab 2 is the Stage-2 detect & identify view. Both share one AppState; one
active image at a time. Per-image params are auto-discovered from a sidecar
session and shared optics persist as you move between frames.
"""
from __future__ import annotations
from PySide6 import QtWidgets, QtCore, QtGui   # import Qt before OpenCV (avoids plugin hijack)
import os

from rwtag import io
from rwtag import project as PJ
from rwtag.types import CorrectionParams, LevelsParams
from rwtag.refwarp import series as S
from .state import AppState
from .canvas import ImageCanvas
from .correct_panel import (CorrectPanel, SEC_VIGNETTE, SEC_LENS, SEC_LOWPASS,
                            SEC_ROTATE, SEC_LEVELS)
from .detect_panel import DetectPanel
from .filter_panel import FilterPanel
from .tag_panel import TagPanel
from .project_panel import ProjectSidebar
from .pair_panel import PairPanel
from .overlay_panel import OverlayPanel
from .field_panel import FieldPanel
from .summary_panel import SummaryPanel


def _stage_page(canvas, panel):
    """A stage tab: [ large canvas | scrollable control panel ]."""
    scroll = QtWidgets.QScrollArea(); scroll.setWidgetResizable(True)
    scroll.setWidget(panel)
    # wide enough that every panel's natural width fits inside the viewport (incl.
    # the vertical scrollbar), so nothing is clipped; AsNeeded (not AlwaysOff) means
    # a horizontal bar would only ever appear as a genuine last resort, never clip.
    scroll.setMinimumWidth(360); scroll.setMaximumWidth(480)
    scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
    split = QtWidgets.QSplitter()
    split.addWidget(canvas); split.addWidget(scroll)
    split.setStretchFactor(0, 1); split.setStretchFactor(1, 0)
    split.setSizes([960, 380])
    return split

# fields owned by each section (for selective restore-on-open)
SECTION_FIELDS = {
    SEC_VIGNETTE: ("vig_strength", "vig_power", "vig_cx", "vig_cy", "vig_floor"),
    SEC_LENS: ("k1", "k2", "dist_cx", "dist_cy"),
    SEC_LOWPASS: ("lp_enable", "lp_cutoff", "lp_shape", "lp_order"),
    SEC_ROTATE: ("rotate_deg",),
}
LEVELS_FIELDS = ("lv_enable", "lv_white", "lv_gamma", "lv_black_mode",
                 "lv_black_k", "lv_black_pct", "lv_black")

IMG_FILTER = "Images (*.tif *.tiff *.ome.tif *.png *.jpg);;All files (*)"
IMG_EXTS = (".tif", ".tiff", ".png", ".jpg", ".jpeg")

# default open dir: the project's Stitched Images folder if present
_STITCHED = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "Stitched Images"))


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Reference-Warp Tagger")
        self.resize(1360, 860)
        self._open_dir = _STITCHED if os.path.isdir(_STITCHED) else ""

        # log dock (create early: panels log during init)
        self.logbox = QtWidgets.QPlainTextEdit(readOnly=True, maximumBlockCount=500)
        dock = QtWidgets.QDockWidget("Log", self)
        dock.setWidget(self.logbox)
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea, dock)

        tb = self.addToolBar("main")
        tb.addAction("Add images…", self.add_images)
        tb.addAction("Save project", self.save_project)
        tb.addAction("Open project…", self.open_project)
        tb.addSeparator()
        tb.addAction("Save session…", self.save_session)
        tb.addAction("Load session…", self.load_session)
        tb.addAction("Copy to all…", self.copy_to_all)
        tb.addSeparator()
        tb.addAction("Export marked image…", self.export_marked)

        self.state = AppState()
        # Stage 1
        self.canvas = ImageCanvas()
        self.panel = CorrectPanel(self.state, self.canvas, self.log)
        # Stage 2 (own canvas so overlays don't bleed into the editor)
        self.canvas2 = ImageCanvas()
        self.detect = DetectPanel(self.state, self.canvas2, self.log)
        self.detect.deskewApplied.connect(self._on_deskew)
        # Stage 3
        self.canvas3 = ImageCanvas()
        self.filter = FilterPanel(self.state, self.canvas3, self.log)
        # Stage 4
        self.canvas4 = ImageCanvas()
        self.tagger = TagPanel(self.state, self.canvas4, self.log)

        # project sidebar (multi-image workspace) — created before the cross-image
        # tabs, which need a project accessor
        self.project = PJ.Project()
        self.current_entry = None
        self._clf = None
        # Phases B-C: cross-image tabs (operate on the project, not the selection)
        self.canvas5 = ImageCanvas()
        self.pair = PairPanel(self.state, self.canvas5, self.log, lambda: self.project)
        self.canvas6 = ImageCanvas()
        self.overlay = OverlayPanel(self.state, self.canvas6, self.log, lambda: self.project)
        self.canvas7 = ImageCanvas()
        self.field = FieldPanel(self.state, self.canvas7, self.log, lambda: self.project)
        import pyqtgraph as _pg
        self.sumplot = _pg.PlotWidget(title="measured vs expected expansion")
        self.summarize = SummaryPanel(self.state, self.sumplot, self.log,
                                      lambda: self.project)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(_stage_page(self.canvas, self.panel), "1 · Correct optics")
        self.tabs.addTab(_stage_page(self.canvas2, self.detect), "2 · Detect && identify")
        self.tabs.addTab(_stage_page(self.canvas3, self.filter), "3 · Filter")
        self.tabs.addTab(_stage_page(self.canvas4, self.tagger), "4 · Tag")
        self.tabs.addTab(_stage_page(self.canvas5, self.pair), "5 · Pair")
        self.tabs.addTab(_stage_page(self.canvas6, self.overlay), "6 · Overlay")
        self.tabs.addTab(_stage_page(self.canvas7, self.field), "7 · Field")
        self.tabs.addTab(_stage_page(self.sumplot, self.summarize), "8 · Summary")
        self.tabs.currentChanged.connect(self._on_tab)
        self.sidebar = ProjectSidebar(self.project)
        self.sidebar.setMinimumWidth(190); self.sidebar.setMaximumWidth(260)
        self.sidebar.entrySelected.connect(self.select_entry)
        self.sidebar.runOne.connect(self.run_stages_for)
        self.sidebar.runAll.connect(self.run_all_pending)
        self.sidebar.projectEdited.connect(lambda: self.sidebar.refresh_status())

        outer = QtWidgets.QSplitter()
        outer.addWidget(self.sidebar); outer.addWidget(self.tabs)
        outer.setStretchFactor(0, 0); outer.setStretchFactor(1, 1)
        outer.setSizes([210, 1150])
        self.setCentralWidget(outer)

        self.readout = QtWidgets.QLabel("—")
        self.statusBar().addPermanentWidget(self.readout)
        for c in (self.canvas, self.canvas2, self.canvas3, self.canvas4, self.canvas5,
                  self.canvas6, self.canvas7):
            c.cursorMoved.connect(self._on_cursor)
        # keep sidebar stage ticks live as results land
        for sig in (self.state.detectionChanged, self.state.featuresChanged,
                    self.state.taggingChanged, self.state.correctionChanged):
            sig.connect(self.sidebar.refresh_status)

        self._install_shortcuts()
        self.log("Ready. Add images to build the project (labels parse from '1.5X…' names).")

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
        if val != val:      # NaN -> out of bounds
            self.readout.setText("—")
        else:
            self.readout.setText(f"(x={x:.0f}, y={y:.0f})  value={val:.0f}")

    def _on_tab(self, idx):
        if idx == 1:        # entering Stage 2 -> show the current corrected frame
            self.detect.refresh_base_image()
        elif idx == 2:      # entering Stage 3 -> show the Stage-2 detection
            self.filter.refresh_base_image()
        elif idx == 3:      # entering Stage 4 -> show the frame + any existing tags
            self.tagger.refresh_base_image()
        elif idx == 4:      # entering Pair -> rebuild combo + (re)pair
            self.pair.refresh()
        elif idx == 5:      # entering Overlay -> align + compose
            self.overlay.refresh()
        elif idx == 6:      # entering Field -> displacement/strain field
            self.field.refresh()
        elif idx == 7:      # entering Summary -> measured vs expected
            self.summarize.refresh()

    def _on_deskew(self, deg):
        """Stage 2's Auto-deskew wrote rotate_deg -> sync the Stage-1 panel and
        re-render SYNCHRONOUSLY so corrected_image is fresh before Stage 2 re-detects."""
        self.panel.s_rot.set_value(deg)
        self.panel.read_correction()
        self.panel._recompute_full()
        self.log(f"Stage 1 rotation set to {deg:.1f}° from Stage-2 auto-deskew.")

    # ---------------------------------------------------------------- project
    def _classifier(self):
        if self._clf is None:
            from rwtag.glyph import detect as D
            model = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                 "reference", "glyph_knn.yml")
            self._clf = D.load_classifier(model)
        return self._clf

    def add_images(self, *_):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Add images to project", self._open_dir, IMG_FILTER)
        added = None
        for p in paths:
            if any(os.path.abspath(p) == e.path for e in self.project.images):
                continue
            lab = S.parse_label(p)
            if lab is None:
                lab, ok = QtWidgets.QInputDialog.getDouble(
                    self, "Expected expansion",
                    f"Expected × for {os.path.basename(p)}:", 1.0, 0.1, 100.0, 2)
                if not ok:
                    continue
            added = self.project.add(p, lab)
            self._open_dir = os.path.dirname(p)
        if added is None:
            return
        if not self.project.folder:
            self.project.folder = os.path.dirname(added.path)
        self.sidebar.refresh()
        self.log(f"project: {len(self.project.images)} image(s); "
                 f"initial = {self.project.initial().label:g}×")
        if self.current_entry is None:
            self.sidebar.select(self.project.initial())

    def _load_path(self, path):
        """Add (or find) one image in the project and select it. Kept as the
        single-image compatibility entry point."""
        ap = os.path.abspath(path)
        entry = next((e for e in self.project.images if e.path == ap), None)
        if entry is None:
            lab = S.parse_label(path) or 1.0
            entry = self.project.add(ap, lab)
            if not self.project.folder:
                self.project.folder = os.path.dirname(ap)
            self.sidebar.refresh()
        self._open_dir = os.path.dirname(ap)
        self.sidebar.select(entry)                    # -> select_entry via signal
        if self.current_entry is not entry:           # offscreen/no-signal fallback
            self.select_entry(entry)

    def open_image(self, *_):                          # back-compat alias
        self.add_images()

    def select_entry(self, entry):
        if entry is None or entry is self.current_entry:
            return
        prev = self.current_entry
        if prev is not None and prev.pipeline.raw_image is not None:
            self.panel.read_correction(); self.panel.read_levels()
            prev.save_sidecar(self.panel.shared_flags())     # autosave Stage-1 tuning
            prev.unload_images()                             # bound memory
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            try:
                entry.ensure_loaded()
            except Exception as e:                    # pragma: no cover
                QtWidgets.QApplication.restoreOverrideCursor()
                QtWidgets.QMessageBox.critical(self, "Load failed", str(e)); return
            self.current_entry = entry
            self.state.activate(entry.pipeline, entry.glyph_manual)
            # panels: Stage 1 re-syncs sliders + preview; 2-4 restore stored results
            self.panel.sync_from_state()
            self.panel._on_image_loaded()
            self.detect.load_from_state()
            self.filter.load_from_state()
            self.tagger.load_from_state()
            self._on_tab(self.tabs.currentIndex())
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.sidebar.refresh_status()
        img = entry.pipeline.raw_image
        self.log(f"selected {entry.name}  {img.shape[1]}x{img.shape[0]}  "
                 f"[{img.min():.0f}, {img.max():.0f}]  ·  {entry.label:g}× {entry.role}")

    def run_stages_for(self, entry):
        if entry is None:
            return
        self.log(f"running stages 2–4 for {entry.name}…")
        # accepted anchors: every other already-tagged entry (initial first) — the
        # cross-frame validation that catches a confidently-wrong box numbering
        accepted = [e for e in sorted(self.project.images, key=lambda e: e.label)
                    if e is not entry and e.pipeline.tagging is not None]
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            ok, msg = PJ.run_stages_validated(entry, accepted, self._classifier(),
                                              log=self.log)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.log(f"  {entry.label:g}× — {'OK · ' + msg if ok else 'FAILED · ' + msg}")
        if entry is not self.current_entry:
            entry.unload_images()                     # keep only results in memory
        else:
            self.detect.load_from_state()
            self.filter.load_from_state()
            self.tagger.load_from_state()
            self._on_tab(self.tabs.currentIndex())
        self.sidebar.refresh_status()

    def run_all_pending(self):
        pend = [e for e in sorted(self.project.images, key=lambda e: e.label)
                if e.pipeline.tagging is None]
        if not pend:
            self.log("Run all: nothing pending."); return
        for e in pend:
            self.run_stages_for(e)
            QtWidgets.QApplication.processEvents()

    def save_project(self, *_):
        if not self.project.images:
            self.log("Project is empty."); return
        if self.current_entry is not None and self.current_entry.pipeline.raw_image is not None:
            self.panel.read_correction(); self.panel.read_levels()
            self.current_entry.save_sidecar(self.panel.shared_flags())
        path = self.project.save()
        self.log(f"project saved -> {path}")

    def open_project(self, *_):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open project", self._open_dir, "Project (*.rwproj.json);;All files (*)")
        if not path:
            return
        self.project = PJ.Project.load(path)
        self.current_entry = None
        self.sidebar.project = self.project
        self.sidebar.refresh(keep_selection=False)
        self._open_dir = self.project.folder
        self.log(f"project opened: {len(self.project.images)} image(s)")
        if self.project.images:
            self.sidebar.select(self.project.initial())
        self.log(f"loaded {os.path.basename(path)}  {img.shape[1]}x{img.shape[0]}  "
                 f"[{img.min():.0f}, {img.max():.0f}]  ·  {note}")

    # ---------------------------------------------------------------- sessions
    def save_session(self, *_):
        if self.state.pipeline.source_path is None:
            self.log("Open an image first."); return
        default = io.sidecar_path(self.state.pipeline.source_path)
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save session", default, "JSON (*.json)")
        if not path:
            return
        io.save_session(path, self.state.pipeline.source_path,
                        self.panel.read_correction(), self.panel.read_levels(),
                        self.panel.shared_flags())
        self.log(f"saved session -> {os.path.basename(path)}")

    def load_session(self, *_):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load session", self._open_dir,
                                                        "JSON (*.json);;All files (*)")
        if not path:
            return
        src, corr, lv, flags = io.load_session(path)
        # replace both dataclasses wholesale
        for f in corr.__dataclass_fields__:
            setattr(self.state.correction, f, getattr(corr, f))
        for f in lv.__dataclass_fields__:
            setattr(self.state.levels, f, getattr(lv, f))
        self.panel.set_shared_flags(flags)
        self.panel.sync_from_state()
        if self.state.pipeline.raw_image is not None:
            self.panel._recompute_full()
        elif src and os.path.exists(src):
            self._load_path(src)
        self.log(f"loaded session <- {os.path.basename(path)}")

    def copy_to_all(self, *_):
        if self.state.pipeline.source_path is None:
            self.log("Open an image first."); return
        folder = os.path.dirname(self.state.pipeline.source_path)
        files = [os.path.join(folder, f) for f in sorted(os.listdir(folder))
                 if f.lower().endswith(IMG_EXTS)]
        if not files:
            self.log("No images found next to the current file."); return
        msg = (f"Write the current correction as a sidecar session for all "
               f"{len(files)} image(s) in:\n{folder}\n\nExisting sidecars will be overwritten.")
        if QtWidgets.QMessageBox.question(self, "Copy to all", msg) != QtWidgets.QMessageBox.Yes:
            self.log("Copy to all: cancelled."); return
        corr, lv, flags = self.panel.read_correction(), self.panel.read_levels(), self.panel.shared_flags()
        for p in files:
            io.save_session(io.sidecar_path(p), p, corr, lv, flags)
        self.log(f"copied correction to {len(files)} sidecar session(s) in {folder}")

    # ---------------------------------------------------------------- export
    def export_marked(self, *_):
        """Render the current marked image to PNG (Stage-3 filtered view if it's
        active/available, else the Stage-2 detection view), plus a sidecar JSON."""
        det = self.state.pipeline.detection
        if det is None:
            self.log("Export: run Stage 2 (Detect grid) first."); return
        idx = self.tabs.currentIndex()
        if idx == 3 and self.state.pipeline.tagging is not None:
            self.tagger.refresh_base_image(); canvas = self.canvas4; suffix = "_tagged"
        elif idx == 2 and self.state.pipeline.features is not None:
            self.filter.refresh_base_image(); canvas = self.canvas3; suffix = "_filtered"
        else:
            self.tabs.setCurrentIndex(1); self.detect.refresh_base_image()
            canvas = self.canvas2; suffix = "_marked"
        QtWidgets.QApplication.processEvents()
        base = os.path.splitext(os.path.basename(self.state.pipeline.source_path or "marked"))[0]
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export marked image", os.path.join(self._open_dir, base + suffix + ".png"),
            "PNG (*.png)")
        if not path:
            return
        try:
            from pyqtgraph.exporters import ImageExporter
            # export the whole layout (includes the colorbar legend when present)
            ImageExporter(canvas.glw.ci).export(path)
        except Exception as e:                # pragma: no cover
            QtWidgets.QMessageBox.critical(self, "Export failed", str(e)); return
        self._write_stage2_sidecar(os.path.splitext(path)[0] + ".stage2.json", det)
        self.log(f"exported marked image -> {os.path.basename(path)} (+ .stage2.json)")

    def _write_stage2_sidecar(self, path, det):
        import json
        model = det.model or {}
        reg = model.get("reg")
        out = {
            "source_path": self.state.pipeline.source_path,
            "stage": det.stage,
            "n_dots": int(len(det.dots)),
            "n_dashes_on_grid": int(len(det.dashes_on_grid)),
            "box_pitch_px": float(det.grid.get("box_pitch", 0.0)),
            "angle_deg": float(det.basis.get("angle_deg", 0.0)),
            "registered": bool(model.get("registered", False)),
            "reg": {"orient": list(reg["orient"]), "offset": list(reg["offset"])} if reg else None,
            "box_numbers": {f"{k[0]}_{k[1]}": v for k, v in (model.get("node_num") or {}).items()
                            if v is not None},
            "reads": [{"x": r["x"], "y": r["y"], "char": r["char"], "conf": r["conf"],
                       "kind": r["kind"], "box": list(r["box"]), "slot": r["slot"]}
                      for r in det.reads],
            "summary": model.get("summary", ""),
        }
        with open(path, "w") as f:
            json.dump(out, f, indent=1)


def main():
    import sys
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow(); w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
