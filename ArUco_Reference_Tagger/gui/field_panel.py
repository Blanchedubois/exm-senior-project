"""
gui.field_panel
===============
Tab 7 · Field. Ported from Reference_Warp_Tagger/gui/field_panel.py: the
displacement and local-deformation field of a compared image against the
reference, drawn over the reference. Changes: the alignment is selectable
(similarity = distortion only, rigid = growth + distortion); vectors can carry
their 1-sigma error ellipses; the heat map offers eight quantities, each with
its own null and sigma so cells within 1 sigma of the null can be hidden.
These views are a check before export, not the analysis.
"""
from __future__ import annotations
import csv
import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets, QtCore

from rwtag import pairing as PR
from rwtag.refwarp import tagframe as TF
from .compare_common import PairSelector, cyclic_cmap, ellipse
from .widgets import SliderSpin

# label, key, unit, null ("zero" | "expansion" | "expansion2" | "median" | None), sigma key, cyclic
QUANTITIES = [
    ("|u| displacement after alignment", "umag", "px", "zero", "umag_sigma", False),
    ("local linear expansion √J", "lin", "×", "expansion", "lin_sigma", False),
    ("areal expansion J", "J", "×²", "expansion2", "J_sigma", False),
    ("anisotropy λ1/λ2 − 1", "anisotropy", "", "zero", "anisotropy_sigma", False),
    ("principal-axis orientation φ", "phi_deg", "°", None, "phi_deg_sigma", True),
    ("local rotation", "rot_deg", "°", "median", "rot_deg_sigma", False),
    ("local warping (affine misfit)", "resid_rms", "px", None, None, False),
    ("compared image: deviation from design", "dev1_mag", "px", "zero", "dev1_sigma", False),
]


def compute(ref, cmp, design, mode="similarity", k=8):
    """(pairs, align, sim, field) for two project entries (headless; used by the
    Field and Series tabs and their tests)."""
    pairs = PR.pair_frames(ref.pipeline.tagging, cmp.pipeline.tagging)
    sim = PR.similarity_align(pairs)
    if mode == "rigid":
        boxes = PR.common_boxes(pairs)
        if not boxes:
            return pairs, None, sim, None
        N = boxes[0][0]
        c0 = TF.warped_box_centers(ref.pipeline.tagging.warp, design)[N]
        c1 = TF.warped_box_centers(cmp.pipeline.tagging.warp, design)[N]
        align = PR.rigid_align(pairs, N, c0, c1)
    else:
        align = sim
    if not align.get("ok"):
        return pairs, align, sim, None
    f = PR.field(pairs, align, k=k, tr1=cmp.pipeline.tagging, design=design)
    if "dev1" in f:
        f["dev1_sigma"] = np.sqrt(0.5 * (f["C1"][:, 0, 0] + f["C1"][:, 1, 1]))
    return pairs, align, sim, f


def null_value(kind, f, sim):
    if kind == "zero":
        return 0.0
    if kind == "expansion":
        return float(sim.get("expansion", np.nanmedian(f["lin"])))
    if kind == "expansion2":
        return float(sim.get("expansion", np.nanmedian(f["lin"]))) ** 2
    if kind == "median":
        return float(np.nanmedian(f["rot_deg"]))
    return None


