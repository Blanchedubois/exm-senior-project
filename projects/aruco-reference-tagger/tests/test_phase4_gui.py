"""
Phase 4 offscreen GUI smoke test: Filter and Tag one dummy frame through the
tabs, then Run all pending from the sidebar, with Stage-1 tuning copied to every
image, and check acceptance, the series list and the sidebar ticks.
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


def test_gui_filter_tag_and_run_all():
    d, truth = DM.run("optimistic", "opt_warp")
    if d is None:
        return
    from PySide6 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from gui.app import MainWindow
    from rwtag import io
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for lam in (1.0, 2.0, 6.0):
            src = os.path.join(d, DM.frame(truth, lam)["files"][0] + ".ome.tif")
            dst = os.path.join(tmp, os.path.basename(src))
            try:
                os.symlink(src, dst)
            except OSError:
                shutil.copy(src, dst)
            paths.append(dst)
        w = MainWindow()
        w.add_paths(paths, ask_label=False)
        cam = truth["camera"]
        w.panel.s_strength.set_value(cam["vignette_strength"]); w.panel.s_power.set_value(cam["vignette_power"])
        w.panel.s_k1.set_value(cam["lens_k1"]); w.panel.s_k2.set_value(cam["lens_k2"]); w.panel._recompute_full()
        w.detect.s_psf.setValue(cam["psf_fwhm_um"])
        # Stage 2 -> 3 -> 4 through the tabs on the initial image
        w.tabs.setCurrentIndex(1); w.detect.run_detect()
        w.tabs.setCurrentIndex(2); fr = w.filter.run(); app.processEvents()
        assert fr is not None and fr.dot_counts["kept"] > 17000 and w.filter.table.rowCount() == 25
        w.filter.s_dev.set_value(0.30); app.processEvents()           # live re-filter
        assert w.state.pipeline.features is not None
        w.tabs.setCurrentIndex(3); tr = w.tagger.tag_current(); app.processEvents()
        assert tr is not None and tr.accepted and tr.source == "baseline" and len(tr.tags) > 18000
        assert "accepted" in w.tagger.summary.text() and w.current_entry.stage_status() == (True, True, True, True)
        w.tagger.chk_exp.setChecked(True); w.tagger.kindcombo.setCurrentText("aruco"); app.processEvents()
        # copy Stage 1 to all images (sidecars), then run the rest from the sidebar
        corr, lv, flags = w.panel.read_correction(), w.panel.read_levels(), w.panel.shared_flags()
        for e in w.project.images:
            io.save_session(io.sidecar_path(e.path), e.path, corr, lv, flags)
            if e is not w.current_entry:
                e.unload_images(); e._sidecar_loaded = False
                for f in corr.__dataclass_fields__:
                    setattr(e.pipeline.correction, f, getattr(corr, f))
        w.run_all_pending(); app.processEvents()
        for e in w.project.images:
            assert e.pipeline.tagging is not None and e.pipeline.tagging.accepted, (e.label, e.status_text())
            assert e.stage_status()[3]
        assert w.tagger.serieslist.count() == 3
        assert all(w.tagger.serieslist.item(i).text().split("  ", 1)[1].startswith("OK") for i in range(3))
        assert abs(w.project.expanded()[-1].meta.expansion_derived - 6.0) < 0.03
        w.close()
