"""Side-by-side view: one panel per wavelength (+ merged), linked pan/zoom and frame,
with channel alignment (auto, manual nudge, blink/difference check)."""

from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QUndoStack
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QSpinBox, QSplitter,
    QTabWidget, QVBoxLayout, QWidget,
)

from ..core.display import DEFAULT_PRESET, LUT_NAMES
from ..core.offsets import ZERO, Offset, OffsetStore
from ..core.registration import estimate_shift
from ..core.settings_store import SettingsStore
from ..io.scan import FovSet
from .adjust_panel import AdjustPanel
from .align_panel import AlignPanel
from .channel_panel import ChannelPanel, MergedPanel
from .common import MODES
from .undo import connect_undo
from .view_sync import ViewSync
from .workers import LatestOnlyLoader

LAYOUTS = ("Row", "Grid")
NUDGE_PX, FINE_NUDGE_PX = 1.0, 0.1


class GridView(QWidget):
    status = Signal(str)
    export_panels_requested = Signal()
    analysis_changed = Signal()
    analysis_layout_changed = Signal()

    def __init__(self, settings: SettingsStore | None = None, offsets: OffsetStore | None = None,
                 all_datasets=lambda: [], parent=None):
        super().__init__(parent)
        self.settings_store = settings if settings is not None else SettingsStore()
        self.store = offsets if offsets is not None else OffsetStore()
        self.all_datasets = all_datasets
        self.undo_stack = QUndoStack(self)
        self.fov: FovSet | None = None
        self.panels: list[ChannelPanel] = []
        self.reference: ChannelPanel | None = None
        self.offsets: dict[ChannelPanel, Offset] = {}
        self.notes: dict[ChannelPanel, tuple[str, str]] = {}  # panel -> (short note, tooltip)
        self.merged = MergedPanel()
        self.dark_folder: str | None = None
        self.color_preset = DEFAULT_PRESET
        self._fit_pending = False  # zoom-to-fit once every panel of a new set has an image
        self.show_clipping = False
        self.pre_expansion = False
        self._merge_timer = QTimer(self, singleShot=True, interval=40)
        self._merge_timer.timeout.connect(self._refresh_merge)
        self.align_loader = LatestOnlyLoader(self)
        self.view_sync = ViewSync()
        self._build_ui()

    # ---- UI ------------------------------------------------------------
    def _build_ui(self):
        self.set_label = QLabel("Click a Set in the list, or select several acquisitions ▸ right-click ▸ Show side by side")
        self.set_label.setStyleSheet("font-weight: 600;")
        self.notes_label = QLabel()
        self.notes_label.setStyleSheet("color: #d08000;")

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(MODES)
        self.mode_combo.setCurrentText("Mean")
        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_spin = QSpinBox()
        self.lut_combo = QComboBox()
        self.lut_combo.addItems(LUT_NAMES)
        self.layout_combo = QComboBox()
        self.layout_combo.addItems(LAYOUTS)
        self.layout_combo.setCurrentText("Grid")  # 2 x 2 suits laptop screens; Row needs a wide display
        self.merge_check = QCheckBox("Merged panel")
        self.merge_check.setChecked(True)
        self.link_check = QCheckBox("Link zoom")
        self.link_check.setChecked(True)
        self.scale_check = QCheckBox("Scale bar")
        self.scale_check.setChecked(True)
        self.auto_btn = QPushButton("Auto contrast all")
        self.panels_btn = QPushButton("Export panels…")
        self.panels_btn.setToolTip("One image per set (every channel + overlay) for the whole date folder")
        self.readout = QLabel("")
        self.readout.setTextInteractionFlags(Qt.TextSelectableByMouse)

        row1 = QHBoxLayout()
        row1.addWidget(self.set_label)
        row1.addWidget(self.notes_label, 1)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Show"))
        row2.addWidget(self.mode_combo)
        row2.addWidget(QLabel("Frame"))
        row2.addWidget(self.frame_slider, 1)
        row2.addWidget(self.frame_spin)
        row2.addSpacing(8)
        row2.addWidget(QLabel("LUT"))
        row2.addWidget(self.lut_combo)
        row2.addWidget(QLabel("Layout"))
        row2.addWidget(self.layout_combo)
        row3 = QHBoxLayout()
        for w in (self.auto_btn, self.merge_check, self.link_check, self.scale_check):
            row3.addWidget(w)
        row3.addStretch(1)
        row3.addWidget(self.readout)
        row3.addWidget(self.panels_btn)

        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(6)
        self.align = AlignPanel()
        self.adjust = AdjustPanel(self.settings_store, self.all_datasets, multi=True, undo_stack=self.undo_stack)
        self.side_tabs = QTabWidget()
        self.side_tabs.addTab(self.adjust, "Adjust")
        self.side_tabs.addTab(self.align, "Alignment")
        self.side_tabs.setMinimumWidth(260)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.grid_host)
        split.addWidget(self.side_tabs)
        split.setStretchFactor(0, 1)
        split.setCollapsible(0, False)
        split.setCollapsible(1, True)  # drag the divider fully right to hide Adjust/Alignment
        self.side_split = split

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(row1)
        lay.addLayout(row2)
        lay.addWidget(split, 1)
        lay.addLayout(row3)

        self.mode_combo.currentTextChanged.connect(lambda _: self.reload(new_levels=True))
        self.frame_slider.valueChanged.connect(self.frame_spin.setValue)
        self.frame_spin.valueChanged.connect(self.frame_slider.setValue)
        self.frame_spin.valueChanged.connect(lambda _: self.reload())
        self.lut_combo.currentTextChanged.connect(lambda _: self._apply_style())
        self.layout_combo.currentTextChanged.connect(lambda _: self._arrange())
        self.merge_check.toggled.connect(lambda _: self._arrange())
        self.link_check.toggled.connect(lambda _: self._link())
        self.scale_check.toggled.connect(self._apply_scale_bars)
        self.auto_btn.clicked.connect(lambda: [p.auto_contrast() for p in self.panels])
        self.panels_btn.clicked.connect(self.export_panels_requested.emit)
        self.merged.hovered.connect(self._on_hover)
        self.adjust.message.connect(self.status.emit)

        self.align.reference_changed.connect(self._on_reference_changed)
        self.align.selected_changed.connect(lambda _: self._apply_merge_mode())
        self.align.mode_changed.connect(lambda _: self._apply_merge_mode())
        self.align.offset_edited.connect(lambda p, dy, dx: self._set_offset(p, Offset(dy, dx, "manual")))
        self.align.auto_clicked.connect(self.auto_align)
        self.align.reset_auto_clicked.connect(self._reset_to_auto)
        self.align.zero_clicked.connect(self._zero_selected)
        self.align.calibrate_clicked.connect(self._save_calibration)
        self.align.aligned_panels_toggled.connect(lambda _: self._apply_offsets())

        for key, dy, dx in (("Left", 0, -1), ("Right", 0, 1), ("Up", -1, 0), ("Down", 1, 0)):
            for mod, step in (("", NUDGE_PX), ("Shift+", FINE_NUDGE_PX)):
                sc = QShortcut(QKeySequence(mod + key), self, context=Qt.WidgetWithChildrenShortcut)
                sc.activated.connect(lambda dy=dy, dx=dx, step=step: self.nudge(dy * step, dx * step))
        self._sync_frame_controls()

    # ---- public API ----------------------------------------------------
    def set_fov(self, fov: FovSet):
        """Show every wavelength in fov; replicates of one wavelength share a panel."""
        self.fov = fov
        self.undo_stack.clear()  # commands refer to the panels being replaced
        self.view_sync.clear()  # stop syncing views that are about to be deleted
        for p in self.panels:
            p.setParent(None)
            p.deleteLater()
        self.panels = []
        groups: dict = {}
        for d in sorted(fov.members, key=lambda d: d.label):
            groups.setdefault(d.wavelength_nm or d.label, []).append(d)
        # Long wavelength first, i.e. R, G, B for the default colours.
        order = sorted(groups, key=lambda k: (-k, "") if isinstance(k, int) else (1, k))
        for key in order:
            p = ChannelPanel(groups[key], self.settings_store)
            p.hovered.connect(self._on_hover)
            p.image_changed.connect(self._merge_timer.start)
            p.image_changed.connect(self._fit_when_ready)
            p.image_changed.connect(self.analysis_changed.emit)
            p.adjusted.connect(self._merge_timer.start)
            connect_undo(p, self.undo_stack)
            p.merge_toggled.connect(self._merge_timer.start)
            p.dataset_changed.connect(lambda p=p: self._on_dataset_changed(p))
            p.failed.connect(self.status.emit)
            p.set_clipping_overlay(self.show_clipping)
            self.panels.append(p)
        self.set_label.setText(f"Set {fov.label}" if len(fov.label) <= 3 else fov.label)
        self.notes_label.setText("   ".join(fov.notes))
        self._apply_style()
        self.merged.set_panels(self.panels)
        self.reference = _default_reference(self.panels)
        self.align.set_panels(self.panels, self.reference)
        self.adjust.set_targets(self.panels)
        self._load_offsets()
        self._arrange()
        self._link()
        self._apply_scale_bars()
        self._sync_frame_controls()
        self._fit_pending = True
        self.reload(new_levels=True)

    def set_dark_folder(self, folder: str | None):
        self.dark_folder = folder
        self.adjust.set_dark_available(folder is not None)

    def set_color_preset(self, preset: str):
        self.color_preset = preset
        self._apply_style()

    def set_clipping_overlay(self, on: bool):
        self.show_clipping = on
        for p in self.panels:
            p.set_clipping_overlay(on)

    def set_pre_expansion(self, on: bool):
        self.pre_expansion = on
        self._apply_scale_bars()

    def reload(self, new_levels: bool = False):
        mode = self.mode_combo.currentText()
        frame = self.frame_spin.value()
        self.frame_slider.setEnabled(mode == "Frame")
        self.frame_spin.setEnabled(mode == "Frame")
        for p in self.panels:
            p.load(mode, frame, self.dark_folder, new_levels)

    def nudge(self, dy: float, dx: float):
        p = self.align.selected()
        if p is None or p is self.reference:
            return
        if self.align.is_locked(p):
            self.status.emit(f"{_name(p)} is locked")
            return
        o = self.offsets.get(p, ZERO)
        self._set_offset(p, Offset(round(o.dy + dy, 2), round(o.dx + dx, 2), "manual"))

    def auto_align(self):
        ref = self.reference
        if ref is None or ref.shown is None:
            self.status.emit("Auto-align: images are still loading")
            return
        jobs = [(p, p.shown) for p in self.panels
                if p is not ref and not self.align.is_locked(p) and p.shown is not None
                and p.shown.shape == ref.shown.shape]
        if not jobs:
            self.status.emit("Auto-align: nothing to align (all channels locked?)")
            return
        ref_img = ref.shown
        self.align.message.setText("Aligning…")
        self.align.auto_btn.setEnabled(False)
        self.align_loader.request(
            lambda: [(p, estimate_shift(ref_img, img)) for p, img in jobs],
            lambda results: self._on_auto_done(ref, results),
            lambda msg: self._on_auto_failed(msg),
        )

    # ---- alignment internals -------------------------------------------
    def _load_offsets(self):
        self.offsets, self.notes = {}, {}
        for p in self.panels:
            self.offsets[p] = ZERO if p is self.reference else self.store.get(p.ds, self.reference.ds)
        self._apply_offsets()

    def _set_offset(self, p: ChannelPanel, offset: Offset, note: str | None = None, is_auto: bool = False):
        self.offsets[p] = offset
        self.notes[p] = (note, "") if note else ("", "")
        if p is not self.reference:
            self.store.set(p.ds, self.reference.ds, offset, is_auto_result=is_auto)
        self._apply_offsets()

    def _apply_offsets(self):
        aligned = self.align.aligned_check.isChecked()
        for p in self.panels:
            o = self.offsets.get(p, ZERO)
            if aligned:
                p.set_display_offset(o.dy, o.dx)
            else:
                p.set_display_offset(0.0, 0.0)
            self.merged.set_offset(p, o.dy, o.dx)
            note, tip = self.notes.get(p, ("", ""))
            self.align.show_offset(p, o, note or None, tip)
        self.analysis_changed.emit()

    def _on_auto_done(self, ref, results):
        self.align.auto_btn.setEnabled(True)
        if ref is not self.reference:
            return  # reference changed while computing
        use_uncertain = self.align.uncertain_check.isChecked()
        applied, skipped = [], []
        for p, est in results:
            if p not in self.offsets:
                continue
            if est.reliable or use_uncertain:
                self._set_offset(p, Offset(round(est.dy, 2), round(est.dx, 2), "auto", round(est.confidence, 1)),
                                 note=None if est.reliable else f"⚠ uncertain · confidence {est.confidence:.0f}",
                                 is_auto=True)
                applied.append(_name(p))
            else:
                self.notes[p] = (f"⚠ not applied · conf {est.confidence:.0f} · est ({est.dx:+.1f}, {est.dy:+.1f})",
                                 f"Auto-align estimate ({est.dx:+.2f}, {est.dy:+.2f}) px has confidence "
                                 f"{est.confidence:.0f}, below the reliability threshold, so the current "
                                 "offset was kept. Check with Blink or Difference and nudge by hand, or "
                                 "tick 'Apply uncertain results'.")
                skipped.append(_name(p))
        self._apply_offsets()
        msg = []
        if applied:
            msg.append("Applied: " + ", ".join(applied))
        if skipped:
            msg.append("Uncertain, kept current offset: " + ", ".join(skipped))
        self.align.message.setText(". ".join(msg))

    def _on_auto_failed(self, message):
        self.align.auto_btn.setEnabled(True)
        self.align.message.setText("Auto-align failed: " + message.splitlines()[0])

    def _reset_to_auto(self):
        p = self.align.selected()
        if p is None:
            return
        auto = self.store.auto_result(p.ds, self.reference.ds)
        if auto is None:
            self.align.message.setText(f"No auto result saved for {_name(p)} yet; click Auto-align")
            return
        self._set_offset(p, auto)

    def _zero_selected(self):
        p = self.align.selected()
        if p is not None:
            self._set_offset(p, Offset(0.0, 0.0, "manual"))

    def _save_calibration(self):
        p = self.align.selected()
        if p is None:
            return
        o = self.offsets[p]
        self.store.save_calibration(p.ds, self.reference.ds, o)
        self.align.message.setText(
            f"Saved calibration {p.ds.objective}: {_name(p)} → {_name(self.reference)} = "
            f"({o.dx:+.2f}, {o.dy:+.2f}) px. Used for sets without their own offset.")

    def _on_reference_changed(self, panel):
        if panel is None or panel is self.reference:
            return
        self.reference = panel
        self.align.set_reference(self.panels, panel)
        self._load_offsets()
        self._apply_merge_mode()

    def _apply_merge_mode(self):
        self.merged.set_mode(self.align.mode_combo.currentText(), self.reference, self.align.selected())

    def _on_dataset_changed(self, panel):
        self._sync_frame_controls()
        self._apply_scale_bars()
        if panel is self.reference:
            self._load_offsets()
        else:
            self.offsets[panel] = self.store.get(panel.ds, self.reference.ds)
            self.notes[panel] = ("", "")
            self._apply_offsets()

    # ---- layout / display internals ------------------------------------
    def _tiles(self):
        return self.panels + ([self.merged] if self.merge_check.isChecked() else [])

    def _arrange(self):
        while self.grid.count():
            self.grid.takeAt(0)
        self.merged.setVisible(self.merge_check.isChecked())
        tiles = self._tiles()
        if not tiles:
            return
        cols = len(tiles) if self.layout_combo.currentText() == "Row" else math.ceil(math.sqrt(len(tiles)))
        for i, t in enumerate(tiles):
            self.grid.addWidget(t, i // cols, i % cols)
            t.show()
        for c in range(self.grid.columnCount()):
            self.grid.setColumnStretch(c, 1 if c < cols else 0)
        self._link()
        self._merge_timer.start()
        # Tile sizes change with the layout; re-fit once Qt has applied it.
        if self.panels and all(p.shown is not None for p in self.panels):
            self._fit_pending = True
            QTimer.singleShot(0, self._fit_when_ready)
        self.analysis_layout_changed.emit()

    def _link(self):
        tiles = self._tiles()
        self.view_sync.set_views([t.vb for t in tiles] if (tiles and self.link_check.isChecked()) else [])

    def _apply_style(self):
        for p in self.panels:
            p.set_style(self.lut_combo.currentText(), self.color_preset)
        self._merge_timer.start()

    def _apply_scale_bars(self, *_):
        on = self.scale_check.isChecked()
        px = self.panels[0].ds.pixel_size_um if self.panels else None
        self.merged.scale_bar.set_pixel_size(px)
        for t in self.panels + [self.merged]:
            ds = t.ds if t is not self.merged else (self.panels[0].ds if self.panels else None)
            t.scale_bar.set_expansion(ds.expansion_factor if (self.pre_expansion and ds) else None)
            t.scale_bar.set_enabled(on)

    def _sync_frame_controls(self):
        n = max((p.ds.n_frames for p in self.panels), default=1)
        for w in (self.frame_slider, self.frame_spin):
            w.blockSignals(True)
            w.setRange(0, n - 1)
            w.setValue(min(w.value(), n - 1))
            w.blockSignals(False)

    def _fit_when_ready(self):
        if not self._fit_pending or any(p.shown is None for p in self.panels):
            return
        self._fit_pending = False
        # let pending layout changes settle so the fit uses the tiles' final size
        QTimer.singleShot(50, self._fit_now)

    def _fit_now(self):
        if not self.panels or self.panels[0].shown is None:
            return
        h, w = self.panels[0].shown.shape
        rect = QRectF(0, 0, w, h)
        # Fit to the image rect, not autoRange: the merged tile may still be empty,
        # and an empty linked view would drag every panel to a range around (0, 0).
        targets = self._tiles()[:1] if self.link_check.isChecked() else self._tiles()
        for tile in targets:
            tile.vb.setRange(rect, padding=0.01)
            self.view_sync.adopt(tile.vb)

    def set_view(self, rng):
        """Show a saved view (sessions): centre + horizontal extent on every tile."""
        from .session import set_view
        tiles = self._tiles()
        if tiles:
            set_view(tiles[0].vb, rng)
            self.view_sync.adopt(tiles[0].vb)

    def _refresh_merge(self):
        if self.merge_check.isChecked():
            self.merged.refresh({p: (o.dy, o.dx) for p, o in self.offsets.items()})

    def analysis_channels(self):
        return [p for p in self.panels if p.shown is not None]

    def analysis_vbs(self):
        return [t.vb for t in self._tiles()]

    def _on_hover(self, xy):
        for t in self._tiles():
            t.set_cursor(xy)
        if xy is None:
            self.readout.setText("")
            return
        x, y = xy
        parts = []
        for p in self.panels:
            v = p.value_at(x, y)
            if v is not None:
                parts.append(f"{_name(p)}: {v:,.0f}")
        self.readout.setText(f"x {x}, y {y}   " + "   ".join(parts) + "  ADU" if parts else "")


def _name(p: ChannelPanel) -> str:
    return str(p.wavelength_nm or p.ds.label)


def _default_reference(panels: list[ChannelPanel]) -> ChannelPanel:
    """561 if present (middle of the spectrum, sharp nuclei), else the first panel."""
    return next((p for p in panels if p.wavelength_nm == 561), panels[0])
