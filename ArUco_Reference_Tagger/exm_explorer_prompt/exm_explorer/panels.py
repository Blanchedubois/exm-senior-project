"""Right-hand panels: post view, ACF, CCF and metrics (milestone 4).

Each panel takes the plain-data result of live.analysis_job in update(res).
Image-frame panels (post, windowed CCF) show pixels with y down.
"""

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Qt

DIVERGING = pg.ColorMap([0.0, 0.5, 1.0], ["#3987e5", "#2a2a28", "#d95926"])
SEQUENTIAL = pg.ColorMap([0.0, 0.55, 1.0], ["#141414", "#2f6db8", "#cfe4ff"])
GREY = pg.ColorMap([0.0, 1.0], ["#000000", "#ffffff"])
INK = "#f0efec"
MUTED = "#8a8a84"
BLUE, ORANGE, AQUA, YELLOW = "#3987e5", "#d95926", "#199e70", "#c98500"


def arrow_segments(P, V, head=0.3, max_head=None):
    """Line pairs for arrows from P along V (N, 2), with two head strokes."""
    P, V = np.asarray(P, float), np.asarray(V, float)
    L = np.hypot(V[:, 0], V[:, 1])
    keep = L > 1e-9
    P, V, L = P[keep], V[keep], L[keep]
    if len(P) == 0:
        return np.zeros(0), np.zeros(0)
    T = P + V
    d = V / L[:, None]
    hl = head * L if max_head is None else np.minimum(head * L, max_head)
    hl = hl[:, None]
    c, s = np.cos(np.deg2rad(25)), np.sin(np.deg2rad(25))
    h1 = T - hl * np.c_[c * d[:, 0] - s * d[:, 1], s * d[:, 0] + c * d[:, 1]]
    h2 = T - hl * np.c_[c * d[:, 0] + s * d[:, 1], -s * d[:, 0] + c * d[:, 1]]
    seg = np.stack([P, T, T, h1, T, h2], 1).reshape(-1, 2)
    return seg[:, 0], seg[:, 1]


def image_plot(title, invert_y=True, xlabel=None, ylabel=None):
    p = pg.PlotItem(title=title)
    p.setAspectLocked(True)
    p.invertY(invert_y)
    p.getViewBox().setMenuEnabled(False)
    if xlabel:
        p.setLabel("bottom", xlabel)
    if ylabel:
        p.setLabel("left", ylabel)
    img = pg.ImageItem()
    p.addItem(img)
    return p, img


def zoom_slider(lo, hi, value):
    s = QtWidgets.QSlider(Qt.Orientation.Horizontal)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


# ===================================================================== post view
class PostPanel(QtWidgets.QWidget):
    """The post image rendered for the visible region only. Panning or zooming
    emits regionRequested(x0, y0, w, h) in post px."""
    regionRequested = QtCore.Signal(tuple)

    def __init__(self):
        super().__init__()
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.glw = pg.GraphicsLayoutWidget()
        self.plot, self.img = image_plot("Post image (visible region)", xlabel="post px", ylabel="post px")
        self.glw.addItem(self.plot)
        lay.addWidget(self.glw)
        self.info = QtWidgets.QLabel()
        self.info.setStyleSheet(f"color: {MUTED}")
        lay.addWidget(self.info)
        self.n = None
        self._timer = QtCore.QTimer(self, singleShot=True, interval=120)
        self._timer.timeout.connect(self._emit)
        self.plot.getViewBox().sigRangeChanged.connect(lambda *_: self._timer.start())
        self._ignore = False

    def visible_region(self):
        (x0, x1), (y0, y1) = self.plot.getViewBox().viewRange()
        return (x0, y0, x1 - x0, y1 - y0)

    def _emit(self):
        if self.n is not None and not self._ignore:
            self.regionRequested.emit(self.visible_region())

    def set_size(self, n):
        if n != self.n:
            self.n = n
            self._ignore = True
            self.plot.getViewBox().setRange(xRange=(0, n), yRange=(0, n), padding=0.02)
            self._ignore = False

    def update(self, res):
        p = res["post"]
        img = p["img"]
        x0, y0, w, h = p["region"]
        lo, hi = np.percentile(img, [1, 99.8])
        self.img.setImage(img, levels=(lo, max(hi, lo + 1)), autoLevels=False)
        self.img.setRect(QtCore.QRectF(x0 - 0.5 * p["factor"], y0 - 0.5 * p["factor"], w, h))
        self.info.setText(f"rendered {img.shape[1]} × {img.shape[0]} px at 1:{p['factor']} "
                          f"(only the visible part of the {self.n} px post image)")


