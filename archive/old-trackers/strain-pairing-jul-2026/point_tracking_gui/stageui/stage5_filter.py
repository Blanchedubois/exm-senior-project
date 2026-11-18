"""
app.stage5_filter
================
Stage 5 GUI: quality filters on the tracked points. Each filter is toggleable
with a threshold; re-applying always starts from the unfiltered Stage-4 result so
the user can freely re-tune. Filtered dots turn red on the canvas. Maths delegated
to gridtrack.filters.
"""
from __future__ import annotations
import os
from PySide6 import QtWidgets

from gridtrack import filters, io
from gridtrack.types import FilterParams


class Stage5Panel(QtWidgets.QWidget):
    def __init__(self, state, canvas, log, parent=None):
        super().__init__(parent)
        self.state = state
        self.canvas = canvas
        self.log = log
        self._base = None                               # unfiltered Stage-4 features

        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel("<b>Stage 5 — Filter points</b>"))

        # each filter: a checkbox + one threshold spin
        self.c_prox = QtWidgets.QCheckBox("Min separation (× expected pitch)")
        self.s_prox = self._spin(0.1, 1.0, 0.5, 0.05)
        self.c_qual = QtWidgets.QCheckBox("Blob quality (mass/size MAD)")
        self.s_qual = self._spin(1.0, 15.0, 5.0, 0.5)
        self.c_resid = QtWidgets.QCheckBox("Prediction residual (MAD)")
        self.s_resid = self._spin(1.0, 20.0, 6.0, 0.5)
        self.c_smooth = QtWidgets.QCheckBox("Neighbour smoothness (MAD)")
        self.s_smooth = self._spin(1.0, 20.0, 6.0, 0.5)
        self.c_border = QtWidgets.QCheckBox("Border proximity (px)")
        self.s_border = self._spin(0.0, 300.0, 8.0, 1.0)
        for c in (self.c_prox, self.c_qual, self.c_resid, self.c_border):
            c.setChecked(True)
        for c, s in ((self.c_prox, self.s_prox), (self.c_qual, self.s_qual),
                     (self.c_resid, self.s_resid), (self.c_smooth, self.s_smooth),
                     (self.c_border, self.s_border)):
            r = QtWidgets.QHBoxLayout(); r.addWidget(c, 1); r.addWidget(s)
            root.addLayout(r)

        self.b_apply = QtWidgets.QPushButton("Apply filters")
        self.b_reset = QtWidgets.QPushButton("Reset (unfiltered)")
        self.b_export = QtWidgets.QPushButton("Export filtered…")
        root.addWidget(self.b_apply); root.addWidget(self.b_reset); root.addWidget(self.b_export)

        self.summary = QtWidgets.QLabel("—"); self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        root.addStretch(1)

        self.state.featuresChanged.connect(self._maybe_cache_base)
        self.b_apply.clicked.connect(self.run)
        self.b_reset.clicked.connect(self.reset)
        self.b_export.clicked.connect(self.export)

    @staticmethod
    def _spin(lo, hi, val, step):
        s = QtWidgets.QDoubleSpinBox(); s.setRange(lo, hi); s.setValue(val)
        s.setSingleStep(step); s.setMaximumWidth(80)
        return s

    def _maybe_cache_base(self):
        """Cache the Stage-4 (unfiltered) result as the baseline to re-filter from."""
        feats = self.state.pipeline.features
        if feats is not None and not (feats["status"] == "filtered").any():
            self._base = feats.copy()

    def set_params(self, fp: FilterParams):
        self.c_prox.setChecked(fp.enable_proximity); self.s_prox.setValue(fp.min_sep_frac)
        self.c_qual.setChecked(fp.enable_quality); self.s_qual.setValue(fp.quality_mad)
        self.c_resid.setChecked(fp.enable_residual); self.s_resid.setValue(fp.residual_mad)
        self.c_smooth.setChecked(fp.enable_smoothness); self.s_smooth.setValue(fp.neighbor_mad)
        self.c_border.setChecked(fp.enable_border); self.s_border.setValue(fp.border_px)

    def read_params(self):
        return self._params()

    def _params(self):
        return FilterParams(
            enable_proximity=self.c_prox.isChecked(), min_sep_frac=self.s_prox.value(),
            enable_quality=self.c_qual.isChecked(), quality_mad=self.s_qual.value(),
            enable_residual=self.c_resid.isChecked(), residual_mad=self.s_resid.value(),
            enable_smoothness=self.c_smooth.isChecked(), neighbor_mad=self.s_smooth.value(),
            enable_border=self.c_border.isChecked(), border_px=self.s_border.value())

    def run(self):
        if self._base is None:
            self._maybe_cache_base()
        if self._base is None:
            self.log("Stage 5: run Stage 4 (detect & track) first."); return
        det = self.state.pipeline.detection
        out = filters.apply_filters(self._base, self.state.pipeline.grid,
                                    self.state.pipeline.reference, self._params(),
                                    image_shape=None if det is None else det.image.shape)
        self.state.set_features(out)
        self.canvas.draw_features(out)
        counts = out.attrs.get("filter_counts", {})
        surv = out.attrs.get("n_survivors", 0)
        n_filt = out.attrs.get("n_filtered", 0)
        detail = ", ".join(f"{k}: {v}" for k, v in counts.items()) or "none"
        self.summary.setText(f"survivors: <b>{surv}</b><br>filtered: <b>{n_filt}</b><br>{detail}")
        self.log(f"Stage 5: filtered {n_filt} dots ({detail}); {surv} survive")

    def reset(self):
        if self._base is not None:
            self.state.set_features(self._base.copy())
            self.canvas.draw_features(self._base)
            self.summary.setText("reset to unfiltered")

    def export(self):
        feats = self.state.pipeline.features
        if feats is None:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export filtered features", "features_filtered.parquet",
            "Parquet (*.parquet);;CSV (*.csv)")
        if not path:
            return
        base = os.path.splitext(path)[0]
        try:
            feats.to_parquet(base + ".parquet")
        except Exception as e:
            self.log(f"(parquet failed: {e})")
        feats.to_csv(base + ".csv", index=False)
        self.log(f"Stage 5: exported {base}.parquet/.csv")
