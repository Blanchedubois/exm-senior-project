"""Adjust panel: display (levels, brightness/contrast, gamma, colour, invert,
opacity), processing (dark, background, denoise), copy/apply, presets.

It edits a "target" (an AdjustableChannel). In the side-by-side view a combo
picks which channel; in the single view the target is the view itself.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog,
    QLabel, QMessageBox, QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget,
)

from ..core.adjust import ChannelSettings, bc_from_levels, gamma_to_slider, levels_from_bc, slider_to_gamma
from ..core.processing import BACKGROUND_LABELS, BACKGROUNDS, DENOISE_LABELS, DENOISERS
from ..core.settings_store import LevelStore, SettingsStore
from .adjustable import schedule_save

BG_PARAM = {"percentile": ("Percentile", "%", 0.0, 100.0, 1.0, 5.0),
            "rolling_ball": ("Radius", " px", 4.0, 500.0, 5.0, 50.0)}
DN_PARAM = {"gaussian": ("Sigma", " px", 0.3, 10.0, 0.1, 1.0),
            "median": ("Size", " px", 3.0, 15.0, 2.0, 3.0)}


def _slider(lo, hi) -> QSlider:
    s = QSlider(Qt.Horizontal)
    s.setRange(lo, hi)
    return s


def _level_spin() -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(-1e6, 1e7)
    s.setDecimals(1)
    s.setKeyboardTracking(False)
    return s


class AdjustPanel(QScrollArea):
    message = Signal(str)

    def __init__(self, store: SettingsStore, all_datasets=lambda: [], multi: bool = True,
                 undo_stack=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.undo_stack = undo_stack  # groups multi-channel actions into one undo step
        self.all_datasets = all_datasets
        self.multi = multi
        self.targets: list = []
        self.target = None
        self._refreshing = False
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # fit the width, scroll vertically
        body = QWidget()
        self.setWidget(body)
        self._build(body)
        self._set_enabled(False)

    # ---- UI ------------------------------------------------------------
    def _build(self, body):
        self.channel_combo = QComboBox()
        self.channel_combo.currentIndexChanged.connect(self._on_channel_combo)

        disp = QGroupBox("Display (cosmetic)")
        f = QFormLayout(disp)
        self.min_spin, self.max_spin = _level_spin(), _level_spin()
        for spin in (self.min_spin, self.max_spin):
            spin.setMinimumWidth(60)
        mm = QHBoxLayout()
        mm.addWidget(self.min_spin, 1)
        mm.addWidget(QLabel("–"))
        mm.addWidget(self.max_spin, 1)
        f.addRow("Black/white", mm)
        self.bright = _slider(-100, 100)
        self.contrast = _slider(-100, 100)
        self.gamma = _slider(-100, 100)
        self.gamma_label = QLabel("1.00")
        self.gamma_label.setMinimumWidth(34)
        g = QHBoxLayout()
        g.addWidget(self.gamma, 1)
        g.addWidget(self.gamma_label)
        f.addRow("Brightness", self.bright)
        f.addRow("Contrast", self.contrast)
        f.addRow("Gamma", g)
        self.invert = QCheckBox("Invert")
        self.color_btn = QPushButton("Colour…")
        self.color_reset = QPushButton("Default")
        c = QHBoxLayout()
        c.addWidget(self.color_btn)
        c.addWidget(self.color_reset)
        f.addRow("Colour", c)
        f.addRow("", self.invert)
        self.opacity = _slider(0, 100)
        self.opacity_row_label = QLabel("Merge weight")
        f.addRow(self.opacity_row_label, self.opacity)
        self.auto_btn = QPushButton("Auto contrast")
        self.reset_disp_btn = QPushButton("Reset display")
        b = QHBoxLayout()
        b.addWidget(self.auto_btn)
        b.addWidget(self.reset_disp_btn)
        f.addRow(b)

        proc = QGroupBox("Processing (changes pixel values)")
        f2 = QFormLayout(proc)
        self.dark = QCheckBox("Subtract dark frame")
        f2.addRow(self.dark)
        self.bg_combo = QComboBox()
        for k in BACKGROUNDS:
            self.bg_combo.addItem(BACKGROUND_LABELS[k], k)
        f2.addRow("Background", self.bg_combo)
        self.bg_param_label = QLabel("")
        self.bg_param = QDoubleSpinBox()
        self.bg_param.setKeyboardTracking(False)
        f2.addRow(self.bg_param_label, self.bg_param)
        self.roi_btn = QPushButton("Show region box")
        self.roi_btn.setCheckable(True)
        self.roi_btn.setToolTip("Drag the yellow box onto an empty area; its median is subtracted")
        f2.addRow("", self.roi_btn)
        self.dn_combo = QComboBox()
        for k in DENOISERS:
            self.dn_combo.addItem(DENOISE_LABELS[k], k)
        f2.addRow("Denoise", self.dn_combo)
        self.dn_param_label = QLabel("")
        self.dn_param = QDoubleSpinBox()
        self.dn_param.setKeyboardTracking(False)
        f2.addRow(self.dn_param_label, self.dn_param)

        apply = QGroupBox("Apply")
        v = QVBoxLayout(apply)
        self.copy_btn = QPushButton("Copy to other channels")
        self.copy_btn.setToolTip("Copy processing, gamma and invert (not levels or colour) to the other channels")
        self.all_sets_btn = QPushButton("Apply to all sets")
        self.all_sets_btn.setToolTip("Give every acquisition of this wavelength and objective these settings and levels")
        self.reset_btn = QPushButton("Reset channel")
        for w in (self.copy_btn, self.all_sets_btn, self.reset_btn):
            v.addWidget(w)

        pre = QGroupBox("Presets")
        p = QVBoxLayout(pre)
        self.preset_combo = QComboBox()
        pb = QHBoxLayout()
        self.preset_load = QPushButton("Load")
        self.preset_save = QPushButton("Save…")
        self.preset_delete = QPushButton("Delete")
        for w in (self.preset_load, self.preset_save, self.preset_delete):
            pb.addWidget(w)
        p.addWidget(self.preset_combo)
        p.addLayout(pb)
        hint = QLabel("A preset stores every channel's settings and levels, by wavelength.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 11px;")
        p.addWidget(hint)

        lay = QVBoxLayout(body)
        if self.multi:
            row = QHBoxLayout()
            row.addWidget(QLabel("Channel"))
            row.addWidget(self.channel_combo, 1)
            lay.addLayout(row)
        for w in (disp, proc, apply, pre):
            lay.addWidget(w)
        lay.addStretch(1)
        self.opacity.setVisible(self.multi)
        self.opacity_row_label.setVisible(self.multi)
        self.copy_btn.setVisible(self.multi)

        self.min_spin.valueChanged.connect(self._on_minmax)
        self.max_spin.valueChanged.connect(self._on_minmax)
        self.bright.valueChanged.connect(self._on_bc)
        self.contrast.valueChanged.connect(self._on_bc)
        self.gamma.valueChanged.connect(self._on_gamma)
        self.invert.toggled.connect(lambda on: self._edit("invert", invert=on))
        self.color_btn.clicked.connect(self._pick_color)
        self.color_reset.clicked.connect(lambda: self._edit("color", color=None))
        self.opacity.valueChanged.connect(lambda v: self._edit("opacity", opacity=v / 100))
        self.auto_btn.clicked.connect(lambda: self.target and self.target.auto_contrast())
        self.reset_disp_btn.clicked.connect(self._reset_display)
        self.dark.toggled.connect(lambda on: self._edit_proc(dark=on))
        self.bg_combo.currentIndexChanged.connect(self._on_bg_mode)
        self.bg_param.valueChanged.connect(lambda v: self._edit_proc(bg_param=v))
        self.roi_btn.toggled.connect(self._on_roi_btn)
        self.dn_combo.currentIndexChanged.connect(self._on_dn_mode)
        self.dn_param.valueChanged.connect(lambda v: self._edit_proc(denoise_param=v))
        self.copy_btn.clicked.connect(self._copy_to_others)
        self.all_sets_btn.clicked.connect(self._apply_all_sets)
        self.reset_btn.clicked.connect(self._reset_channel)
        self.preset_save.clicked.connect(self._save_preset)
        self.preset_load.clicked.connect(self._load_preset)
        self.preset_delete.clicked.connect(self._delete_preset)
        self._reload_presets()

    # ---- targets -------------------------------------------------------
    def set_targets(self, targets: list, current=None):
        for t in self.targets:
            try:
                t.adjusted.disconnect(self._on_target_adjusted)
            except (RuntimeError, TypeError):
                pass
        if self.target is not None:
            self._hide_roi(self.target)
        self.targets = list(targets)
        for t in self.targets:
            t.adjusted.connect(self._on_target_adjusted)
        self.channel_combo.blockSignals(True)
        self.channel_combo.clear()
        for t in self.targets:
            self.channel_combo.addItem(t.name, t)
        self.channel_combo.blockSignals(False)
        self.select(current if current in self.targets else (self.targets[0] if self.targets else None))

    def select(self, target):
        if self.target is not None and self.target is not target:
            self._hide_roi(self.target)
        self.target = target
        if target is not None and self.multi:
            self.channel_combo.blockSignals(True)
            self.channel_combo.setCurrentIndex(self.targets.index(target))
            self.channel_combo.blockSignals(False)
        self._set_enabled(target is not None)
        self.refresh()

    def set_dark_available(self, available: bool):
        self.dark.setEnabled(available)
        self.dark.setToolTip("" if available else "Open a date folder that contains a DarkCount acquisition")

    def _on_channel_combo(self, i):
        if 0 <= i < len(self.targets):
            self.select(self.targets[i])

    def _on_target_adjusted(self):
        if self.sender() is self.target:
            self.refresh()

    def _set_enabled(self, on: bool):
        self.widget().setEnabled(on)

    # ---- refresh from target -------------------------------------------
    def refresh(self):
        t = self.target
        if t is None or t.ds is None:
            return
        self._refreshing = True
        try:
            s, p = t.settings, t.settings.processing
            lo, hi = t.levels()
            for spin, v in ((self.min_spin, lo), (self.max_spin, hi)):
                spin.setValue(v)
            b, c = bc_from_levels((lo, hi), t.data_range())
            self.bright.setValue(int(round(b)))
            self.contrast.setValue(int(round(c)))
            self.gamma.setValue(gamma_to_slider(s.gamma))
            self.gamma_label.setText(f"{s.gamma:.2f}")
            self.invert.setChecked(s.invert)
            r, g, bl = (int(v * 255) for v in t.color)
            self.color_btn.setStyleSheet(f"background: rgb({r},{g},{bl}); color: {'black' if g > 150 else 'white'};")
            self.color_reset.setEnabled(s.color is not None)
            self.opacity.setValue(int(round(s.opacity * 100)))
            if self.dark.isEnabled():
                self.dark.setChecked(p.dark)
            self.bg_combo.setCurrentIndex(BACKGROUNDS.index(p.background))
            self._config_param(self.bg_param, self.bg_param_label, BG_PARAM.get(p.background), p.bg_param)
            self.roi_btn.setVisible(p.background == "region")
            self.roi_btn.setChecked(t.bg_roi is not None)
            self.dn_combo.setCurrentIndex(DENOISERS.index(p.denoise))
            self._config_param(self.dn_param, self.dn_param_label, DN_PARAM.get(p.denoise), p.denoise_param)
        finally:
            self._refreshing = False

    @staticmethod
    def _config_param(spin, label, spec, value):
        visible = spec is not None
        spin.setVisible(visible)
        label.setVisible(visible)
        if visible:
            name, suffix, lo, hi, step, _default = spec
            label.setText(name)
            spin.setRange(lo, hi)
            spin.setSingleStep(step)
            spin.setSuffix(suffix)
            spin.setDecimals(1)
            spin.setValue(value)

    # ---- edits ---------------------------------------------------------
    def _edit(self, kind, **changes):
        if self._refreshing or self.target is None:
            return
        self.target.set_settings(self.target.settings.with_(**changes), kind)

    def _edit_proc(self, **changes):
        if self._refreshing or self.target is None:
            return
        p = replace(self.target.settings.processing, **changes)
        self.target.set_settings(self.target.settings.with_(processing=p), "processing")

    def _on_minmax(self):
        if not self._refreshing and self.target is not None:
            self.target.set_levels(self.min_spin.value(), self.max_spin.value())

    def _on_bc(self):
        if not self._refreshing and self.target is not None:
            self.target.set_levels(*levels_from_bc(self.bright.value(), self.contrast.value(), self.target.data_range()))

    def _on_gamma(self, v):
        self.gamma_label.setText(f"{slider_to_gamma(v):.2f}")
        self._edit("gamma", gamma=slider_to_gamma(v))

    def _pick_color(self):
        if self.target is None:
            return
        r, g, b = (int(v * 255) for v in self.target.color)
        c = QColorDialog.getColor(QColor(r, g, b), self, f"Colour for {self.target.name}")
        if c.isValid():
            self._edit("color", color=(c.redF(), c.greenF(), c.blueF()))

    def _reset_display(self):
        if self.target is None:
            return
        self._edit("reset", gamma=1.0, invert=False, color=None, opacity=1.0)
        self.target.auto_contrast()

    def _on_bg_mode(self, i):
        if self._refreshing or self.target is None:
            return
        mode = BACKGROUNDS[i]
        changes = {"background": mode}
        spec = BG_PARAM.get(mode)
        if spec and self.target.settings.processing.background != mode:
            changes["bg_param"] = spec[5]
        if mode == "region":
            self.target.show_bg_roi(True)
            changes["roi"] = self.target.current_roi_rect()
        else:
            self._hide_roi(self.target)
        self._edit_proc(**changes)

    def _on_dn_mode(self, i):
        if self._refreshing or self.target is None:
            return
        mode = DENOISERS[i]
        changes = {"denoise": mode}
        spec = DN_PARAM.get(mode)
        if spec and self.target.settings.processing.denoise != mode:
            changes["denoise_param"] = spec[5]
        self._edit_proc(**changes)

    def _on_roi_btn(self, on):
        if not self._refreshing and self.target is not None:
            self.target.show_bg_roi(on)

    def _hide_roi(self, target):
        try:
            target.show_bg_roi(False)
        except RuntimeError:  # panel already deleted
            pass

    # ---- apply ---------------------------------------------------------
    @contextmanager
    def _one_undo_step(self, text: str):
        if self.undo_stack is not None:
            self.undo_stack.beginMacro(text)
        try:
            yield
        finally:
            if self.undo_stack is not None:
                self.undo_stack.endMacro()

    def _copy_to_others(self):
        src = self.target
        if src is None:
            return
        n = 0
        with self._one_undo_step(f"copy {src.name} settings"):
            for t in self.targets:
                if t is src:
                    continue
                t.set_settings(t.settings.with_(processing=src.settings.processing, gamma=src.settings.gamma,
                                                invert=src.settings.invert), "copy")
                n += 1
        self.message.emit(f"Copied {src.name}'s processing, gamma and invert to {n} channel(s)")

    def _apply_all_sets(self):
        src = self.target
        if src is None:
            return
        same = [d for d in self.all_datasets()
                if d.wavelength_nm == src.ds.wavelength_nm and d.objective == src.ds.objective
                and d.folder != src.ds.folder]
        if not same:
            self.message.emit(f"No other {src.name} acquisitions with {src.ds.objective}")
            return
        mode, levels = src.current_mode(), src.levels()
        for d in same:
            self.store.set(d, src.settings)
            self.store.levels[LevelStore.key(d, mode, src.settings.processing)] = levels
        schedule_save(self.store)
        self.message.emit(f"Applied {src.name} settings and {mode} levels to {len(same)} other acquisition(s)")

    def _reset_channel(self):
        if self.target is not None:
            self._hide_roi(self.target)
            self.target.set_settings(ChannelSettings(), "reset")

    # ---- presets -------------------------------------------------------
    def _reload_presets(self, select: str | None = None):
        self.preset_combo.clear()
        names = self.store.list_presets()
        self.preset_combo.addItems(names)
        if select in names:
            self.preset_combo.setCurrentText(select)
        for w in (self.preset_load, self.preset_delete):
            w.setEnabled(bool(names))

    def _save_preset(self):
        if not self.targets:
            return
        name, ok = QInputDialog.getText(self, "Save preset", "Preset name:")
        if not ok or not name.strip():
            return
        channels = {t.name: {"settings": t.settings, "levels": {t.current_mode(): t.levels()}}
                    for t in self.targets if t.ds is not None}
        self.store.save_preset(name.strip(), channels)
        self._reload_presets(select=name.strip())
        self.message.emit(f"Saved preset '{name.strip()}' ({', '.join(channels)})")

    def _load_preset(self):
        name = self.preset_combo.currentText()
        if not name:
            return
        preset = self.store.load_preset(name)
        used = []
        with self._one_undo_step(f"load preset {name}"):
            for t in self.targets:
                entry = preset.get(t.name)
                if entry is None:
                    continue
                t.set_settings(entry["settings"], "preset", levels=entry["levels"].get(t.current_mode()))
                used.append(t.name)
        self.message.emit(f"Loaded '{name}' for {', '.join(used)}" if used
                          else f"'{name}' has no settings for these channels")

    def _delete_preset(self):
        name = self.preset_combo.currentText()
        if name and QMessageBox.question(self, "Delete preset", f"Delete preset '{name}'?") == QMessageBox.Yes:
            self.store.delete_preset(name)
            self._reload_presets()
