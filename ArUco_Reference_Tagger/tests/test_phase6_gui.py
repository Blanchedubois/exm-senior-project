"""
Phase 6 offscreen GUI smoke test: a three-image dummy project through Run all,
then the Pair, Overlay, Field and Series tabs with their options and exports.
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


def test_gui_cross_image_tabs():
    d, truth = DM.run("optimistic", "opt_warp")
    if d is None:
        return
    from PySide6 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from gui.app import MainWindow
    from rwtag import io
    with tempfile.TemporaryDirectory() as tmp:
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
        # 5 Pair
        w.tabs.setCurrentIndex(4); app.processEvents()
        assert w.pair.table.rowCount() > 10000 and "shared tags" in w.pair.summary.text()
        w.pair.sel.cmb_cmp.setCurrentIndex(2); w.pair.sel.changed.emit(); app.processEvents()
        assert "1× ↔ 4×" in w.pair.summary.text()
        # 6 Overlay, both alignments, PNG
        w.tabs.setCurrentIndex(5); app.processEvents()
        assert "rigid" in w.overlay.summary.text()
        w.overlay.cmb_mode.setCurrentIndex(1); app.processEvents()
        assert "expansion removed" in w.overlay.summary.text()
        png = w.overlay.export_png(os.path.join(tmp, "ov.png")); assert png and os.path.getsize(png) > 1000
        # 7 Field: every quantity, significance mask, ellipses, CSV
        w.tabs.setCurrentIndex(6); app.processEvents()
        assert "uniform expansion" in w.field.summary.text()
        w.field.chk_ell.setChecked(True); w.field.chk_sig.setChecked(True)
        for i in range(w.field.cmb_q.count()):
            w.field.cmb_q.setCurrentIndex(i); app.processEvents()
            assert w.field.lbl_range.text() != "—", w.field.cmb_q.currentText()
        w.field.cmb_mode.setCurrentIndex(1); app.processEvents()
        csvp = w.field.export_csv(os.path.join(tmp, "f.csv")); assert csvp and os.path.getsize(csvp) > 10000
        # 8 Series: two maps on one scale, PNG
        w.tabs.setCurrentIndex(7); app.processEvents()
        maps = w.series.compute(); app.processEvents()
        assert maps is not None and len(maps) == 2 and w.series.table.rowCount() == 2
        w.series.cmb_q.setCurrentIndex(1); app.processEvents()
        assert len(w.strip.views) == 2
        png2 = w.series.export_png(os.path.join(tmp, "strip.png")); assert png2 and os.path.getsize(png2) > 1000
        w.close()
