"""
Phase 2 offscreen GUI smoke test: build the window, add dummy images, edit the
metadata (cells checkbox + description, camera gain), switch images and back,
tune Stage 1, save and re-open the project. No display needed.
"""
from __future__ import annotations
import json
import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
DUMMY = os.path.normpath(os.path.join(ROOT, "..", "ArUco_Tracker_V2", "dummy", "optimistic", "opt_clean"))


def _app():
    from PySide6 import QtWidgets
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_gui_project_meta_and_stage1():
    if not os.path.exists(os.path.join(DUMMY, "truth.json")):
        print("  skip: dummy run not generated"); return
    app = _app()
    from gui.app import MainWindow
    from rwtag import meta as M
    with tempfile.TemporaryDirectory() as d:
        paths = []
        for name in ("1X_optimistic_s0.ome.tif", "2X_optimistic_s0.ome.tif"):
            dst = os.path.join(d, name)
            try:
                os.symlink(os.path.join(DUMMY, name), dst)
            except OSError:
                shutil.copy(os.path.join(DUMMY, name), dst)
            paths.append(dst)
        w = MainWindow()
        w.add_paths(paths, ask_label=False)
        app.processEvents()
        assert len(w.project.images) == 2 and w.current_entry is w.project.initial()
        assert w.current_entry.label == 1.0 and w.state.pipeline.raw_image is not None
        # header values reached the form
        assert w.meta._editors["magnification"].text() == "20"
        assert "file" in w.meta._badges["magnification"].text()
        assert w.meta.gain_warn.isVisibleTo(w.meta)
        # cells checkbox enables the description; edits are 'user' and hit the sidecar
        assert not w.meta._editors["cells_description"].isEnabled()
        w.meta._editors["cells_present"].setChecked(True)
        assert w.meta._editors["cells_description"].isEnabled()
        ed = w.meta._editors["cells_description"]; ed.setText("HeLa, fixed"); ed.editingFinished.emit()
        g = w.meta._editors["gain_e_per_adu"]; g.setText("0.235"); g.editingFinished.emit()
        assert not w.meta.gain_warn.isVisibleTo(w.meta)
        side = json.load(open(M.meta_path(paths[0])))["meta"]
        assert side["cells_present"] is True and side["cells_description"] == "HeLa, fixed"
        assert side["sources"]["cells_description"] == "user" and side["gain_e_per_adu"] == 0.235
        # derived fields are read-only
        assert not w.meta._editors["expansion_derived"].isEnabled()
        # Stage 1: tune the lens and check the corrected image updates
        before = w.state.pipeline.corrected_image.copy()
        w.panel.s_k1.set_value(-0.05); w.panel._recompute_full()
        assert w.state.pipeline.corrected_image is not None and \
            abs(float(w.state.pipeline.corrected_image.mean()) - float(before.mean())) > 1e-6
        # switch to the 2X image and back
        other = [e for e in w.project.images if e is not w.current_entry][0]
        w.select_entry(other); app.processEvents()
        assert w.meta._editors["cells_present"].isChecked() is False
        assert w.meta._editors["expansion_expected"].text() == "2"
        first = w.project.initial()
        w.select_entry(first); app.processEvents()
        assert w.meta._editors["cells_description"].text() == "HeLa, fixed"
        assert abs(w.panel.s_k1.value() + 0.05) < 1e-9          # Stage-1 sidecar restored
        # apply optics/camera to all
        w._apply_meta_to_all()
        assert other.meta.gain_e_per_adu == 0.235
        # save + re-open
        path = w.save_project()
        w2 = MainWindow(); w2.open_project_path(path); app.processEvents()
        assert len(w2.project.images) == 2
        e = w2.project.initial()
        assert e.meta.cells_description == "HeLa, fixed" and abs(e.pipeline.correction.k1 + 0.05) < 1e-9
        w.close(); w2.close()
