"""Milestone 3 GUI smoke test (offscreen): window opens, workers deliver,
moving a site through its ROI updates the site and the truth overlay, the
editor writes back to the ROI, add / remove work, extrema appear."""

import os
import time

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


def _wait(app, cond, timeout=20.0):
    t0 = time.time()
    while not cond():
        app.processEvents()
        if time.time() - t0 > timeout:
            raise TimeoutError
        time.sleep(0.01)


@pytest.fixture(scope="module")
def win():
    from exm_explorer.app import MainWindow, dark_palette
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    dark_palette(app)
    w = MainWindow()
    w.resize(1500, 920)
    w.show()
    _wait(app, lambda: w.last_pre is not None and w.last_field is not None
          and w.last_ana is not None and w.last_ana["tier"] == "full", timeout=60)
    yield app, w
    w.close()


def test_window_shows_truth(win):
    app, w = win
    assert len(w.rois) == 2
    lo, hi = w.last_field["stats"]["expansion"]
    assert lo < 4.0 * (1 - 0.05)              # the lagging patch shows
    shot = os.environ.get("EXM_SCREENSHOT")
    if shot:
        app.processEvents()
        w.grab().save(shot)


def test_drag_site_updates_field(win):
    app, w = win
    roi = w.rois[0]
    w.select(roi)
    before = w.last_field
    roi.setPos(roi.pos() + (100, -50))        # what a drag does
    _wait(app, lambda: w.last_field is not before)
    s = roi.site
    assert abs(s.cx - 330) < 1e-6 and abs(s.cy - 480) < 1e-6
    assert abs(w.e_cx.value() - 330) < 1e-6
    m = w.last_field["maps"]["expansion"]
    x = w.last_field["x"]
    j = np.argmin(abs(x - 480)); i = np.argmin(abs(x - 330))
    assert m[j, i] < 3.9                      # the lag moved with the site


def test_editor_drives_roi_and_extrema(win):
    app, w = win
    w.select(w.rois[1])
    before = w.last_field
    w.e_phi.setValue(75.0)
    _wait(app, lambda: w.last_field is not before)
    assert abs(w.rois[1].getState()["angle"] - 75.0) < 1e-6
    w.o_heat.setCurrentText("true local anisotropy")
    before = w.last_field
    _wait(app, lambda: w.last_field is not before and w.last_field.get("extrema_map") == "anisotropy")
    ex = w.last_field["extrema"]
    assert any(e["kind"] == "max" for e in ex)
    # a maximum at the anisotropic site; the isotropic lagging patch also
    # makes a ring of anisotropy just outside its edge (pure shear outside an
    # inclusion), which can be stronger
    assert any(e["kind"] == "max" and np.hypot(e["x"] - 520, e["y"] - 260) < 60 for e in ex)
    assert w.extrema_table.rowCount() == len(ex)


def test_add_and_remove(win):
    app, w = win
    n = len(w.rois)
    w.add_site(600, 600)
    assert len(w.rois) == n + 1 and w.current.site.cx == 600
    w.remove_current()
    assert len(w.rois) == n and len(w.scen.sites) == n


# ------------------------------------------------------------------ milestone 4
def test_panels_filled_by_full_tier(win):
    app, w = win
    w.submit_analysis("full")
    before = w.last_ana
    _wait(app, lambda: w.last_ana is not before and w.last_ana["tier"] == "full", timeout=60)
    r = w.last_ana
    m = r["metrics"]
    assert abs(m["tags"]["scale"] / 4.0 - 1) < 0.01 and m["acf"] is not None
    assert m["ccf"]["ratio"] > 1.0
    assert r["extrema"]["global_ccf_peaks"][0]["value"] == pytest.approx(m["ccf"]["peak"], rel=1e-3)
    assert w.acf_panel.res is r and w.ccf_panel.res is r
    assert "Global transform" in w.metrics_panel.text.text()
    assert w.post_panel.n == m["post_size"]


def test_fast_tier_while_dragging_is_restricted(win):
    app, w = win
    roi = w.rois[0]
    w.select(roi)
    before = w.last_ana
    roi.setPos(roi.pos() + (10, 10), finish=False)     # mid-drag: no 'finished' yet
    _wait(app, lambda: w.last_ana is not before and w.last_ana["tier"] == "fast")
    r = w.last_ana
    assert r["tier"] == "fast" and r["which"] is not None
    assert r["which"].sum() < r["which"].size / 3
    roi.sigRegionChangeFinished.emit(roi)          # mouse released
    _wait(app, lambda: w.last_ana["tier"] == "full", timeout=60)


def test_measured_overlay_and_extrema(win):
    app, w = win
    w.o_heat.setCurrentText("measured local expansion (CCF)")
    _wait(app, lambda: w.last_ana["tier"] == "full")
    app.processEvents()
    assert w.heat_meas.isVisible() and not w.heat.isVisible()
    ex = w._shown_extrema
    assert any(e["kind"] == "min" for e in ex)
    # the lagging patch is the deepest minimum, in design um near the site
    s = w.rois[0].site
    low = min((e for e in ex if e["kind"] == "min"), key=lambda e: e["value"])
    assert np.hypot(low["x"] - s.cx, low["y"] - s.cy) < 60
    shot = os.environ.get("EXM_SCREENSHOT")
    if shot:
        for k, name in enumerate(("ACF", "CCF", "Metrics", "Post")):
            w.tabs.setCurrentIndex([w.tabs.tabText(i) for i in range(w.tabs.count())].index(name))
            app.processEvents()
            w.grab().save(shot.replace(".png", f"_{name.lower()}.png"))


# ------------------------------------------------------------------ milestone 5
def test_faithful_run_and_export(win, tmp_path):
    app, w = win
    w.run_faithful()
    _wait(app, lambda: w.last_faithful is not None, timeout=120)
    key, res, ex, secs = w.last_faithful
    assert res["aruco_tags"]["n_tags"] == 36
    assert "Faithful pipeline" in w.metrics_panel.faithful.text()
    w._write_bundle(str(tmp_path), "png")
    for f in ("scenario.json", "pre.png", "post.png", "features_truth.csv", "metrics.json", "window.png"):
        assert (tmp_path / f).is_file(), f
    # changing the scenario marks the faithful result as stale
    w.e_cx.setValue(w.e_cx.value() + 5)
    app.processEvents()
    assert "changed since" in w.metrics_panel.faithful.text()


def test_cancel_faithful(win):
    app, w = win
    w.run_faithful()
    w.cancel_faithful()
    _wait(app, lambda: not w.faithful_worker.isRunning(), timeout=60)
    app.processEvents()
    assert w.a_faithful.isEnabled()


def test_presets_load(win):
    app, w = win
    w.load_preset("exm_sim batch run")
    assert len(w.rois) == 3 and w.scen.solver.model == "kinematic"
    assert w.s_model.currentText().startswith("kinematic")
    w.load_preset("example")
    assert len(w.rois) == 2