class FieldPanel(QtWidgets.QWidget):
    def __init__(self, state, canvas, log, project_fn, design_fn, parent=None):
        super().__init__(parent)
        self.state, self.canvas, self.log, self.project_fn, self.design_fn = state, canvas, log, project_fn, design_fn
        self._f = self._align = self._sim = None
        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel("<b>7 — Field</b>"))
        intro = QtWidgets.QLabel("<small>Per paired dot: displacement after alignment and the local deformation "
                                 "gradient from its 8 nearest neighbours, drawn over the reference image. "
                                 "<b>Similarity</b> alignment shows distortion only; <b>rigid</b> adds the growth.</small>")
        intro.setWordWrap(True); root.addWidget(intro)
        self.sel = PairSelector(project_fn); root.addWidget(self.sel)
        row = QtWidgets.QHBoxLayout()
        self.cmb_mode = QtWidgets.QComboBox(); self.cmb_mode.addItems(["similarity (distortion only)", "rigid (growth + distortion)"])
        row.addWidget(QtWidgets.QLabel("alignment:")); row.addWidget(self.cmb_mode, 1)
        _rw = QtWidgets.QWidget(); _rw.setLayout(row); root.addWidget(_rw)

        vg = QtWidgets.QGroupBox("Vectors"); vl = QtWidgets.QVBoxLayout(vg)
        self.chk_vec = QtWidgets.QCheckBox("Show displacement vectors"); self.chk_vec.setChecked(True)
        self.s_scale = SliderSpin("arrow scale (×)", 0.1, 200.0, 20.0, 0.5, 1)
        self.chk_ell = QtWidgets.QCheckBox("1σ error ellipses at the tips (same scale)"); self.chk_ell.setChecked(False)
        self.spin_dec = QtWidgets.QSpinBox(); self.spin_dec.setRange(1, 50); self.spin_dec.setValue(6)
        dr = QtWidgets.QHBoxLayout(); dr.addWidget(QtWidgets.QLabel("draw every Nth")); dr.addWidget(self.spin_dec)
        _dw = QtWidgets.QWidget(); _dw.setLayout(dr)
        for w in (self.chk_vec, self.s_scale, self.chk_ell, _dw):
            vl.addWidget(w)
        root.addWidget(vg)

        hg = QtWidgets.QGroupBox("Heat map"); hl = QtWidgets.QVBoxLayout(hg)
        self.chk_heat = QtWidgets.QCheckBox("Show heat map"); self.chk_heat.setChecked(True)
        self.cmb_q = QtWidgets.QComboBox(); self.cmb_q.addItems([q[0] for q in QUANTITIES])
        self.chk_sig = QtWidgets.QCheckBox("Hide cells within 1σ of the null (uniform expansion)")
        self.s_alpha = SliderSpin("heat opacity", 0.0, 1.0, 0.6, 0.05, 2)
        self.lbl_range = QtWidgets.QLabel("—"); self.lbl_range.setStyleSheet("color:#999;"); self.lbl_range.setWordWrap(True)
        for w in (self.chk_heat, self.cmb_q, self.chk_sig, self.s_alpha, self.lbl_range):
            hl.addWidget(w)
        root.addWidget(hg)
        self.chk_img = QtWidgets.QCheckBox("Show reference image"); self.chk_img.setChecked(True)
        root.addWidget(self.chk_img)
        self.summary = QtWidgets.QLabel("Tag at least two images."); self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self.b_export = QtWidgets.QPushButton("Export field CSV…"); self.b_export.setEnabled(False)
        root.addWidget(self.b_export); root.addStretch(1)

        self.sel.changed.connect(self._recompute)
        self.cmb_mode.currentIndexChanged.connect(lambda *_: self._recompute())
        for w in (self.chk_vec, self.chk_ell, self.chk_heat, self.chk_sig, self.chk_img):
            w.toggled.connect(lambda *_: self._draw())
        self.cmb_q.currentIndexChanged.connect(lambda *_: self._draw())
        for s in (self.s_scale, self.s_alpha):
            s.valueChanged.connect(lambda *_: self._draw())
        self.spin_dec.valueChanged.connect(lambda *_: self._draw())
        self.b_export.clicked.connect(self.export_csv)

    def refresh(self):
        if not self.sel.refresh() or len(self.sel.entries()) < 2:
            self.summary.setText("Tag at least two images (Run all pending)."); return
        self._recompute()

    def _recompute(self):
        r, c = self.sel.ref(), self.sel.cmp()
        if r is None or c is None or r is c or self.design_fn() is None:
            return
        mode = "rigid" if self.cmb_mode.currentIndex() == 1 else "similarity"
        _p, self._align, self._sim, self._f = compute(r, c, self.design_fn(), mode)
        if self._f is None:
            self.summary.setText("No usable field (alignment failed)."); return
        st = PR.field_stats(self._f)
        s = self._sim
        self.summary.setText(
            f"<b>{st['n']}</b> paired dots · {r.label:g}× → {c.label:g}× · uniform expansion "
            f"<b>{s['expansion']:.4f}</b> ± {s['s_sigma'] / s['s'] ** 2:.4f}<br>"
            f"local linear expansion {st['lin_mean']:.4f} ± {st['lin_sigma']:.4f} (spread) · anisotropy median "
            f"{st['aniso_median']:.4f} (σ per dot ~{np.nanmedian(self._f['anisotropy_sigma']):.4f})<br>"
            f"|u| ({mode}): median {st['umag_median']:.2f} px · p90 {st['umag_p90']:.2f} px · warping residual "
            f"{st['resid_median']:.3f} px")
        self.b_export.setEnabled(True)
        self.log(f"Field: {r.label:g}×→{c.label:g}× {mode} — expansion {s['expansion']:.4f}, n {st['n']}")
        self._draw()

    def _draw(self, *_):
        f, r = self._f, self.sel.ref()
        if f is None or r is None:
            return
        det = r.pipeline.detection
        H, W = det.u8.shape
        self.canvas.set_extent(W, H)
        self.canvas.set_image(det.u8 if self.chk_img.isChecked() else np.zeros((8, 8), np.uint8), levels=(0, 255))
        self.canvas.clear_overlays()
        if self.chk_heat.isChecked():
            label, key, unit, null, skey, cyc = QUANTITIES[self.cmb_q.currentIndex()]
            vals = f.get(key)
            if vals is None:
                self.lbl_range.setText(f"{label}: not available (needs the compared image's design fit)")
                self.canvas.hide_colorbar()
            else:
                grid, (gw, gh) = PR.heat_grid(f["P0"], vals, (H, W))
                ok = np.isfinite(grid)
                nv = null_value(null, f, self._sim)
                if self.chk_sig.isChecked() and skey and f.get(skey) is not None:
                    sg, _ = PR.heat_grid(f["P0"], f[skey], (H, W))
                    if key == "phi_deg":                       # orientation only means something where anisotropic
                        ag, _ = PR.heat_grid(f["P0"], f["anisotropy"], (H, W))
                        asg, _ = PR.heat_grid(f["P0"], f["anisotropy_sigma"], (H, W))
                        ok &= ag > asg
                    elif nv is not None:
                        ok &= np.abs(grid - nv) > sg
                if ok.any():
                    if cyc:
                        lo, hi = 0.0, 180.0; cmap = cyclic_cmap()
                    else:
                        lo, hi = np.nanpercentile(grid[ok], 2), np.nanpercentile(grid[ok], 98)
                        hi = hi if hi > lo else lo + 1e-6
                        cmap = pg.colormap.get("viridis")
                    t = np.clip((np.nan_to_num(grid) - lo) / (hi - lo), 0, 1)
                    rgba = cmap.map(t, mode="byte").reshape(*grid.shape, 4)
                    rgba[..., 3] = np.where(ok, int(self.s_alpha.value() * 255), 0)
                    item = pg.ImageItem(rgba); item.setRect(QtCore.QRectF(0, 0, gw, gh))
                    self.canvas._add(item)
                    nul = "" if nv is None else f" · null {nv:.4g}"
                    self.lbl_range.setText(f"{label}: {lo:.4g} → {hi:.4g} {unit}{nul}"
                                           + (f" · {int((~ok & np.isfinite(grid)).sum())} cells hidden as not significant"
                                              if self.chk_sig.isChecked() else ""))
                    self.canvas.show_colorbar(cmap, lo, hi, label=f"{label} ({unit})" if unit else label)
                else:
                    self.lbl_range.setText(f"{label}: nothing significant to show"); self.canvas.hide_colorbar()
        else:
            self.lbl_range.setText("—"); self.canvas.hide_colorbar()
        if self.chk_vec.isChecked():
            dec = max(1, self.spin_dec.value()); sc = self.s_scale.value()
            P0 = f["P0"][::dec]; U = f["U"][::dec] * sc
            tips = P0 + U
            segs = np.empty((2 * len(P0), 2)); segs[0::2] = P0; segs[1::2] = tips
            self.canvas._add(pg.PlotCurveItem(segs[:, 0], segs[:, 1], connect="pairs",
                                              pen=pg.mkPen((255, 190, 0, 220), width=1.2)))
            self.canvas.add_points(tips, color=(255, 120, 0), size=3)
            if self.chk_ell.isChecked():
                Cu = f["Cu"][::dec]
                ell = [ellipse(tp, c, sc) for tp, c in zip(tips[:1500], Cu[:1500]) if np.isfinite(c).all()]
                self.canvas.add_polylines(ell, color=(255, 255, 255), width=1)

    def export_csv(self, path=None):
        f = self._f
        if f is None:
            return None
        if path is None:
            r, c = self.sel.ref(), self.sel.cmp()
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export field CSV",
                                                            f"field_{r.label:g}x_{c.label:g}x.csv", "CSV (*.csv)")
            if not path:
                return None
        keys = ["lin", "lin_sigma", "J", "J_sigma", "lam1", "lam1_sigma", "lam2", "lam2_sigma", "anisotropy",
                "anisotropy_sigma", "phi_deg", "phi_deg_sigma", "rot_deg", "rot_deg_sigma", "resid_rms", "n_nb"]
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([f"# field, alignment {self._align['kind']}, corrected-frame px of each image; quick export (bundle: port Phase 7)"])
            w.writerow(["tag", "x0", "y0", "x1", "y1", "x1_aligned", "y1_aligned", "ux", "uy", "sxx_u", "syy_u", "sxy_u"] + keys)
            for i, t in enumerate(f["tags"]):
                Cu = f["Cu"][i]
                w.writerow([t, *np.round(f["P0"][i], 3), *np.round(f["P1"][i], 3), *np.round(f["P1a"][i], 3),
                            *np.round(f["U"][i], 4), f"{Cu[0, 0]:.3g}", f"{Cu[1, 1]:.3g}", f"{Cu[0, 1]:.3g}"]
                           + [("" if not np.isfinite(f[k][i]) else f"{f[k][i]:.6g}") for k in keys])
        self.log(f"Field: CSV → {path}")
        return path
