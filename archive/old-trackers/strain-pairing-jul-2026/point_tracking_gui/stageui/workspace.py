"""
stageui.workspace
=================
StageWorkspace bundles the whole single-image 5-stage tuner — stage-nav list,
image canvas (with overlays), and the five stacked stage panels — into ONE
embeddable QWidget. Both the standalone point-tracking app and the expansion
app's Verify view embed this identically.
"""
from __future__ import annotations
from PySide6 import QtWidgets

from PySide6 import QtCore
from .state import AppState
from .canvas import ImageCanvas
from .stage1_correct import Stage1Panel
from .stage_glyphgrid import GlyphGridPanel
from .stage_results import ResultsPanel
from .stage_filter import DotFilterPanel

# This copy is repurposed to the OLD number/letter marker system, so the ArUco
# stages are replaced by the glyph-grid + results + dot-filter stages.
STAGE_NAMES = ["1  Correct optics", "2  Glyph grid", "3  Results", "4  Filter dots"]


class StageWorkspace(QtWidgets.QWidget):
    """A horizontal stage bar on top; below it a splitter of [ large canvas |
    scrollable stage-panel ], all sharing one AppState. Laid out so the image is
    the dominant element and the controls never squeeze it."""

    def __init__(self, state: AppState = None, log_fn=None, parent=None):
        super().__init__(parent)
        self.state = state or AppState()
        self._log = log_fn or (lambda *_: None)

        self.canvas = ImageCanvas()

        # stage nav: a horizontal bar (frees the ~170px a left list used to cost)
        self.tabbar = QtWidgets.QTabBar()
        self.tabbar.setExpanding(False)
        self.tabbar.setDrawBase(False)
        for name in STAGE_NAMES:
            self.tabbar.addTab(name)
        self.tabbar.currentChanged.connect(self._switch_stage)

        self.controls = QtWidgets.QStackedWidget()
        self.panels = [
            Stage1Panel(self.state, self.canvas, self.log),
            GlyphGridPanel(self.state, self.canvas, self.log),
            ResultsPanel(self.state, self.canvas, self.log),
            DotFilterPanel(self.state, self.canvas, self.log),
        ]
        for p in self.panels:
            self.controls.addWidget(p)

        # controls scroll (Stage-3 schematic / Stage-4 table are tall) with a
        # capped sensible width so they can't dictate the split
        self.ctrl_scroll = QtWidgets.QScrollArea()
        self.ctrl_scroll.setWidgetResizable(True)
        self.ctrl_scroll.setWidget(self.controls)
        self.ctrl_scroll.setMinimumWidth(250)
        self.ctrl_scroll.setMaximumWidth(360)
        self.ctrl_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self._ctrl_target = 290                 # preferred controls width; canvas gets the rest

        self.split = QtWidgets.QSplitter()
        self.split.addWidget(self.canvas)
        self.split.addWidget(self.ctrl_scroll)
        self.split.setStretchFactor(0, 1)      # canvas absorbs extra width on resize
        self.split.setStretchFactor(1, 0)
        self.split.setSizes([900, self._ctrl_target])

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(self.tabbar)
        lay.addWidget(self.split, 1)

    def showEvent(self, ev):
        """Pin the controls to their preferred width once the real geometry is
        known, handing every remaining pixel to the image (canvas)."""
        super().showEvent(ev)
        total = self.split.width()
        if total > 350:
            self.split.setSizes([total - self._ctrl_target, self._ctrl_target])

    def log(self, msg):
        self._log(msg)

    def _switch_stage(self, row):
        if 0 <= row < self.controls.count():
            self.controls.setCurrentIndex(row)
            if row == 0:                       # Correct optics: strip all point/grid
                self.canvas.clear_overlays()   # overlays so the raw image can be aligned
                self.panels[0]._recompute()

    def set_stage(self, i):
        self.tabbar.setCurrentIndex(i)

    def panel(self, i):
        return self.panels[i]

    # ------------------------------------------------------------ orchestration
    def run_all(self):
        """Run Stages 1→5 in order on the currently-loaded image, keeping the UI
        responsive between stages. Stage 1 is driven by _recompute; 2–5 by run().
        Stops early (with a log line) if a stage has no prerequisites."""
        self.panels[0]._recompute()                      # Stage 1 (optics)
        for p in self.panels[1:]:
            QtWidgets.QApplication.processEvents()
            p.run()

    def redraw_current(self):
        """Re-render the active stage's overlay for the current pipeline state
        (used after switching images so the visible stage reflects the new run)."""
        row = self.tabbar.currentIndex()
        pl = self.state.pipeline
        if row == 0:
            self.panels[0]._recompute()
        elif row == 1 and pl.detection is not None:
            d = pl.detection
            self.canvas.set_image(d.image)
            self.canvas.draw_detection(d.corners, d.centers, d.ids)
        elif row == 2 and pl.grid is not None:
            self.canvas.set_image(pl.detection.image)
            self.canvas.draw_grid(pl.grid, labels=True)
        elif row in (3, 4) and pl.features is not None:
            self.canvas.set_image(pl.detection.image)
            self.canvas.draw_features(pl.features)
