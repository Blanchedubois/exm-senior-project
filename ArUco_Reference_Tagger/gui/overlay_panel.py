"""
gui.overlay_panel
=================
Tab 6 · Overlay. Ported from Reference_Warp_Tagger/gui/overlay_panel.py: the
compared image aligned onto the reference and drawn over it, reference cyan,
compared red, grey where they coincide. Two alignments:
  rigid       rotation + translation about a common box centre, scale UNTOUCHED
              (V1): the red lattice grows outward -- the real expansion;
  similarity  the uniform scale removed too: only the NON-uniform part remains,
              so any red / cyan separation is distortion.
"""
from __future__ import annotations
import numpy as np
from PySide6 import QtWidgets

from rwtag import pairing as PR
from rwtag.refwarp import tagframe as TF
from .compare_common import PairSelector
from .widgets import SliderSpin


class OverlayPanel(QtWidgets.QWidget):
    def __init__(self, state, canvas, log, project_fn, design_fn, parent=None):
        super().__init__(parent)
        self.state, self.canvas, self.log, self.project_fn, self.design_fn = state, canvas, log, project_fn, design_fn
        self._align = self._rgb = self._origin = self._pairs = None
        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel("<b>6 — Overlay</b>"))
        intro = QtWidgets.QLabel("<small>Reference = cyan, aligned compared = red, coincidence = grey. "
                                 "<b>Rigid</b> keeps the scale (the red lattice grows: expansion); "
                                 "<b>similarity</b> removes it (what is left is distortion).</small>")
        intro.setWordWrap(True); root.addWidget(intro)
        self.sel = PairSelector(project_fn); root.addWidget(self.sel)
        row = QtWidgets.QHBoxLayout()
        self.cmb_mode = QtWidgets.QComboBox(); self.cmb_mode.addItems(["rigid (scale kept)", "similarity (scale removed)"])
        self.cmb_box = QtWidgets.QComboBox()
        row.addWidget(QtWidgets.QLabel("alignment:")); row.addWidget(self.cmb_mode, 1)
        row.addWidget(QtWidgets.QLabel("box:")); row.addWidget(self.cmb_box, 1)
        _rw = QtWidgets.QWidget(); _rw.setLayout(row); root.addWidget(_rw)
        vo = QtWidgets.QGroupBox("Layers"); vl = QtWidgets.QVBoxLayout(vo)
        self.chk_ref = QtWidgets.QCheckBox("Reference (cyan)"); self.chk_ref.setChecked(True)
        self.s_ref = SliderSpin("reference gain", 0.0, 2.0, 1.0, 0.05, 2)
        self.chk_cmp = QtWidgets.QCheckBox("Compared (red)"); self.chk_cmp.setChecked(True)
        self.s_cmp = SliderSpin("compared gain", 0.0, 2.0, 1.0, 0.05, 2)
        self.chk_centre = QtWidgets.QCheckBox("Common-box centre marker"); self.chk_centre.setChecked(True)
        for w in (self.chk_ref, self.s_ref, self.chk_cmp, self.s_cmp, self.chk_centre):
            vl.addWidget(w)
        root.addWidget(vo)
        self.summary = QtWidgets.QLabel("Tag at least two images."); self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self.b_export = QtWidgets.QPushButton("Export overlay PNG…"); self.b_export.setEnabled(False)
        root.addWidget(self.b_export); root.addStretch(1)
        self.sel.changed.connect(lambda: self._recompute())
        self.cmb_mode.currentIndexChanged.connect(lambda *_: self._recompute(keep_boxes=True))
        self.cmb_box.activated.connect(lambda *_: self._recompute(keep_boxes=True))
        for w in (self.chk_ref, self.chk_cmp):
            w.toggled.connect(lambda *_: self._compose())
        for s in (self.s_ref, self.s_cmp):
            s.valueChanged.connect(lambda *_: self._compose())
        self.chk_centre.toggled.connect(lambda *_: self._marks())
        self.b_export.clicked.connect(self.export_png)

    def refresh(self):
        if not self.sel.refresh() or len(self.sel.entries()) < 2:
            self.summary.setText("Tag at least two images (Run all pending)."); return
        self._recompute()

    def _recompute(self, keep_boxes=False):
        r, c = self.sel.ref(), self.sel.cmp()
        design = self.design_fn()
        if r is None or c is None or r is c or design is None:
            return
        self._pairs = PR.pair_frames(r.pipeline.tagging, c.pipeline.tagging)
        boxes = PR.common_boxes(self._pairs)
        if not boxes:
            self.summary.setText("No box with paired dots."); return
        if not keep_boxes or self.cmb_box.count() != len(boxes):
            self.cmb_box.blockSignals(True); self.cmb_box.clear()
            self.cmb_box.addItems([f"B{N} ({n} dots)" for N, n in boxes]); self.cmb_box.blockSignals(False)
        N = boxes[min(max(0, self.cmb_box.currentIndex()), len(boxes) - 1)][0]
        if self.cmb_mode.currentIndex() == 0:
            c0 = TF.warped_box_centers(r.pipeline.tagging.warp, design)[N]
            c1 = TF.warped_box_centers(c.pipeline.tagging.warp, design)[N]
            self._align = PR.rigid_align(self._pairs, N, c0, c1)
        else:
            self._align = PR.similarity_align(self._pairs)
        a = self._align
        if not a.get("ok"):
            self.summary.setText(f"Alignment failed: {a.get('reason')}"); return
        self._compose()
        extra = (f" · about <b>B{a['box']}</b> · scale untouched" if a["kind"] == "rigid" else
                 f" · expansion removed: <b>{a['expansion']:.4f}×</b> (± {a['s_sigma'] / a['s'] ** 2:.4f})")
        self.summary.setText(f"{r.label:g}× ↔ {c.label:g}× · {a['kind']} · rotation <b>{a['angle_deg']:+.3f}°</b> "
                             f"± {a['angle_sigma_deg']:.3f}{extra} · {a['n_pairs']} paired dots")
        self.log(f"Overlay: {r.label:g}×↔{c.label:g}× {a['kind']}, rot {a['angle_deg']:+.3f}°")

    def _compose(self):
        a = self._align
        if a is None or not a.get("ok"):
            return
        r, c = self.sel.ref(), self.sel.cmp()
        cg = self.s_ref.value() if self.chk_ref.isChecked() else 0.0
        rg = self.s_cmp.value() if self.chk_cmp.isChecked() else 0.0
        self._rgb, self._origin = PR.overlay_composite(r.pipeline.detection.u8, c.pipeline.detection.u8, a, cg, rg)
        h, w = self._rgb.shape[:2]
        self.canvas.set_extent(w, h); self.canvas.set_image(self._rgb, levels=(0, 255))
        self.b_export.setEnabled(True)
        self._marks()

    def _marks(self, *_):
        if self._align is None or self._origin is None:
            return
        self.canvas.clear_overlays()
        if self.chk_centre.isChecked() and self._align.get("kind") == "rigid":
            c = np.asarray(self._align["c0"]) - self._origin
            self.canvas.add_points([tuple(c)], color=(255, 230, 0), size=16, symbol="+")
            self.canvas.add_labels([tuple(c)], [f"B{self._align['box']}"], color=(255, 230, 0), size=11)

    def export_png(self, path=None):
        if self._rgb is None:
            return None
        if path is None:
            r, c = self.sel.ref(), self.sel.cmp()
            name = f"overlay_{r.label:g}x_vs_{c.label:g}x_{self._align['kind']}.png"
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export overlay PNG", name, "PNG (*.png)")
            if not path:
                return None
        import cv2
        cv2.imwrite(path, cv2.cvtColor(self._rgb, cv2.COLOR_RGB2BGR))
        self.log(f"Overlay: PNG → {path}")
        return path
