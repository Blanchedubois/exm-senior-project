"""
gui.correct_panel
=================
Stage-1 control panel: vignette, lens distortion, FFT low-pass, deskew rotation,
and a per-image contrast/threshold (levels) remap -- with live preview, an
intensity histogram and a mid-row brightness profile. All maths is delegated to
`rwtag.correct` (headless).

Rebuilt from the Point-Tracking GUI's `stage1_correct.py`. Differences:
  * levels live in shared PipelineState (per-image), not panel-local;
  * shared vs per-image is a per-section toggle in each group header;
  * interactive preview computes on a downsampled copy; the full-resolution
    result is rendered on settle and pushed to state (Stage 2 consumes it).
"""
from __future__ import annotations
import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets, QtCore

from rwtag import correct, io
from rwtag.types import CorrectionParams, LevelsParams
from .widgets import SliderSpin, Collapsible

# section keys used for the shared/per-image flags and for selective restore-on-open
SEC_VIGNETTE, SEC_LENS, SEC_LOWPASS, SEC_ROTATE, SEC_LEVELS = \
    "vignette", "lens", "lowpass", "rotate", "levels"
SHARED_DEFAULT = {SEC_VIGNETTE: True, SEC_LENS: True, SEC_LOWPASS: True,
                  SEC_ROTATE: False, SEC_LEVELS: False}


