"""ExM Distortion Explorer: main window.

Sample view with draggable / resizable / rotatable sites, the site editor,
global, solver and analysis controls, live truth and measured overlays,
node grid and tag ids, and maxima / minima markers; right-hand panels for the
truth summary, the post view, ACF, CCF and metrics.

Two compute threads, both latest-request-wins: the truth field (cheap, every
change) and the analysis (fast tier while dragging: windowed CCF around the
selected site; full tier on release or 'Recompute full': every window, the
whole post ACF up to a 4096 px crop).

The sample view works in DESIGN um with y up (pyqtgraph's default), so sites
need no conversion; the pre image is placed with its px -> design affine.
"""

import copy
import os
import sys

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from . import live
from .panels import AcfPanel, CcfPanel, MetricsPanel, PostPanel
from .scenario import LAMBDA_PRESETS, Scenario, Site, legacy_scenario
from .worker import LatestWorker

pg.setConfigOptions(imageAxisOrder="row-major", antialias=True,
                    background="#141414", foreground="#c9c9c4")

# categorical slots of the reference palette (dark-mode steps), fixed order
SITE_COLORS = ["#d95926", "#3987e5", "#199e70", "#c98500", "#d55181", "#9085e9", "#e66767", "#008300"]

# diverging map (blue below the reference, neutral grey at it, orange above)
# and a one-hue sequential map; both readable on the dark background
# the neutral end is transparent so the image shows where nothing happens
DIVERGING = pg.ColorMap([0.0, 0.5, 1.0], [(57, 135, 229, 255), (58, 58, 55, 0), (217, 89, 38, 255)])
SEQUENTIAL = pg.ColorMap([0.0, 1.0], [(29, 42, 60, 0), (156, 200, 255, 255)])

HEATMAPS = {
    "none": None,
    "true local expansion": dict(key="expansion", cmap="div", ref="lam", unit="", fmt="{:.4f}"),
    "true local anisotropy": dict(key="anisotropy", cmap="seq", ref=1.0, unit="", fmt="{:.4f}"),
    "true local rotation": dict(key="rotation", cmap="div", ref=0.0, unit="°", fmt="{:+.3f}"),
    "measured local expansion (CCF)": dict(key="meas_scale", cmap="div", ref="median", unit="", fmt="{:.4f}",
                                           measured=True),
    "measured local anisotropy (CCF)": dict(key="meas_aniso", cmap="seq", ref=1.0, unit="", fmt="{:.4f}",
                                            measured=True),
}
EXTREMA_DEFAULT_DEV = {"expansion": 0.01, "anisotropy": 0.005, "rotation": 0.05,
                       "meas_scale": 0.02, "meas_aniso": 0.01}
MEASURED_EXTREMA_KEY = {"meas_scale": "measured_expansion", "meas_aniso": "measured_anisotropy"}


# ===================================================================== site ROI
class SiteROI(pg.EllipseROI):
    """Ellipse with move (drag the body), two semi-axis handles and a rotate
    handle. ROI frame: size = (2a, 2b), angle = phi (design frame)."""

    def __init__(self, site):
        super().__init__([0, 0], [1, 1], movable=True, rotatable=True, resizable=True)
        for h in list(self.getHandles()):
            self.removeHandle(h)
        self.addScaleHandle([1.0, 0.5], [0.5, 0.5])           # a
        self.addScaleHandle([0.5, 1.0], [0.5, 0.5])           # b
        d = 0.5 + 0.5 / np.sqrt(2)
        self.addRotateHandle([d, d], [0.5, 0.5])
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.site = site
        self.selected = False
        self.label = pg.TextItem(anchor=(0.5, 1.2))
        self.set_style()

    def set_style(self):
        c = QtGui.QColor(self.site.color)
        if not self.site.enabled:
            c.setAlpha(110)
        pen = pg.mkPen(c, width=3.0 if self.selected else 1.6,
                       style=Qt.PenStyle.SolidLine if self.site.enabled else Qt.PenStyle.DashLine)
        self.setPen(pen)
        self.hoverPen = pg.mkPen(c, width=3.5)
        self.label.setText(self.site.name)
        self.label.setColor(c)
        self.update()

    def set_from_site(self):
        s = self.site
        t = np.deg2rad(s.phi_deg)
        R = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
        corner = np.array([s.cx, s.cy]) - R @ [s.a, s.b]
        self.setPos(pg.Point(*corner), update=False)
        self.setSize(pg.Point(2 * s.a, 2 * s.b), update=False)
        self.setAngle(s.phi_deg, update=False)
        self.stateChanged(finish=False)
        self.label.setPos(s.cx, s.cy + s.b)

    def write_to_site(self):
        st = self.getState()
        a, b = abs(st["size"][0]) / 2, abs(st["size"][1]) / 2
        phi = st["angle"]
        t = np.deg2rad(phi)
        R = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
        c = np.array([st["pos"][0], st["pos"][1]]) + R @ [st["size"][0] / 2, st["size"][1] / 2]
        s = self.site
        s.cx, s.cy, s.a, s.b = float(c[0]), float(c[1]), float(max(a, 0.5)), float(max(b, 0.5))
        s.phi_deg = float((phi + 180) % 360 - 180)
        self.label.setPos(s.cx, s.cy + s.b)


# ===================================================================== small widgets
def spin(lo, hi, step, dec, value=0.0, suffix=""):
    w = QtWidgets.QDoubleSpinBox()
    w.setRange(lo, hi)
    w.setSingleStep(step)
    w.setDecimals(dec)
    w.setValue(value)
    w.setKeyboardTracking(False)
    if suffix:
        w.setSuffix(suffix)
    return w


def combo(items, current=None):
    w = QtWidgets.QComboBox()
    for it in items:
        w.addItem(it)
    if current is not None:
        w.setCurrentText(current)
    return w


def group(title, layout):
    g = QtWidgets.QGroupBox(title)
    g.setLayout(layout)
    return g