# ===================================================================== ACF
class AcfPanel(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.glw = pg.GraphicsLayoutWidget()
        self.p_pre, self.i_pre = image_plot("ACF pre", xlabel="lag (pre px)")
        self.p_post, self.i_post = image_plot("ACF post (visible region)", xlabel="lag (post px)")
        self.p_diff, self.i_diff = image_plot("ACF(corrected post) − ACF(pre), pre frame",
                                              xlabel="lag (pre px)")
        for p, i in ((self.p_pre, self.i_pre), (self.p_post, self.i_post), (self.p_diff, self.i_diff)):
            i.setColorMap(DIVERGING)
        self.glw.addItem(self.p_pre, 0, 0)
        self.glw.addItem(self.p_post, 0, 1)
        self.glw.addItem(self.p_diff, 1, 0, 1, 2)
        lay.addWidget(self.glw, 1)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("lag zoom, pre:"))
        self.z_pre = zoom_slider(0, 100, 0)
        row.addWidget(self.z_pre)
        row.addWidget(QtWidgets.QLabel("post:"))
        self.z_post = zoom_slider(0, 100, 0)
        row.addWidget(self.z_post)
        lay.addLayout(row)
        note = QtWidgets.QLabel("Zoom: left = dot lattice, right = node lattice. Arrows: lattice basis. "
                                "Difference panel: blue arrows = peak shift ×5, orange rings = widening.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {MUTED}; font-size: 11px")
        lay.addWidget(note)
        self.basis = {}
        for name, p in (("pre", self.p_pre), ("post", self.p_post), ("diff", self.p_diff)):
            c = pg.PlotCurveItem(pen=pg.mkPen(AQUA, width=2), connect="pairs")
            p.addItem(c)
            self.basis[name] = c
        self.shift_arrows = pg.PlotCurveItem(pen=pg.mkPen(BLUE, width=2), connect="pairs")
        self.rings = pg.PlotCurveItem(pen=pg.mkPen(ORANGE, width=1.5), connect="pairs")
        self.p_diff.addItem(self.rings)
        self.p_diff.addItem(self.shift_arrows)
        self.z_pre.valueChanged.connect(self._zoom)
        self.z_post.valueChanged.connect(self._zoom)
        self.res = None

    def _span(self, slider, pitch, L):
        t = slider.value() / 100
        lo = 5.5 * pitch
        return lo * (L / lo) ** t if L > lo else L

    def _zoom(self, *_):
        r = self.res
        if r is None:
            return
        pitch = np.sqrt(abs(np.linalg.det(r["Bpre"])))
        z = self._span(self.z_pre, pitch, r["L_pre"])
        self.p_pre.getViewBox().setRange(xRange=(-z, z), yRange=(-z, z), padding=0)
        if r["Bpost"] is not None:
            pp = np.sqrt(abs(np.linalg.det(r["Bpost"])))
            Lp = r["L_post"] * r["f_acf"]
            z = self._span(self.z_post, pp, Lp)
            self.p_post.getViewBox().setRange(xRange=(-z, z), yRange=(-z, z), padding=0)
        Ld = r["L_diff"]
        self.p_diff.getViewBox().setRange(xRange=(-Ld, Ld), yRange=(-Ld, Ld), padding=0)

    def _show(self, img, item, L, scale=1.0, v=None):
        if v is None:
            c = img.shape[0] // 2
            a = np.abs(img).copy()
            a[c - 2:c + 3, c - 2:c + 3] = 0
            v = max(float(np.percentile(a, 99.9)), 1e-6)
        item.setImage(img, levels=(-v, v), autoLevels=False)
        item.setRect(QtCore.QRectF((-L - 0.5) * scale, (-L - 0.5) * scale, (2 * L + 1) * scale,
                                   (2 * L + 1) * scale))

    def update(self, r):
        first = self.res is None
        self.res = r
        self._show(r["acf_pre"], self.i_pre, r["L_pre"])
        self._show(r["acf_post"], self.i_post, r["L_post"], scale=r["f_acf"])
        self._show(r["acf_diff"], self.i_diff, r["L_diff"])
        for name, B in (("pre", r["Bpre"]), ("post", r["Bpost"]), ("diff", r["Bpre"])):
            if B is None:
                self.basis[name].setData([], [])
                continue
            x, y = arrow_segments(np.zeros((2, 2)), B.T, head=0.25)
            self.basis[name].setData(x, y)
        sh = r["shifts"]
        if len(sh):
            x, y = arrow_segments(sh[:, 2:4], 5 * sh[:, 4:6], head=0.3, max_head=1.5)
            self.shift_arrows.setData(x, y)
            xs, ys = [], []
            t = np.linspace(0, 2 * np.pi, 33)
            for row in sh:
                w = row[6]
                if np.isfinite(w) and w > 1.02:
                    rad = 1.0 + 20 * (w - 1)
                    cx, cy = row[2] + rad * np.cos(t), row[3] + rad * np.sin(t)
                    xs += list(np.repeat(cx, 2)[1:-1])
                    ys += list(np.repeat(cy, 2)[1:-1])
            self.rings.setData(np.array(xs), np.array(ys))
        if first:
            self._zoom()


