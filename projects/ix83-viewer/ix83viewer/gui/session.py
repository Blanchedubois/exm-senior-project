"""Sessions: save and reopen exactly what is on screen.

A session file (.ix83session, JSON) records the folders, both views' state
(acquisition / set, replicates, mode, frame, LUT, layout, zoom, reference
channel, merge ticks), View-menu toggles, expansion/pixel-size overrides,
the Analysis dock's line and box, and copies of the saved display settings,
contrast levels and channel offsets for the acquisitions involved, so the
file is self-contained when moved to another computer with the same data.

The last session is written automatically on quit and reopened on launch.
"""

from __future__ import annotations

import json
import os

from PySide6.QtCore import QTimer

from ..core.adjust import ChannelSettings
from ..core.offsets import config_dir
from ..io.scan import FovSet, group_by_position

VERSION = 1
LAST_SESSION = "last_session.ix83session"


def last_session_path() -> str:
    return os.path.join(config_dir(), LAST_SESSION)


def _range(vb):
    (x0, x1), (y0, y1) = vb.viewRange()
    return [[x0, x1], [y0, y1]]


def set_view(vb, rng):
    """Restore a saved view: same centre and horizontal extent. The height
    follows the panel's current shape (window size or the Analysis dock may
    differ from when the session was saved)."""
    (x0, x1), (y0, y1) = rng
    cy = (y0 + y1) / 2
    vb.setRange(xRange=(x0, x1), yRange=(cy - 0.5, cy + 0.5), padding=0)


# ---- capture -------------------------------------------------------------
def capture(win) -> dict:
    v, g, d = win.view, win.grid, win.analysis
    datasets = win.browser.datasets()
    involved = set()
    single = None
    if v.ds is not None:
        involved.add(v.ds.folder)
        single = {"folder": v.ds.folder, "mode": v.current_mode(), "frame": v.frame_spin.value(),
                  "lut": v.lut_combo.currentText(), "range": _range(v.vb)}
    grid = None
    if g.fov is not None and g.panels:
        involved.update(m.folder for m in g.fov.members)
        grid = {
            "label": g.fov.label, "members": [m.folder for m in g.fov.members],
            "panels": [{"name": p.name, "folder": p.ds.folder, "merge": p.merge_check.isChecked()} for p in g.panels],
            "reference": g.reference.name if g.reference else None,
            "mode": g.mode_combo.currentText(), "frame": g.frame_spin.value(), "lut": g.lut_combo.currentText(),
            "layout": g.layout_combo.currentText(), "merged": g.merge_check.isChecked(),
            "link": g.link_check.isChecked(), "scale_bar": g.scale_check.isChecked(),
            "merge_view": g.align.mode_combo.currentText(), "aligned_panels": g.align.aligned_check.isChecked(),
            "range": _range(g._tiles()[0].vb),
        }
    store, offsets = win.store, g.store
    return {
        "version": VERSION,
        "date_folder": win.scan.root if win.scan else None,
        "added_folders": [ds.folder for ds in win.browser._extra],
        "tab": win.tabs.currentIndex(),
        "color_preset": win.settings.value("color_preset"),
        "clipping_overlay": win.clip_action.isChecked(),
        "pre_expansion": win.pre_exp_action.isChecked(),
        "overrides": {ds.folder: {"expansion": ds.expansion_override, "pixel_size_um": ds.pixel_size_override_um}
                      for ds in datasets if ds.expansion_override or ds.pixel_size_override_um},
        "single": single,
        "grid": grid,
        "analysis": {"visible": d.isVisible(), "tab": d.tabs.currentIndex(),
                     "line": d.line_pts, "box": d.box_rect},
        "settings": {f: s.to_dict() for f, s in store.channels.items() if f in involved},
        "levels": {k: list(v) for k, v in store.levels.items() if k.split("|", 1)[0] in involved},
        "offset_pairs": {k: v for k, v in offsets.pairs.items() if k.split("|", 1)[0] in involved},
        "calibrations": dict(offsets.calibrations),
    }


def save(win, path: str):
    data = capture(win)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


