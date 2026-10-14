"""
Phase 7 offscreen GUI test: a three-image dummy project through Run all, the
Export dialog (built, options read), the export itself, then the saved project
through scripts/export_project.py: the GUI and headless bundles must hold
identical tables.
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _dummy as DM                                                    # noqa: E402


def test_gui_export_equals_headless():
    d, truth = DM.run("optimistic", "opt_warp")
    if d is None:
        return
    from PySide6 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from gui.app import MainWindow
    from gui.export_dialog import ExportDialog
    from rwtag import io, export as EX, export_reader as RD
    tmp = tempfile.mkdtemp(prefix="rwtag_p7g_")
    try:
        paths = []
        for lam in (1.0, 2.0, 4.0):
            src = os.path.join(d, DM.frame(truth, lam)["files"][0] + ".ome.tif")
            dst = os.path.join(tmp, os.path.basename(src))
            try:
                os.symlink(src, dst)
            except OSError:
                shutil.copy(src, dst)
            paths.append(dst)
        w = MainWindow()
        w.add_paths(paths, ask_label=False)
        p = DM.stage1(truth, 0.0)
        for e in w.project.images:
            io.save_session(io.sidecar_path(e.path), e.path, p, e.pipeline.levels, {})
            for f in p.__dataclass_fields__:
                setattr(e.pipeline.correction, f, getattr(p, f))
        w.panel.sync_from_state()
        w.detect.s_psf.setValue(truth["camera"]["psf_fwhm_um"])
        w.run_all_pending(); app.processEvents()
        assert all(e.pipeline.tagging.accepted for e in w.project.images)
        assert w.project.settings["aruco"]["psf_fwhm_um"] == truth["camera"]["psf_fwhm_um"]
        # the dialog: preview counts, options
        preview = EX.build_bundle(w.project, w.detect.design, EX.ExportOptions(n_boot=10))
        dlg = ExportDialog(w, w.project, preview, tmp)
        assert dlg.table.rowCount() == len(preview.tables) and "none" in dlg.lbl_rej.text()
        dlg.chk_cons.setChecked(True); dlg._add_pair()
        o = dlg.options()
        assert o.consecutive_pairs and len(o.extra_pairs) == 1
        dlg.close()
        # the export through the window
        folder, b = w.export_bundle(tmp, EX.ExportOptions(n_boot=50), name="gui")
        assert folder and "Export ->" in w.logbox.toPlainText()
        RD.read_bundle(folder).check()
        proj_path = w.save_project()
        w.close()
        # the same project, headless
        res = subprocess.run([sys.executable, os.path.join(DM.ROOT, "scripts", "export_project.py"), proj_path,
                              "--name", "script", "--boot", "50"], capture_output=True, text=True, timeout=600)
        assert res.returncode == 0, res.stdout + res.stderr
        m1 = json.load(open(os.path.join(folder, "manifest.json")))
        m2 = json.load(open(os.path.join(tmp, "script", "manifest.json")))
        diff = [k for k in m1["tables"] if m1["tables"][k]["sha256"] != m2["tables"].get(k, {}).get("sha256")]
        print(f"  info  GUI vs headless: {len(m1['tables'])} tables, differing {diff or 'none'}")
        assert set(m1["tables"]) == set(m2["tables"]) and not diff
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
