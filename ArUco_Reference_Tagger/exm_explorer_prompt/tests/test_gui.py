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
    _wait(app, lambda: w.last_pre is not None and w.last_field is not None)
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
