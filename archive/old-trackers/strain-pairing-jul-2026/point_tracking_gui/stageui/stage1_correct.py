"""
app.stage1_correct
==================
Stage 1 GUI: sliders for vignetting + lens distortion with live preview.
All maths is delegated to gridtrack.correct (headless).
"""
from __future__ import annotations
import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets, QtCore

from gridtrack import correct
from gridtrack.types import CorrectionParams, LevelsParams
from .widgets import SliderSpin, Collapsible


class Stage1Panel(QtWidgets.QWidget):
    def __init__(self, state, canvas, log, parent=None):
        super().__init__(parent)
        self.state = state
        self.canvas = canvas
        self.log = log
        self._show_before = False
        self._levels = LevelsParams()          # PER-IMAGE contrast/threshold (see set_levels)

        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel("<b>Stage 1 — Correct optics</b>"))

        # --- vignetting ---
        vg = Collapsible("Vignetting (flat-field)")
        c = self.state.correction
        self.s_strength = vg.add(SliderSpin("strength", 0.0, 1.0, c.vig_strength, 0.01))
        self.s_power = vg.add(SliderSpin("power", 0.5, 5.0, c.vig_power, 0.05))
        self.b_auto = QtWidgets.QPushButton("Auto-estimate vignette")
        vg.add(self.b_auto)
        root.addWidget(vg)

        # --- lens distortion ---
        ld = Collapsible("Lens distortion")
        self.s_k1 = ld.add(SliderSpin("k1 (barrel < 0)", -0.30, 0.30, c.k1, 0.005, 4))
        self.s_k2 = ld.add(SliderSpin("k2", -0.10, 0.10, c.k2, 0.002, 4))
        root.addWidget(ld)

        # --- 2-D FFT low-pass denoise ---
        lp = Collapsible("Low-pass (FFT denoise)")
        self.chk_lp = QtWidgets.QCheckBox("Enable")
        self.chk_lp.setChecked(c.lp_enable)
        lp.add(self.chk_lp)
        self.s_lp_cut = lp.add(SliderSpin("cut-off (× Nyquist)", 0.02, 1.0, c.lp_cutoff, 0.02, 3))
        shp = QtWidgets.QHBoxLayout()
        self.cmb_lp_shape = QtWidgets.QComboBox()
        self.cmb_lp_shape.addItems(["gaussian", "butterworth", "ideal"])
        self.cmb_lp_shape.setCurrentText(c.lp_shape)
        self.spin_lp_order = QtWidgets.QSpinBox(); self.spin_lp_order.setRange(1, 8)
        self.spin_lp_order.setValue(c.lp_order)
        shp.addWidget(QtWidgets.QLabel("shape")); shp.addWidget(self.cmb_lp_shape, 1)
        shp.addWidget(QtWidgets.QLabel("order")); shp.addWidget(self.spin_lp_order)
        _w = QtWidgets.QWidget(); _w.setLayout(shp); lp.add(_w)
        self.lbl_lp = QtWidgets.QLabel(); self.lbl_lp.setStyleSheet("color:#999;")
        lp.add(self.lbl_lp)
        root.addWidget(lp)

        # --- deskew: rotate the whole grid upright (helps glyph recognition) ---
        dsk = Collapsible("Deskew (rotate grid upright)")
        self.s_rot = dsk.add(SliderSpin("rotation (deg)", -180.0, 180.0, c.rotate_deg, 0.5, 1))
        self.b_deskew = QtWidgets.QPushButton("Auto-deskew (from glyph grid)")
        dsk.add(self.b_deskew)
        self.lbl_rot = QtWidgets.QLabel(); self.lbl_rot.setStyleSheet("color:#999;")
        dsk.add(self.lbl_rot)
        root.addWidget(dsk)

        # --- contrast / threshold (levels) : PER-IMAGE ---
        lv = Collapsible("Contrast / threshold (levels)")
        self.chk_lv = QtWidgets.QCheckBox("Enable")
        lv.add(self.chk_lv)
        mrow = QtWidgets.QHBoxLayout()
        self.cmb_lv_mode = QtWidgets.QComboBox()
        self.cmb_lv_mode.addItems(["auto", "percentile", "value"])
        self.b_lv_auto = QtWidgets.QPushButton("auto-estimate")
        mrow.addWidget(QtWidgets.QLabel("black point")); mrow.addWidget(self.cmb_lv_mode, 1)
        mrow.addWidget(self.b_lv_auto)
        _mw = QtWidgets.QWidget(); _mw.setLayout(mrow); lv.add(_mw)
        # one black-point control per mode; only the active one is shown
        self.s_lv_k = lv.add(SliderSpin("floor = bg + k·σ", 0.5, 8.0, 3.0, 0.5, 2))
        self.s_lv_pct = lv.add(SliderSpin("floor percentile", 0.0, 95.0, 40.0, 1.0, 1))
        self.s_lv_val = lv.add(SliderSpin("black value (×full)", 0.0, 1.0, 0.0, 0.01, 3))
        self.s_lv_white = lv.add(SliderSpin("white point (×full)", 0.05, 1.0, 1.0, 0.01, 3))
        self.s_lv_gamma = lv.add(SliderSpin("gamma", 0.2, 3.0, 1.0, 0.05, 2))
        self.lbl_lv = QtWidgets.QLabel(); self.lbl_lv.setStyleSheet("color:#999;")
        lv.add(self.lbl_lv)
        root.addWidget(lv)

        # --- intensity histogram (see the floor being cut) ---
        self.hist = pg.PlotWidget(title="intensity histogram (pre-levels)")
        self.hist.setMaximumHeight(150)
        self.hist.showGrid(x=True, y=False, alpha=0.2)
        self.hist_curve = self.hist.plot(stepMode="center", fillLevel=0,
                                         brush=(120, 120, 120, 120), pen=pg.mkPen((160, 160, 160)))
        self.line_black = pg.InfiniteLine(angle=90, movable=False,
                                          pen=pg.mkPen((255, 80, 80), width=2))
        self.line_white = pg.InfiniteLine(angle=90, movable=False,
                                          pen=pg.mkPen((90, 200, 255), width=2))
        self.hist.addItem(self.line_black); self.hist.addItem(self.line_white)
        root.addWidget(self.hist)

        # --- view options ---
        vo = Collapsible("View")
        self.chk_grid = QtWidgets.QCheckBox("Straightness grid overlay")
        self.chk_before = QtWidgets.QCheckBox("Show original (before)")
        vo.add(self.chk_grid); vo.add(self.chk_before)
        root.addWidget(vo)

        # --- row-intensity profile (flatness check) ---
        self.profile = pg.PlotWidget(title="mid-row brightness envelope")
        self.profile.setMaximumHeight(150)
        self.profile.showGrid(x=False, y=True, alpha=0.2)
        self.prof_curve = self.profile.plot(pen=pg.mkPen((255, 190, 0), width=2))
        root.addWidget(self.profile)

        self.b_reset = QtWidgets.QPushButton("Reset correction")
        root.addWidget(self.b_reset)
        root.addStretch(1)

        # debounce so dragging a slider stays smooth
        self._timer = QtCore.QTimer(self); self._timer.setSingleShot(True)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._recompute)

        self.s_rot.valueChanged.connect(lambda *_: self._timer.start())
        self.b_deskew.clicked.connect(self._auto_deskew)
        self._deskew_clf = None
        for s in (self.s_strength, self.s_power, self.s_k1, self.s_k2, self.s_lp_cut):
            s.valueChanged.connect(lambda *_: self._timer.start())
        self.chk_lp.toggled.connect(lambda *_: self._timer.start())
        self.cmb_lp_shape.currentTextChanged.connect(self._on_lp_shape)
        self.spin_lp_order.valueChanged.connect(lambda *_: self._timer.start())
        self.s_lp_cut.valueChanged.connect(lambda *_: self._update_lp_label())
        self._on_lp_shape(self.cmb_lp_shape.currentText())

        for s in (self.s_lv_k, self.s_lv_pct, self.s_lv_val, self.s_lv_white, self.s_lv_gamma):
            s.valueChanged.connect(lambda *_: self._timer.start())
        self.chk_lv.toggled.connect(lambda *_: self._timer.start())
        self.cmb_lv_mode.currentTextChanged.connect(self._on_lv_mode)
        self.b_lv_auto.clicked.connect(lambda: self.cmb_lv_mode.setCurrentText("auto"))
        self._on_lv_mode(self.cmb_lv_mode.currentText())

        self.chk_grid.toggled.connect(self.canvas.show_grid)
        self.chk_before.toggled.connect(self._toggle_before)
        self.b_auto.clicked.connect(self._auto)
        self.b_reset.clicked.connect(self._reset)
        self.state.imageLoaded.connect(self._recompute)

    # ---------------------------------------------------------------- binding
    def set_correction(self, c: CorrectionParams):
        """Point the panel at an external CorrectionParams (edits write through to
        it) and sync the sliders to its values. Used by the embedder to share one
        optics object across images."""
        self.state.pipeline.correction = c
        for s, v in ((self.s_strength, c.vig_strength), (self.s_power, c.vig_power),
                     (self.s_k1, c.k1), (self.s_k2, c.k2), (self.s_lp_cut, c.lp_cutoff),
                     (self.s_rot, getattr(c, "rotate_deg", 0.0))):
            s.set_value(v)
        self.chk_lp.blockSignals(True); self.chk_lp.setChecked(c.lp_enable)
        self.chk_lp.blockSignals(False)
        self.cmb_lp_shape.blockSignals(True); self.cmb_lp_shape.setCurrentText(c.lp_shape)
        self.cmb_lp_shape.blockSignals(False)
        self.spin_lp_order.blockSignals(True); self.spin_lp_order.setValue(c.lp_order)
        self.spin_lp_order.blockSignals(False)
        self._on_lp_shape(c.lp_shape)

    def _on_lp_shape(self, name):
        self.spin_lp_order.setEnabled(name == "butterworth")   # order only for butterworth
        self._update_lp_label()
        self._timer.start()

    def _update_lp_label(self):
        # unit-free read-out: cut-off as a fraction of Nyquist -> cyc/px + coarsest period
        frac = self.s_lp_cut.value()
        cyc_px = frac * 0.5
        period = 1.0 / cyc_px if cyc_px > 0 else float("inf")
        self.lbl_lp.setText(f"cut-off ≈ {cyc_px:.3f} cyc/px  (period ≥ {period:.1f} px)")

    # ------------------------------------------------------ levels (per-image)
    def set_levels(self, lv: LevelsParams):
        """Bind an external LevelsParams (edits write through to it) and sync the
        widgets. Used by the Verify view to make the levels per-image."""
        self._levels = lv
        self.s_lv_k.set_value(lv.lv_black_k)
        self.s_lv_pct.set_value(lv.lv_black_pct)
        self.s_lv_val.set_value(lv.lv_black)
        self.s_lv_white.set_value(lv.lv_white)
        self.s_lv_gamma.set_value(lv.lv_gamma)
        self.chk_lv.blockSignals(True); self.chk_lv.setChecked(lv.lv_enable)
        self.chk_lv.blockSignals(False)
        self.cmb_lv_mode.blockSignals(True); self.cmb_lv_mode.setCurrentText(lv.lv_black_mode)
        self.cmb_lv_mode.blockSignals(False)
        self._on_lv_mode(lv.lv_black_mode)

    def read_levels(self) -> LevelsParams:
        return self._levels_params()

    def _levels_params(self) -> LevelsParams:
        lv = self._levels
        lv.lv_enable = self.chk_lv.isChecked()
        lv.lv_black_mode = self.cmb_lv_mode.currentText()
        lv.lv_black_k = self.s_lv_k.value()
        lv.lv_black_pct = self.s_lv_pct.value()
        lv.lv_black = self.s_lv_val.value()
        lv.lv_white = self.s_lv_white.value()
        lv.lv_gamma = self.s_lv_gamma.value()
        return lv

    def _on_lv_mode(self, name):
        self.s_lv_k.setVisible(name == "auto")            # show only the active black control
        self.s_lv_pct.setVisible(name == "percentile")
        self.s_lv_val.setVisible(name == "value")
        self._timer.start()

    # ---------------------------------------------------------------- helpers
    def _params(self) -> CorrectionParams:
        c = self.state.correction
        c.vig_strength = self.s_strength.value()
        c.vig_power = self.s_power.value()
        c.k1 = self.s_k1.value()
        c.k2 = self.s_k2.value()
        c.lp_enable = self.chk_lp.isChecked()
        c.lp_cutoff = self.s_lp_cut.value()
        c.lp_shape = self.cmb_lp_shape.currentText()
        c.lp_order = self.spin_lp_order.value()
        c.rotate_deg = self.s_rot.value()
        return c

    def _auto_deskew(self):
        """Estimate the rotation that makes the marker grid upright and set the
        deskew slider. Uses the glyph classifier to pick the correct quadrant."""
        raw = self.state.pipeline.raw_image
        if raw is None:
            self.log("Deskew: open an image first."); return
        import os
        from gridtrack import io
        from glyphtrack import reader as gr
        from glyphtrack.classifier import GlyphClassifier
        model = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reference",
                             "glyph_knn.yml")
        if self._deskew_clf is None:
            if not os.path.exists(model):
                self.lbl_rot.setText("model not found (reference/glyph_knn.yml)"); return
            self._deskew_clf = GlyphClassifier.load(model)
        self.lbl_rot.setText("estimating…"); QtWidgets.QApplication.processEvents()
        c = self._params(); c.rotate_deg = 0.0                   # estimate on un-rotated frame
        base = correct.apply(raw, c)
        deg = gr.estimate_deskew(io.to_uint8(base), self._deskew_clf)
        self.s_rot.set_value(round(deg, 1))
        self.lbl_rot.setText(f"deskew ≈ {deg:.1f}°")
        self.log(f"Deskew: auto-estimated {deg:.1f}°")
        self._recompute()

    def _recompute(self):
        raw = self.state.pipeline.raw_image
        if raw is None:
            return
        p = self._params()
        pre = correct.apply(raw, p)                       # shared optics (pre-levels)
        lv = self._levels_params()
        out = correct.levels(pre, lv)                     # per-image contrast/threshold
        self.state.set_corrected(out)
        shown = raw if self._show_before else out
        self.canvas.set_image(shown)
        self._update_profile(shown)
        self._update_histogram(pre, lv)

    def _update_histogram(self, pre, lv):
        finite = pre[np.isfinite(pre)]
        if finite.size == 0:
            return
        counts, edges = np.histogram(finite, bins=96)
        self.hist_curve.setData(edges, counts.astype(float))
        scale = correct._value_scale(pre)
        black = correct.resolve_black_level(pre, lv) if lv.lv_enable else float("nan")
        self.line_black.setValue(black); self.line_black.setVisible(lv.lv_enable)
        self.line_white.setValue(lv.lv_white * scale); self.line_white.setVisible(lv.lv_enable)
        if lv.lv_enable:
            self.lbl_lv.setText(f"floor ≈ {black:.0f}  ·  white ≈ {lv.lv_white * scale:.0f}  "
                                f"(full {scale:.0f})")
        else:
            self.lbl_lv.setText("disabled")

    def _update_profile(self, img):
        # brightness envelope along the middle rows (dilated so features dominate)
        h = img.shape[0]
        band = img[max(0, h // 2 - 15): h // 2 + 15]
        env = band.max(axis=0)
        self.prof_curve.setData(np.asarray(env, float))

    def _toggle_before(self, on):
        self._show_before = on
        self._recompute()

    def _auto(self):
        raw = self.state.pipeline.raw_image
        if raw is None:
            return
        s, pw = correct.estimate_vignette(raw)
        self.s_strength.set_value(s); self.s_power.set_value(pw)
        self.log(f"auto-estimate vignette: strength={s:.2f}, power={pw:.2f}")
        self._recompute()

    def _reset(self):
        for s, v in ((self.s_strength, 0.0), (self.s_power, 2.0),
                     (self.s_k1, 0.0), (self.s_k2, 0.0)):
            s.set_value(v)
        self._recompute()
