"""
Phase 5 offscreen GUI smoke test: calibrate the error model from repeat frames
through the Detect tab, see it applied, and read ± sigmas in the Tag tab.
"""
from __future__ import annotations
import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _dummy as DM                                                    # noqa: E402


def test_gui_error_model():
    d, truth = DM.run("optimistic", "opt_noise")
    if d is None:
        return
    from PySide6 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from gui.app import MainWindow
    fr = DM.frame(truth, 2.0)
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for f in fr["files"][:4]:
            src = os.path.join(d, f + ".ome.tif")
            dst = os.path.join(tmp, os.path.basename(src))
            try:
                os.symlink(src, dst)
            except OSError:
                shutil.copy(src, dst)
            paths.append(dst)
        w = MainWindow()
        w.add_paths(paths[:1], ask_label=False)
        cam = truth["camera"]
        w.panel.s_strength.set_value(cam["vignette_strength"]); w.panel.s_power.set_value(cam["vignette_power"])
        w.panel.s_k1.set_value(cam["lens_k1"]); w.panel.s_k2.set_value(cam["lens_k2"]); w.panel._recompute_full()
        w.detect.s_psf.setValue(cam["psf_fwhm_um"])
        w.tabs.setCurrentIndex(1); app.processEvents()
        assert "not set" in w.detect.lbl_noise.text() and "defaults" in w.detect.lbl_noise.text()
        # enter the camera gain, calibrate from the repeat frames
        g = w.meta._editors["gain_e_per_adu"]; g.setText(f"{cam['true_gain_e_per_adu']:.4f}"); g.editingFinished.emit()
        cal = w.detect.calibrate_from_files(paths)
        assert 0.6 < cal["kappa_dot"] < 1.3 and "repeat images: 4 frames" in w.detect.lbl_noise.text()
        assert w.project.noise["kappa_dot"] == cal["kappa_dot"]
        det = w.detect.run_detect()
        assert not det.noise["relative"] and abs(det.noise["kappa_dot"] - cal["kappa_dot"]) < 1e-12
        assert "errors: dots σ" in w.detect.summary.text()
        # Tag tab: sigma colouring and the ± readout
        w.tabs.setCurrentIndex(2); w.filter.run()
        w.tabs.setCurrentIndex(3); tr = w.tagger.tag_current()
        assert tr is not None and len(tr.cov) > 0.99 * len(tr.tags)
        w.tagger.chk_sigma.setChecked(True); app.processEvents()
        assert not w.tagger.chk_resid.isChecked()
        labels = [e[0] for e in w.canvas4._tag_entries]
        assert any("±" in s and "rot" in s for s in labels if s.startswith("aruco|"))
        # persisted with the project
        path = w.save_project()
        import json
        assert json.load(open(path))["noise"]["kappa_source"].startswith("repeat images")
        w.close()
