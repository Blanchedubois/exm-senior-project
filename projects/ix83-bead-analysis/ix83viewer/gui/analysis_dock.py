"""Analysis dock (View ▸ Analysis): line profile, region statistics,
photobleaching curve and colocalisation for the channels on screen.

A "host" (the single view or the side-by-side view) provides:
  analysis_channels() -> list of AdjustableChannel-like objects with an image
  analysis_vbs()      -> ViewBoxes; the first gets the draggable line/box,
                         the others show non-interactive mirrors
  analysis_changed    -> Qt signal when images or offsets change (re-measure)
  analysis_layout_changed -> Qt signal when the ViewBoxes change (re-place shapes)
Shapes live in view coordinates; each channel's display offset (alignment)
is removed before sampling, so measurements compare the same sample point.
"""

from __future__ import annotations

import csv

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDockWidget, QFileDialog, QGraphicsRectItem, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from ..core.analysis import (
    bleach_curve, colocalization, fit_bleaching, joint_histogram, line_profile, rect_mask, region_stats,
)
from ..core.corrections import subtract_dark
from ..core.registration import apply_shift
from .common import dark_frame
from .workers import LatestOnlyLoader

_SHAPE_PEN = pg.mkPen((255, 255, 255), width=2)
_MIRROR_PEN = pg.mkPen((255, 255, 255, 160), width=1, style=Qt.DashLine)
STAT_COLUMNS = ("mean", "median", "std", "min", "max", "snr", "saturated", "pixels", "area_um2")


def _pen(color, width=2):
    r, g, b = (int(c * 255) for c in color)
    if r + g + b < 120:  # keep dark custom colours visible on the black plot
        r, g, b = min(255, r + 80), min(255, g + 80), min(255, b + 80)
    return pg.mkPen((r, g, b), width=width)


def _offset(ch):
    return getattr(ch, "display_offset", (0.0, 0.0))


