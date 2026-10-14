"""
gui.tag_panel
=============
Stage-4 tab (4 · Tag). Ported from Reference_Warp_Tagger/gui/tag_panel.py: warp
the design onto the frame and give every filtered feature its design tag; hover
any marker to read its tag; filter by kind and box; overlay the TPS-warped
reference grid. Changes: kinds are aruco / dash / dot (no glyphs); a second,
dashed grid shows the uniform-expansion (similarity) model so the non-uniform
part is visible; the series group lists the PROJECT's images with their
acceptance and reason (the folder-scan driver and the strain table / trend plot
are gone -- analysis happens downstream).
"""
from __future__ import annotations
import os
import numpy as np
from PySide6 import QtWidgets, QtCore

from rwtag.refwarp import tagframe as TF, io_csv
from rwtag import series as SR

KIND_COLOR = {"dot": (255, 190, 0), "dash": (255, 60, 180), "aruco": (60, 230, 90)}
KIND_SIZE = {"dot": 4, "dash": 8, "aruco": 14}
KIND_ALPHA = {"dot": 170, "dash": 220, "aruco": 240}


class TagPanel(QtWidgets.QWidget):
    runAllRequested = QtCore.Signal()

    def __init__(self, state, canvas, log, design_fn, project_fn, parent=None):
        super().__init__(parent)
        self.state, self.canvas, self.log = state, canvas, log
        self.design_fn, self.project_fn = design_fn, project_fn

        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel("<b>Stage 4 — Tag</b>"))
        intro = QtWidgets.QLabel("<small>Warps the design onto the frame (tag affine → ICP homography → "
                                 "thin-plate spline) and gives every filtered dot and dash its design tag; "
                                 "tags are matched by id. Hover a marker to read its tag.</small>")
        intro.setWordWrap(True); root.addWidget(intro)
        self.b_tag = QtWidgets.QPushButton("Tag current frame")
        root.addWidget(self.b_tag)
        self.summary = QtWidgets.QLabel("Run Stages 2–3, then Tag."); self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        vo = QtWidgets.QGroupBox("View"); vl = QtWidgets.QVBoxLayout(vo)
        row = QtWidgets.QHBoxLayout()
        self.kindcombo = QtWidgets.QComboBox(); self.kindcombo.addItems(["all", "aruco", "dash", "dot"])
        self.boxcombo = QtWidgets.QComboBox(); self.boxcombo.addItem("all")
        row.addWidget(QtWidgets.QLabel("kind:")); row.addWidget(self.kindcombo, 1)
        row.addWidget(QtWidgets.QLabel("box:")); row.addWidget(self.boxcombo, 1)
        _rw = QtWidgets.QWidget(); _rw.setLayout(row); vl.addWidget(_rw)
        self.chk_grid = QtWidgets.QCheckBox("Warped grid (TPS, solid cyan)"); self.chk_grid.setChecked(True)
        self.chk_exp = QtWidgets.QCheckBox("Uniform-expansion grid (similarity, magenta)"); self.chk_exp.setChecked(False)
        self.chk_nums = QtWidgets.QCheckBox("Box numbers"); self.chk_nums.setChecked(True)
        self.chk_resid = QtWidgets.QCheckBox("Colour by residual (green 0 → red ≥ ½ pitch)")
        self.chk_sigma = QtWidgets.QCheckBox("Colour by position σ (green small → red large, frame range)")
        for w in (self.chk_grid, self.chk_exp, self.chk_nums, self.chk_resid, self.chk_sigma):
            vl.addWidget(w)
        self.readout = QtWidgets.QLabel("hover a point to read its tag")
        self.readout.setStyleSheet("color:#8cf; font-weight:bold;"); self.readout.setWordWrap(True)
        vl.addWidget(self.readout)
        root.addWidget(vo)
        self.b_export = QtWidgets.QPushButton("Export tagged CSV (this frame)…"); self.b_export.setEnabled(False)
        root.addWidget(self.b_export)

        sg = QtWidgets.QGroupBox("Project series"); sl = QtWidgets.QVBoxLayout(sg)
        self.serieslist = QtWidgets.QListWidget(); self.serieslist.setMinimumHeight(140)
        self.b_series = QtWidgets.QPushButton("Run stages 2–4 on all pending images")
        sl.addWidget(self.serieslist); sl.addWidget(self.b_series)
        root.addWidget(sg)
        root.addStretch(1)

        self.b_tag.clicked.connect(self.tag_current)
        self.b_export.clicked.connect(self.export_tagged)
        self.b_series.clicked.connect(self.runAllRequested)
        self.kindcombo.currentIndexChanged.connect(self._redraw)
        self.boxcombo.currentIndexChanged.connect(self._redraw)
        for c in (self.chk_grid, self.chk_exp, self.chk_nums, self.chk_resid, self.chk_sigma):
            c.toggled.connect(self._redraw)
        self.chk_resid.toggled.connect(lambda on: on and self.chk_sigma.setChecked(False))
        self.chk_sigma.toggled.connect(lambda on: on and self.chk_resid.setChecked(False))
        self.canvas.tagHovered.connect(lambda t: self.readout.setText(t or "hover a point to read its tag"))
        self.state.imageLoaded.connect(self._invalidate)
        self.state.detectionChanged.connect(self._invalidate)
        self.state.featuresChanged.connect(self._invalidate)

    # ---------------------------------------------------------------- state
    def _invalidate(self, *_):
        if self.state.pipeline.tagging is not None and self.sender() is not None:
            self.state.pipeline.tagging = None
        self.b_export.setEnabled(False)
        self.summary.setText("Run Stages 2–3, then Tag.")
        self.canvas.clear_hover_points()
        self.fill_series()

    def load_from_state(self):
        tr = self.state.pipeline.tagging
        self.b_export.setEnabled(tr is not None)
        self.fill_series()
        if tr is None:
            self.summary.setText("Run Stages 2–3, then Tag."); return
        self._fill(tr)

    def refresh_base_image(self):
        det = self.state.pipeline.detection
        if det is None:
            return
        h, w = det.u8.shape
        self.canvas.set_extent(w, h)
        self.canvas.set_image(det.u8, levels=(0, 255))
        self.fill_series()
        if self.state.pipeline.tagging is not None:
            self._redraw()
        else:
            self.canvas.clear_overlays(); self.canvas.clear_hover_points()

    def fill_series(self):
        self.serieslist.clear()
        proj = self.project_fn()
        if proj is None:
            return
        for e in sorted(proj.images, key=lambda e: e.label):
            tr = e.pipeline.tagging
            if tr is None:
                s = "pending"
            elif tr.accepted:
                s = (f"OK · {tr.source} · {len(tr.tags)} tags · residual "
                     f"{tr.per_category.get('dot', {}).get('res_median', float('nan')):.2f} px")
            else:
                s = f"REJECTED · {tr.reason}"
            item = QtWidgets.QListWidgetItem(f"{e.label:g}×  {s}")
            if tr is not None and not tr.accepted:
                item.setForeground(QtCore.Qt.red)
            self.serieslist.addItem(item)

    # ---------------------------------------------------------------- tagging
    def tag_current(self, accepted=None):
        det, filt = self.state.pipeline.detection, self.state.pipeline.features
        design = self.design_fn()
        if det is None or not (det.model and det.model.get("registered")):
            self.summary.setText("Need a registered Stage-2 detection — run Detect first.")
            self.log("Stage 4: no registered detection."); return None
        if filt is None:
            self.log("Stage 4: no Stage-3 filter — tagging every non-edge detection.")
        self.log("Stage 4: fitting warp + tagging…"); QtWidgets.QApplication.processEvents()
        tr = TF.tag_frame(det, filt, design)
        if tr is None:
            self.summary.setText("Warp fit failed — too few dots?"); return None
        e = self._entry()
        if e is not None:
            tr.label = e.label
            proj = self.project_fn()
            acc = [x.pipeline.tagging for x in proj.images if x is not e and x.pipeline.tagging is not None]
            ok, reason, _s = SR.validate(tr, det, e.label, acc)
            tr.accepted, tr.reason = ok, ("" if ok else reason)
            tr.source = "baseline" if ok and not [a for a in acc if a.accepted] else "direct"
            tr.confidence = reason + " · " + tr.confidence
        self.state.set_tagging(tr)
        self._fill(tr)
        self.fill_series()
        self.log(f"Stage 4: {len(tr.tags)} tags · {tr.confidence}" + ("" if tr.accepted else f" · REJECTED: {tr.reason}"))
        return tr

    def _entry(self):
        proj = self.project_fn()
        src = self.state.pipeline.source_path
        if proj is None or not src:
            return None
        return next((e for e in proj.images if e.path == os.path.abspath(src)), None)

    def _fill(self, tr):
        self.b_export.setEnabled(True)
        boxes = sorted({int(t.split("|")[1][1:]) for t in tr.tags if t.startswith("dot|")})
        self.boxcombo.blockSignals(True); self.boxcombo.clear()
        self.boxcombo.addItem("all"); self.boxcombo.addItems([str(b) for b in boxes])
        self.boxcombo.blockSignals(False)
        pc = tr.per_category
        sim = tr.similarity or {}
        um = 1.0
        det = self.state.pipeline.detection
        if det is not None and det.params:
            um = float(det.params.get("um_per_px", 1.0))
        status = ("<span style='color:#3ce65a'>accepted</span> (" + tr.source + ")" if tr.accepted
                  else f"<span style='color:#ff3c3c'>REJECTED</span> — {tr.reason}")
        self.summary.setText(
            f"{status}<br><b>{len(tr.tags)}</b> tags — dots {pc['dot']['n']} · dashes {pc['dash']['n']} · "
            f"ArUco {pc['aruco']['n']}<br>warp <b>{tr.warp['kind']}</b> · cross-validated residual "
            f"<b>{pc['dot']['res_median']:.2f} px</b> · matched {tr.warp['matched_frac']:.0%}<br>"
            + (f"uniform-expansion fit: λ {sim.get('s', float('nan')) * um:.4f} · rot {sim.get('angle_deg', float('nan')):+.2f}° "
               f"(corrected frame) · rms {sim.get('rms', float('nan')):.2f} px<br>" if sim else "")
            + f"<small>untagged: {len(tr.unmatched.get('dot', []))} dots, {len(tr.unmatched.get('dash', []))} dashes; "
            f"box disagreements {len(tr.unmatched.get('box_mismatch', []))}</small>")
        self._redraw()

    def _redraw(self, *_):
        tr, det = self.state.pipeline.tagging, self.state.pipeline.detection
        design = self.design_fn()
        if tr is None or det is None or design is None:
            return
        self.canvas.set_image(det.u8, levels=(0, 255))
        self.canvas.clear_overlays()
        kind_f, box_f = self.kindcombo.currentText(), self.boxcombo.currentText()
        by_resid = self.chk_resid.isChecked() and tr.residuals
        by_sigma = self.chk_sigma.isChecked() and tr.cov
        rmax = 0.5 * float(det.basis["pitch"])
        sig = {t: float(np.sqrt(max(c[0], c[1]))) for t, c in (tr.cov or {}).items()}
        if by_sigma and sig:
            s_lo, s_hi = np.percentile(list(sig.values()), [5, 95]); s_hi = max(s_hi, s_lo + 1e-6)
        rot_s = {i: v["rot_sigma_deg"] for i, v in (det.tag_cov or {}).items() if v}
        entries = []
        for tag, (x, y) in tr.tags.items():
            k = tag.split("|")[0]
            if kind_f != "all" and k != kind_f:
                continue
            if box_f != "all" and f"|B{box_f}|" not in tag:
                continue
            r = tr.residuals.get(tag, 0.0) if tr.residuals else 0.0
            if by_resid:
                t = min(r / max(rmax, 1e-6), 1.0)
                color = (int(60 + 195 * t), int(230 - 170 * t), 60, 220)
            elif by_sigma and tag in sig:
                t = float(np.clip((sig[tag] - s_lo) / (s_hi - s_lo), 0, 1))
                color = (int(60 + 195 * t), int(230 - 170 * t), 60, 220)
            else:
                color = KIND_COLOR.get(k, (200, 200, 200)) + (KIND_ALPHA.get(k, 200),)
            c = tr.cov.get(tag) if tr.cov else None
            pos = (f"x {x:.2f} ± {np.sqrt(c[0]):.3f}, y {y:.2f} ± {np.sqrt(c[1]):.3f} px" if c else f"({x:.1f}, {y:.1f}) px")
            extra = ""
            if k == "aruco":
                i = int(tag.split("|")[2])
                if i in det.tags:
                    extra = f" · rot {det.tags[i].rot_deg:+.2f} ± {rot_s.get(i, float('nan')):.2f}°"
            entries.append((f"{tag}   {pos}{extra} · residual {r:.2f} px", x, y, color, KIND_SIZE.get(k, 6)))
        self.canvas.draw_hover_points(entries)
        if self.chk_grid.isChecked():
            self.canvas.add_polylines(TF.warped_grid_segments(tr.warp, design), color=(0, 220, 255), width=1.4)
        if self.chk_exp.isChecked() and tr.similarity:
            self.canvas.add_polylines(TF.expected_grid_segments(tr.similarity, design), color=(255, 0, 255), width=1.2)
        if self.chk_nums.isChecked():
            centres = TF.warped_box_centers(tr.warp, design, tr.tags)
            if centres:
                self.canvas.add_labels(list(centres.values()), [str(N) for N in centres],
                                       color=(255, 230, 0), anchor=(0.5, 0.5), size=12)

    # ---------------------------------------------------------------- export
    def export_tagged(self):
        tr = self.state.pipeline.tagging
        if tr is None:
            return
        base = os.path.splitext(os.path.basename(self.state.pipeline.source_path or "frame"))[0].replace(".ome", "")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export tagged CSV", base + "_tagged.csv", "CSV (*.csv)")
        if path:
            io_csv.write_tagged(tr, path)
            self.log(f"Stage 4: tagged CSV → {path}")
