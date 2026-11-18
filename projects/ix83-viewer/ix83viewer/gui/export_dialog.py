"""File ▸ Export… dialog. Collects what is on screen (or every set, for batch)
and runs core.export_jobs in a background thread."""

from __future__ import annotations

import json
import os
import traceback

from PySide6.QtCore import QSettings, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QProgressBar, QPushButton, QSpinBox, QVBoxLayout,
)

from ..core.export import ChannelData, ffmpeg_path
from ..core.export_jobs import ExportOptions, export_batch, export_channels


class _Worker(QThread):
    progress = Signal(str)
    done = Signal(list)
    failed = Signal(str)

    def __init__(self, job):
        super().__init__()
        self.job = job

    def run(self):
        try:
            self.done.emit(self.job(self.progress.emit))
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}\n{traceback.format_exc()}")


class ExportDialog(QDialog):
    """channels: what is on screen. batch: callable(progress, out_dir, prefix, opts) -> files, or None."""

    def __init__(self, channels: list[ChannelData], title: str, default_dir: str, base_name: str,
                 dark=None, batch=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export")
        self.setMinimumWidth(560)
        self.channels, self.title, self.dark, self.batch = channels, title, dark, batch
        self.settings = QSettings("IX83 Analysis Pipeline", "ix83viewer")
        self.worker: _Worker | None = None
        self.out_dir_written: str | None = None
        multi = len(channels) > 1

        self.dir_edit = QLineEdit(self.settings.value("export_dir", default_dir))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        self.name_edit = QLineEdit(base_name)
        top = QFormLayout()
        d = QHBoxLayout()
        d.addWidget(self.dir_edit, 1)
        d.addWidget(browse)
        top.addRow("Folder", d)
        top.addRow("Name", self.name_edit)
        what = QLabel(f"{title}: " + ", ".join(c.label for c in channels))
        what.setWordWrap(True)
        what.setStyleSheet("color: #666;")
        top.addRow("", what)

        q = QGroupBox("Quantitative (processed values, no contrast stretch)")
        fq = QFormLayout(q)
        self.raw = QCheckBox("One TIFF per channel")
        self.dtype = QComboBox()
        self.dtype.addItem("16-bit (rounded)", "uint16")
        self.dtype.addItem("32-bit float (exact mean)", "float32")
        fq.addRow(self.raw, self.dtype)
        self.stack = QCheckBox("Multi-channel stack for Fiji")
        self.ome = QCheckBox("OME-TIFF instead")
        fq.addRow(self.stack, self.ome)

        r = QGroupBox("Rendered (as displayed)")
        fr = QFormLayout(r)
        self.merged = QCheckBox("Merged image")
        self.channel_imgs = QCheckBox("Each channel image")
        self.fmt = QComboBox()
        self.fmt.addItems(["png", "jpg"])
        self.quality = QSpinBox()
        self.quality.setRange(50, 100)
        self.quality.setSuffix(" % quality")
        f1 = QHBoxLayout()
        f1.addWidget(self.fmt)
        f1.addWidget(self.quality)
        fr.addRow(self.merged, self.channel_imgs)
        fr.addRow("Format", f1)
        self.scale_bar = QCheckBox("Burn in scale bar")
        self.aligned = QCheckBox("Apply channel offsets")
        fr.addRow(self.scale_bar, self.aligned)
        f_exp = channels[0].ds.expansion_factor if channels else None
        self.pre_exp = QCheckBox(f"Scale bars in pre-expansion units (÷{f_exp:g})" if f_exp
                                 else "Scale bars in pre-expansion units (no factor set)")
        self.pre_exp.setEnabled(bool(f_exp))
        fr.addRow(self.pre_exp)
        self.figure = QCheckBox("Figure (panels + merge + colour bars)")
        self.fig_fmt = QComboBox()
        self.fig_fmt.addItems(["png", "pdf", "svg"])
        self.dpi = QSpinBox()
        self.dpi.setRange(72, 1200)
        self.dpi.setSuffix(" dpi")
        f2 = QHBoxLayout()
        f2.addWidget(self.fig_fmt)
        f2.addWidget(self.dpi)
        fr.addRow(self.figure, f2)
        self.movie = QCheckBox("Movie through all frames")
        self.movie_fmt = QComboBox()
        self.movie_fmt.addItem("GIF", "gif")
        self.movie_fmt.addItem("MP4" if ffmpeg_path() else "MP4 (needs ffmpeg)", "mp4")
        self.movie_src = QComboBox()
        if multi:
            self.movie_src.addItem("Merged")
        for c in channels:
            self.movie_src.addItem(c.name)
        self.fps = QDoubleSpinBox()
        self.fps.setRange(1, 60)
        self.fps.setSuffix(" fps")
        f3 = QHBoxLayout()
        for w in (self.movie_fmt, self.movie_src, self.fps):
            f3.addWidget(w)
        fr.addRow(self.movie, f3)

        self.batch_check = QCheckBox("Export every set in this date folder (each with its saved settings)")
        self.batch_check.setVisible(batch is not None)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.files = QListWidget()
        self.files.setMaximumHeight(140)
        self.files.hide()
        self.reveal = QPushButton("Show in Finder")
        self.reveal.hide()
        self.reveal.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.out_dir_written)))

        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.export_btn = self.buttons.addButton("Export", QDialogButtonBox.AcceptRole)
        self.buttons.accepted.connect(self._start)
        self.buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(q)
        lay.addWidget(r)
        lay.addWidget(self.batch_check)
        lay.addWidget(self.progress)
        lay.addWidget(self.status)
        lay.addWidget(self.files)
        lay.addWidget(self.reveal)
        lay.addWidget(self.buttons)

        for w in (self.stack, self.ome, self.merged):
            w.setEnabled(multi or batch is not None)
        self.aligned.setEnabled(multi or batch is not None)
        self.fmt.currentTextChanged.connect(lambda t: self.quality.setEnabled(t == "jpg"))
        self._load_options()

    # ---- options -------------------------------------------------------
    def options(self) -> ExportOptions:
        return ExportOptions(
            aligned=self.aligned.isChecked(), raw_tiffs=self.raw.isChecked(), dtype=self.dtype.currentData(),
            hyperstack=self.stack.isChecked(), ome=self.ome.isChecked(), merged=self.merged.isChecked(),
            merged_format=self.fmt.currentText(), jpeg_quality=self.quality.value(),
            channel_images=self.channel_imgs.isChecked(), scale_bar=self.scale_bar.isChecked(),
            pre_expansion=self.pre_exp.isChecked() and self.pre_exp.isEnabled(),
            figure=self.figure.isChecked(), figure_format=self.fig_fmt.currentText(), dpi=self.dpi.value(),
            movie=self.movie.isChecked(), movie_format=self.movie_fmt.currentData(),
            movie_source=self.movie_src.currentText(), fps=self.fps.value())

    def _load_options(self):
        try:
            saved = json.loads(self.settings.value("export_options", "{}"))
        except ValueError:
            saved = {}
        o = ExportOptions(**{k: v for k, v in saved.items() if k in ExportOptions.__dataclass_fields__})
        self.raw.setChecked(o.raw_tiffs)
        self.dtype.setCurrentIndex(max(0, self.dtype.findData(o.dtype)))
        self.stack.setChecked(o.hyperstack)
        self.ome.setChecked(o.ome)
        self.merged.setChecked(o.merged)
        self.channel_imgs.setChecked(o.channel_images)
        self.fmt.setCurrentText(o.merged_format)
        self.quality.setValue(o.jpeg_quality)
        self.quality.setEnabled(o.merged_format == "jpg")
        self.scale_bar.setChecked(o.scale_bar)
        self.pre_exp.setChecked(o.pre_expansion)
        self.aligned.setChecked(o.aligned)
        self.figure.setChecked(o.figure)
        self.fig_fmt.setCurrentText(o.figure_format)
        self.dpi.setValue(o.dpi)
        self.movie.setChecked(o.movie)
        self.movie_fmt.setCurrentIndex(max(0, self.movie_fmt.findData(o.movie_format)))
        self.fps.setValue(o.fps)

    # ---- run -----------------------------------------------------------
    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Export folder", self.dir_edit.text())
        if d:
            self.dir_edit.setText(d)

    def _start(self):
        opts = self.options()
        if opts.movie and opts.movie_format == "mp4" and not ffmpeg_path():
            self.status.setText("MP4 needs ffmpeg (brew install ffmpeg); choose GIF instead.")
            return
        out_dir, base = self.dir_edit.text().strip(), self.name_edit.text().strip() or "export"
        if not out_dir:
            self.status.setText("Choose an export folder.")
            return
        self.settings.setValue("export_dir", out_dir)
        self.settings.setValue("export_options", json.dumps(opts.to_dict()))
        self.out_dir_written = out_dir
        if self.batch_check.isChecked() and self.batch is not None:
            job = lambda progress: self.batch(progress, out_dir, base, opts)  # noqa: E731
        else:
            chs, title, dark = self.channels, self.title, self.dark
            job = lambda progress: export_channels(chs, out_dir, base, opts, title, dark, progress)  # noqa: E731
        self.export_btn.setEnabled(False)
        self.progress.show()
        self.worker = _Worker(job)
        self.worker.progress.connect(self.status.setText)
        self.worker.done.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _done(self, files):
        self.progress.hide()
        self.export_btn.setEnabled(True)
        self.status.setText(f"Wrote {len(files)} file(s) to “{os.path.basename(self.out_dir_written)}”")
        self.status.setToolTip(self.out_dir_written)
        self.files.clear()
        self.files.addItems([os.path.relpath(f, self.out_dir_written) for f in files])
        self.files.show()
        self.reveal.show()
        # Grow to fit the file list instead of squashing the options; wait one
        # event-loop turn so the newly shown widgets have been measured.
        QTimer.singleShot(0, lambda: self.resize(self.width(), max(self.height(), self.sizeHint().height())))

    def _failed(self, message):
        self.progress.hide()
        self.export_btn.setEnabled(True)
        self.status.setText("Export failed: " + message.splitlines()[0])

    def reject(self):
        if self.worker is not None and self.worker.isRunning():
            self.status.setText("Wait for the export to finish…")
            return
        super().reject()
