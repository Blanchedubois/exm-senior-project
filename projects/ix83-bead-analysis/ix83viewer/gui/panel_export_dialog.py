"""Export panels…: one image per set (every channel + overlay) for the whole
date folder, plus the expansion comparison. Runs in the background."""

from __future__ import annotations

import os

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QProgressBar, QPushButton, QSpinBox, QVBoxLayout,
)

from ..core.panels import FULL_RES_DPI
from .export_dialog import _Worker


class PanelExportDialog(QDialog):
    """job(progress, out_dir, prefix, force_dark, pre_expansion, comparison, variants,
    expanded_frame, inferno, dpi) -> list of files."""

    def __init__(self, job, default_dir: str, prefix: str, n_sets: int, mode: str, has_dark: bool,
                 has_expansion: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export panels")
        self.setMinimumWidth(520)
        self.job = job
        self.settings = QSettings("IX83 Bead Analysis", "ix83-bead-analysis")
        self.worker = None

        self.dir_edit = QLineEdit(self.settings.value("panel_export_dir", default_dir))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        self.prefix = QLineEdit(prefix)
        d = QHBoxLayout()
        d.addWidget(self.dir_edit, 1)
        d.addWidget(browse)
        form = QFormLayout()
        form.addRow("Folder", d)
        form.addRow("Name", self.prefix)
        self.resolution = QComboBox()
        self.resolution.addItem("Standard (about 600 px per image)", 200)
        self.resolution.addItem("Full camera resolution (1412 px per image, larger files)", FULL_RES_DPI)
        self.resolution.setCurrentIndex(int(self.settings.value("panel_export_full_res", 0, type=int)))
        form.addRow("Resolution", self.resolution)
        info = QLabel(f"One image per set ({n_sets} sets): every channel and the overlay side by side, with "
                      f"colour bars, scale bars and the acquisition settings. Shown as <b>{mode}</b> "
                      "(the Show setting). The set on screen uses exactly what you see; the others use each "
                      "acquisition's saved Adjust settings and offsets.")
        info.setWordWrap(True)
        self.dark = QCheckBox("Subtract the dark frame in every panel")
        self.dark.setChecked(has_dark)
        self.dark.setEnabled(has_dark)
        if not has_dark:
            self.dark.setToolTip("No DarkCount acquisition in this date folder")
        self.pre_exp = QCheckBox("Scale bars in pre-expansion µm (expanded sets)")
        self.pre_exp.setEnabled(has_expansion)
        self.single = QCheckBox("Expanded sets (3.0×, 4.2× …): show one frame, not an average. Frame:")
        self.single.setChecked(has_expansion)
        self.single.setEnabled(has_expansion)
        self.single.setToolTip("Expanded gels keep moving while a stack is recorded, so averaging frames blurs them")
        self.single_frame = QSpinBox()
        self.single_frame.setRange(0, 999)
        self.single_frame.setEnabled(has_expansion)
        self.single.toggled.connect(self.single_frame.setEnabled)
        self.single_row = QHBoxLayout()
        self.single_row.addWidget(self.single)
        self.single_row.addWidget(self.single_frame)
        self.single_row.addStretch(1)
        self.inferno = QCheckBox("Also: an inferno image of each channel (folder “inferno”)")
        self.inferno.setChecked(True)
        self.no633 = QCheckBox("Also: panels without 633 nm (red)")
        self.no633.setChecked(True)
        self.gray = QCheckBox("Also: grayscale, each channel on its own (no overlay)")
        self.gray.setChecked(True)
        self.inferno_panels = QCheckBox("Also: inferno, each channel on its own (no overlay)")
        self.inferno_panels.setChecked(True)
        self.comparison = QCheckBox("Also make the expansion comparison (1× / 3.0× / 4.2× …)")
        self.comparison.setChecked(True)
        self.comparison.setEnabled(has_expansion)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        self.status = QLabel("")
        self.files = QListWidget()
        self.files.setMaximumHeight(160)
        self.files.hide()
        self.reveal = QPushButton("Show in Finder")
        self.reveal.hide()
        self.reveal.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.dir_edit.text())))
        self.buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.export_btn = self.buttons.addButton("Export panels", QDialogButtonBox.AcceptRole)
        self.buttons.accepted.connect(self._start)
        self.buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(info)
        lay.addLayout(self.single_row)
        for w in (self.dark, self.pre_exp, self.no633, self.gray, self.inferno_panels, self.inferno, self.comparison,
                  self.progress,
                  self.status,
                  self.files, self.reveal,
                  self.buttons):
            lay.addWidget(w)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Export panels to", self.dir_edit.text())
        if d:
            self.dir_edit.setText(d)

    def _start(self):
        out_dir = self.dir_edit.text().strip()
        if not out_dir:
            self.status.setText("Choose a folder.")
            return
        self.settings.setValue("panel_export_dir", out_dir)
        self.settings.setValue("panel_export_full_res", self.resolution.currentIndex())
        prefix = self.prefix.text().strip() or "panels"
        args = (out_dir, prefix, self.dark.isChecked() and self.dark.isEnabled(),
                self.pre_exp.isChecked() and self.pre_exp.isEnabled(),
                self.comparison.isChecked() and self.comparison.isEnabled(),
                ("colour",) + (("no633",) if self.no633.isChecked() else ()) + (("gray",) if self.gray.isChecked() else ())
                + (("inferno",) if self.inferno_panels.isChecked() else ()),
                self.single_frame.value() if (self.single.isChecked() and self.single.isEnabled()) else None,
                self.inferno.isChecked(), self.resolution.currentData())
        self.export_btn.setEnabled(False)
        self.progress.show()
        self.worker = _Worker(lambda progress: self.job(progress, *args))
        self.worker.progress.connect(self.status.setText)
        self.worker.done.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _done(self, files):
        self.progress.hide()
        self.export_btn.setEnabled(True)
        self.status.setText(f"Wrote {len(files)} file(s) to “{os.path.basename(self.dir_edit.text())}”")
        self.files.clear()
        self.files.addItems([os.path.basename(f) for f in files])
        self.files.show()
        self.reveal.show()
        self.adjustSize()

    def _failed(self, message):
        self.progress.hide()
        self.export_btn.setEnabled(True)
        self.status.setText("Export failed: " + message.splitlines()[0])

    def reject(self):
        if self.worker is not None and self.worker.isRunning():
            self.status.setText("Wait for the export to finish…")
            return
        super().reject()