# ---- restore -------------------------------------------------------------
def load(win, path: str) -> list[str]:
    """Restore a session; returns human-readable problems (missing folders...)."""
    with open(path, encoding="utf-8") as f:
        s = json.load(f)
    problems = []
    if s.get("date_folder"):
        if os.path.isdir(s["date_folder"]):
            win.open_path(s["date_folder"])
        else:
            problems.append(f"Date folder not found: {s['date_folder']}")
    for folder in s.get("added_folders", []):
        if os.path.isdir(folder):
            win.open_path(folder)
        else:
            problems.append(f"Folder not found: {folder}")
    by_folder = {ds.folder: ds for ds in win.browser.datasets()}

    # stored state first, so views pick it up when they load
    for folder, d in s.get("settings", {}).items():
        win.store.channels[folder] = ChannelSettings.from_dict(d)
    win.store.levels.update({k: tuple(v) for k, v in s.get("levels", {}).items()})
    win.store.save()
    win.grid.store.pairs.update(s.get("offset_pairs", {}))
    win.grid.store.calibrations.update(s.get("calibrations", {}))
    win.grid.store._save()
    for folder, o in s.get("overrides", {}).items():
        if folder in by_folder:
            by_folder[folder].expansion_override = o.get("expansion")
            by_folder[folder].pixel_size_override_um = o.get("pixel_size_um")

    if s.get("color_preset"):
        win.set_color_preset(s["color_preset"])
    win.clip_action.setChecked(bool(s.get("clipping_overlay")))
    win.pre_exp_action.setChecked(bool(s.get("pre_expansion")))

    g = s.get("grid")
    if g:
        members = [by_folder[f] for f in g["members"] if f in by_folder]
        if len(members) < len(g["members"]):
            problems.append("Some acquisitions of the side-by-side set were not found")
        if members:
            _restore_grid(win, g, members)
    sv = s.get("single")
    if sv and sv["folder"] in by_folder:
        _restore_single(win, sv, by_folder[sv["folder"]])
    elif sv:
        problems.append(f"Acquisition not found: {sv['folder']}")
    win.tabs.setCurrentIndex(s.get("tab", 0))

    a = s.get("analysis") or {}
    d = win.analysis
    d.line_pts = tuple(map(tuple, a["line"])) if a.get("line") else None
    d.box_rect = tuple(a["box"]) if a.get("box") else None
    for btn, on in ((d.line_btn, d.line_pts is not None), (d.box_btn, d.box_rect is not None)):
        btn.blockSignals(True)
        btn.setChecked(on)
        btn.blockSignals(False)
    d.tabs.setCurrentIndex(a.get("tab", 0))
    d.setVisible(bool(a.get("visible")))
    d.set_host(win._host())
    return problems


def _restore_grid(win, g, members):
    gv = win.grid
    fov = None
    if win.scan is not None and len(g["label"]) <= 3:
        want = {m.folder for m in members}
        fov = next((s for s in group_by_position(win.scan.samples) if {m.folder for m in s.members} == want), None)
    fov = fov or FovSet(label=g["label"], members=members)
    for w, val in ((gv.mode_combo, g["mode"]), (gv.lut_combo, g["lut"]), (gv.layout_combo, g["layout"])):
        w.blockSignals(True)
        w.setCurrentText(val)
        w.blockSignals(False)
    gv.merge_check.setChecked(g["merged"])
    gv.link_check.setChecked(g["link"])
    gv.scale_check.setChecked(g["scale_bar"])
    win._show_set(fov)
    for p, saved in zip(gv.panels, g["panels"]):
        idx = next((i for i in range(p.combo.count()) if p.combo.itemData(i).folder == saved["folder"]), None)
        if idx is not None and idx != p.combo.currentIndex():
            p.combo.setCurrentIndex(idx)
        p.merge_check.setChecked(saved["merge"])
    ref = next((i for i, p in enumerate(gv.panels) if p.name == g.get("reference")), None)
    if ref is not None:
        gv.align.ref_combo.setCurrentIndex(ref)
    gv.align.mode_combo.setCurrentText(g.get("merge_view", "Overlay"))
    gv.align.aligned_check.setChecked(g.get("aligned_panels", True))
    if g["mode"] == "Frame":
        gv.frame_spin.setValue(g["frame"])
    gv._fit_pending = False  # keep the saved zoom instead of fitting when images arrive
    # wait for the new tiles to be laid out, so the zoom is applied at their real size
    QTimer.singleShot(150, lambda: gv.set_view(g["range"]))


def _restore_single(win, sv, ds):
    v = win.view
    v.lut_combo.setCurrentText(sv["lut"])
    v.mode_combo.blockSignals(True)
    v.mode_combo.setCurrentText(sv["mode"])
    v.mode_combo.blockSignals(False)
    v.restore_range = sv["range"]
    win.browser.select(ds.folder)
    if win.view.ds is not ds:  # already selected: set_dataset was not re-triggered
        win._show_dataset(ds)
    if sv["mode"] == "Frame":
        v.frame_spin.setValue(sv["frame"])
