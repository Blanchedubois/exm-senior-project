"""
stageui.stage_glyphgrid
=======================
Glyph-marker geometry stage (this copy's replacement for the ArUco stages).
Detects the fine dot lattice, refines it globally, locks the box grid from the
boundary dashes, and overlays dots + box boundaries + fiducial slots on the
image. Maths delegated to the headless `glyphtrack.lattice`.
"""
from __future__ import annotations
import os
import numpy as np
from PySide6 import QtWidgets

from collections import defaultdict
from gridtrack import io
from glyphtrack import lattice as lt
from glyphtrack import reader as gr
from glyphtrack import gridmodel as gm
from glyphtrack.classifier import GlyphClassifier

_STATE_COLOR = {"confirmed": (60, 230, 90), "corrected": (255, 190, 0),
                "predicted": (80, 160, 255), "conflict": (255, 60, 60),
                "raw": (200, 200, 200)}

_MODEL = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reference", "glyph_knn.yml")


class GlyphGridPanel(QtWidgets.QWidget):
    def __init__(self, state, canvas, log, parent=None):
        super().__init__(parent)
        self.state = state
        self.canvas = canvas
        self.log = log
        self._grid = None
        self._dots = None
        self._u8 = None

        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel("<b>Glyph grid — dots &amp; box lattice</b>"))
        root.addWidget(QtWidgets.QLabel(
            "<small>Recovers the marker geometry from the dot lattice, then locks the "
            "5×5 box grid from the boundary dashes.</small>"))

        form = QtWidgets.QFormLayout()
        self.dot_min = QtWidgets.QSpinBox(); self.dot_min.setRange(4, 400); self.dot_min.setValue(30)
        self.dot_max = QtWidgets.QSpinBox(); self.dot_max.setRange(20, 2000); self.dot_max.setValue(220)
        self.tophat = QtWidgets.QSpinBox(); self.tophat.setRange(5, 41); self.tophat.setSingleStep(2)
        self.tophat.setValue(15)
        form.addRow("dot area min", self.dot_min)
        form.addRow("dot area max", self.dot_max)
        form.addRow("dot top-hat (px)", self.tophat)
        root.addLayout(form)

        self.chk_dots = QtWidgets.QCheckBox("Show dots"); self.chk_dots.setChecked(True)
        self.chk_slots = QtWidgets.QCheckBox("Show fiducial slots"); self.chk_slots.setChecked(True)
        self.chk_dashes = QtWidgets.QCheckBox("Show dash centres (pink ▲)")
        self.chk_dashes.setChecked(True)
        root.addWidget(self.chk_dots); root.addWidget(self.chk_slots); root.addWidget(self.chk_dashes)

        self.b_run = QtWidgets.QPushButton("Detect grid")
        self.b_read = QtWidgets.QPushButton("Read glyphs (beta)")
        self.chk_weak = QtWidgets.QCheckBox("Show low-confidence reads (faint)")
        root.addWidget(self.b_run); root.addWidget(self.b_read); root.addWidget(self.chk_weak)
        self.b_solve = QtWidgets.QPushButton("Solve grid (auto-complete)")
        cf = QtWidgets.QFormLayout()
        self.s_club = QtWidgets.QDoubleSpinBox(); self.s_club.setRange(0.05, 0.30)
        self.s_club.setValue(0.12); self.s_club.setSingleStep(0.01)
        cf.addRow("digit club dist (×box)", self.s_club)
        root.addWidget(self.b_solve); root.addLayout(cf)

        # manual anchors — used when auto-registration can't lock the grid
        mbox = QtWidgets.QGroupBox("Identify a box (if solve fails)")
        ml = QtWidgets.QVBoxLayout(mbox)
        self.b_pick_num = QtWidgets.QPushButton("Set box number (click a box)")
        self.b_pick_num.setCheckable(True)
        self.b_pick_let = QtWidgets.QPushButton("Set letter (click a letter)")
        self.b_pick_let.setCheckable(True)
        self.b_clear_anchor = QtWidgets.QPushButton("Clear manual anchors")
        self.lbl_anchor = QtWidgets.QLabel("no manual anchors"); self.lbl_anchor.setWordWrap(True)
        ml.addWidget(self.b_pick_num); ml.addWidget(self.b_pick_let)
        ml.addWidget(self.b_clear_anchor); ml.addWidget(self.lbl_anchor)
        root.addWidget(mbox)
        self._fit = None
        self.summary = QtWidgets.QLabel("—"); self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        root.addStretch(1)

        self._clf = None
        self._pick_mode = None
        self.b_run.clicked.connect(self.run)
        self.b_read.clicked.connect(self.read)
        self.b_solve.clicked.connect(self.solve)
        self.b_pick_num.toggled.connect(lambda on: self._set_pick("number" if on else None))
        self.b_pick_let.toggled.connect(lambda on: self._set_pick("letter" if on else None))
        self.b_clear_anchor.clicked.connect(self._clear_anchors)
        self.canvas.clicked.connect(self._on_pick)
        self.chk_dots.toggled.connect(self._redraw)
        self.chk_slots.toggled.connect(self._redraw)
        self.chk_dashes.toggled.connect(self._redraw)
        self._dashes = None
        self._update_anchor_label()

    # ------------------------------------------------------------------ run
    def run(self):
        img = self.state.working_image()
        if img is None:
            self.log("Glyph grid: open an image first."); return
        self.log("Glyph grid: detecting dots…")
        QtWidgets.QApplication.processEvents()
        u8 = io.to_uint8(img)
        dots = lt.detect_dots(u8, tophat=self.tophat.value(),
                              dot_area=(self.dot_min.value(), self.dot_max.value()))
        if len(dots) < 30:
            self.summary.setText(f"only {len(dots)} dots found — adjust the dot size/top-hat.")
            self.log("Glyph grid: too few dots."); return
        basis = lt.refine_basis(dots, lt.estimate_basis(dots))
        dashes = lt.detect_dashes(u8)
        grid = lt.fit_box_grid(basis, dashes)
        self._dashes, ndrop = lt.dashes_on_grid(dashes, grid)   # keep only on-grid dash centres
        self._dots = dots; self._grid = grid; self._u8 = u8
        self.canvas.set_image(u8)
        self._redraw()
        self.summary.setText(
            f"dots: <b>{len(dots)}</b> (lattice {basis['n_inliers']} inliers)<br>"
            f"dot pitch: <b>{basis['pitch']:.1f}</b> px · angle <b>{basis['angle_deg']:.1f}°</b><br>"
            f"box pitch: <b>{grid['box_pitch']:.0f}</b> px<br>"
            f"dash centres on grid: <b>{len(self._dashes)}</b> "
            f"(pink ▲; {ndrop} off-line dropped)<br>"
            "<i>box grid is approximate — registration refinement is the next step.</i>")
        self.log(f"Glyph grid: {len(dots)} dots, box {grid['box_pitch']:.0f}px, "
                 f"{len(self._dashes)} dash centres on grid ({ndrop} dropped)")

    def _geometry(self, slots=True):
        grid = self._grid
        H, W = self._u8.shape

        def inb(p):
            return -60 <= p[0] <= W + 60 and -60 <= p[1] <= H + 60
        quads, num_pts, letter_pts = [], [], []
        for i in range(-2, 10):
            for j in range(-2, 10):
                corners = [lt.box_corner(grid, i, j), lt.box_corner(grid, i + 1, j),
                           lt.box_corner(grid, i + 1, j + 1), lt.box_corner(grid, i, j + 1)]
                if any(inb(c) for c in corners):
                    quads.append(corners)
                if slots:
                    for slot in lt.NUMBER_SLOTS:
                        p = lt.slot_point(grid, i, j, lt.FIDUCIALS[slot])
                        if inb(p):
                            num_pts.append(p)
                    for slot in lt.LETTER_SLOTS:
                        p = lt.slot_point(grid, i, j, lt.FIDUCIALS[slot])
                        if inb(p):
                            letter_pts.append(p)
        return quads, num_pts, letter_pts

    def _redraw(self, *_):
        if self._grid is None:
            return
        quads, num_pts, letter_pts = self._geometry(slots=self.chk_slots.isChecked())
        dash_pts = self._dashes if self.chk_dashes.isChecked() else None
        self.canvas.draw_glyph_grid(self._dots, quads, num_pts, letter_pts,
                                    show_dots=self.chk_dots.isChecked(), dash_pts=dash_pts)

    # ------------------------------------------------------------------ read
    def read(self):
        if self._grid is None:
            self.run()
        if self._grid is None:
            return
        if self._clf is None:
            if not os.path.exists(_MODEL):
                self.summary.setText("recognition model not found (reference/glyph_knn.yml)."); return
            self._clf = GlyphClassifier.load(_MODEL)
        self.log("Glyph grid: reading glyphs at slot positions…")
        QtWidgets.QApplication.processEvents()
        _coarse, fit = gr.read_glyphs(self._u8, self._clf, self._grid)   # geometry
        recs = gr.read_slots(self._u8, self._clf, fit)                   # OCR only at slots
        shown = [r for r in recs if r["interior"] and (self.chk_weak.isChecked() or r["conf"] >= 0.35)]
        # base overlay (grid only, no slot markers, so labels read clearly)
        quads, _, _ = self._geometry(slots=False)
        self.canvas.set_image(self._u8)
        self.canvas.draw_glyph_grid(self._dots if self.chk_dots.isChecked() else None,
                                    quads, None, None, show_dots=self.chk_dots.isChecked())
        strong = [r for r in shown if r["conf"] >= 0.45]
        weak = [r for r in shown if r["conf"] < 0.45]
        for group, lcol, dcol in ((strong, (60, 230, 90), (0, 200, 255)),
                                  (weak, (40, 130, 60), (0, 110, 150))):
            lets = [r for r in group if r["kind"] == "letter"]
            digs = [r for r in group if r["kind"] == "digit"]
            if lets:
                self.canvas.add_labels([(r["x"], r["y"]) for r in lets],
                                       [r["char"] for r in lets], color=lcol)
            if digs:
                self.canvas.add_labels([(r["x"], r["y"]) for r in digs],
                                       [r["char"] for r in digs], color=dcol)
        nl = sum(r["kind"] == "letter" for r in shown)
        self.summary.setText(
            f"read <b>{len(shown)}</b> interior glyphs ({nl} letters, {len(shown) - nl} digits)<br>"
            "green = letter, cyan = digit.<br>"
            "<i>Recognition on real frames is still limited (beta) — the geometry is solid; "
            "read accuracy needs training on real crops. Judge the labels by eye.</i>")
        self.log(f"Glyph grid: read {len(shown)} glyphs ({nl} letters)")

    # ------------------------------------------------------------------ solve
    def solve(self):
        """Read glyphs, then infer the 5x5 grid and auto-complete every slot from
        its redundancy + numbering rule; overlay per-glyph labels by state."""
        if self._grid is None:
            self.run()
        if self._grid is None:
            return
        if self._clf is None:
            if not os.path.exists(_MODEL):
                self.summary.setText("recognition model not found."); return
            self._clf = GlyphClassifier.load(_MODEL)
        self.log("Glyph grid: solving grid…")
        QtWidgets.QApplication.processEvents()
        _coarse, fit = gr.read_glyphs(self._u8, self._clf, self._grid)   # geometry
        self._fit = fit
        reads = gr.read_slots(self._u8, self._clf, fit)                  # OCR only at slots
        model = gm.build_grid_model(reads, fit, thresh_frac=self.s_club.value(),
                                    dots=self._dots, manual=self.state.glyph_manual)
        if not model["registered"]:
            self.canvas.set_image(self._u8)
            quads, _, _ = self._geometry(slots=False)
            self.canvas.draw_glyph_grid(None, quads, None, None, show_dots=False)
            self.summary.setText(
                "<b>Could not auto-register the grid.</b><br>" + model.get("reason", "") +
                "<br>Click <b>Set box number</b>, then click a box you can read and type its "
                "number — one or two boxes is enough. The numbers increase upward.")
            self.log("Glyph grid: not registered — identify a box.")
            return
        quads, _, _ = self._geometry(slots=False)
        self.canvas.set_image(self._u8)
        self.canvas.draw_glyph_grid(None, quads, None, None, show_dots=False)
        by_state = defaultdict(list)
        for L in model["labels"]:
            by_state[L["state"]].append(L)
        for st, items in by_state.items():
            self.canvas.add_labels([(L["x"], L["y"]) for L in items],
                                   [L["text"] for L in items],
                                   color=_STATE_COLOR.get(st, (200, 200, 200)))
        self.summary.setText(
            model["summary"].replace(" · ", "<br>") + "<br>"
            "<span style='color:#3ce65a'>confirmed</span> · "
            "<span style='color:#ffbe00'>corrected</span> · "
            "<span style='color:#50a0ff'>predicted</span> · "
            "<span style='color:#ff3c3c'>conflict</span>")
        self.log("Glyph grid: " + model["summary"])

    # ------------------------------------------------------ manual anchors
    def _set_pick(self, mode):
        self._pick_mode = mode
        self.canvas.set_pick(mode is not None)
        # keep the two toggle buttons mutually exclusive
        self.b_pick_num.blockSignals(True); self.b_pick_let.blockSignals(True)
        self.b_pick_num.setChecked(mode == "number")
        self.b_pick_let.setChecked(mode == "letter")
        self.b_pick_num.blockSignals(False); self.b_pick_let.blockSignals(False)
        if mode:
            self.log(f"Glyph grid: click a {'box to number' if mode=='number' else 'letter'}…")

    def _on_pick(self, x, y):
        if self._pick_mode is None or self._fit is None:
            return
        Minv = np.linalg.inv(np.column_stack([self._fit["U"], self._fit["V"]]))
        bc = (np.array([x, y]) - self._fit["O"]) @ Minv.T
        node = (int(np.floor(bc[0])), int(np.floor(bc[1])))
        if self._pick_mode == "number":
            N, ok = QtWidgets.QInputDialog.getInt(
                self, "Box number", f"Number for the clicked box {node} (1–25):", 1, 1, 25)
            if ok:
                self.state.glyph_manual["numbers"].append((node, int(N)))
        else:
            L, ok = QtWidgets.QInputDialog.getItem(
                self, "Letter", f"Which letter did you click (box {node})?",
                list("ABCD"), 0, False)
            if ok:
                self.state.glyph_manual["letters"].append(
                    {"box": node, "x": float(x), "y": float(y), "char": L})
        self._set_pick(None)
        self._update_anchor_label()
        if ok:
            self.solve()                                 # re-register with the new anchor

    def _clear_anchors(self):
        self.state.glyph_manual["numbers"].clear()
        self.state.glyph_manual["letters"].clear()
        self._update_anchor_label()
        self.log("Glyph grid: cleared manual anchors.")

    def _update_anchor_label(self):
        m = self.state.glyph_manual
        nums = ", ".join(f"{n}={N}" for n, N in m["numbers"])
        lets = ", ".join(f"{l['char']}@{l['box']}" for l in m["letters"])
        parts = [p for p in (nums, lets) if p]
        self.lbl_anchor.setText("manual: " + " · ".join(parts) if parts else "no manual anchors")
