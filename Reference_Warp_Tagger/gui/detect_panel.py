"""
gui.detect_panel
================
Stage-2 control panel (second tab): detect the dot lattice, lock the box grid to
the boundary dashes, read the digit/letter glyphs at the fiducial slots, then
register the 5x5 grid and auto-complete every box number. Runs on the Stage-1
CORRECTED image. Maths delegated to the headless `rwtag.glyph`.

Modelled on the old `stageui/stage_glyphgrid.py`, rewired to the new AppState /
ImageCanvas and the staged `rwtag.glyph.detect` API.
"""
from __future__ import annotations
import os
from collections import defaultdict
from dataclasses import replace
import numpy as np
from PySide6 import QtWidgets, QtCore

from rwtag import io, correct as C
from rwtag.glyph import lattice as lt, detect as D
from rwtag.glyph.types import DetectResult

_STATE_COLOR = {"confirmed": (60, 230, 90), "corrected": (255, 190, 0),
                "predicted": (80, 160, 255), "conflict": (255, 60, 60),
                "raw": (200, 200, 200)}
_MODEL = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reference", "glyph_knn.yml")


class DetectPanel(QtWidgets.QWidget):
    deskewApplied = QtCore.Signal(float)     # emitted after Auto-deskew writes rotate_deg

    def __init__(self, state, canvas, log, parent=None):
        super().__init__(parent)
        self.state = state
        self.canvas = canvas
        self.log = log
        self._clf = None
        self._pick_mode = None
        # working results for this frame
        self._u8 = None
        self._geo = None          # dict from detect_grid
        self._read = None         # dict from read
        self._model = None        # build_grid_model output

        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel("<b>Stage 2 — Detect &amp; identify</b>"))
        _intro = QtWidgets.QLabel(
            "<small>Recovers the geometry from the dot lattice, locks the 5×5 box grid to the "
            "boundary dashes, reads the glyphs, then predicts every box number.</small>")
        _intro.setWordWrap(True)
        root.addWidget(_intro)

        # detection params
        form = QtWidgets.QFormLayout()
        self.dot_min = QtWidgets.QSpinBox(); self.dot_min.setRange(4, 400); self.dot_min.setValue(30)
        self.dot_max = QtWidgets.QSpinBox(); self.dot_max.setRange(20, 4000); self.dot_max.setValue(220)
        self.tophat = QtWidgets.QSpinBox(); self.tophat.setRange(5, 41); self.tophat.setSingleStep(2)
        self.tophat.setValue(15)
        form.addRow("dot area min", self.dot_min)
        form.addRow("dot area max", self.dot_max)
        form.addRow("dot top-hat (px)", self.tophat)
        root.addLayout(form)

        # progressive-disclosure buttons
        self.b_run = QtWidgets.QPushButton("1 · Detect grid")
        self.b_read = QtWidgets.QPushButton("2 · Read glyphs")
        self.b_solve = QtWidgets.QPushButton("3 · Solve grid (auto-complete)")
        self.b_deskew = QtWidgets.QPushButton("Auto-deskew (write to Stage 1)")
        for b in (self.b_run, self.b_read, self.b_solve, self.b_deskew):
            root.addWidget(b)
        cf = QtWidgets.QFormLayout()
        self.s_club = QtWidgets.QDoubleSpinBox(); self.s_club.setRange(0.05, 0.60)
        self.s_club.setValue(0.35); self.s_club.setSingleStep(0.01)
        cf.addRow("digit club dist (×box)", self.s_club)
        root.addLayout(cf)

        # manual anchors (high-expansion fallback)
        mbox = QtWidgets.QGroupBox("Identify a box (if solve fails)")
        ml = QtWidgets.QVBoxLayout(mbox)
        self.b_pick_num = QtWidgets.QPushButton("Set box number (click a box)")
        self.b_pick_num.setCheckable(True)
        self.b_pick_let = QtWidgets.QPushButton("Set letter (click a letter)")
        self.b_pick_let.setCheckable(True)
        self.b_clear_anchor = QtWidgets.QPushButton("Clear manual anchors")
        self.lbl_anchor = QtWidgets.QLabel("no manual anchors"); self.lbl_anchor.setWordWrap(True)
        for w in (self.b_pick_num, self.b_pick_let, self.b_clear_anchor, self.lbl_anchor):
            ml.addWidget(w)
        root.addWidget(mbox)

        # view toggles
        vo = QtWidgets.QGroupBox("View")
        vl = QtWidgets.QVBoxLayout(vo)
        self.chk_dots = QtWidgets.QCheckBox("Dots"); self.chk_dots.setChecked(True)
        self.chk_dashes = QtWidgets.QCheckBox("Dash centres (pink ▲)"); self.chk_dashes.setChecked(True)
        self.chk_slots = QtWidgets.QCheckBox("Fiducial slots"); self.chk_slots.setChecked(False)
        self.chk_weak = QtWidgets.QCheckBox("Low-confidence reads (faint)")
        self.chk_nums = QtWidgets.QCheckBox("Box numbers"); self.chk_nums.setChecked(True)
        for w in (self.chk_dots, self.chk_dashes, self.chk_slots, self.chk_weak, self.chk_nums):
            vl.addWidget(w)
        root.addWidget(vo)

        self.summary = QtWidgets.QLabel("Open an image and run Stage 1, then Detect grid.")
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        root.addStretch(1)

        # wiring
        self.b_run.clicked.connect(self.run_detect)
        self.b_read.clicked.connect(self.run_read)
        self.b_solve.clicked.connect(self.run_solve)
        self.b_deskew.clicked.connect(self.run_deskew)
        self.b_pick_num.toggled.connect(lambda on: self._set_pick("number" if on else None))
        self.b_pick_let.toggled.connect(lambda on: self._set_pick("letter" if on else None))
        self.b_clear_anchor.clicked.connect(self._clear_anchors)
        self.canvas.clicked.connect(self._on_pick)
        for chk in (self.chk_dots, self.chk_dashes, self.chk_slots, self.chk_weak, self.chk_nums):
            chk.toggled.connect(self._redraw)
        self.state.imageLoaded.connect(self._on_new_image)

    # ---------------------------------------------------------------- helpers
    def _classifier(self):
        if self._clf is None:
            if not os.path.exists(_MODEL):
                self.summary.setText("recognition model not found (reference/glyph_knn.yml)."); return None
            self._clf = D.load_classifier(_MODEL)
        return self._clf

    def _base_u8(self):
        """The image detection runs on: the Stage-1 corrected frame (or raw)."""
        img = self.state.working_image()
        return None if img is None else io.to_uint8(img)

    def _on_new_image(self):
        self._u8 = self._geo = self._read = self._model = None
        self.summary.setText("New image — run Stage 1, then Detect grid.")

    def load_from_state(self):
        """Restore panel caches from the active image's stored DetectResult
        (project selection change) — or clear if that image has none."""
        det = self.state.pipeline.detection
        self._update_anchor_label()
        if det is None:
            self._on_new_image()
            return
        self._u8 = det.u8
        self._geo = dict(dots=det.dots, basis=det.basis, dashes_all=det.dashes_all,
                         dashes_on_grid=det.dashes_on_grid, grid=det.grid,
                         n_dashes_dropped=det.n_dashes_dropped)
        self._read = (dict(glyphs=det.glyphs, fit=det.fit, reads=det.reads,
                           glyph_h=det.glyph_h) if det.fit is not None else None)
        self._model = det.model
        if det.model and det.model.get("registered"):
            self.summary.setText(det.model["summary"].replace(" · ", "<br>"))
        else:
            self.summary.setText("Detection restored — not registered yet (Solve / anchor).")

    def refresh_base_image(self):
        """Called when the tab is shown: put the current corrected frame on the canvas."""
        u8 = self._base_u8()
        if u8 is None:
            return
        h, w = u8.shape
        self.canvas.set_extent(w, h)
        if self._geo is None:
            self.canvas.set_image(u8, levels=(0, 255))
        else:
            self._redraw()

    def _store_detection(self):
        """Publish a DetectResult to state so Stage 3/4 + export can read it."""
        if self._geo is None:
            return
        g, r = self._geo, (self._read or {})
        det = DetectResult(
            u8=self._u8, dots=g["dots"], basis=g["basis"], dashes_all=g["dashes_all"],
            dashes_on_grid=g["dashes_on_grid"], glyphs=r.get("glyphs", np.zeros((0, 2))),
            grid=g["grid"], fit=r.get("fit"), reads=r.get("reads", []), model=self._model,
            glyph_h=r.get("glyph_h", 30.0), n_dashes_dropped=g["n_dashes_dropped"],
            stage="solved" if self._model else ("read" if self._read else "grid"))
        self.state.set_detection(det)

    # ---------------------------------------------------------------- step 1
    def run_detect(self):
        u8 = self._base_u8()
        if u8 is None:
            self.log("Stage 2: open an image first."); return
        self.log("Stage 2: detecting dots + box grid…"); QtWidgets.QApplication.processEvents()
        try:
            self._geo = D.detect_grid(u8, dot_area=(self.dot_min.value(), self.dot_max.value()),
                                      tophat=self.tophat.value())
        except ValueError as e:
            self.summary.setText(str(e)); self.log(f"Stage 2: {e}"); return
        self._u8 = u8; self._read = None; self._model = None
        h, w = u8.shape; self.canvas.set_extent(w, h)
        self.canvas.set_image(u8, levels=(0, 255))
        self._redraw()
        g = self._geo
        self.summary.setText(
            f"dots: <b>{len(g['dots'])}</b> · pitch <b>{g['basis']['pitch']:.1f}</b>px · "
            f"angle <b>{g['basis']['angle_deg']:.1f}°</b><br>"
            f"box pitch: <b>{g['grid']['box_pitch']:.0f}</b>px<br>"
            f"dashes on grid: <b>{len(g['dashes_on_grid'])}</b> "
            f"({g['n_dashes_dropped']} off-line dropped)<br>"
            "<i>Now Read glyphs, then Solve.</i>")
        self.log(f"Stage 2: {len(g['dots'])} dots, box {g['grid']['box_pitch']:.0f}px, "
                 f"{len(g['dashes_on_grid'])} dashes on grid")
        self._store_detection()

    # ---------------------------------------------------------------- step 2
    def run_read(self):
        if self._geo is None:
            self.run_detect()
        if self._geo is None:
            return
        clf = self._classifier()
        if clf is None:
            return
        self.log("Stage 2: reading glyphs at slot positions…"); QtWidgets.QApplication.processEvents()
        self._read = D.read(self._u8, clf, self._geo["grid"])
        self._model = None
        self._redraw()
        r = self._read
        nfit = "yes" if r["fit"] is not None else "NONE (too few confident glyphs)"
        nl = sum(x["kind"] == "letter" for x in r["reads"])
        self.summary.setText(
            f"glyph blobs: <b>{len(r['glyphs'])}</b> · fiducial fit: <b>{nfit}</b><br>"
            f"slot reads: <b>{len(r['reads'])}</b> ({nl} letters, {len(r['reads']) - nl} digits)<br>"
            "green = letter · cyan = digit.<br>"
            "<i>Recognition on real frames is beta — judge by eye; then Solve (manual anchor "
            "if it can't register).</i>")
        self.log(f"Stage 2: read {len(r['reads'])} slot glyphs ({nl} letters); fit={nfit}")
        self._store_detection()

    # ---------------------------------------------------------------- step 3
    def run_solve(self):
        if self._read is None:
            self.run_read()
        if self._read is None or self._read["fit"] is None:
            self.summary.setText("No fiducial fit — Read glyphs first (or add a manual anchor)."); return
        self.log("Stage 2: solving grid…"); QtWidgets.QApplication.processEvents()
        self._model = D.solve(self._read["reads"], self._read["fit"], self._geo["dots"],
                              manual=self.state.glyph_manual, thresh_frac=self.s_club.value())
        self._redraw()
        m = self._model
        if not m["registered"]:
            self.summary.setText(
                "<b>Could not auto-register.</b><br>" + m.get("reason", "") +
                "<br>Click <b>Set box number</b>, click a box you can read, type its number — "
                "one or two anchors locks the grid (numbers increase by the grid rule).")
            self.log("Stage 2: not registered — identify a box.")
        else:
            self.summary.setText(
                m["summary"].replace(" · ", "<br>") + "<br>"
                "<span style='color:#3ce65a'>confirmed</span> · "
                "<span style='color:#ffbe00'>corrected</span> · "
                "<span style='color:#50a0ff'>predicted</span> · "
                "<span style='color:#ff3c3c'>conflict</span>")
            self.log("Stage 2: " + m["summary"])
        self._store_detection()

    # ---------------------------------------------------------------- deskew
    def run_deskew(self):
        raw = self.state.pipeline.raw_image
        if raw is None:
            self.log("Stage 2: open an image first."); return
        clf = self._classifier()
        if clf is None:
            return
        self.log("Stage 2: estimating deskew…"); QtWidgets.QApplication.processEvents()
        # Estimate on the UN-rotated optics base (rotate_deg=0), so the result is an
        # ABSOLUTE deskew angle — not compounded with whatever Stage-1 rotation is set.
        base = C.apply(raw, replace(self.state.correction, rotate_deg=0.0))
        deg = round(float(D.estimate_deskew(io.to_uint8(base), clf)), 1)
        # what was already done, so we can re-run it on the deskewed frame
        had_grid, had_read, had_model = self._geo is not None, self._read is not None, self._model is not None
        self.state.correction.rotate_deg = deg
        self.deskewApplied.emit(deg)          # syncs Stage 1 + SYNCHRONOUSLY re-renders corrected_image
        self.log(f"Stage 2: auto-deskew ≈ {deg:.1f}° set as Stage-1 rotation (absolute).")
        # reflect the deskew in Stage 2 immediately (re-detect on the upright frame)
        self.refresh_base_image()
        if had_grid:
            self.run_detect()
            if had_read:
                self.run_read()
            if had_model:
                self.run_solve()
        else:
            self.summary.setText(f"Auto-deskew ≈ <b>{deg:.1f}°</b> applied. Now click "
                                 "<b>Detect grid</b> on the upright frame.")

    # ---------------------------------------------------------------- geometry
    def _geometry(self, slots=True):
        grid = self._geo["grid"]; H, W = self._u8.shape
        # once glyphs are read, the fit lattice tracks the real box boundaries (dashes)
        # far better than the coarse dash-phase grid — draw from it when available.
        fit = self._read["fit"] if self._read else None
        corner = (lambda i, j: lt.fit_box_corner(fit, i, j)) if fit is not None \
            else (lambda i, j: lt.box_corner(grid, i, j))
        slot = (lambda i, j, lu: lt.fslot_point(fit, i, j, lu)) if fit is not None \
            else (lambda i, j, lu: lt.slot_point(grid, i, j, lu))

        def inb(p):
            return -60 <= p[0] <= W + 60 and -60 <= p[1] <= H + 60
        quads, num_pts, letter_pts = [], [], []
        for i in range(-2, 10):
            for j in range(-2, 10):
                corners = [corner(i, j), corner(i + 1, j), corner(i + 1, j + 1), corner(i, j + 1)]
                if any(inb(c) for c in corners):
                    quads.append(corners)
                if slots:
                    for s in lt.NUMBER_SLOTS:
                        p = slot(i, j, lt.FIDUCIALS[s])
                        if inb(p):
                            num_pts.append(p)
                    for s in lt.LETTER_SLOTS:
                        p = slot(i, j, lt.FIDUCIALS[s])
                        if inb(p):
                            letter_pts.append(p)
        return quads, num_pts, letter_pts

    def _box_numbers(self):
        """(x,y,'N') at each in-view box centre from the solved model."""
        if not (self._model and self._model.get("registered") and self._read
                and self._read["fit"] is not None):
            return None
        fit = self._read["fit"]; H, W = self._u8.shape
        out = []
        for node, N in self._model.get("node_num", {}).items():
            if N is None:
                continue
            c = fit["O"] + (node[0] + 0.5) * fit["U"] + (node[1] + 0.5) * fit["V"]
            if -60 <= c[0] <= W + 60 and -60 <= c[1] <= H + 60:
                out.append((float(c[0]), float(c[1]), str(N)))
        return out

    def _redraw(self, *_):
        if self._geo is None:
            return
        show_slots = self.chk_slots.isChecked()
        quads, num_pts, letter_pts = self._geometry(slots=show_slots)
        dots = self._geo["dots"] if self.chk_dots.isChecked() else None
        dash_pts = self._geo["dashes_on_grid"] if self.chk_dashes.isChecked() else None
        labels_by_state = None
        if self._model is not None:
            by_state = defaultdict(list)
            for L in self._model["labels"]:
                by_state[L["state"]].append((L["x"], L["y"], L["text"]))
            labels_by_state = [(_STATE_COLOR.get(st, (200, 200, 200)), items)
                               for st, items in by_state.items()]
        elif self._read is not None:
            # read (not solved): green letters, cyan digits; gate weak by checkbox
            recs = [r for r in self._read["reads"]
                    if self.chk_weak.isChecked() or r["conf"] >= 0.35]
            lets = [(r["x"], r["y"], r["char"]) for r in recs if r["kind"] == "letter"]
            digs = [(r["x"], r["y"], r["char"]) for r in recs if r["kind"] == "digit"]
            labels_by_state = [((60, 230, 90), lets), ((0, 200, 255), digs)]
        box_numbers = self._box_numbers() if self.chk_nums.isChecked() else None
        self.canvas.draw_glyph_grid(
            dots=dots, box_quads=quads,
            num_pts=(num_pts if show_slots else None),
            letter_pts=(letter_pts if show_slots else None),
            dash_pts=dash_pts, labels_by_state=labels_by_state,
            box_numbers=box_numbers, show_dots=self.chk_dots.isChecked())

    # ------------------------------------------------------ manual anchors
    def _set_pick(self, mode):
        self._pick_mode = mode
        self.canvas.set_pick(mode is not None)
        self.b_pick_num.blockSignals(True); self.b_pick_let.blockSignals(True)
        self.b_pick_num.setChecked(mode == "number")
        self.b_pick_let.setChecked(mode == "letter")
        self.b_pick_num.blockSignals(False); self.b_pick_let.blockSignals(False)
        if mode:
            self.log(f"Stage 2: click a {'box to number' if mode == 'number' else 'letter'}…")

    def _on_pick(self, x, y):
        if self._pick_mode is None or self._read is None or self._read["fit"] is None:
            return
        fit = self._read["fit"]
        Minv = np.linalg.inv(np.column_stack([fit["U"], fit["V"]]))
        bc = (np.array([x, y]) - fit["O"]) @ Minv.T
        node = (int(np.floor(bc[0])), int(np.floor(bc[1])))
        ok = False
        if self._pick_mode == "number":
            N, ok = QtWidgets.QInputDialog.getInt(
                self, "Box number", f"Number for the clicked box {node} (1–25):", 1, 1, 25)
            if ok:
                self.state.glyph_manual["numbers"].append((node, int(N)))
        else:
            L, ok = QtWidgets.QInputDialog.getItem(
                self, "Letter", f"Which letter did you click (box {node})?", list("ABCD"), 0, False)
            if ok:
                self.state.glyph_manual["letters"].append(
                    {"box": node, "x": float(x), "y": float(y), "char": L})
        self._set_pick(None)
        self._update_anchor_label()
        if ok:
            self.run_solve()

    def _clear_anchors(self):
        self.state.glyph_manual["numbers"].clear()
        self.state.glyph_manual["letters"].clear()
        self._update_anchor_label()
        self.log("Stage 2: cleared manual anchors.")

    def _update_anchor_label(self):
        m = self.state.glyph_manual
        nums = ", ".join(f"{n}={N}" for n, N in m["numbers"])
        lets = ", ".join(f"{l['char']}@{l['box']}" for l in m["letters"])
        parts = [p for p in (nums, lets) if p]
        self.lbl_anchor.setText("manual: " + " · ".join(parts) if parts else "no manual anchors")