# ===================================================================== main window
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, scenario=None):
        super().__init__()
        self.setWindowTitle("ExM Distortion Explorer")
        self.resize(1500, 920)
        self.scen = scenario or self.default_scenario()
        self.rois = []
        self.current = None              # selected SiteROI
        self._syncing = False
        self.last_field = None
        self.last_pre = None
        self._shown_extrema = []

        self.field_worker = LatestWorker(self._run_field, "field")
        self.field_worker.done.connect(self.on_field)
        self.field_worker.failed.connect(self.on_failed)
        self.field_worker.start()
        self.pre_worker = LatestWorker(lambda p, stale: live.pre_job(p), "pre")
        self.pre_worker.done.connect(self.on_pre)
        self.pre_worker.failed.connect(self.on_failed)
        self.pre_worker.start()

        self.ana_worker = LatestWorker(self._run_analysis, "analysis")
        self.ana_worker.done.connect(self.on_analysis)
        self.ana_worker.failed.connect(self.on_failed)
        self.ana_worker.start()
        self.last_ana = None
        self.meas = None                 # merged measured maps (full + fast patches)
        self._dragging = False
        self._want_full = False          # a full run was asked for and not delivered yet

        self.field_timer = QtCore.QTimer(self, singleShot=True, interval=30)
        self.field_timer.timeout.connect(self.submit_field)
        self.pre_timer = QtCore.QTimer(self, singleShot=True, interval=150)
        self.pre_timer.timeout.connect(self.submit_pre)
        self.fast_timer = QtCore.QTimer(self, singleShot=True, interval=30)
        self.fast_timer.timeout.connect(lambda: self.submit_analysis("fast"))
        self.full_timer = QtCore.QTimer(self, singleShot=True, interval=600)
        self.full_timer.timeout.connect(lambda: self.submit_analysis("full"))

        self._build_view()
        self._build_side_panels()
        self._build_controls()
        self._build_menus()
        self.statusBar().showMessage("Rendering the pre image…")
        self.load_scenario(self.scen)

    @staticmethod
    def default_scenario():
        return Scenario(sites=[
            Site(cx=230, cy=530, a=40, b=40, eps1=-0.12, eps2=-0.12, lock_isotropic=True,
                 name="lagging patch", color=SITE_COLORS[0]),
            Site(cx=520, cy=260, a=60, b=30, phi_deg=30, eps1=0.05, eps2=-0.05,
                 name="anisotropic site", color=SITE_COLORS[1])], name="example")

    # ------------------------------------------------------------ view
    def _build_view(self):
        self.plot = pg.PlotWidget()
        pi = self.plot.getPlotItem()
        pi.setAspectLocked(True)
        pi.showGrid(False, False)
        pi.setLabel("bottom", "x (design µm)")
        pi.setLabel("left", "y (design µm, up)")
        pi.setXRange(-30, 780, padding=0)
        pi.setYRange(-30, 780, padding=0)
        self.vb = pi.getViewBox()
        self.vb.setMenuEnabled(False)

        self.bg = pg.ImageItem()
        self.bg.setZValue(-20)
        pi.addItem(self.bg)
        self.heat = pg.ImageItem()
        self.heat.setZValue(-10)
        self.heat.setOpacity(0.75)
        pi.addItem(self.heat)
        self.heat_meas = pg.ImageItem()
        self.heat_meas.setZValue(-10)
        self.heat_meas.setOpacity(0.75)
        pi.addItem(self.heat_meas)
        self.cbar = pg.ColorBarItem(values=(0, 1), colorMap=DIVERGING, interactive=False, width=14)
        self.cbar.setImageItem(self.heat, insert_in=pi)
        self.cbar.hide()
        self.grid_lines = pg.PlotCurveItem(pen=pg.mkPen("#8a8a84", width=1, style=Qt.PenStyle.DotLine),
                                           connect="pairs")
        self.grid_lines.setZValue(-5)
        pi.addItem(self.grid_lines)
        self.tag_labels = []
        self.arrows = pg.PlotCurveItem(pen=pg.mkPen(240, 239, 236, 200, width=1.2), connect="pairs")
        self.arrows.setZValue(5)
        pi.addItem(self.arrows)
        self.extrema_pts = pg.ScatterPlotItem(size=13, pxMode=True)
        self.extrema_pts.setZValue(20)
        pi.addItem(self.extrema_pts)
        self.plot.scene().sigMouseClicked.connect(self.on_scene_click)
        self.plot.scene().sigMouseMoved.connect(self.on_mouse_moved)

        for key in (QtGui.QKeySequence.StandardKey.Delete, QtGui.QKeySequence(Qt.Key.Key_Backspace)):
            sc = QtGui.QShortcut(key, self.plot)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(self.remove_current)

    def _build_side_panels(self):
        """Right-hand tabs: truth summary and extrema now, the post view, ACF,
        CCF and metrics panels in milestone 4."""
        self.tabs = QtWidgets.QTabWidget()
        truth = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(truth)
        self.truth_text = QtWidgets.QLabel()
        self.truth_text.setTextFormat(Qt.TextFormat.RichText)
        self.truth_text.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.truth_text.setWordWrap(True)
        lay.addWidget(self.truth_text)
        lay.addWidget(QtWidgets.QLabel("Maxima and minima (click a row to centre it):"))
        self.extrema_table = QtWidgets.QTableWidget(0, 5)
        self.extrema_table.setHorizontalHeaderLabels(["", "x µm", "y µm", "value", "deviation"])
        self.extrema_table.verticalHeader().setVisible(False)
        self.extrema_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.extrema_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.extrema_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.extrema_table.cellClicked.connect(self.on_extremum_clicked)
        lay.addWidget(self.extrema_table, 1)
        self.tabs.addTab(truth, "Truth")
        self.post_panel = PostPanel()
        self.acf_panel = AcfPanel()
        self.ccf_panel = CcfPanel()
        self.metrics_panel = MetricsPanel()
        self.tabs.addTab(self.post_panel, "Post")
        self.tabs.addTab(self.acf_panel, "ACF")
        self.tabs.addTab(self.ccf_panel, "CCF")
        self.tabs.addTab(self.metrics_panel, "Metrics")
        self.post_panel.regionRequested.connect(lambda *_: self.request_analysis())
        self.ccf_panel.extremumClicked.connect(self.centre_on_pre_px)
        split = QtWidgets.QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.plot)
        split.addWidget(self.tabs)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        split.setSizes([860, 640])
        self.setCentralWidget(split)

    # ------------------------------------------------------------ controls dock
    def _build_controls(self):
        panel = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(panel)
        v.setContentsMargins(6, 6, 6, 6)

        # --- sites
        sl = QtWidgets.QVBoxLayout()
        self.site_list = QtWidgets.QListWidget()
        self.site_list.setMaximumHeight(110)
        self.site_list.currentRowChanged.connect(self.on_list_select)
        for key in (QtGui.QKeySequence.StandardKey.Delete, QtGui.QKeySequence(Qt.Key.Key_Backspace)):
            sc = QtGui.QShortcut(key, self.site_list)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(self.remove_current)
        sl.addWidget(self.site_list)
        row = QtWidgets.QHBoxLayout()
        for text, fn in (("Add", self.add_site_centre), ("Duplicate", self.duplicate_current),
                         ("Remove", self.remove_current)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        sl.addLayout(row)
        hint = QtWidgets.QLabel("Double-click empty space to add a site; drag the ellipse to move it, "
                                "its two square handles for the semi-axes, the round one to rotate.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8a8a84; font-size: 11px")
        sl.addWidget(hint)

        f = QtWidgets.QFormLayout()
        f.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.e_name = QtWidgets.QLineEdit()
        self.e_enabled = QtWidgets.QCheckBox("enabled")
        self.e_color = QtWidgets.QPushButton()
        self.e_color.setFixedWidth(60)
        self.e_color.clicked.connect(self.pick_color)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.e_enabled)
        top.addWidget(self.e_color)
        self.e_profile = combo(["tanh", "gaussian"])
        self.e_cx = spin(-200, 950, 1, 1, suffix=" µm")
        self.e_cy = spin(-200, 950, 1, 1, suffix=" µm")
        self.e_a = spin(1, 800, 1, 1, suffix=" µm")
        self.e_b = spin(1, 800, 1, 1, suffix=" µm")
        self.e_phi = spin(-180, 180, 1, 1, suffix=" °")
        self.e_aspect = spin(0.05, 20, 0.05, 3)
        self.e_soft = spin(0, 2, 0.02, 2)
        self.e_eps1 = spin(-50, 50, 0.5, 2, suffix=" %")
        self.e_eps2 = spin(-50, 50, 0.5, 2, suffix=" %")
        self.e_lock = QtWidgets.QCheckBox("lock isotropic (ε₂ = ε₁)")
        self.e_aniso = spin(0.2, 5, 0.01, 4)
        self.e_follow = QtWidgets.QCheckBox("follows φ")
        self.e_epsang = spin(-180, 180, 1, 1, suffix=" °")
        epsang = QtWidgets.QHBoxLayout()
        epsang.addWidget(self.e_follow)
        epsang.addWidget(self.e_epsang)
        f.addRow("name", self.e_name)
        f.addRow("", top)
        f.addRow("edge profile", self.e_profile)
        f.addRow("centre x", self.e_cx)
        f.addRow("centre y", self.e_cy)
        f.addRow("semi-axis a", self.e_a)
        f.addRow("semi-axis b", self.e_b)
        f.addRow("orientation φ", self.e_phi)
        f.addRow("site shape a/b", self.e_aspect)
        f.addRow("edge softness", self.e_soft)
        f.addRow("ε₁ (along)", self.e_eps1)
        f.addRow("ε₂ (across)", self.e_eps2)
        f.addRow("", self.e_lock)
        f.addRow("strain anisotropy\n(1+ε₁)/(1+ε₂)", self.e_aniso)
        f.addRow("eigenstrain angle", epsang)
        self.e_aspect.setToolTip("Changes a/b keeping the site's area")
        self.e_aniso.setToolTip("Changes (1+ε₁)/(1+ε₂) keeping the area change (1+ε₁)(1+ε₂)")
        self.e_soft.setToolTip("Width of the tanh edge as a fraction of the size; 0 = sharp. "
                               "For the gaussian profile, a and b are the sigmas")
        self.editor = QtWidgets.QWidget()
        self.editor.setLayout(f)
        sl.addWidget(self.editor)
        v.addWidget(group("Sites", sl))

        for w in (self.e_cx, self.e_cy, self.e_a, self.e_b, self.e_phi, self.e_soft, self.e_eps1,
                  self.e_eps2, self.e_epsang):
            w.valueChanged.connect(self.on_editor)
        self.e_aspect.valueChanged.connect(self.on_aspect)
        self.e_aniso.valueChanged.connect(self.on_strain_aniso)
        self.e_name.editingFinished.connect(self.on_editor)
        for w in (self.e_enabled, self.e_lock, self.e_follow):
            w.toggled.connect(self.on_editor)
        self.e_profile.currentTextChanged.connect(self.on_editor)

        # --- expansion and imaging
        g = QtWidgets.QFormLayout()
        self.c_preset = combo(list(LAMBDA_PRESETS) + ["custom"])
        self.c_lam = spin(1, 12, 0.1, 2)
        self.c_theta = spin(-45, 45, 0.5, 2, suffix=" °")
        self.c_theta_pre = spin(-45, 45, 0.1, 2, suffix=" °")
        self.c_gel = spin(0, 5, 0.05, 2, suffix=" µm")
        self.c_print = spin(0, 2, 0.01, 2, suffix=" µm")
        self.c_noise = QtWidgets.QCheckBox("shot + read noise")
        self.c_psf = spin(1.5, 3.0, 0.05, 2, suffix=" µm")
        self.c_seed = QtWidgets.QSpinBox()
        self.c_seed.setRange(0, 1_000_000)
        g.addRow("λ preset", self.c_preset)
        g.addRow("λ", self.c_lam)
        g.addRow("stage rotation (post)", self.c_theta)
        g.addRow("stage rotation (pre)", self.c_theta_pre)
        g.addRow("gel jitter (post µm)", self.c_gel)
        g.addRow("print jitter", self.c_print)
        g.addRow("", self.c_noise)
        g.addRow("PSF FWHM", self.c_psf)
        g.addRow("seed", self.c_seed)
        v.addWidget(group("Expansion and imaging", g))
        self.c_preset.currentTextChanged.connect(self.on_preset)
        self.c_lam.valueChanged.connect(self.on_lambda)
        for w in (self.c_theta, self.c_gel):
            w.valueChanged.connect(self.on_imaging_post)
        for w in (self.c_theta_pre, self.c_print, self.c_psf):
            w.valueChanged.connect(self.on_imaging_pre)
        self.c_noise.toggled.connect(self.on_imaging_pre)
        self.c_seed.valueChanged.connect(self.on_imaging_pre)

        # --- solver
        s = QtWidgets.QFormLayout()
        self.s_model = combo(["navier", "kinematic (legacy)"])
        self.s_nu = spin(0, 0.49, 0.01, 2)
        self.s_mode = combo(["plane strain", "plane stress"])
        self.s_mean = combo(["zero mean strain", "traction-free"])
        s.addRow("model", self.s_model)
        s.addRow("Poisson ratio ν", self.s_nu)
        s.addRow("", self.s_mode)
        s.addRow("boundary", self.s_mean)
        self.s_mean.setToolTip("zero: sites leave the global expansion alone (as exm_sim). "
                               "traction-free: adds the mean eigenstrain (zero average stress)")
        v.addWidget(group("Solver", s))
        self.s_model.currentTextChanged.connect(self.on_solver)
        self.s_nu.valueChanged.connect(self.on_solver)
        self.s_mode.currentTextChanged.connect(self.on_solver)
        self.s_mean.currentTextChanged.connect(self.on_solver)

        # --- analysis
        q = QtWidgets.QFormLayout()
        self.a_reg = combo(["tag centres", "ACF", "truth"])
        self.a_tagnoise = spin(0, 5, 0.05, 2, 0.3, suffix=" px")
        self.a_tagnoise.setToolTip("Live mode simulates tag detection: true centres plus this noise")
        self.a_win = combo(["32", "48", "64", "96", "128"], "64")
        self.a_step = QtWidgets.QSpinBox()
        self.a_step.setRange(8, 128)
        self.a_step.setSingleStep(4)
        self.a_step.setSuffix(" px")
        self.a_search = QtWidgets.QSpinBox()
        self.a_search.setRange(4, 40)
        self.a_search.setSuffix(" px")
        self.a_ccfmin = spin(0, 50, 0.5, 1, 1.0, suffix=" px")
        self.a_ccfmin.setToolTip("Mark |displacement| maxima at least this large")
        self.a_auto = QtWidgets.QCheckBox("full tier on release / after edits")
        self.a_auto.setChecked(True)
        self.a_full = QtWidgets.QPushButton("Recompute full")
        self.a_full.clicked.connect(lambda: self.submit_analysis("full"))
        self.a_status = QtWidgets.QLabel("–")
        self.a_status.setStyleSheet("color: #8a8a84")
        q.addRow("registration", self.a_reg)
        q.addRow("tag detection noise", self.a_tagnoise)
        q.addRow("CCF window", self.a_win)
        q.addRow("CCF step", self.a_step)
        q.addRow("search radius", self.a_search)
        q.addRow("mark |d| maxima ≥", self.a_ccfmin)
        q.addRow(self.a_auto)
        q.addRow(self.a_full, self.a_status)
        v.addWidget(group("Analysis (ACF / CCF)", q))
        self.a_reg.currentTextChanged.connect(self.on_analysis_settings)
        self.a_tagnoise.valueChanged.connect(self.on_analysis_settings)
        self.a_win.currentTextChanged.connect(self.on_analysis_settings)
        self.a_step.valueChanged.connect(self.on_analysis_settings)
        self.a_search.valueChanged.connect(self.on_analysis_settings)
        self.a_ccfmin.valueChanged.connect(self.on_analysis_settings)

        # --- overlays and extrema
        o = QtWidgets.QFormLayout()
        self.o_bg = combo(["pre image", "design render", "none"])
        self.o_heat = combo(list(HEATMAPS), "true local expansion")
        self.o_opacity = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.o_opacity.setRange(0, 100)
        self.o_opacity.setValue(75)
        self.o_arrows = QtWidgets.QCheckBox("true displacement arrows")
        self.o_arrows.setChecked(True)
        self.o_scale = spin(0.5, 500, 1, 1, 10.0, suffix=" ×")
        self.o_grid = QtWidgets.QCheckBox("node grid and tag ids")
        self.o_grid.setChecked(True)
        self.o_ext = QtWidgets.QCheckBox("mark maxima ▲ and minima ▼")
        self.o_ext.setChecked(True)
        self.o_sep = spin(2, 300, 2, 0, 30, suffix=" µm")
        self.o_dev = spin(0, 10, 0.001, 4, EXTREMA_DEFAULT_DEV["expansion"])
        self.o_dev.setToolTip("Only extrema at least this far from the reference value "
                              "(λ for expansion, 1 for anisotropy, 0 for rotation)")
        o.addRow("background", self.o_bg)
        o.addRow("heatmap", self.o_heat)
        o.addRow("opacity", self.o_opacity)
        o.addRow(self.o_arrows, self.o_scale)
        o.addRow("", self.o_grid)
        o.addRow("", self.o_ext)
        o.addRow("min separation", self.o_sep)
        o.addRow("min deviation", self.o_dev)
        v.addWidget(group("Overlays", o))
        self.o_bg.currentTextChanged.connect(self.show_background)
        self.o_heat.currentTextChanged.connect(self.on_heatmap_choice)
        self.o_opacity.valueChanged.connect(lambda x: self.heat.setOpacity(x / 100))
        self.o_arrows.toggled.connect(self.draw_field)
        self.o_scale.valueChanged.connect(self.draw_field)
        self.o_grid.toggled.connect(self.draw_grid)
        self.o_ext.toggled.connect(self.request_field)
        self.o_sep.valueChanged.connect(self.request_field)
        self.o_dev.valueChanged.connect(self.request_field)
        v.addStretch(1)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(330)
        dock = QtWidgets.QDockWidget("Controls", self)
        dock.setObjectName("controls")
        dock.setWidget(scroll)
        dock.setFeatures(QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable |
                         QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

    def _build_menus(self):
        m = self.menuBar().addMenu("&File")
        for text, fn, key in (("New scenario", self.new_scenario, QtGui.QKeySequence.StandardKey.New),
                              ("Open scenario…", self.open_scenario, QtGui.QKeySequence.StandardKey.Open),
                              ("Save scenario…", self.save_scenario, QtGui.QKeySequence.StandardKey.Save),
                              (None, None, None),
                              ("Load the exm_sim batch-run scenario", self.load_legacy, None),
                              (None, None, None),
                              ("Quit", self.close, QtGui.QKeySequence.StandardKey.Quit)):
            if text is None:
                m.addSeparator()
                continue
            a = m.addAction(text)
            a.triggered.connect(fn)
            if key is not None:
                a.setShortcut(key)
        v = self.menuBar().addMenu("&View")
        a = v.addAction("Reset zoom")
        a.triggered.connect(lambda: self.vb.setRange(xRange=(-30, 780), yRange=(-30, 780), padding=0))

    # ------------------------------------------------------------ scenario <-> widgets
    def load_scenario(self, scen):
        self.scen = scen
        self._syncing = True
        try:
            im, so = scen.imaging, scen.solver
            preset = next((k for k, v in LAMBDA_PRESETS.items() if abs(v - im.lam) < 1e-9), "custom")
            self.c_preset.setCurrentText(preset)
            self.c_lam.setValue(im.lam)
            self.c_theta.setValue(im.theta_post_deg)
            self.c_theta_pre.setValue(im.theta_pre_deg)
            self.c_gel.setValue(im.gel_jitter_um)
            self.c_print.setValue(im.print_jitter_um)
            self.c_noise.setChecked(im.noise)
            self.c_psf.setValue(im.psf_fwhm_um)
            self.c_seed.setValue(im.seed)
            self.s_model.setCurrentText("navier" if so.model == "navier" else "kinematic (legacy)")
            self.s_nu.setValue(so.nu)
            self.s_mode.setCurrentText(so.mode.replace("_", " "))
            self.s_mean.setCurrentText("zero mean strain" if so.mean_strain == "zero" else "traction-free")
            an_ = scen.analysis
            self.a_reg.setCurrentText({"tags": "tag centres", "acf": "ACF", "truth": "truth"}[an_.registration])
            self.a_tagnoise.setValue(an_.tag_noise_px)
            self.a_win.setCurrentText(str(an_.win))
            self.a_step.setValue(an_.step)
            self.a_search.setValue(an_.search)
        finally:
            self._syncing = False
        for r in self.rois:
            self.plot.removeItem(r)
            self.plot.removeItem(r.label)
        self.rois = []
        self.current = None
        for s in scen.sites:
            self._add_roi(s)
        self.refresh_list()
        self.select(self.rois[0] if self.rois else None)
        self.update_solver_widgets()
        self.submit_pre()
        self.request_field()
        self.meas = None
        self.request_analysis(full=True)

    def _add_roi(self, site):
        r = SiteROI(site)
        r.set_from_site()
        self.plot.addItem(r)
        self.plot.addItem(r.label)
        r.sigRegionChanged.connect(self.on_roi_changed)
        r.sigRegionChangeFinished.connect(self.on_roi_released)
        r.sigClicked.connect(lambda roi, ev: self.select(roi))
        self.rois.append(r)
        return r

    def refresh_list(self):
        self.site_list.blockSignals(True)
        self.site_list.clear()
        for r in self.rois:
            s = r.site
            it = QtWidgets.QListWidgetItem(f"{s.name}" + ("" if s.enabled else "  (off)"))
            it.setForeground(QtGui.QColor(s.color))
            self.site_list.addItem(it)
        if self.current in self.rois:
            self.site_list.setCurrentRow(self.rois.index(self.current))
        self.site_list.blockSignals(False)

    def select(self, roi):
        for r in self.rois:
            r.selected = r is roi
            r.set_style()
        self.current = roi
        self.editor.setEnabled(roi is not None)
        if roi is not None:
            self.site_list.blockSignals(True)
            self.site_list.setCurrentRow(self.rois.index(roi))
            self.site_list.blockSignals(False)
            self.load_editor()

    def load_editor(self):
        s = self.current.site
        self._syncing = True
        try:
            self.e_name.setText(s.name)
            self.e_enabled.setChecked(s.enabled)
            self.e_color.setStyleSheet(f"background: {s.color}")
            self.e_profile.setCurrentText(s.profile)
            self.e_cx.setValue(s.cx)
            self.e_cy.setValue(s.cy)
            self.e_a.setValue(s.a)
            self.e_b.setValue(s.b)
            self.e_phi.setValue(s.phi_deg)
            self.e_aspect.setValue(s.shape_aspect)
            self.e_soft.setValue(s.softness)
            e1, e2 = s.eps
            self.e_eps1.setValue(100 * e1)
            self.e_eps2.setValue(100 * e2)
            self.e_lock.setChecked(s.lock_isotropic)
            self.e_eps2.setEnabled(not s.lock_isotropic)
            self.e_aniso.setValue(s.strain_anisotropy)
            self.e_aniso.setEnabled(not s.lock_isotropic)
            self.e_follow.setChecked(s.eps_angle_deg is None)
            self.e_epsang.setValue(s.strain_angle_deg)
            self.e_epsang.setEnabled(s.eps_angle_deg is not None)
            self.e_soft.setEnabled(s.profile == "tanh")
        finally:
            self._syncing = False

    def update_solver_widgets(self):
        kin = self.s_model.currentText().startswith("kinematic")
        self.s_nu.setEnabled(not kin)
        self.s_mode.setEnabled(not kin)

    # ------------------------------------------------------------ editing
    def on_editor(self, *_):
        if self._syncing or self.current is None:
            return
        s = self.current.site
        s.name = self.e_name.text() or "site"
        s.enabled = self.e_enabled.isChecked()
        s.profile = self.e_profile.currentText()
        s.cx, s.cy = self.e_cx.value(), self.e_cy.value()
        s.a, s.b = self.e_a.value(), self.e_b.value()
        s.phi_deg = self.e_phi.value()
        s.softness = self.e_soft.value()
        s.lock_isotropic = self.e_lock.isChecked()
        s.eps1 = self.e_eps1.value() / 100
        s.eps2 = s.eps1 if s.lock_isotropic else self.e_eps2.value() / 100
        s.eps_angle_deg = None if self.e_follow.isChecked() else self.e_epsang.value()
        self.site_changed()

    def on_aspect(self, value):
        if self._syncing or self.current is None:
            return
        self.current.site.set_shape_aspect(value)
        self.site_changed()

    def on_strain_aniso(self, value):
        if self._syncing or self.current is None:
            return
        self.current.site.set_strain_anisotropy(value)
        self.site_changed()

    def site_changed(self):
        """A site's properties changed from the editor: redraw its ROI, refresh
        the derived editor fields, recompute."""
        self._dragging = False
        self._syncing = True
        try:
            self.current.set_from_site()
        finally:
            self._syncing = False
        self.current.set_style()
        self.load_editor()
        self.refresh_list()
        self.request_field()

    def on_roi_changed(self, roi):
        if self._syncing:
            return
        self._dragging = True
        roi.write_to_site()
        if roi is not self.current:
            self.select(roi)
        else:
            self.load_editor()
        self.request_field()

    def pick_color(self):
        if self.current is None:
            return
        c = QtWidgets.QColorDialog.getColor(QtGui.QColor(self.current.site.color), self, "Site colour")
        if c.isValid():
            self.current.site.color = c.name()
            self.site_changed()

    def next_color(self):
        used = {r.site.color for r in self.rois}
        return next((c for c in SITE_COLORS if c not in used), SITE_COLORS[len(self.rois) % len(SITE_COLORS)])

    def add_site(self, x, y):
        s = Site(cx=float(x), cy=float(y), a=40, b=40, eps1=-0.10, eps2=-0.10, lock_isotropic=True,
                 name=f"site {len(self.rois) + 1}", color=self.next_color())
        self.scen.sites.append(s)
        r = self._add_roi(s)
        self.refresh_list()
        self.select(r)
        self.request_field()

    def add_site_centre(self):
        c = self.vb.viewRect().center()
        self.add_site(c.x(), c.y())

    def duplicate_current(self):
        if self.current is None:
            return
        s = copy.deepcopy(self.current.site)
        s.cx += 30
        s.cy -= 30
        s.name += " copy"
        s.color = self.next_color()
        self.scen.sites.append(s)
        r = self._add_roi(s)
        self.refresh_list()
        self.select(r)
        self.request_field()

    def remove_current(self):
        r = self.current
        if r is None:
            return
        k = self.rois.index(r)
        self.plot.removeItem(r)
        self.plot.removeItem(r.label)
        self.rois.remove(r)
        self.scen.sites.remove(r.site)
        self.current = None
        self.refresh_list()
        self.select(self.rois[min(k, len(self.rois) - 1)] if self.rois else None)
        self.request_field()

    def on_list_select(self, row):
        if 0 <= row < len(self.rois):
            self.select(self.rois[row])

    def on_scene_click(self, ev):
        if not ev.double() or ev.button() != Qt.MouseButton.LeftButton:
            return
        for it in self.plot.scene().items(ev.scenePos()):
            node = it
            while node is not None:
                if isinstance(node, SiteROI):
                    return
                node = node.parentItem()
        p = self.vb.mapSceneToView(ev.scenePos())
        if self.vb.sceneBoundingRect().contains(ev.scenePos()):
            self.add_site(p.x(), p.y())

    def on_mouse_moved(self, pos):
        if not self.vb.sceneBoundingRect().contains(pos) or self.last_field is None:
            return
        p = self.vb.mapSceneToView(pos)
        F = self.last_field
        x = F["x"]
        i = int(round((p.x() - x[0]) / F["step"]))
        j = int(round((p.y() - x[0]) / F["step"]))
        if 0 <= i < len(x) and 0 <= j < len(x):
            m = F["maps"]
            self.statusBar().showMessage(
                f"x {p.x():7.1f} µm  y {p.y():7.1f} µm   |  expansion {m['expansion'][j, i]:.4f}   "
                f"anisotropy {m['anisotropy'][j, i]:.4f}   rotation {m['rotation'][j, i]:+.3f}°   "
                f"|  last update {1e3 * F['t_total']:.0f} ms")

    # ------------------------------------------------------------ global controls
    def on_preset(self, name):
        if self._syncing or name not in LAMBDA_PRESETS:
            return
        self.c_lam.setValue(LAMBDA_PRESETS[name])

    def on_lambda(self, value):
        if self._syncing:
            return
        self.scen.imaging.lam = float(value)
        preset = next((k for k, v in LAMBDA_PRESETS.items() if abs(v - value) < 1e-9), "custom")
        self.c_preset.blockSignals(True)
        self.c_preset.setCurrentText(preset)
        self.c_preset.blockSignals(False)
        self.request_field()

    def on_imaging_post(self, *_):
        if self._syncing:
            return
        im = self.scen.imaging
        im.theta_post_deg = self.c_theta.value()
        im.gel_jitter_um = self.c_gel.value()
        self.request_analysis()

    def on_imaging_pre(self, *_):
        if self._syncing:
            return
        im = self.scen.imaging
        im.theta_pre_deg = self.c_theta_pre.value()
        im.print_jitter_um = self.c_print.value()
        im.psf_fwhm_um = self.c_psf.value()
        im.noise = self.c_noise.isChecked()
        im.seed = int(self.c_seed.value())
        self.pre_timer.start()
        self.meas = None
        self.request_analysis()

    def on_solver(self, *_):
        if self._syncing:
            return
        so = self.scen.solver
        so.model = "navier" if self.s_model.currentText() == "navier" else "kinematic"
        so.nu = self.s_nu.value()
        so.mode = self.s_mode.currentText().replace(" ", "_")
        so.mean_strain = "zero" if self.s_mean.currentText().startswith("zero") else "traction_free"
        self.update_solver_widgets()
        self.request_field()

    def on_heatmap_choice(self, name):
        spec = HEATMAPS.get(name)
        if isinstance(spec, dict):
            self.o_dev.blockSignals(True)
            self.o_dev.setValue(EXTREMA_DEFAULT_DEV[spec["key"]])
            self.o_dev.blockSignals(False)
        self.draw_field()
        self.request_field()

    # ------------------------------------------------------------ compute
    def request_field(self, *_):
        self.field_timer.start()
        self.request_analysis()

    def request_analysis(self, *_, full=False):
        """Fast tier now (debounced), and the full tier once things settle."""
        if full:
            self.full_timer.start(50)
            return
        self.fast_timer.start()
        if self.a_auto.isChecked() and not self._dragging:
            self.full_timer.start()
        else:
            self.full_timer.stop()

    def on_roi_released(self, roi):
        self._dragging = False
        if self.a_auto.isChecked():
            self.full_timer.start(50)

    def submit_analysis(self, tier):
        if tier == "full":
            self.full_timer.stop()
            self._want_full = True
        focus = copy.deepcopy(self.current.site) if self.current is not None else None
        n = self.post_panel.n
        region = self.post_panel.visible_region() if n else None
        self.a_status.setText(f"computing ({tier})…")
        self.ana_worker.submit(dict(scen=copy.deepcopy(self.scen), tier=tier, focus=focus, region=region,
                                    extrema=dict(ccf_min_px=self.a_ccfmin.value(),
                                                 aniso_min=EXTREMA_DEFAULT_DEV["meas_aniso"]
                                                 if self.o_heat.currentText() != "measured local anisotropy (CCF)"
                                                 else self.o_dev.value(),
                                                 expansion_min=EXTREMA_DEFAULT_DEV["meas_scale"]
                                                 if self.o_heat.currentText() != "measured local expansion (CCF)"
                                                 else self.o_dev.value())))

    @staticmethod
    def _run_analysis(p, is_stale):
        try:
            return live.analysis_job(p["scen"], p["tier"], post_region=p["region"], focus_site=p["focus"],
                                     extrema=p["extrema"], is_stale=is_stale)
        except live.Stale:
            return None

    def on_analysis_settings(self, *_):
        if self._syncing:
            return
        a = self.scen.analysis
        a.registration = {"tag centres": "tags", "ACF": "acf", "truth": "truth"}[self.a_reg.currentText()]
        a.tag_noise_px = self.a_tagnoise.value()
        a.win = int(self.a_win.currentText())
        a.step = int(self.a_step.value())
        a.search = int(self.a_search.value())
        self.meas = None
        self.request_analysis()

    def on_analysis(self, gen, r):
        self.last_ana = r
        if r["tier"] == "full":
            self._want_full = False
        elif self._want_full and not self._dragging and not self.full_timer.isActive():
            self.full_timer.start(50)     # a newer fast request superseded it: ask again
        self.merge_measured(r)
        self.post_panel.set_size(r["metrics"].get("post_size") or self.post_panel.n)
        self.acf_panel.update(r)
        self.ccf_panel.update(r)
        self.post_panel.update(r)
        self.metrics_panel.update(r)
        m = r["metrics"]
        self.a_status.setText(f"{r['tier']}: {1e3 * m['total_s']:.0f} ms")
        self.draw_field()

    def merge_measured(self, r):
        """Keep the last full-tier maps and patch in the windows a fast-tier
        run recomputed, so the overlay never goes blank while dragging."""
        new = dict(meas_scale=r["meas_scale"], meas_aniso=r["meas_aniso"], cs_x=r["cs_x"], cs_y=r["cs_y"])
        w = r["which"]
        old = self.meas
        if w is None or old is None or old["meas_scale"].shape != new["meas_scale"].shape:
            self.meas = new
        else:
            for k in ("meas_scale", "meas_aniso"):
                old[k] = np.where(w, new[k], old[k])
        self.meas["extrema"] = r["extrema"]

    def centre_on_pre_px(self, x, y):
        if self.last_pre is None:
            return
        Ad, D0 = self.last_pre["px_to_design"]
        d = Ad @ [x, y] + D0
        r = self.vb.viewRect()
        self.vb.setRange(xRange=(d[0] - r.width() / 2, d[0] + r.width() / 2),
                         yRange=(d[1] - r.height() / 2, d[1] + r.height() / 2), padding=0)

    def submit_field(self):
        spec = HEATMAPS.get(self.o_heat.currentText())
        ext = None
        if self.o_ext.isChecked() and isinstance(spec, dict):
            ext = dict(map=spec["key"], min_separation_um=self.o_sep.value(),
                       min_deviation=self.o_dev.value())
        self.field_worker.submit(dict(sites=copy.deepcopy(self.scen.sites),
                                      solver=copy.deepcopy(self.scen.solver),
                                      lam=self.scen.imaging.lam, extrema=ext))

    @staticmethod
    def _run_field(p, is_stale):
        return live.field_job(p["sites"], p["solver"], p["lam"], arrow_step=37.5, extrema=p["extrema"])

    def submit_pre(self):
        self.statusBar().showMessage("Rendering the pre image…")
        self.pre_worker.submit(copy.deepcopy(self.scen))

    def on_failed(self, gen, text):
        print(text, file=sys.stderr)
        self.statusBar().showMessage("Computation failed: " + text.strip().splitlines()[-1])

    def on_pre(self, gen, res):
        self.last_pre = res
        Ad, D0 = res["px_to_design"]
        o = D0 - Ad @ [0.5, 0.5]                     # pixel i covers [i - 0.5, i + 0.5]
        self.bg_transform = QtGui.QTransform(Ad[0, 0], Ad[1, 0], Ad[0, 1], Ad[1, 1], o[0], o[1])
        self.show_background()
        self.draw_grid()
        self.statusBar().showMessage(f"Pre image ready ({1e3 * res['t_total']:.0f} ms)", 4000)

    def show_background(self, *_):
        if self.last_pre is None:
            return
        which = self.o_bg.currentText()
        if which == "none":
            self.bg.hide()
            return
        img = self.last_pre["pre" if which == "pre image" else "design"]
        lo, hi = np.percentile(img, [1, 99.7])
        self.bg.setImage(img, levels=(lo, hi), autoLevels=False)
        self.bg.setTransform(self.bg_transform)
        self.bg.show()

    def draw_grid(self, *_):
        for t in self.tag_labels:
            self.plot.removeItem(t)
        self.tag_labels = []
        if not self.o_grid.isChecked() or self.last_pre is None:
            self.grid_lines.setData([], [])
            return
        p = self.last_pre["node_pitch"]
        nodes = 11.5 + p * np.arange(6)
        xs, ys = [], []
        for n in nodes:
            xs += [n, n, nodes[0], nodes[-1]]
            ys += [nodes[0], nodes[-1], n, n]
        self.grid_lines.setData(np.array(xs), np.array(ys))
        for (x, y), i in zip(self.last_pre["tag_xy"], self.last_pre["tag_id"]):
            t = pg.TextItem(str(int(i)), color="#f0efec", anchor=(-0.15, 1.1))
            t.setPos(x + 11.5, y + 11.5)
            t.setZValue(15)
            self.plot.addItem(t)
            self.tag_labels.append(t)

    def on_field(self, gen, res):
        self.last_field = res
        self.draw_field()

    def draw_field(self, *_):
        F = self.last_field
        if F is None:
            return
        lam = self.scen.imaging.lam
        name = self.o_heat.currentText()
        spec = HEATMAPS.get(name)
        self.heat.hide()
        self.heat_meas.hide()
        self.cbar.hide()
        ex = []
        if isinstance(spec, dict) and spec.get("measured"):
            M = self.meas
            if M is not None and self.last_pre is not None:
                img = M[spec["key"]]
                ref = float(np.nanmedian(img)) if spec["ref"] == "median" else spec["ref"]
                self._show_heat(self.heat_meas, img, spec, ref, name)
                cs_x, cs_y = M["cs_x"], M["cs_y"]
                st = float(cs_x[1] - cs_x[0])
                Ad, D0 = self.last_pre["px_to_design"]
                # window (col, row) -> pre px -> design um
                L = Ad * st
                o = D0 + Ad @ [cs_x[0] - st / 2, cs_y[0] - st / 2]
                self.heat_meas.setTransform(QtGui.QTransform(L[0, 0], L[1, 0], L[0, 1], L[1, 1], o[0], o[1]))
                for e in M["extrema"].get(MEASURED_EXTREMA_KEY[spec["key"]], []):
                    d = Ad @ [e["x"], e["y"]] + D0
                    ex.append(dict(e, x=float(d[0]), y=float(d[1])))
        elif isinstance(spec, dict):
            img = F["maps"][spec["key"]]
            ref = lam if spec["ref"] == "lam" else spec["ref"]
            self._show_heat(self.heat, img, spec, ref, name)
            x = F["x"]
            st = F["step"]
            self.heat.setRect(QtCore.QRectF(x[0] - st / 2, x[0] - st / 2, len(x) * st, len(x) * st))
            ex = F["extrema"]

        if self.o_arrows.isChecked():
            P, U = F["arrow_xy"], F["arrow_u"] * self.o_scale.value()
            T = P + U
            L = np.hypot(U[:, 0], U[:, 1])
            keep = L > 0.4
            P, T, U, L = P[keep], T[keep], U[keep], L[keep]
            d = U / L[:, None]
            hl = np.minimum(0.35 * L, 6.0)[:, None]
            c, s = np.cos(np.deg2rad(25)), np.sin(np.deg2rad(25))
            h1 = T - hl * np.c_[c * d[:, 0] - s * d[:, 1], s * d[:, 0] + c * d[:, 1]]
            h2 = T - hl * np.c_[c * d[:, 0] + s * d[:, 1], -s * d[:, 0] + c * d[:, 1]]
            segs = np.stack([P, T, T, h1, T, h2], 1).reshape(-1, 2)
            self.arrows.setData(segs[:, 0], segs[:, 1])
            self.arrows.show()
        else:
            self.arrows.hide()

        ex = ex if self.o_ext.isChecked() else []
        spots = [dict(pos=(e["x"], e["y"]), symbol="t1" if e["kind"] == "max" else "t",
                      brush=pg.mkBrush("#d95926" if e["kind"] == "max" else "#3987e5"),
                      pen=pg.mkPen("#f0efec", width=1.5)) for e in ex]
        self.extrema_pts.setData(spots)
        self._shown_extrema = ex
        self.fill_extrema_table(ex, spec)
        self.fill_truth_text(F, lam)

    def _show_heat(self, item, img, spec, ref, name):
        if spec["cmap"] == "div":
            span = max(float(np.nanmax(np.abs(img - ref))) if np.isfinite(img).any() else 0.0,
                       1e-3 * max(abs(ref), 1))
            lo, hi, cmap = ref - span, ref + span, DIVERGING
        else:
            top = float(np.nanmax(img)) if np.isfinite(img).any() else ref
            lo, hi, cmap = ref, max(top, ref + 1e-3), SEQUENTIAL
        item.setImage(np.where(np.isfinite(img), img, np.nan).astype(np.float32), autoLevels=False)
        self.cbar.setImageItem(item)
        self.cbar.setColorMap(cmap)
        self.cbar.setLevels((lo, hi))
        self.cbar.setLabel("right", name)
        item.show()
        self.cbar.show()

    def fill_extrema_table(self, ex, spec):
        fmt = spec["fmt"] if isinstance(spec, dict) else "{:.4f}"
        t = self.extrema_table
        t.setRowCount(len(ex))
        for k, e in enumerate(ex):
            vals = ["▲ max" if e["kind"] == "max" else "▼ min", f"{e['x']:.1f}", f"{e['y']:.1f}",
                    fmt.format(e["value"]), f"{e['deviation']:+.4f}"]
            for c, v in enumerate(vals):
                t.setItem(k, c, QtWidgets.QTableWidgetItem(v))

    def on_extremum_clicked(self, row, col):
        if row >= len(self._shown_extrema):
            return
        e = self._shown_extrema[row]
        r = self.vb.viewRect()
        self.vb.setRange(xRange=(e["x"] - r.width() / 2, e["x"] + r.width() / 2),
                         yRange=(e["y"] - r.height() / 2, e["y"] + r.height() / 2), padding=0)

    def fill_truth_text(self, F, lam):
        st = F["stats"]
        n_on = sum(s.enabled for s in self.scen.sites)
        model = "Navier" if self.scen.solver.model == "navier" else "kinematic (legacy)"
        self.truth_text.setText(
            f"<b>Ground truth</b> ({model}, {n_on} active site{'s' if n_on != 1 else ''})<br>"
            f"local expansion {st['expansion'][0]:.4f} … {st['expansion'][1]:.4f} "
            f"(global λ {lam:.3f})<br>"
            f"local anisotropy up to {st['anisotropy'][1]:.4f}<br>"
            f"local rotation {st['rotation'][0]:+.3f}° … {st['rotation'][1]:+.3f}°<br>"
            f"largest displacement {F['u_max']:.3f} µm (design, before ×λ)<br>"
            f"<span style='color:#8a8a84'>solve {1e3 * F['t_solve']:.0f} ms, "
            f"update {1e3 * F['t_total']:.0f} ms</span>")

    # ------------------------------------------------------------ files
    def new_scenario(self):
        self.load_scenario(Scenario(name="untitled"))

    def load_legacy(self):
        sc = legacy_scenario()
        for k, s in enumerate(sc.sites):
            s.color = SITE_COLORS[k]
        self.load_scenario(sc)

    def open_scenario(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open scenario", "", "Scenario (*.json)")
        if path:
            try:
                self.load_scenario(Scenario.load(path))
            except Exception as e:  # malformed file: say so, keep the current one
                QtWidgets.QMessageBox.warning(self, "Open scenario", f"Could not read {path}:\n{e}")

    def save_scenario(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save scenario", f"{self.scen.name}.json",
                                                        "Scenario (*.json)")
        if path:
            self.scen.save(path)
            self.statusBar().showMessage(f"Saved {path}", 4000)

    def closeEvent(self, ev):
        self.ana_worker.stop()
        self.field_worker.stop()
        self.pre_worker.stop()
        super().closeEvent(ev)


# ===================================================================== app
def dark_palette(app):
    app.setStyle("Fusion")
    p = QtGui.QPalette()
    base, alt, text = QtGui.QColor("#1a1a19"), QtGui.QColor("#232322"), QtGui.QColor("#e8e7e3")
    for role, col in ((QtGui.QPalette.ColorRole.Window, alt), (QtGui.QPalette.ColorRole.WindowText, text),
                      (QtGui.QPalette.ColorRole.Base, base), (QtGui.QPalette.ColorRole.AlternateBase, alt),
                      (QtGui.QPalette.ColorRole.Text, text), (QtGui.QPalette.ColorRole.Button, alt),
                      (QtGui.QPalette.ColorRole.ButtonText, text),
                      (QtGui.QPalette.ColorRole.ToolTipBase, base), (QtGui.QPalette.ColorRole.ToolTipText, text),
                      (QtGui.QPalette.ColorRole.Highlight, QtGui.QColor("#3987e5")),
                      (QtGui.QPalette.ColorRole.HighlightedText, QtGui.QColor("#ffffff"))):
        p.setColor(role, col)
    p.setColor(QtGui.QPalette.ColorGroup.Disabled, QtGui.QPalette.ColorRole.Text, QtGui.QColor("#6b6b66"))
    p.setColor(QtGui.QPalette.ColorGroup.Disabled, QtGui.QPalette.ColorRole.WindowText, QtGui.QColor("#6b6b66"))
    p.setColor(QtGui.QPalette.ColorGroup.Disabled, QtGui.QPalette.ColorRole.ButtonText, QtGui.QColor("#6b6b66"))
    app.setPalette(p)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    dark_palette(app)
    scen = Scenario.load(argv[0]) if argv and os.path.isfile(argv[0]) else None
    w = MainWindow(scen)
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