# ===================================================================== CCF
class CcfPanel(QtWidgets.QWidget):
    extremumClicked = QtCore.Signal(float, float)        # pre px

    def __init__(self):
        super().__init__()
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.glw = pg.GraphicsLayoutWidget()
        self.p_g, self.i_g = image_plot("Global CCF(pre, corrected post)", invert_y=True, xlabel="shift (pre px)")
        self.i_g.setColorMap(SEQUENTIAL)
        self.p_w, self.i_w = image_plot("Windowed CCF |displacement|", xlabel="pre px")
        self.i_w.setColorMap(SEQUENTIAL)
        self.glw.addItem(self.p_g, 0, 0)
        self.glw.addItem(self.p_w, 1, 0)
        self.cbar = pg.ColorBarItem(values=(0, 1), colorMap=SEQUENTIAL, interactive=False, width=12)
        self.cbar.setImageItem(self.i_w, insert_in=self.p_w)
        lay.addWidget(self.glw, 3)
        self.main_pk = pg.ScatterPlotItem(size=14, symbol="o", pen=pg.mkPen(AQUA, width=2), brush=None)
        self.next_pk = pg.ScatterPlotItem(size=14, symbol="x", pen=pg.mkPen(ORANGE, width=2), brush=pg.mkBrush(ORANGE))
        self.g_ext = pg.ScatterPlotItem(size=9, symbol="t1", pen=pg.mkPen(INK, width=1), brush=pg.mkBrush(YELLOW))
        for it in (self.g_ext, self.main_pk, self.next_pk):
            self.p_g.addItem(it)
        self.quiver = pg.PlotCurveItem(pen=pg.mkPen(INK, width=1), connect="pairs")
        self.w_ext = pg.ScatterPlotItem(size=12, pxMode=True)
        self.region = pg.PlotCurveItem(pen=pg.mkPen(MUTED, width=1, style=Qt.PenStyle.DashLine))
        for it in (self.region, self.quiver, self.w_ext):
            self.p_w.addItem(it)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("global zoom"))
        self.z_g = zoom_slider(0, 100, 15)
        row.addWidget(self.z_g)
        self.mode = QtWidgets.QComboBox()
        self.mode.addItems(["lattice-aware", "naive (largest peak)"])
        self.show = QtWidgets.QComboBox()
        self.show.addItems(["|displacement|", "quiver", "error vs truth"])
        row.addWidget(self.mode)
        row.addWidget(self.show)
        lay.addLayout(row)
        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["where", "", "x", "y", "value"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.setMaximumHeight(170)
        self.table.cellClicked.connect(self._clicked)
        lay.addWidget(self.table, 1)
        self.z_g.valueChanged.connect(self._zoom)
        self.mode.currentIndexChanged.connect(lambda *_: self.redraw())
        self.show.currentIndexChanged.connect(lambda *_: self.redraw())
        self.res = None
        self._rows = []

    def _zoom(self, *_):
        if self.res is None:
            return
        Lg = self.res["Lg"]
        z = 12 * (Lg / 12) ** (self.z_g.value() / 100)
        self.p_g.getViewBox().setRange(xRange=(-z, z), yRange=(-z, z), padding=0)

    def update(self, r):
        first = self.res is None
        self.res = r
        Lg = r["Lg"]
        G = r["G"]
        self.i_g.setImage(G, levels=(float(np.percentile(G, 1)), float(G.max())), autoLevels=False)
        self.i_g.setRect(QtCore.QRectF(-Lg - 0.5, -Lg - 0.5, 2 * Lg + 1, 2 * Lg + 1))
        self.main_pk.setData([0], [0])
        nb = r["next_best_at"]
        self.next_pk.setData([nb[0]], [nb[1]])
        pk = r["extrema"].get("global_ccf_peaks", [])
        self.g_ext.setData([e["x"] for e in pk[1:]], [e["y"] for e in pk[1:]])
        m = r["metrics"]["ccf"]
        self.p_g.setTitle(f"Global CCF: peak {m['peak']:.3f}, next best {m['next_best']:.3f} "
                          f"at {tuple(m['next_best_at'])}, ratio {m['ratio']:.3f}")
        self.redraw()
        if first:
            self._zoom()

    def redraw(self):
        r = self.res
        if r is None:
            return
        disp = r["unwrapped"] if self.mode.currentIndex() == 0 else r["naive"]
        cs_x, cs_y = r["cs_x"], r["cs_y"]
        st = cs_x[1] - cs_x[0]
        rect = QtCore.QRectF(cs_x[0] - st / 2, cs_y[0] - st / 2, len(cs_x) * st, len(cs_y) * st)
        what = self.show.currentText()
        if what == "error vs truth" and r.get("true_win") is not None:
            img = np.hypot(*np.moveaxis(disp - r["true_win"], -1, 0))
            title = "error vs truth (px)"
        else:
            img = np.hypot(disp[..., 0], disp[..., 1])
            title = "|displacement| (px)"
        tw = r.get("true_win")
        vmax = np.nanmax(np.hypot(tw[..., 0], tw[..., 1])) * 1.2 if tw is not None and np.isfinite(tw).any() \
            else np.nanmax(img)
        vmax = float(vmax) if np.isfinite(vmax) and vmax > 0 else 1.0
        self.i_w.setImage(np.nan_to_num(img, nan=0.0), levels=(0, vmax), autoLevels=False)
        self.i_w.setRect(rect)
        self.cbar.setLevels((0, vmax))
        self.cbar.setLabel("right", title)
        mode = "lattice-aware" if self.mode.currentIndex() == 0 else "naive"
        self.p_w.setTitle(f"Windowed CCF ({mode}), pre frame")
        if what == "quiver":
            X, Y = np.meshgrid(cs_x, cs_y)
            ok = np.isfinite(disp[..., 0])
            x, y = arrow_segments(np.c_[X[ok], Y[ok]], 4 * disp[ok], head=0.3, max_head=6)
            self.quiver.setData(x, y)
            self.quiver.show()
        else:
            self.quiver.hide()
        w = r.get("which")
        if w is not None and w.any():
            X, Y = np.meshgrid(cs_x, cs_y)
            x0, x1, y0, y1 = X[w].min() - st / 2, X[w].max() + st / 2, Y[w].min() - st / 2, Y[w].max() + st / 2
            self.region.setData([x0, x1, x1, x0, x0], [y0, y0, y1, y1, y0])
        else:
            self.region.setData([], [])
        ex = r["extrema"].get("ccf_magnitude", []) if self.mode.currentIndex() == 0 else []
        self.w_ext.setData([dict(pos=(e["x"], e["y"]), symbol="t1" if e["kind"] == "max" else "t",
                                 brush=pg.mkBrush(ORANGE if e["kind"] == "max" else BLUE),
                                 pen=pg.mkPen(INK, width=1.2)) for e in ex if e["kind"] == "max"])
        self._fill_table(r)

    def _fill_table(self, r):
        rows = [("global CCF", e) for e in r["extrema"].get("global_ccf_peaks", [])[:6]]
        rows += [("|displacement|", e) for e in r["extrema"].get("ccf_magnitude", []) if e["kind"] == "max"][:10]
        self._rows = rows
        t = self.table
        t.setRowCount(len(rows))
        for k, (where, e) in enumerate(rows):
            vals = [where, "▲ max" if e["kind"] == "max" else "▼ min", f"{e['x']:.1f}", f"{e['y']:.1f}",
                    f"{e['value']:.3f}"]
            for c, v in enumerate(vals):
                t.setItem(k, c, QtWidgets.QTableWidgetItem(v))

    def _clicked(self, row, col):
        if row < len(self._rows):
            where, e = self._rows[row]
            if where == "|displacement|":
                self.extremumClicked.emit(e["x"], e["y"])
            else:
                z = max(12.0, 2.5 * np.hypot(e["x"], e["y"]))
                self.p_g.getViewBox().setRange(xRange=(-z, z), yRange=(-z, z), padding=0)


# ===================================================================== metrics
class MetricsPanel(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        lay = QtWidgets.QVBoxLayout(self)
        self.text = QtWidgets.QLabel()
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidget(self.text)
        scroll.setWidgetResizable(True)
        lay.addWidget(scroll, 3)
        self.faithful = QtWidgets.QLabel()
        self.faithful.setTextFormat(Qt.TextFormat.RichText)
        self.faithful.setWordWrap(True)
        self.faithful.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.faithful)
        self.plot = pg.PlotWidget(title="ACF peak height, post / pre, vs lag")
        self.plot.setLabel("bottom", "lag (dot-lattice spacings)")
        self.plot.setLabel("left", "post / pre")
        self.plot.addLine(y=1, pen=pg.mkPen(MUTED, style=Qt.PenStyle.DashLine))
        self.pts = pg.ScatterPlotItem(size=6, pen=None, brush=pg.mkBrush(ORANGE))
        self.mean = pg.PlotCurveItem(pen=pg.mkPen(INK, width=2))
        self.plot.addItem(self.pts)
        self.plot.addItem(self.mean)
        self.plot.setMinimumHeight(200)
        lay.addWidget(self.plot, 2)

    def update(self, r):
        m = r["metrics"]
        o, q = r["heights"]["order"], r["heights"]["ratio"]
        self.pts.setData(o, q)
        if len(o):
            k = np.round(o).astype(int)
            u = np.unique(k)
            self.mean.setData(u.astype(float), np.array([q[k == v].mean() for v in u]))
        else:
            self.mean.setData([], [])

        def row(name, d):
            if d is None:
                return f"<tr><td>{name}</td><td colspan=4 style='color:{MUTED}'>not available</td></tr>"
            return (f"<tr><td>{name}</td><td>{d['scale']:.4f}</td><td>{d['anisotropy']:.4f}</td>"
                    f"<td>{d['stretch_dir_deg']:.1f}°</td><td>{d['rotation_deg']:+.3f}°</td></tr>")
        w = m["windows"]
        c = m["ccf"]

        def pct(x):
            return f"{100 * x:.1f} %" if x is not None and np.isfinite(x) else "–"

        def num(x, f="{:.3f}"):
            return f.format(x) if x is not None and np.isfinite(x) else "–"
        tier = "full" if m["tier"] == "full" else ("fast, near the selected site" if m["restricted"] else "fast")
        timing = " · ".join(f"{k} {1e3 * v:.0f}" for k, v in m["timings"].items())
        html = f"""
<style>td {{ padding: 2px 8px; }} th {{ color: {MUTED}; padding: 2px 8px; text-align: left; }}</style>
<b>Global transform, pre → post</b>
<table><tr><th></th><th>scale</th><th>anisotropy</th><th>stretch dir</th><th>rotation</th></tr>
{row("ACF (dot lattice)", m["acf"])}{row("tag centres", m["tags"])}{row("truth", m["truth"])}</table>
<p style='color:{MUTED}'>registration used: {m["registration"]}</p>
<b>Global CCF</b><br>
peak {c["peak"]:.4f} · next best {c["next_best"]:.4f} at {tuple(c["next_best_at"])} ·
ratio <b>{c["ratio"]:.3f}</b> (ambiguity margin {100 * (c["ratio"] - 1):.1f} %)<br><br>
<b>Windowed CCF vs truth</b> ({w.get("windows", 0)} windows; {tier})
<table><tr><th></th><th>naive</th><th>lattice-aware</th></tr>
<tr><td>rms error, all windows</td><td>{num(w.get("naive_rms_err_px"))} px</td><td>{num(w.get("unwrapped_rms_err_px"))} px</td></tr>
<tr><td>off by a cell, all windows</td><td>{pct(w.get("naive_frac_off_by_a_cell"))}</td><td>{pct(w.get("unwrapped_frac_off_by_a_cell"))}</td></tr>
<tr><td>rms error, dot windows</td><td>{num(w.get("dots_only_naive_rms_err_px"))} px</td><td>{num(w.get("dots_only_unwrapped_rms_err_px"))} px</td></tr>
<tr><td>off by a cell, dot windows</td><td>{pct(w.get("dots_only_naive_frac_off_by_a_cell"))}</td><td>{pct(w.get("dots_only_unwrapped_frac_off_by_a_cell"))}</td></tr>
<tr><td>local expansion r</td><td></td><td>{num(w.get("local_scale_corr"))}</td></tr>
<tr><td>local expansion rms error</td><td></td><td>{num(w.get("local_scale_rms_err"), "{:.4f}")}</td></tr></table>
<p style='color:{MUTED}'>Windows with a tag or dash carry a shape bias; "dot windows" leave them out.</p>
<b>Compute</b>: {1e3 * m["total_s"]:.0f} ms ({tier})<br><span style='color:{MUTED}'>{timing} ms</span>
"""
        self.text.setText(html)

    def set_faithful(self, res, stale=False, seconds=None):
        """Summary of the last faithful-pipeline run."""
        if res is None:
            self.faithful.setText("")
            return
        tg, ac, tr = res["aruco_tags"]["global_"], res["acf_global"], res["truth_global"]
        lines = [f"<b>Faithful pipeline</b> (exact render, {res['aruco_tags']['n_tags']} tags decoded by OpenCV"
                 + (f", {seconds:.1f} s" if seconds else "") + ")"
                 + (f" <span style='color:{ORANGE}'>· the scenario has changed since</span>" if stale else ""),
                 f"scale: ACF {ac['scale']:.4f} · tags {tg['scale']:.4f} · truth {tr['scale']:.4f}; "
                 f"rotation: tags {tg['rotation_deg']:+.3f}° · truth {tr['rotation_deg']:+.3f}°"]
        for key, st in res.items():
            if key.startswith("ccf_after_"):
                reg = key[len("ccf_after_"):-len("_correction")]
                lines.append(f"CCF after {reg}: peak {st['ccf_peak']:.3f} / next {st['next_best_peak']:.3f}; "
                             f"lattice-aware rms {st['unwrapped_rms_err_px']:.2f} px, "
                             f"{100 * st['unwrapped_frac_off_by_a_cell']:.1f} % off a cell "
                             f"(dot windows {st.get('dots_only_unwrapped_rms_err_px', float('nan')):.3f} px); "
                             f"local expansion r {st['local_scale_corr']:.3f}")
        self.faithful.setText("<br>".join(lines))
