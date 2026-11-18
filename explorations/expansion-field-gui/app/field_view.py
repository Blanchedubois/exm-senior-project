"""
app.field_view
=============
Quiver visualisation of a pairing's displacement field on the initial image:
an interpolated magnitude heatmap background, colour-by-magnitude arrows (with
arrowheads and a density control), and a magnitude legend.
"""
from __future__ import annotations
import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets

from fieldkit import analysis

pg.setConfigOptions(imageAxisOrder="row-major", background="k")


def _arrow_segments(base, tip, head_frac=0.28, head_max=18.0):
    """Return an (M,2) point array (connect='pairs') of shafts + arrowheads."""
    v = tip - base
    L = np.hypot(v[:, 0], v[:, 1])
    ok = L > 1e-6
    u = np.zeros_like(v); u[ok] = v[ok] / L[ok, None]
    hl = np.minimum(head_frac * L, head_max)
    # barbs: rotate the unit vector by +/-150 deg, scaled by head length
    ang = np.deg2rad(150.0)
    ca, sa = np.cos(ang), np.sin(ang)
    b1 = np.stack([u[:, 0] * ca - u[:, 1] * sa, u[:, 0] * sa + u[:, 1] * ca], 1) * hl[:, None]
    b2 = np.stack([u[:, 0] * ca + u[:, 1] * sa, -u[:, 0] * sa + u[:, 1] * ca], 1) * hl[:, None]
    segs = np.empty((6 * len(base), 2))
    segs[0::6], segs[1::6] = base, tip                # shaft
    segs[2::6], segs[3::6] = tip, tip + b1            # barb 1
    segs[4::6], segs[5::6] = tip, tip + b2            # barb 2
    return segs


class FieldView(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.glw = pg.GraphicsLayoutWidget()
        self.view = self.glw.addViewBox(lockAspect=True, invertY=True)
        self.img_item = pg.ImageItem()
        self.heat_item = pg.ImageItem()
        self.heat_item.setZValue(1); self.heat_item.setOpacity(0.55)
        self.view.addItem(self.img_item)
        self.view.addItem(self.heat_item)
        self._items = []
        self.legend = pg.GradientLegend((14, 160), (24, 24))
        self._cmap = pg.colormap.get("turbo")
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.glw)

        # hover readout
        self._hover_f = None
        self._hover_col = None
        self.tip = pg.TextItem(color=(255, 255, 255), fill=(0, 0, 0, 160))
        self.tip.setZValue(10); self.tip.setVisible(False)
        self.view.addItem(self.tip)
        self._proxy = pg.SignalProxy(self.view.scene().sigMouseMoved, rateLimit=30,
                                     slot=self._on_hover)

    def _clear(self):
        for it in self._items:
            self.view.removeItem(it)
        self._items = []

    def set_field(self, image, field, mode="full", scale=1.0, density=1,
                  show_heatmap=True, nbins=12):
        self.img_item.setImage(np.asarray(image), autoLevels=True)
        self._clear()
        f = field[field["status"] == "paired"]
        if len(f) == 0:
            self.heat_item.clear()
            return analysis.field_summary(field)

        # mode "J" -> colour/heatmap by areal expansion, arrows from the full field
        j_mode = mode == "J" and "J" in f.columns
        vec_mode = "full" if j_mode else mode
        heat_col = "J" if j_mode else f"u_{vec_mode}_mag_um"
        unit = "" if j_mode else " µm"

        base = f[["x_init_px", "y_init_px"]].to_numpy(float)
        u = f[[f"u_{vec_mode}_x_px", f"u_{vec_mode}_y_px"]].to_numpy(float)
        mag = f[heat_col].to_numpy(float)
        self._hover_f = f.reset_index(drop=True)      # for hover lookups
        self._hover_col = heat_col
        self._hover_unit = unit
        finite = np.isfinite(mag)
        vmin = float(np.nanmin(mag[finite])) if finite.any() else 0.0
        vmax = float(np.nanmax(mag[finite])) if finite.any() else 1.0
        if vmax <= vmin:
            vmax = vmin + 1.0

        # heatmap background (interpolated scalar)
        if show_heatmap:
            try:
                Z, step = analysis.interpolate_scalar(field, heat_col, image.shape, step=6)
                norm = np.clip((Z - vmin) / max(vmax - vmin, 1e-9), 0, 1)
                rgba = self._cmap.map(np.nan_to_num(norm), mode="byte")
                rgba[..., 3] = np.where(np.isfinite(Z), 150, 0).astype(np.uint8)
                self.heat_item.setImage(rgba)
                self.heat_item.setRect(pg.QtCore.QRectF(0, 0, image.shape[1], image.shape[0]))
                self.heat_item.setVisible(True)
            except Exception:
                self.heat_item.setVisible(False)
        else:
            self.heat_item.setVisible(False)

        # subsample for the arrows
        step_i = max(1, int(density))
        idx = np.arange(0, len(base), step_i)
        b, t, m = base[idx], base[idx] + scale * u[idx], mag[idx]

        edges = np.linspace(vmin, vmax, nbins + 1)
        for i in range(nbins):
            lo, hi = edges[i], edges[i + 1]
            sel = (m >= lo) & (m <= hi) if i == nbins - 1 else (m >= lo) & (m < hi)
            if not sel.any():
                continue
            seg = _arrow_segments(b[sel], t[sel])
            color = self._cmap.map((i + 0.5) / nbins, mode="qcolor")
            it = pg.PlotCurveItem(seg[:, 0], seg[:, 1], connect="pairs",
                                  pen=pg.mkPen(color, width=1))
            it.setZValue(2)
            self.view.addItem(it); self._items.append(it)

        # legend
        self.legend.setParentItem(self.view)
        self.legend.setLabels({f"{vmax:.1f}{unit}": 0.0, f"{(vmin+vmax)/2:.1f}": 0.5,
                               f"{vmin:.1f}": 1.0})
        self.legend.setGradient(self._cmap.getGradient())
        self.view.autoRange(padding=0.02)
        return analysis.field_summary(field)

    def _on_hover(self, evt):
        f = self._hover_f
        if f is None or len(f) == 0:
            return
        pos = self.view.mapSceneToView(evt[0])
        xy = np.array([pos.x(), pos.y()])
        b = f[["x_init_px", "y_init_px"]].to_numpy(float)
        d = np.hypot(b[:, 0] - xy[0], b[:, 1] - xy[1])
        i = int(np.argmin(d))
        if d[i] > 25:                                 # only near a marker
            self.tip.setVisible(False); return
        r = f.iloc[i]
        val = r[self._hover_col]
        self.tip.setText(f"{r['tag_key']}  ({r['type']})\n"
                         f"{self._hover_col} = {val:.2f}{self._hover_unit}")
        self.tip.setPos(b[i, 0], b[i, 1])
        self.tip.setVisible(True)