class AnalysisDock(QDockWidget):
    def __init__(self, parent=None):
        super().__init__("Analysis", parent)
        self.setObjectName("analysis_dock")
        self.host = None
        self.pre_expansion = False
        self.line_pts: tuple[tuple[float, float], tuple[float, float]] | None = None
        self.box_rect: tuple[float, float, float, float] | None = None
        self.line_roi = self.box_roi = None
        self._roi_vb = None  # ViewBox holding the interactive shapes
        self._mirrors: list = []
        self._bleach: dict | None = None
        self.loader = LatestOnlyLoader(self)
        self._build()

    # ---- UI ------------------------------------------------------------
    def _build(self):
        self.tabs = QTabWidget()
        self.setWidget(self.tabs)

        # profile
        w = QWidget()
        v = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.line_btn = QPushButton("Draw line")
        self.line_btn.setCheckable(True)
        self.profile_csv = QPushButton("Export CSV")
        self.profile_info = QLabel("Click Draw line, then drag its ends on the first image.")
        bar.addWidget(self.line_btn)
        bar.addWidget(self.profile_csv)
        bar.addWidget(self.profile_info, 1)
        self.profile_plot = pg.PlotWidget()
        self.profile_plot.addLegend(offset=(-10, 10))
        self.profile_plot.setLabel("left", "Intensity", units="")
        v.addLayout(bar)
        v.addWidget(self.profile_plot, 1)
        self.tabs.addTab(w, "Line profile")

        # region stats
        w = QWidget()
        v = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.box_btn = QPushButton("Draw box")
        self.box_btn.setCheckable(True)
        self.stats_csv = QPushButton("Export CSV")
        self.stats_info = QLabel("Whole image. Click Draw box to measure a region.")
        bar.addWidget(self.box_btn)
        bar.addWidget(self.stats_csv)
        bar.addWidget(self.stats_info, 1)
        self.table = QTableWidget(0, len(STAT_COLUMNS))
        self.table.setHorizontalHeaderLabels(["Mean", "Median", "Std", "Min", "Max", "SNR (mean/std)",
                                              "Saturated px", "Pixels", "Area µm²"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        v.addLayout(bar)
        v.addWidget(self.table, 1)
        self.tabs.addTab(w, "Region stats")

        # bleaching
        w = QWidget()
        v = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.bleach_btn = QPushButton("Compute over all frames")
        self.bleach_norm = QCheckBox("Normalise to first frame")
        self.bleach_norm.setChecked(True)
        self.bleach_csv = QPushButton("Export CSV")
        bar.addWidget(self.bleach_btn)
        bar.addWidget(self.bleach_norm)
        bar.addWidget(self.bleach_csv)
        bar.addStretch(1)
        self.bleach_info = QLabel("Mean of the box (or whole image) in every raw frame, "
                                  "dark-subtracted if that channel subtracts dark; fit I = A·e^(−t/τ) + C.")
        self.bleach_info.setWordWrap(True)
        self.bleach_plot = pg.PlotWidget()
        self.bleach_plot.addLegend(offset=(-10, 10))
        self.bleach_plot.setLabel("bottom", "Time (s)")
        v.addLayout(bar)
        v.addWidget(self.bleach_info)
        v.addWidget(self.bleach_plot, 1)
        self.tabs.addTab(w, "Bleaching")

        # colocalisation
        w = QWidget()
        h = QHBoxLayout(w)
        left = QVBoxLayout()
        row = QHBoxLayout()
        self.coloc_a, self.coloc_b = QComboBox(), QComboBox()
        self.coloc_thr = QComboBox()
        self.coloc_thr.addItems(["Otsu thresholds", "No threshold"])
        row.addWidget(QLabel("A"))
        row.addWidget(self.coloc_a)
        row.addWidget(QLabel("B"))
        row.addWidget(self.coloc_b)
        left.addLayout(row)
        left.addWidget(self.coloc_thr)
        self.coloc_result = QLabel("")
        self.coloc_result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.coloc_result.setWordWrap(True)
        left.addWidget(self.coloc_result, 1)
        note = QLabel("Uses the box if drawn, the displayed (processed) images and the alignment offsets. "
                      "Channels labelling different structures will score low.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #888; font-size: 11px;")
        left.addWidget(note)
        self.coloc_plot = pg.PlotWidget()
        self.coloc_img = pg.ImageItem()
        self.coloc_plot.addItem(self.coloc_img)
        self.coloc_plot.setAspectLocked(False)
        h.addLayout(left, 1)
        h.addWidget(self.coloc_plot, 1)
        self.tabs.addTab(w, "Colocalisation")

        self.line_btn.toggled.connect(self._toggle_line)
        self.box_btn.toggled.connect(self._toggle_box)
        self.profile_csv.clicked.connect(self._export_profile)
        self.stats_csv.clicked.connect(self._export_stats)
        self.bleach_btn.clicked.connect(self._compute_bleaching)
        self.bleach_norm.toggled.connect(lambda _: self._plot_bleaching())
        self.bleach_csv.clicked.connect(self._export_bleaching)
        self.coloc_a.currentIndexChanged.connect(lambda _: self._update_coloc())
        self.coloc_b.currentIndexChanged.connect(lambda _: self._update_coloc())
        self.coloc_thr.currentIndexChanged.connect(lambda _: self._update_coloc())
        self.tabs.currentChanged.connect(lambda _: self.refresh())

    # ---- host binding --------------------------------------------------
    def set_host(self, host):
        if self.host is not None:
            for sig, slot in ((self.host.analysis_changed, self._on_data_changed),
                              (self.host.analysis_layout_changed, self._on_host_changed)):
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        self._remove_shapes()
        self.host = host
        self._bleach = None
        self.bleach_plot.clear()
        if host is not None:
            host.analysis_changed.connect(self._on_data_changed)
            host.analysis_layout_changed.connect(self._on_host_changed)
        self._on_host_changed()

    def set_pre_expansion(self, on: bool):
        self.pre_expansion = on
        self.refresh()

    def _channels(self):
        return [c for c in self.host.analysis_channels() if c.shown is not None] if self.host else []

    def _on_host_changed(self):
        self._remove_shapes()
        self._place_shapes()
        self._on_data_changed()

    def _on_data_changed(self):
        if not self.isVisible():
            return
        names = [c.name for c in self._channels()]
        for combo, pick in ((self.coloc_a, 0), (self.coloc_b, 1)):
            keep = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            combo.setCurrentIndex(names.index(keep) if keep in names else min(pick, len(names) - 1))
            combo.blockSignals(False)
        self.refresh()

    # ---- shapes --------------------------------------------------------
    def _vbs(self):
        return self.host.analysis_vbs() if self.host else []

    def _default_geometry(self):
        chs = self._channels()
        h, w = chs[0].shown.shape if chs else (512, 512)
        return h, w

    def _toggle_line(self, on):
        if on and self.line_pts is None:
            h, w = self._default_geometry()
            self.line_pts = ((w * 0.3, h * 0.5), (w * 0.7, h * 0.5))
        if not on:
            self.line_pts = None
        self._remove_shapes()
        self._place_shapes()
        self.refresh()

    def _toggle_box(self, on):
        if on and self.box_rect is None:
            h, w = self._default_geometry()
            self.box_rect = (w * 0.4, h * 0.4, w * 0.2, h * 0.2)
        if not on:
            self.box_rect = None
        self._remove_shapes()
        self._place_shapes()
        self.refresh()

    def _place_shapes(self):
        vbs = self._vbs()
        if not vbs:
            return
        main, others = vbs[0], vbs[1:]
        self._roi_vb = main
        if self.line_pts is not None:
            self.line_roi = pg.LineSegmentROI(list(self.line_pts), pen=_SHAPE_PEN)
            self.line_roi.setZValue(30)
            main.addItem(self.line_roi)
            self.line_roi.sigRegionChanged.connect(self._on_line_moved)
            for vb in others:
                m = pg.PlotCurveItem(pen=_MIRROR_PEN)
                m.setZValue(30)
                vb.addItem(m, ignoreBounds=True)
                self._mirrors.append(("line", vb, m))
        if self.box_rect is not None:
            x, y, w, h = self.box_rect
            self.box_roi = pg.RectROI((x, y), (w, h), pen=_SHAPE_PEN)
            self.box_roi.setZValue(30)
            main.addItem(self.box_roi)
            self.box_roi.sigRegionChanged.connect(self._on_box_moved)
            self.box_roi.sigRegionChangeFinished.connect(lambda: self._update_coloc())
            for vb in others:
                m = QGraphicsRectItem()
                m.setPen(QPen(_MIRROR_PEN))
                m.setZValue(30)
                vb.addItem(m, ignoreBounds=True)
                self._mirrors.append(("box", vb, m))
        self._update_mirrors()

    def _remove_shapes(self):
        for roi in (self.line_roi, self.box_roi):
            if roi is not None and self._roi_vb is not None:
                try:
                    self._roi_vb.removeItem(roi)
                except RuntimeError:  # host already deleted
                    pass
        self.line_roi = self.box_roi = None
        for _, vb, m in self._mirrors:
            try:
                vb.removeItem(m)
            except RuntimeError:
                pass
        self._mirrors = []

    def _on_line_moved(self):
        pts = [self.line_roi.mapToParent(h["item"].pos()) for h in self.line_roi.handles]
        self.line_pts = ((pts[0].x(), pts[0].y()), (pts[1].x(), pts[1].y()))
        self._update_mirrors()
        if self.tabs.currentIndex() == 0:
            self._update_profile()

    def _on_box_moved(self):
        p, s = self.box_roi.pos(), self.box_roi.size()
        self.box_rect = (p.x(), p.y(), s.x(), s.y())
        self._update_mirrors()
        if self.tabs.currentIndex() == 1:
            self._update_stats()

    def _update_mirrors(self):
        for kind, _, m in self._mirrors:
            if kind == "line" and self.line_pts:
                (x0, y0), (x1, y1) = self.line_pts
                m.setData([x0, x1], [y0, y1])
            elif kind == "box" and self.box_rect:
                m.setRect(QRectF(*self.box_rect))

    # ---- measurements --------------------------------------------------
    def refresh(self):
        i = self.tabs.currentIndex()
        if i == 0:
            self._update_profile()
        elif i == 1:
            self._update_stats()
        elif i == 3:
            self._update_coloc()

    def _distance_scale(self, ch):
        px = ch.ds.pixel_size_um
        if not px:
            return 1.0, "Distance (px)"
        f = getattr(ch.ds, "expansion_factor", None)
        if self.pre_expansion and f:
            return px / f, "Distance (µm, pre-expansion)"
        return px, "Distance (µm)"

    def _update_profile(self):
        self.profile_plot.clear()
        chs = self._channels()
        if not chs or self.line_pts is None:
            return
        (x0, y0), (x1, y1) = self.line_pts
        scale, label = self._distance_scale(chs[0])
        self.profile_plot.setLabel("bottom", label)
        self._profile_rows = []
        for ch in chs:
            dy, dx = _offset(ch)
            d, vals = line_profile(ch.shown, (x0 - dx, y0 - dy), (x1 - dx, y1 - dy))
            self.profile_plot.plot(d * scale, vals, pen=_pen(ch.color), name=ch.name)
            self._profile_rows.append((ch.name, d * scale, vals))
        self.profile_info.setText(f"Length {np.hypot(x1 - x0, y1 - y0) * scale:.1f} "
                                  f"{'µm' if chs[0].ds.pixel_size_um else 'px'}")

    def _update_stats(self):
        chs = self._channels()
        self.table.setRowCount(len(chs))
        self.table.setVerticalHeaderLabels([c.name for c in chs])
        self._stats_rows = []
        for r, ch in enumerate(chs):
            rect = None
            if self.box_rect is not None:
                dy, dx = _offset(ch)
                x, y, w, h = self.box_rect
                rect = (x - dx, y - dy, w, h)
            s = region_stats(ch.shown, rect, getattr(ch, "raw", None), ch.ds.pixel_size_um)
            self._stats_rows.append((ch.name, s))
            for c, key in enumerate(STAT_COLUMNS):
                v = s.get(key)
                text = "" if v is None else (f"{v:,}" if isinstance(v, int) else f"{v:,.2f}")
                self.table.setItem(r, c, QTableWidgetItem(text))
        self.stats_info.setText("Box" if self.box_rect else "Whole image")

    # bleaching (background thread)
    def _compute_bleaching(self):
        chs = self._channels()
        if not chs:
            return
        jobs = []
        for ch in chs:
            dy, dx = _offset(ch)
            rect = None
            if self.box_rect is not None:
                x, y, w, h = self.box_rect
                rect = (x - dx, y - dy, w, h)
            dark_folder = getattr(ch, "dark_folder", None) if ch.settings.processing.dark else None
            jobs.append((ch.name, ch.color, ch.ds, rect, dark_folder))
        self.bleach_btn.setEnabled(False)
        self.bleach_info.setText("Reading every frame…")
        self.loader.request(lambda: [_bleach_job(*j) for j in jobs], self._on_bleach_done,
                            lambda msg: self._on_bleach_failed(msg))

    def _on_bleach_done(self, results):
        self.bleach_btn.setEnabled(True)
        self._bleach = {name: r for name, r in results}
        self._plot_bleaching()

    def _on_bleach_failed(self, msg):
        self.bleach_btn.setEnabled(True)
        self.bleach_info.setText("Failed: " + msg.splitlines()[0])

    def _plot_bleaching(self):
        self.bleach_plot.clear()
        if not self._bleach:
            return
        norm = self.bleach_norm.isChecked()
        self.bleach_plot.setLabel("left", "Intensity / first frame" if norm else "Mean intensity (ADU)")
        lines = []
        for name, r in self._bleach.items():
            t, vals, fit, color = r["t"], r["values"], r["fit"], r["color"]
            k = vals[0] if norm and vals[0] else 1.0
            pen = _pen(color)
            self.bleach_plot.plot(t, vals / k, pen=pen, name=name)
            loss = 100 * (1 - vals[-1] / vals[0]) if vals[0] else 0
            text = f"{name}: {loss:.0f}% lower after {t[-1]:.0f} s"
            if fit is not None:
                tt = np.linspace(t[0], t[-1], 200)
                self.bleach_plot.plot(tt, (fit.amplitude * np.exp(-(tt - t[0]) / fit.tau_s) + fit.offset) / k,
                                      pen=pg.mkPen(pen.color(), width=1, style=Qt.DashLine))
                text += f", τ = {fit.tau_s:.1f} s (half-life {fit.half_life_s:.1f} s, R² {fit.r2:.2f})"
            else:
                text += ", no significant bleaching"
            lines.append(text)
        region = "box" if self.box_rect else "whole image"
        self.bleach_info.setText(f"Region: {region}.  " + "   ".join(lines))

    # colocalisation
    def _update_coloc(self):
        if self.tabs.currentIndex() != 3:
            return
        chs = {c.name: c for c in self._channels()}
        a, b = chs.get(self.coloc_a.currentText()), chs.get(self.coloc_b.currentText())
        if a is None or b is None or a is b:
            self.coloc_result.setText("Choose two different channels.")
            self.coloc_img.clear()
            return
        if a.shown.shape != b.shown.shape:
            self.coloc_result.setText("Channels differ in size.")
            return
        ia, ib = (apply_shift(c.shown.astype(np.float32), *_offset(c)) for c in (a, b))
        mask = rect_mask(ia.shape, self.box_rect) if self.box_rect else None
        if self.coloc_thr.currentIndex() == 1:
            res = colocalization(ia, ib, mask, threshold_a=-np.inf, threshold_b=-np.inf)
        else:
            res = colocalization(ia, ib, mask)
        self.coloc_result.setText(
            f"<b>Pearson r = {res.pearson:.3f}</b><br>"
            f"Manders M1 ({a.name} overlapping {b.name}) = {res.manders_m1:.3f}<br>"
            f"Manders M2 ({b.name} overlapping {a.name}) = {res.manders_m2:.3f}<br>"
            f"Thresholds: {a.name} > {res.threshold_a:,.1f}, {b.name} > {res.threshold_b:,.1f}<br>"
            f"Pixels: {res.pixels:,} ({'box' if mask is not None else 'whole image'})")
        hist = joint_histogram(ia, ib, a.levels(), b.levels(), bins=128, mask=mask)
        self.coloc_img.setImage(hist.T, autoLevels=True)  # x = A, y = B
        la, lb = a.levels(), b.levels()
        self.coloc_img.setRect(QRectF(la[0], lb[0], la[1] - la[0], lb[1] - lb[0]))
        self.coloc_plot.setLabel("bottom", f"{a.name} (ADU)")
        self.coloc_plot.setLabel("left", f"{b.name} (ADU)")
        self.coloc_plot.autoRange()

    # ---- CSV -----------------------------------------------------------
    def _save_csv(self, default, header, rows):
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", default, "CSV (*.csv)")
        if path:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(header)
                w.writerows(rows)
        return path

    def _export_profile(self):
        rows = getattr(self, "_profile_rows", [])
        if rows:
            n = len(rows[0][1])
            self._save_csv("line_profile.csv", ["distance"] + [r[0] for r in rows],
                           [[rows[0][1][i]] + [r[2][i] for r in rows] for i in range(n)])

    def _export_stats(self):
        rows = getattr(self, "_stats_rows", [])
        if rows:
            self._save_csv("region_stats.csv", ["channel"] + list(STAT_COLUMNS),
                           [[name] + [s.get(k, "") for k in STAT_COLUMNS] for name, s in rows])

    def _export_bleaching(self):
        if self._bleach:
            names = list(self._bleach)
            n = max(len(r["values"]) for r in self._bleach.values())
            rows = []
            for i in range(n):
                row = []
                for name in names:
                    r = self._bleach[name]
                    row += [r["t"][i], r["values"][i]] if i < len(r["values"]) else ["", ""]
                rows.append(row)
            self._save_csv("bleaching.csv", [f"{n}_{c}" for n in names for c in ("time_s", "mean")], rows)


def _bleach_job(name, color, ds, rect, dark_folder):
    """Worker thread: mean per frame over the whole stack."""
    dark = dark_frame(dark_folder) if dark_folder else None
    frames = (subtract_dark(f, dark) if dark is not None else f for f in ds.iter_frames())
    values = bleach_curve(frames, rect)
    elapsed = [f.elapsed_ms for f in ds.frames[:len(values)]]
    if len(elapsed) == len(values) and None not in elapsed:
        t = (np.asarray(elapsed) - elapsed[0]) / 1000
    else:  # no timestamps: assume back-to-back exposures
        t = np.arange(len(values)) * (ds.exposure_ms or 1) / 1000
    return name, {"t": t, "values": values, "fit": fit_bleaching(t, values), "color": color}
