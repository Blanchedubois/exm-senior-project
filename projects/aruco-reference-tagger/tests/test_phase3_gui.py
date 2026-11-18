"""
Phase 3 offscreen GUI smoke test: Detect tab on a dummy image, design switch,
auto-deskew writing the rotation back to Stage 1, metadata derived fields, and
the design persisted in the project file.
"""
from __future__ import annotations
import json
import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _dummy as DM                                                    # noqa: E402


def test_gui_detect_tab():
    d, truth = DM.run("optimistic", "opt_warp")
    if d is None:
        return
    from PySide6 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from gui.app import MainWindow
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for lam in (1.0, 2.0):
            src = os.path.join(d, DM.frame(truth, lam)["files"][0] + ".ome.tif")
            dst = os.path.join(tmp, os.path.basename(src))
            try:
                os.symlink(src, dst)
            except OSError:
                shutil.copy(src, dst)
            paths.append(dst)
        w = MainWindow()
        w.add_paths(paths, ask_label=False)
        e = w.current_entry
        cam = truth["camera"]
        w.panel.s_strength.set_value(cam["vignette_strength"]); w.panel.s_power.set_value(cam["vignette_power"])
        w.panel.s_k1.set_value(cam["lens_k1"]); w.panel.s_k2.set_value(cam["lens_k2"])
        w.panel._recompute_full()
        w.tabs.setCurrentIndex(1); app.processEvents()
        assert w.detect.design.name == "1_optimistic"
        assert abs(w.detect.s_umpx.value() - 0.51) < 1e-9          # from the header
        w.detect.s_psf.setValue(cam["psf_fwhm_um"])
        det = w.detect.run_detect(); app.processEvents()
        assert det is not None and det.model["registered"] and e.stage_status()[1]
        assert w.detect.table.rowCount() == 25 and "λ 0.99" in w.detect.summary.text()
        assert w.meta._editors["expansion_derived"].text().startswith("0.999")
        assert w.panel.b_deskew.isEnabled()
        # auto-deskew: Stage-1 rotation becomes -raw rotation, then re-detect upright
        w.detect.run_deskew(); app.processEvents()
        assert abs(w.panel.s_rot.value() + truth["frames"][0]["rotation_deg"]) < 0.1
        det2 = w.state.pipeline.detection
        assert abs(det2.frame_pose.frame_rot_deg) < 0.15 and abs(det2.rot_raw_deg - det.rot_raw_deg) < 0.1   # 36 tags
        # switching design re-labels the run (detection is per click, not automatic)
        w.detect.set_design_folder(os.path.join(DM.DESIGNS, "4_spectrum"))
        assert w.project.design_folder.endswith("4_spectrum")
        w.detect.set_design_folder(os.path.join(DM.DESIGNS, "1_optimistic"))
        path = w.save_project()
        saved = json.load(open(path))
        assert saved["design_folder"].endswith("1_optimistic")
        assert saved["images"][0]["meta"]["print_design"] == "optimistic"
        # select the other image: no detection yet, then back: restored
        other = [x for x in w.project.images if x is not e][0]
        w.select_entry(other); app.processEvents()
        assert w.detect.table.rowCount() == 0 and not w.panel.b_deskew.isEnabled()
        w.select_entry(e); app.processEvents()
        assert w.detect.table.rowCount() == 25
        w.close()
