"""
app.verify_view
===============
The **Verify** tab: embeds the shared `stageui.StageWorkspace` (the identical
5-stage tuner from the point-tracking app) and drives it from the project's image
list. Selecting an image binds the workspace to that frame's parameters —
Stage-1 optics are *shared* (`project.correction`), Stages 2-5 are *per-image*
(`project.image_params[path]`) — loads the raw frame, and auto-runs all five
stages so every overlay is live. Tuning any slider and re-running writes back into
that image's params (Stage 1 writes through to the shared optics).

Runs on the main thread with a busy cursor (Qt requires GUI draws on the main
thread); trackpy is a few seconds/image. Threaded pre-compute + caching is a
later polish (see docs/verify_view_plan.md §5).
"""
from __future__ import annotations
import os
import copy
from PySide6 import QtWidgets, QtCore, QtGui

from gridtrack import io as gio
from fieldkit.project import ImageParams
from stageui.workspace import StageWorkspace


class VerifyView(QtWidgets.QWidget):
    def __init__(self, project, log_fn, select_delta_fn, parent=None):
        super().__init__(parent)
        self.project = project
        self.log = log_fn
        self._select_delta = select_delta_fn        # (delta:int) -> move list selection
        self.current_path = None                     # image currently bound + run
        self.pending_path = None                     # last selected; run when tab shown

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        bar = QtWidgets.QHBoxLayout()
        self.b_prev = QtWidgets.QToolButton(); self.b_prev.setText("◀ Prev")
        self.b_next = QtWidgets.QToolButton(); self.b_next.setText("Next ▶")
        self.lbl = QtWidgets.QLabel("—"); self.lbl.setStyleSheet("font-weight:bold;")
        self.b_rerun = QtWidgets.QPushButton("Re-run stages")
        self.b_copy = QtWidgets.QPushButton("Copy params → all")
        bar.addWidget(self.b_prev); bar.addWidget(self.b_next)
        bar.addSpacing(8); bar.addWidget(self.lbl, 1)
        bar.addWidget(self.b_rerun); bar.addWidget(self.b_copy)
        root.addLayout(bar)

        self.workspace = StageWorkspace(log_fn=log_fn)
        root.addWidget(self.workspace, 1)

        self.b_prev.clicked.connect(lambda: self._select_delta(-1))
        self.b_next.clicked.connect(lambda: self._select_delta(+1))
        self.b_rerun.clicked.connect(self._run_current)
        self.b_copy.clicked.connect(self._copy_to_all)

        # ←/→ cycle images while the Verify tab is focused
        for key, d in ((QtCore.Qt.Key_Left, -1), (QtCore.Qt.Key_Right, +1)):
            sc = QtGui.QShortcut(QtGui.QKeySequence(key), self)
            sc.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(lambda d=d: self._select_delta(d))

    # ------------------------------------------------------------ selection flow
    def on_select(self, path):
        """Image list picked `path`. Run now if the Verify tab is showing;
        otherwise defer until it is (avoids trackpy while on Image/Field tabs)."""
        self.pending_path = path
        if self.isVisible():
            self._run_current()

    def showEvent(self, ev):                          # tab became active
        super().showEvent(ev)
        if self.pending_path and self.pending_path != self.current_path:
            self._run_current()

    # ------------------------------------------------------------ run + binding
    def _run_current(self):
        path = self.pending_path
        if not path:
            return
        if self.project.reference is None:
            self.project.load_reference()
        # persist the params tuned on the outgoing image before rebinding
        if self.current_path and self.current_path != path:
            self._read_back(self.current_path)
        try:
            img = gio.load_tiff(path)
        except Exception as e:                        # pragma: no cover
            self.log(f"Verify: load failed — {e}"); return

        ip = self.project.params_for(path)
        ws = self.workspace
        ws.panels[0].set_correction(self.project.correction)     # shared optics
        ws.panels[0].set_levels(ip.levels)                        # per-image contrast/threshold
        ws.panels[2].set_params(ip.transform_model, ip.ransac_px)
        ws.panels[2]._reference = self.project.reference          # project's grid ref
        ws.state.pipeline.reference = self.project.reference
        ws.panels[3].set_params(ip.measure)
        ws.panels[4].set_params(ip.filters)
        ws.state.set_raw(path, img)

        self.lbl.setText(f"{os.path.basename(path)}  ({self._role(path)})")
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            ws.run_all()
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.current_path = path
        self.log(f"Verify: ran 5 stages on {os.path.basename(path)}")

    def _read_back(self, path):
        """Copy the workspace's current Stage 3-5 widget values into `path`'s
        per-image params (Stage-1 optics are shared and already written through)."""
        ip = self.project.params_for(path)
        ip.levels = self.workspace.panels[0].read_levels()   # per-image contrast/threshold
        model, ransac = self.workspace.panels[2].read_params()
        ip.transform_model, ip.ransac_px = model, ransac
        ip.measure = self.workspace.panels[3].read_params()
        ip.filters = self.workspace.panels[4].read_params()

    def _copy_to_all(self):
        if not self.current_path:
            self.log("Verify: select an image first."); return
        self._read_back(self.current_path)
        src = self.project.params_for(self.current_path)
        for p in self.project.all_paths():
            self.project.image_params[p] = ImageParams(
                levels=copy.deepcopy(src.levels),
                measure=copy.deepcopy(src.measure), filters=copy.deepcopy(src.filters),
                transform_model=src.transform_model, ransac_px=src.ransac_px)
        n = len(self.project.all_paths())
        self.log(f"Verify: copied {os.path.basename(self.current_path)} params to all {n} images")

    def _role(self, path):
        return "initial" if path == self.project.initial_path else "expansion"

    def flush(self):
        """Write the currently-displayed image's tuned Stage 3-5 widgets back into
        its per-image params. Call before batch Run-all / Save so edits made on the
        current image (without switching away) are not lost."""
        if self.current_path:
            self._read_back(self.current_path)

    def rebind_project(self, project):
        """After Open-project: point at the new project (state reset on next select)."""
        self.project = project
        self.current_path = None
        self.pending_path = None
