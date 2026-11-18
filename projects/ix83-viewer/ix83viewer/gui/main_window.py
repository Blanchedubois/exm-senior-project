"""Main window: browser | [single-channel view | side-by-side view] | info."""

from __future__ import annotations

import html
import os

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QUndoGroup, QUndoStack
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QMainWindow, QMessageBox, QSplitter, QTabWidget, QTextBrowser,
    QVBoxLayout,
)

from ..core.checks import check_scan
from ..core.display import COLOR_PRESETS, DEFAULT_PRESET
from ..core.export import ChannelData
from ..core.export_jobs import export_batch
from ..core.panels import export_panels as write_panels
from ..core.offsets import ZERO, OffsetStore
from ..core.settings_store import SettingsStore
from ..io.mm_dataset import MMDataset
from ..io.scan import FovSet, group_by_position, scan_folder
from .adjust_panel import AdjustPanel
from .analysis_dock import AnalysisDock
from .browser_panel import BrowserPanel
from .common import dark_frame
from .export_dialog import ExportDialog
from .panel_export_dialog import PanelExportDialog
from . import session
from .grid_view import GridView
from .info_panel import InfoPanel
from .single_view import SingleChannelView
from .undo import connect_undo

SINGLE_TAB, GRID_TAB = 0, 1