class CorrectPanel(QtWidgets.QWidget):
    def __init__(self, state, canvas, log, parent=None):
        super().__init__(parent)
        self.state = state
        self.canvas = canvas
        self.log = log
        self._show_before = False
        self._raw_prev = None            # cached preview-scale raw for interactive recompute
        self._disp_levels = None         # fixed display range for the active image

        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel("<b>Stage 1 — Correct optics</b>"))
        c = self.state.correction

        # --- vignetting ---
        vg = Collapsible("Vignetting (flat-field)", shared_default=SHARED_DEFAULT[SEC_VIGNETTE])
        self.s_strength = vg.add(SliderSpin("strength", 0.0, 1.0, c.vig_strength, 0.01))
        self.s_power = vg.add(SliderSpin("power", 0.5, 5.0, c.vig_power, 0.05))
        self.b_auto = QtWidgets.QPushButton("Auto-estimate vignette")
        vg.add(self.b_auto)
        root.addWidget(vg)

        # --- lens distortion ---
        ld = Collapsible("Lens distortion", shared_default=SHARED_DEFAULT[SEC_LENS])
        self.s_k1 = ld.add(SliderSpin("k1 (barrel < 0)", -0.30, 0.30, c.k1, 0.005, 4))
        self.s_k2 = ld.add(SliderSpin("k2", -0.10, 0.10, c.k2, 0.002, 4))
        root.addWidget(ld)

        # --- 2-D FFT low-pass denoise ---
        lp = Collapsible("Low-pass (FFT denoise)", shared_default=SHARED_DEFAULT[SEC_LOWPASS])
        self.chk_lp = QtWidgets.QCheckBox("Enable"); self.chk_lp.setChecked(c.lp_enable)
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

        # --- deskew: rotate the whole grid upright ---
        dsk = Collapsible("Rotation (deskew)", shared_default=SHARED_DEFAULT[SEC_ROTATE])
        self.s_rot = dsk.add(SliderSpin("rotation (deg)", -180.0, 180.0, c.rotate_deg, 0.5, 1))
        self.b_deskew = QtWidgets.QPushButton("Auto-deskew (from glyph grid)")
        self.b_deskew.setEnabled(False)
        self.b_deskew.setToolTip("Available after Stage 2 (needs the glyph classifier).")
        dsk.add(self.b_deskew)
        root.addWidget(dsk)

        # --- contrast / threshold (levels) : PER-IMAGE ---
        lv_p = self.state.levels
        lv = Collapsible("Contrast / threshold (levels)", shared_default=SHARED_DEFAULT[SEC_LEVELS])
        self.chk_lv = QtWidgets.QCheckBox("Enable"); self.chk_lv.setChecked(lv_p.lv_enable)
        lv.add(self.chk_lv)
        mrow = QtWidgets.QHBoxLayout()
        self.cmb_lv_mode = QtWidgets.QComboBox()
        self.cmb_lv_mode.addItems(["auto", "percentile", "value"])
        self.cmb_lv_mode.setCurrentText(lv_p.lv_black_mode)
        self.b_lv_auto = QtWidgets.QPushButton("auto-estimate")
        mrow.addWidget(QtWidgets.QLabel("black point")); mrow.addWidget(self.cmb_lv_mode, 1)
        mrow.addWidget(self.b_lv_auto)
        _mw = QtWidgets.QWidget(); _mw.setLayout(mrow); lv.add(_mw)
        self.s_lv_k = lv.add(SliderSpin("floor = bg + k·σ", 0.5, 8.0, lv_p.lv_black_k, 0.5, 2))
        self.s_lv_pct = lv.add(SliderSpin("floor percentile", 0.0, 95.0, lv_p.lv_black_pct, 1.0, 1))
        self.s_lv_val = lv.add(SliderSpin("black value (×full)", 0.0, 1.0, lv_p.lv_black, 0.01, 3))
        self.s_lv_white = lv.add(SliderSpin("white point (×full)", 0.05, 1.0, lv_p.lv_white, 0.01, 3))
        self.s_lv_gamma = lv.add(SliderSpin("gamma", 0.2, 3.0, lv_p.lv_gamma, 0.05, 2))
        self.lbl_lv = QtWidgets.QLabel(); self.lbl_lv.setStyleSheet("color:#999;")
        lv.add(self.lbl_lv)
        root.addWidget(lv)

        self.sections = {SEC_VIGNETTE: vg, SEC_LENS: ld, SEC_LOWPASS: lp,
                         SEC_ROTATE: dsk, SEC_LEVELS: lv}

        # --- intensity histogram (pre-levels) ---
        self.hist = pg.PlotWidget(title="intensity histogram (pre-levels)")
        self.hist.setMaximumHeight(150); self.hist.showGrid(x=True, y=False, alpha=0.2)
        self.hist_curve = self.hist.plot(stepMode="center", fillLevel=0,
                                         brush=(120, 120, 120, 120), pen=pg.mkPen((160, 160, 160)))
        self.line_black = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen((255, 80, 80), width=2))
        self.line_white = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen((90, 200, 255), width=2))
        self.hist.addItem(self.line_black); self.hist.addItem(self.line_white)
        root.addWidget(self.hist)

        # --- view options ---
        vo = Collapsible("View")
        self.chk_grid = QtWidgets.QCheckBox("Straightness grid overlay")
        self.chk_before = QtWidgets.QCheckBox("Show original (before)  [B]")
        vo.add(self.chk_grid); vo.add(self.chk_before)
        root.addWidget(vo)

        # --- row-intensity profile (flatness check) ---
        self.profile = pg.PlotWidget(title="mid-row brightness envelope")
        self.profile.setMaximumHeight(150); self.profile.showGrid(x=False, y=True, alpha=0.2)
        self.prof_curve = self.profile.plot(pen=pg.mkPen((255, 190, 0), width=2))
        root.addWidget(self.profile)

        self.b_reset = QtWidgets.QPushButton("Reset correction")
        root.addWidget(self.b_reset)
        root.addStretch(1)

        # debounce: a fast timer drives the interactive preview (the ONLY thing on
        # the canvas while dragging -> constant resolution, no jumps). A slower,
        # idle-only timer renders the full-resolution result and pushes it to state
        # (Stage 2 consumes it); it never fires mid-drag, so it can't stutter the UI.
        self._prev_timer = QtCore.QTimer(self); self._prev_timer.setSingleShot(True)
        self._prev_timer.setInterval(30); self._prev_timer.timeout.connect(self._recompute_preview)
        self._full_timer = QtCore.QTimer(self); self._full_timer.setSingleShot(True)
        self._full_timer.setInterval(350); self._full_timer.timeout.connect(self._recompute_full)
        self._full_busy = False       # re-entry guard for the heavy full render
        self._full_key = None         # params snapshot of the last full render (skip if unchanged)

        self._wire()
        self.state.imageLoaded.connect(self._on_image_loaded)

    # ---------------------------------------------------------------- wiring
    def _wire(self):
        edit_sliders = (self.s_strength, self.s_power, self.s_k1, self.s_k2, self.s_lp_cut,
                        self.s_rot, self.s_lv_k, self.s_lv_pct, self.s_lv_val,
                        self.s_lv_white, self.s_lv_gamma)
        for s in edit_sliders:
            s.valueChanged.connect(lambda *_: self._edited())
        for chk in (self.chk_lp, self.chk_lv):
            chk.toggled.connect(lambda *_: self._edited())
        self.spin_lp_order.valueChanged.connect(lambda *_: self._edited())
        self.cmb_lp_shape.currentTextChanged.connect(self._on_lp_shape)
        self.s_lp_cut.valueChanged.connect(lambda *_: self._update_lp_label())
        self.cmb_lv_mode.currentTextChanged.connect(self._on_lv_mode)
        self.b_lv_auto.clicked.connect(lambda: self.cmb_lv_mode.setCurrentText("auto"))
        self.chk_grid.toggled.connect(self.canvas.show_grid)
        self.chk_before.toggled.connect(self._toggle_before)
        self.b_auto.clicked.connect(self._auto_vignette)
        self.b_reset.clicked.connect(self._reset)
        self._on_lp_shape(self.cmb_lp_shape.currentText())
        self._on_lv_mode(self.cmb_lv_mode.currentText())

    def _edited(self):
        self._prev_timer.start()
        self._full_timer.start()

    def _on_lp_shape(self, name):
        self.spin_lp_order.setEnabled(name == "butterworth")   # order only for butterworth
        self._update_lp_label()
        self._edited()

    def _update_lp_label(self):
        frac = self.s_lp_cut.value()
        cyc_px = frac * 0.5
        period = 1.0 / cyc_px if cyc_px > 0 else float("inf")
        self.lbl_lp.setText(f"cut-off ≈ {cyc_px:.3f} cyc/px  (period ≥ {period:.1f} px)")

    def _on_lv_mode(self, name):
        self.s_lv_k.setVisible(name == "auto")            # show only the active black control
        self.s_lv_pct.setVisible(name == "percentile")
        self.s_lv_val.setVisible(name == "value")
        self._edited()

    # ---------------------------------------------------------------- params <-> widgets
    def read_correction(self) -> CorrectionParams:
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

    def read_levels(self) -> LevelsParams:
        lv = self.state.levels
        lv.lv_enable = self.chk_lv.isChecked()
        lv.lv_black_mode = self.cmb_lv_mode.currentText()
        lv.lv_black_k = self.s_lv_k.value()
        lv.lv_black_pct = self.s_lv_pct.value()
        lv.lv_black = self.s_lv_val.value()
        lv.lv_white = self.s_lv_white.value()
        lv.lv_gamma = self.s_lv_gamma.value()
        return lv

    def sync_from_state(self):
        """Push the state dataclasses into the widgets (after a session load or a
        selective restore-on-open). Blocks signals so it doesn't retrigger compute."""
        c, lv = self.state.correction, self.state.levels
        pairs = ((self.s_strength, c.vig_strength), (self.s_power, c.vig_power),
                 (self.s_k1, c.k1), (self.s_k2, c.k2), (self.s_lp_cut, c.lp_cutoff),
                 (self.s_rot, c.rotate_deg), (self.s_lv_k, lv.lv_black_k),
                 (self.s_lv_pct, lv.lv_black_pct), (self.s_lv_val, lv.lv_black),
                 (self.s_lv_white, lv.lv_white), (self.s_lv_gamma, lv.lv_gamma))
        for s, v in pairs:
            s.set_value(v)
        for chk, v in ((self.chk_lp, c.lp_enable), (self.chk_lv, lv.lv_enable)):
            chk.blockSignals(True); chk.setChecked(v); chk.blockSignals(False)
        self.cmb_lp_shape.blockSignals(True); self.cmb_lp_shape.setCurrentText(c.lp_shape)
        self.cmb_lp_shape.blockSignals(False)
        self.spin_lp_order.blockSignals(True); self.spin_lp_order.setValue(c.lp_order)
        self.spin_lp_order.blockSignals(False)
        self.cmb_lv_mode.blockSignals(True); self.cmb_lv_mode.setCurrentText(lv.lv_black_mode)
        self.cmb_lv_mode.blockSignals(False)
        self._on_lp_shape(c.lp_shape)
        self._on_lv_mode(lv.lv_black_mode)

    # ---------------------------------------------------------------- shared flags
    def shared_flags(self) -> dict:
        return {k: sec.is_shared() for k, sec in self.sections.items() if k != "view"}

    def set_shared_flags(self, flags: dict):
        for k, on in (flags or {}).items():
            if k in self.sections:
                self.sections[k].set_shared(bool(on))

    def per_image_sections(self):
        """Section keys currently marked per-image (restored from a frame's sidecar)."""
        return [k for k, sec in self.sections.items() if not sec.is_shared()]

    # ---------------------------------------------------------------- image load
    def _on_image_loaded(self):
        raw = self.state.pipeline.raw_image
        if raw is None:
            return
        self._raw_prev = io.preview_downsample(raw)
        self._disp_levels = io.display_levels(raw)   # fixed reference range for this image
        # pin the view extent to the FULL-RES pixel dimensions so preview and full
        # occupy the identical rectangle (the fix for the slider-drag jumping).
        h, w = raw.shape[:2]
        self.canvas.set_extent(w, h)
        self._full_key = None
        self._recompute_preview()                     # instant preview
        self._full_timer.start()                      # sharpen + push to state when idle

    # ---------------------------------------------------------------- compute
    def _recompute_preview(self):
        """Fast, constant-resolution canvas update — the only thing shown while a
        slider is moving. Also refreshes the histogram + profile."""
        img = self._raw_prev
        if img is None:
            return
        c = self.read_correction(); lv = self.read_levels()
        pre = correct.apply(img, c)
        out = correct.levels(pre, lv)
        shown = img if self._show_before else out
        self.canvas.set_image(shown, levels=self._disp_levels)
        self._update_profile(shown)
        self._update_histogram(pre, lv)

    def _full_snapshot(self):
        return (tuple(sorted(self.read_correction().to_dict().items())),
                tuple(sorted(self.read_levels().to_dict().items())),
                self._show_before)

    def _recompute_full(self):
        """Idle-only: render the full-resolution result, push it to state (Stage 2
        consumes it) and sharpen the canvas in place (same extent -> no jump).
        Guarded so it never re-enters and skips work when params are unchanged."""
        raw = self.state.pipeline.raw_image
        if raw is None or self._full_busy:
            return
        key = self._full_snapshot()
        if key == self._full_key:
            return                                    # nothing changed since last full render
        self._full_busy = True
        try:
            c = self.read_correction(); lv = self.read_levels()
            out = correct.process(raw, c, lv)         # full-resolution result
            self.state.set_corrected(out)             # <- Stage 2 consumes this
            shown = raw if self._show_before else out
            self.canvas.set_image(shown, levels=self._disp_levels)
            self._full_key = key
        finally:
            self._full_busy = False

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
        h = img.shape[0]
        band = img[max(0, h // 2 - 15): h // 2 + 15]
        env = band.max(axis=0)
        self.prof_curve.setData(np.asarray(env, float))

    # ---------------------------------------------------------------- buttons
    def _toggle_before(self, on):
        self._show_before = on
        self._recompute_preview()     # instant, constant-res
        self._full_timer.start()      # sharpen when idle

    def _auto_vignette(self):
        raw = self.state.pipeline.raw_image
        if raw is None:
            self.log("Auto-vignette: open an image first."); return
        s, pw = correct.estimate_vignette(raw)
        self.s_strength.set_value(s); self.s_power.set_value(pw)
        self.log(f"auto-estimate vignette: strength={s:.2f}, power={pw:.2f}")
        self._edited()

    def _reset(self):
        for s, v in ((self.s_strength, 0.0), (self.s_power, 2.0),
                     (self.s_k1, 0.0), (self.s_k2, 0.0), (self.s_rot, 0.0)):
            s.set_value(v)
        self.chk_lp.blockSignals(True); self.chk_lp.setChecked(False); self.chk_lp.blockSignals(False)
        self.chk_lv.blockSignals(True); self.chk_lv.setChecked(False); self.chk_lv.blockSignals(False)
        self.read_correction(); self.read_levels()
        self._recompute_preview()
        self._full_timer.start()
