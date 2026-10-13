"""
gui.overlay_panel
=================
Phase-C tab (6 · Overlay): rigidly align each Expanded image onto the Initial
about a common box centre (rotation + translation from the paired dots, scale
deliberately UNTOUCHED) and show them overlaid — initial in CYAN, expanded in
RED, grey where they coincide. The physical growth stays visible: the red
lattice spreads outward from the aligned centre.
"""
from __future__ import annotations
import os
import numpy as np
from PySide6 import QtWidgets

from rwtag import pairing as PR
from rwtag.refwarp import tagframe as TF
from .widgets import SliderSpin


class OverlayPanel(QtWidgets.QWidget):
    def __init__(self, state, canvas, log, project_fn, parent=None):
        super().__init__(parent)
        self.state = state
        self.canvas = canvas
        self.log = log
        self.project_fn = project_fn
        self._align = None
        self._rgb = None
        self._origin = None
        self._init_entry = None
        self._exp_entry = None
        self._pairs = None

        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel("<b>6 — Overlay (aligned, NOT scaled)</b>"))
        _intro = QtWidgets.QLabel(
            "<small>Aligns the expanded image to the initial about a common box centre "
            "(rotation + translation only). Initial = cyan, expanded = red, coincidence = "
            "grey — the red lattice grows outward from the aligned centre.</small>")
        _intro.setWordWrap(True)
        root.addWidget(_intro)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("expanded:"))
        self.expcombo = QtWidgets.QComboBox(); row.addWidget(self.expcombo, 1)
        row.addWidget(QtWidgets.QLabel("box:"))
        self.boxcombo = QtWidgets.QComboBox(); row.addWidget(self.boxcombo, 1)
        _rw = QtWidgets.QWidget(); _rw.setLayout(row)
        root.addWidget(_rw)

        vo = QtWidgets.QGroupBox("Layers"); vl = QtWidgets.QVBoxLayout(vo)
        self.chk_init = QtWidgets.QCheckBox("Initial (cyan)"); self.chk_init.setChecked(True)
        self.s_init = SliderSpin("initial opacity", 0.0, 2.0, 1.0, 0.05, 2)
        self.chk_exp = QtWidgets.QCheckBox("Expanded (red)"); self.chk_exp.setChecked(True)
        self.s_exp = SliderSpin("expanded opacity", 0.0, 2.0, 1.0, 0.05, 2)
        self.chk_center = QtWidgets.QCheckBox("Common-box centre marker")
        self.chk_center.setChecked(True)
        for w in (self.chk_init, self.s_init, self.chk_exp, self.s_exp, self.chk_center):
            vl.addWidget(w)
        root.addWidget(vo)

        self.summary = QtWidgets.QLabel("Tag the initial + an expanded image, then open this tab.")
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        self.b_export = QtWidgets.QPushButton("Export overlay PNG…")
        self.b_export.setEnabled(False)
        root.addWidget(self.b_export)
        root.addStretch(1)

        self.expcombo.currentIndexChanged.connect(lambda *_: self._recompute())
        self.boxcombo.currentIndexChanged.connect(lambda *_: self._recompute(keep_boxes=True))
        for w in (self.chk_init, self.chk_exp):
            w.toggled.connect(lambda *_: self._compose())
        for s in (self.s_init, self.s_exp):
            s.valueChanged.connect(lambda *_: self._compose())
        self.chk_center.toggled.connect(lambda *_: self._draw_marks())
        self.b_export.clicked.connect(self.export_png)
        self.state.taggingChanged.connect(lambda *_: setattr(self, "_pairs", None))

    # ---------------------------------------------------------------- data
    def _tagged(self):
        proj = self.project_fn()
        init = proj.initial()
        if init is None or init.pipeline.tagging is None:
            return None, []
        return init, [e for e in proj.expanded() if e.pipeline.tagging is not None]

    def refresh(self):
        init, exp = self._tagged()
        cur = self.expcombo.currentText()
        self.expcombo.blockSignals(True)
        self.expcombo.clear()
        self.expcombo.addItems([f"{e.label:g}×" for e in exp])
        i = self.expcombo.findText(cur)
        if i >= 0:
            self.expcombo.setCurrentIndex(i)
        self.expcombo.blockSignals(False)
        if init is None or not exp:
            self.summary.setText("Tag the initial and ≥1 expanded image first."); return
        self._recompute()

    def _recompute(self, keep_boxes=False):
        init, exp = self._tagged()
        if init is None or not exp:
            return
        idx = max(0, self.expcombo.currentIndex())
        if idx >= len(exp):
            return
        e = exp[idx]
        self._init_entry, self._exp_entry = init, e
        self._pairs = PR.pair_tags(init.pipeline.tagging.tags, e.pipeline.tagging.tags)
        boxes = PR.common_boxes(self._pairs)
        if not boxes:
            self.summary.setText("No common box with paired dots."); return
        if not keep_boxes or self.boxcombo.count() != len(boxes):
            self.boxcombo.blockSignals(True)
            self.boxcombo.clear()
            self.boxcombo.addItems([f"B{N} ({n} dots)" for N, n in boxes])
            self.boxcombo.blockSignals(False)
        bi = max(0, self.boxcombo.currentIndex())
        box_n = boxes[min(bi, len(boxes) - 1)][0]
        # box centres from each frame's TPS warp
        c0 = TF.warped_box_centers(init.pipeline.tagging.warp, None)[box_n]
        c1 = TF.warped_box_centers(e.pipeline.tagging.warp, None)[box_n]
        self._align = PR.rigid_align(self._pairs, box_n, c0, c1)
        if not self._align.get("ok"):
            self.summary.setText(f"Alignment failed: {self._align.get('reason')}"); return
        self._compose()
        a = self._align
        self.summary.setText(
            f"aligned about <b>B{box_n}</b> · rotation <b>{a['angle_deg']:.2f}°</b> · "
            f"{a['n_pairs']} paired dots<br>"
            f"<small>scale untouched — red growth from the centre is the real "
            f"expansion ({init.label:g}× → {e.label:g}×).</small>")
        self.log(f"Overlay: {init.label:g}×↔{e.label:g}× about B{box_n}, "
                 f"rot {a['angle_deg']:.2f}°, {a['n_pairs']} pairs")

    # ---------------------------------------------------------------- render
    def _compose(self):
        if self._align is None or not self._align.get("ok"):
            return
        init, e = self._init_entry, self._exp_entry
        u80 = init.pipeline.detection.u8
        u81 = e.pipeline.detection.u8
        cg = self.s_init.value() if self.chk_init.isChecked() else 0.0
        rg = self.s_exp.value() if self.chk_exp.isChecked() else 0.0
        self._rgb, self._origin = PR.overlay_composite(u80, u81, self._align,
                                                       cyan_gain=cg, red_gain=rg)
        h, w = self._rgb.shape[:2]
        self.canvas.set_extent(w, h)
        self.canvas.set_image(self._rgb, levels=(0, 255))
        self.b_export.setEnabled(True)
        self._draw_marks()

    def _draw_marks(self, *_):
        if self._align is None or self._origin is None:
            return
        self.canvas.clear_overlays()
        if self.chk_center.isChecked():
            c = np.asarray(self._align["c_init"]) - self._origin
            self.canvas.add_points([tuple(c)], color=(255, 230, 0), size=16, symbol="+")
            self.canvas.add_labels([tuple(c)], [f"B{self._align['box']}"],
                                   color=(255, 230, 0), size=11)

    # ---------------------------------------------------------------- export
    def export_png(self):
        if self._rgb is None:
            return
        name = (f"overlay_{self._init_entry.label:g}x_vs_{self._exp_entry.label:g}x"
                f"_B{self._align['box']}.png")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export overlay PNG", name,
                                                        "PNG (*.png)")
        if not path:
            return
        import cv2
        cv2.imwrite(path, cv2.cvtColor(self._rgb, cv2.COLOR_RGB2BGR))
        self.log(f"Overlay: PNG → {path}")