def is_acquisition_folder(path: str) -> bool:
    return os.path.isdir(path) and any(n.endswith(".ome.tif") for n in os.listdir(path))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IX83 Viewer")
        self.settings = QSettings("IX83 Analysis Pipeline", "ix83viewer")
        self._fit_to_screen()

        # One store, so settings and contrast chosen in one view carry to the other.
        self.store = SettingsStore()
        self.scan = None  # last opened date folder
        self.browser = BrowserPanel()
        self.view = SingleChannelView(self.store)
        self.grid = GridView(self.store, OffsetStore(), self.browser.datasets)
        self.info = InfoPanel()
        self.single_undo = QUndoStack(self)
        self.adjust = AdjustPanel(self.store, self.browser.datasets, multi=False, undo_stack=self.single_undo)
        self.adjust.set_targets([self.view])
        self.right_tabs = QTabWidget()
        self.right_tabs.addTab(self.info, "Info")
        self.right_tabs.addTab(self.adjust, "Adjust")
        self.tabs = QTabWidget()
        self.tabs.addTab(self.view, "Single channel")
        self.tabs.addTab(self.grid, "Side by side")

        connect_undo(self.view, self.single_undo)
        self.undo_group = QUndoGroup(self)
        self.undo_group.addStack(self.single_undo)
        self.undo_group.addStack(self.grid.undo_stack)
        self.undo_group.setActiveStack(self.single_undo)
        self.tabs.currentChanged.connect(self._on_tab)

        # Minimum widths stop any panel from being squeezed to nothing when the
        # window is narrower than the panels' preferred sizes (small screens).
        self.browser.setMinimumWidth(220)
        self.right_tabs.setMinimumWidth(260)
        self.tabs.setMinimumWidth(420)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.browser)
        split.addWidget(self.tabs)
        split.addWidget(self.right_tabs)
        split.setStretchFactor(1, 1)
        for i in range(3):
            split.setCollapsible(i, False)
        self.split = split
        self.setCentralWidget(split)
        self.analysis = AnalysisDock(self)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.analysis)
        self.analysis.hide()
        self.analysis.visibilityChanged.connect(self._on_analysis_visible)
        self.analysis.set_host(self.view)

        self.browser.dataset_selected.connect(self._show_dataset)
        self.browser.set_selected.connect(self._show_set)
        self.view.image_changed.connect(self.info.set_image)
        self.info.expansion_changed.connect(lambda _ds: self.set_pre_expansion(self.pre_exp_action.isChecked()))
        self.view.status.connect(lambda m: self.statusBar().showMessage(m, 8000))
        self.grid.status.connect(lambda m: self.statusBar().showMessage(m, 8000))
        self.grid.export_panels_requested.connect(self.export_panels)
        self.adjust.message.connect(lambda m: self.statusBar().showMessage(m, 8000))
        self._build_menus()
        self.statusBar().showMessage("File ▸ Open date folder… to start")

    def _build_menus(self):
        m = self.menuBar().addMenu("&File")
        a = QAction("Open date folder…", self, shortcut=QKeySequence.Open)
        a.triggered.connect(self.choose_date_folder)
        m.addAction(a)
        a = QAction("Add acquisition folder…", self, shortcut=QKeySequence("Ctrl+Shift+O"))
        a.triggered.connect(self.choose_acquisition)
        m.addAction(a)
        m.addSeparator()
        a = QAction("Open session…", self)
        a.triggered.connect(self.open_session)
        m.addAction(a)
        a = QAction("Save session…", self, shortcut=QKeySequence.Save)
        a.triggered.connect(self.save_session)
        m.addAction(a)
        m.addSeparator()
        a = QAction("Export…", self, shortcut=QKeySequence("Ctrl+E"))
        a.triggered.connect(self.export)
        m.addAction(a)
        a = QAction("Export panels for all sets…", self, shortcut=QKeySequence("Ctrl+Shift+E"))
        a.triggered.connect(self.export_panels)
        m.addAction(a)
        m.addSeparator()
        a = QAction("Quit", self, shortcut=QKeySequence.Quit)
        a.triggered.connect(self.close)
        m.addAction(a)

        m = self.menuBar().addMenu("&Edit")
        undo = self.undo_group.createUndoAction(self, "Undo")
        undo.setShortcut(QKeySequence.Undo)
        redo = self.undo_group.createRedoAction(self, "Redo")
        redo.setShortcut(QKeySequence.Redo)
        m.addAction(undo)
        m.addAction(redo)

        t = self.menuBar().addMenu("&Tools")
        a = QAction("Data check…", self)
        a.triggered.connect(self.data_check)
        t.addAction(a)

        m = self.menuBar().addMenu("&View")
        a = self.analysis.toggleViewAction()
        a.setText("Analysis (profile, stats, bleaching, colocalisation)")
        a.setShortcut(QKeySequence("Ctrl+Shift+A"))
        m.addAction(a)
        m.addSeparator()
        self.clip_action = QAction("Highlight saturated / clipped pixels", self, checkable=True)
        self.clip_action.setToolTip("Magenta: camera saturated (65535). Yellow: above the white level.")
        self.clip_action.toggled.connect(self.set_clipping_overlay)
        m.addAction(self.clip_action)
        self.pre_exp_action = QAction("Pre-expansion scale bars (÷ expansion factor)", self, checkable=True)
        self.pre_exp_action.toggled.connect(self.set_pre_expansion)
        m.addAction(self.pre_exp_action)
        m.addSeparator()
        colors = m.addMenu("Wavelength colours")
        group = QActionGroup(self)
        saved = self.settings.value("color_preset", DEFAULT_PRESET)
        if saved not in COLOR_PRESETS:
            saved = DEFAULT_PRESET
        for name in COLOR_PRESETS:
            a = QAction(name, self, checkable=True, checked=name == saved)
            a.triggered.connect(lambda _=False, n=name: self.set_color_preset(n))
            group.addAction(a)
            colors.addAction(a)
        self.set_color_preset(saved)

    # ---- actions -------------------------------------------------------
    def choose_date_folder(self):
        start = self.settings.value("last_folder", os.path.expanduser("~"))
        path = QFileDialog.getExistingDirectory(self, "Open date folder (contains acquisition folders)", start)
        if path:
            self.open_path(path)

    def choose_acquisition(self):
        start = self.settings.value("last_folder", os.path.expanduser("~"))
        path = QFileDialog.getExistingDirectory(self, "Add acquisition folder (contains .ome.tif)", start)
        if path:
            self.open_path(path)

    def open_path(self, path: str):
        """Open a date folder (scan + group) or a single acquisition folder."""
        path = os.path.abspath(path)
        try:
            if is_acquisition_folder(path):
                self.browser.add_dataset(MMDataset.open(path))
                self.settings.setValue("last_folder", os.path.dirname(path))
                return
            scan = scan_folder(path)
        except Exception as e:
            QMessageBox.warning(self, "Could not open", f"{path}\n\n{type(e).__name__}: {e}")
            return
        if not scan.datasets:
            QMessageBox.information(self, "Nothing found", f"No acquisition folders (with .ome.tif) in\n{path}")
            return
        self.settings.setValue("last_folder", path)
        self.scan = scan
        self.browser.set_scan(scan)
        dark = scan.dark()
        self.view.set_dark_folder(dark.folder if dark else None)
        self.adjust.set_dark_available(dark is not None)
        self.grid.set_dark_folder(dark.folder if dark else None)
        msg = f"{os.path.basename(path)}: {len(scan.samples)} acquisitions, {len(scan.calibrations)} calibration"
        if scan.errors:
            msg += f", {len(scan.errors)} could not be read ({', '.join(scan.errors)})"
        self.statusBar().showMessage(msg)
        if scan.samples:
            self.browser.select(scan.samples[0].folder)

    # ---- export --------------------------------------------------------
    def export(self):
        chs, title, base = self._export_channels()
        if not chs:
            QMessageBox.information(self, "Export", "Open an acquisition or a set first.")
            return
        self.store.save()
        dark_folder = self.scan.dark().folder if self.scan and self.scan.dark() else None
        dark = dark_frame(dark_folder) if dark_folder and any(c.settings.processing.dark for c in chs) else None
        batch = None
        if self.scan is not None:
            mode = (self.view if self.tabs.currentIndex() == SINGLE_TAB else self.grid).mode_combo.currentText()
            sets = group_by_position(self.scan.samples)
            preset = self.settings.value("color_preset", DEFAULT_PRESET)

            def batch(progress, out_dir, prefix, opts):
                d = dark_frame(dark_folder) if dark_folder else None
                return export_batch(sets, out_dir, prefix, opts, mode, self.store, self.grid.store, d, preset, progress)
        if self.scan is not None:
            default_dir = os.path.join(os.path.dirname(self.scan.root), "Exports", os.path.basename(self.scan.root))
        else:
            default_dir = os.path.expanduser("~/Desktop/IX83 Exports")
        ExportDialog(chs, title, default_dir, base, dark, batch, self).exec()

    def export_panels(self):
        """One panel per set for the whole date folder (+ expansion comparison)."""
        if self.scan is None:
            QMessageBox.information(self, "Export panels", "Open a date folder first.")
            return
        self.store.save()
        sets = group_by_position(self.scan.samples)
        g = self.grid
        mode = g.mode_combo.currentText() if g.panels else "Mean"
        current = None
        if g.fov is not None and g.panels:  # the set on screen is exported exactly as shown
            shown, _, _ = self._grid_export_channels()
            want = {m.folder for m in g.fov.members}
            match = next((s for s in sets if {m.folder for m in s.members} == want), None)
            if match is not None and shown:
                current = (match, shown)
        dark_folder = self.scan.dark().folder if self.scan.dark() else None
        preset = self.settings.value("color_preset", DEFAULT_PRESET)
        offsets = g.store

        def job(progress, out_dir, prefix, force_dark, pre_expansion, comparison, variants, expanded_frame, inferno,
                dpi):
            dark = dark_frame(dark_folder) if dark_folder else None
            return write_panels(sets, out_dir, prefix, mode, self.store, offsets, dark, preset, pre_expansion,
                                current, progress, comparison, force_dark, variants, expanded_frame, inferno, dpi)

        date = os.path.basename(self.scan.root)
        default_dir = os.path.join(os.path.dirname(self.scan.root), "Exports", date, "panels")
        has_expansion = any(d.expansion_factor for d in self.scan.samples)
        PanelExportDialog(job, default_dir, date, len(sets), mode, dark_folder is not None, has_expansion,
                          self).exec()

    def _export_channels(self):
        """Snapshot of what the current tab shows, as ChannelData."""
        date = os.path.basename(self.scan.root) if self.scan else ""
        lut = lambda t: t.colormap().getLookupTable(nPts=256, alpha=False)[:, :3]  # noqa: E731
        if self.tabs.currentIndex() != SINGLE_TAB:
            return self._grid_export_channels()
        v = self.view
        if v.shown is None:
            return [], "", ""
        mode = v.current_mode()
        ch = ChannelData(v.ds, v.shown, v.levels(), v.settings, v.color, ZERO, mode,
                         v.frame_spin.value(), lut(v))
        shown = mode if mode != "Frame" else f"frame{v.frame_spin.value()}"
        return [ch], v.ds.label, "_".join(filter(None, (date, v.ds.label, shown)))

    def _grid_export_channels(self):
        """Snapshot of the side-by-side view, as ChannelData."""
        date = os.path.basename(self.scan.root) if self.scan else ""
        lut = lambda t: t.colormap().getLookupTable(nPts=256, alpha=False)[:, :3]  # noqa: E731
        g = self.grid
        panels = [p for p in g.panels if p.shown is not None]
        if not panels:
            return [], "", ""
        mode = g.mode_combo.currentText()
        chs = [ChannelData(p.ds, p.shown, p.levels(), p.settings, p.color, g.offsets.get(p, ZERO), mode,
                           g.frame_spin.value(), lut(p), p.merge_check.isChecked()) for p in panels]
        label = g.fov.label if g.fov else "Selection"
        title = f"{date} Set {label}" if len(label) <= 3 else f"{date} {label}"
        shown = mode if mode != "Frame" else f"frame{g.frame_spin.value()}"
        return chs, title.strip(), "_".join(filter(None, (date, f"Set_{label}" if len(label) <= 3 else label, shown)))

    def set_color_preset(self, name: str):
        self.settings.setValue("color_preset", name)
        self.browser.set_color_preset(name)
        self.view.set_color_preset(name)
        self.grid.set_color_preset(name)

    def data_check(self):
        if self.scan is None:
            QMessageBox.information(self, "Data check", "Open a date folder first.")
            return
        findings = check_scan(self.scan)
        rows = "".join(
            f"<tr><td style='color:{'#d08000' if f.level == 'warning' else '#666'}'>"
            f"{'⚠' if f.level == 'warning' else 'ℹ'}</td><td><b>{html.escape(f.subject)}</b></td>"
            f"<td>{html.escape(f.message)}</td></tr>" for f in findings)
        n_warn = sum(f.level == "warning" for f in findings)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Data check: {os.path.basename(self.scan.root)}")
        dlg.resize(820, 520)
        text = QTextBrowser()
        text.setHtml(f"<p>{len(self.scan.datasets)} acquisitions, {n_warn} warning(s), "
                     f"{len(findings) - n_warn} note(s).</p><table cellspacing=6>{rows}</table>")
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dlg.reject)
        lay = QVBoxLayout(dlg)
        lay.addWidget(text)
        lay.addWidget(buttons)
        dlg.exec()

    def set_clipping_overlay(self, on: bool):
        self.view.set_clipping_overlay(on)
        self.grid.set_clipping_overlay(on)

    def set_pre_expansion(self, on: bool):
        self.view.set_pre_expansion(on)
        self.grid.set_pre_expansion(on)
        self.analysis.set_pre_expansion(on)

    def _host(self):
        return self.view if self.tabs.currentIndex() == SINGLE_TAB else self.grid

    def _fit_to_screen(self):
        """Saved size if any, else up to 1500 x 950 but never larger than the screen."""
        geometry = self.settings.value("window_geometry")
        if geometry is not None and self.restoreGeometry(geometry):
            return
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().availableGeometry()
        w, h = min(1500, int(screen.width() * 0.95)), min(950, int(screen.height() * 0.92))
        self.resize(w, h)
        self.move(screen.x() + (screen.width() - w) // 2, screen.y() + (screen.height() - h) // 2)

    def showEvent(self, e):
        super().showEvent(e)
        if getattr(self, "_shown_once", False):
            return
        self._shown_once = True
        state = self.settings.value("splitter_state")
        if state is None or not self.split.restoreState(state):
            # proportional split of whatever width the window really got
            w = self.split.width()
            left, right = max(220, int(w * 0.2)), max(260, int(w * 0.2))
            self.split.setSizes([left, max(420, w - left - right), right])

    def _update_title(self):
        if self.tabs.currentIndex() == SINGLE_TAB:
            name = self.view.ds.label if self.view.ds else ""
        else:
            label = self.grid.fov.label if self.grid.fov else ""
            name = f"Set {label}" if label and len(label) <= 3 else label
        self.setWindowTitle(f"IX83 Viewer — {name}" if name else "IX83 Viewer")

    def _on_tab(self, index: int):
        self.right_tabs.setVisible(index == SINGLE_TAB)
        self._update_title()
        self.analysis.set_host(self._host())
        self.undo_group.setActiveStack(self.single_undo if index == SINGLE_TAB else self.grid.undo_stack)

    def closeEvent(self, e):
        self.settings.setValue("window_geometry", self.saveGeometry())
        self.settings.setValue("splitter_state", self.split.saveState())
        self.store.save()
        try:
            session.save(self, session.last_session_path())
        except Exception as err:  # never block quitting
            print(f"Could not save last session: {err}")
        super().closeEvent(e)

    # ---- sessions ------------------------------------------------------
    def save_session(self):
        start = os.path.join(self.settings.value("session_dir", os.path.expanduser("~")), "session.ix83session")
        path, _ = QFileDialog.getSaveFileName(self, "Save session", start, "IX83 session (*.ix83session)")
        if path:
            if not path.endswith(".ix83session"):
                path += ".ix83session"
            session.save(self, path)
            self.settings.setValue("session_dir", os.path.dirname(path))
            self.statusBar().showMessage(f"Saved session {os.path.basename(path)}", 8000)

    def open_session(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open session", self.settings.value("session_dir", ""),
                                              "IX83 session (*.ix83session)")
        if path:
            self.load_session(path)

    def load_session(self, path: str) -> bool:
        try:
            problems = session.load(self, path)
        except Exception as e:
            QMessageBox.warning(self, "Session", f"Could not open session:\n{type(e).__name__}: {e}")
            return False
        msg = f"Opened session {os.path.basename(path)}"
        if problems:
            msg += " — " + "; ".join(problems)
        self.statusBar().showMessage(msg, 15000)
        return True

    def restore_last_session(self) -> bool:
        path = session.last_session_path()
        return os.path.exists(path) and self.load_session(path)

    def _on_analysis_visible(self, on: bool):
        if on:
            self.resizeDocks([self.analysis], [320], Qt.Vertical)
            self.analysis.set_host(self._host())

    def _show_dataset(self, ds: MMDataset):
        self.tabs.setCurrentIndex(SINGLE_TAB)
        self.single_undo.clear()  # undo history belongs to the previous acquisition
        self.info.set_dataset(ds)
        self.view.set_dataset(ds)
        self._update_title()

    def _show_set(self, fov: FovSet):
        if not fov.members:
            return
        self.tabs.setCurrentIndex(GRID_TAB)
        self.grid.set_fov(fov)
        self._update_title()
