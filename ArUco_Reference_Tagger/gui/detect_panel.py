"""
gui.detect_panel
================
Stage-2 tab (2 · Detect). Replaces V1's three OCR buttons (Detect grid / Read
glyphs / Solve grid) and its manual box anchors with ONE step: decode the ArUco
tags on the Stage-1 corrected frame, fit the design, detect dots per box with
that box's dot size, and run the second pass on the raw frame
(rwtag.aruco.detect). The design comes from the registry or any folder and is
stored on the project. Derived expansion / rotation / handedness go into the
image's metadata.
"""
from __future__ import annotations
import os
import numpy as np
from PySide6 import QtWidgets, QtCore

from rwtag import io, designs as DS, project as PJ
from rwtag.aruco import ArucoParams
from rwtag.aruco.detect import predicted_px

_TAG_COLOR = {"clean": (60, 230, 90), "corrected": (255, 190, 0), "ambiguous": (255, 60, 60),
              "duplicate": (255, 0, 255), "edge": (255, 140, 0)}
_DOT_A, _DOT_B, _DOT_EDGE = (255, 190, 0), (0, 200, 255), (255, 60, 60)


class DetectPanel(QtWidgets.QWidget):
    deskewApplied = QtCore.Signal(float)        # new Stage-1 rotate_deg
    designChanged = QtCore.Signal(str)          # folder

    def __init__(self, state, canvas, log, project_fn, entry_fn, parent=None):
        super().__init__(parent)
        self.state, self.canvas, self.log = state, canvas, log
        self.project_fn, self.entry_fn = project_fn, entry_fn
        self.design = None
        self._loading = False

        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel("<b>Stage 2 — Detect (ArUco)</b>"))
        intro = QtWidgets.QLabel(
            "<small>Decodes the ArUco tags on the corrected frame (each id <i>is</i> its grid node, "
            "so registration, expansion and rotation are read, not inferred), detects the dots box "
            "by box with each box's printed dot size, and detects again on the raw frame.</small>")
        intro.setWordWrap(True); root.addWidget(intro)

        # ---- design
        dg = QtWidgets.QGroupBox("Print design"); dl = QtWidgets.QVBoxLayout(dg)
        self.cmb_design = QtWidgets.QComboBox()
        for lab, folder in DS.registry():
            self.cmb_design.addItem(lab, folder)
        self.cmb_design.addItem("Other design folder…", "")
        self.lbl_design = QtWidgets.QLabel("—"); self.lbl_design.setWordWrap(True)
        self.lbl_design.setStyleSheet("color:#999;")
        dl.addWidget(self.cmb_design); dl.addWidget(self.lbl_design)
        root.addWidget(dg)

        # ---- detector settings
        sg = QtWidgets.QGroupBox("Detector"); sf = QtWidgets.QFormLayout(sg)
        self.s_umpx = QtWidgets.QDoubleSpinBox(); self.s_umpx.setDecimals(4); self.s_umpx.setRange(0.01, 20.0)
        self.s_umpx.setSingleStep(0.001); self.s_umpx.setValue(0.51)
        self.s_umpx.setToolTip("Pixel size of THIS image. Edits are written to its metadata.")
        self.s_psf = QtWidgets.QDoubleSpinBox(); self.s_psf.setRange(0.3, 10.0); self.s_psf.setSingleStep(0.1)
        self.s_psf.setValue(2.5); self.s_psf.setToolTip("Microscope PSF FWHM (µm). Sizes the dot top-hat and refinement window.")
        self.cmb_refine = QtWidgets.QComboBox(); self.cmb_refine.addItems(["gauss", "fit", "none"])
        self.s_noise = QtWidgets.QDoubleSpinBox(); self.s_noise.setRange(0.0, 20.0); self.s_noise.setValue(5.0)
        self.s_noise.setToolTip("Threshold floor = median + k·σ of the top-hat image (0 = plain Otsu).")
        self.s_band = QtWidgets.QDoubleSpinBox(); self.s_band.setRange(0.0, 300.0); self.s_band.setValue(0.0)
        self.s_band.setToolTip("Extra fixed band at the frame edge (µm). The exact un-distortion edge is always applied.")
        self.chk_mask = QtWidgets.QCheckBox("Mask tag interiors"); self.chk_mask.setChecked(True)
        self.chk_raw = QtWidgets.QCheckBox("Second pass on the raw frame"); self.chk_raw.setChecked(True)
        sf.addRow("pixel size (µm/px)", self.s_umpx)
        sf.addRow("PSF FWHM (µm)", self.s_psf)
        sf.addRow("centre refinement", self.cmb_refine)
        sf.addRow("noise floor k", self.s_noise)
        sf.addRow("extra edge band (µm)", self.s_band)
        sf.addRow(self.chk_mask); sf.addRow(self.chk_raw)
        root.addWidget(sg)

        self.b_detect = QtWidgets.QPushButton("Detect")
        self.b_deskew = QtWidgets.QPushButton("Auto-deskew (write rotation to Stage 1)")
        self.b_deskew.setEnabled(False)
        root.addWidget(self.b_detect); root.addWidget(self.b_deskew)

        # ---- view
        vg = QtWidgets.QGroupBox("View"); vl = QtWidgets.QVBoxLayout(vg)
        self.chk_tags = QtWidgets.QCheckBox("Tags (id · rotation)"); self.chk_tags.setChecked(True)
        self.chk_dots = QtWidgets.QCheckBox("Dots (alternate colour per box)"); self.chk_dots.setChecked(True)
        self.chk_edge = QtWidgets.QCheckBox("Edge dots (no real raw source, red)"); self.chk_edge.setChecked(True)
        self.chk_dash = QtWidgets.QCheckBox("Dashes (pink ▲)"); self.chk_dash.setChecked(True)
        self.chk_box = QtWidgets.QCheckBox("Box outlines + numbers (from the tag fit)"); self.chk_box.setChecked(True)
        for w in (self.chk_tags, self.chk_dots, self.chk_edge, self.chk_dash, self.chk_box):
            vl.addWidget(w); w.toggled.connect(self._redraw)
        root.addWidget(vg)

        self.summary = QtWidgets.QLabel("Add an image, correct it in Stage 1, then Detect.")
        self.summary.setWordWrap(True); root.addWidget(self.summary)
        self.table = QtWidgets.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["box", "dot µm", "pitch µm", "design", "found", "pitch px", "λ"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setMinimumHeight(220)
        root.addWidget(self.table, 1)

        self.cmb_design.activated.connect(self._on_design_pick)
        self.s_umpx.editingFinished.connect(self._umpx_to_meta)
        self.b_detect.clicked.connect(self.run_detect)
        self.b_deskew.clicked.connect(self.run_deskew)
        self.state.imageLoaded.connect(self._clear)
        self.set_design_folder(DS.default_folder())

    # ---------------------------------------------------------------- design
    def set_design_folder(self, folder):
        if not folder:
            return
        try:
            self.design = DS.load(folder)
        except Exception as e:                                  # pragma: no cover
            self.log(f"Detect: could not load design {folder}: {e}"); return
        i = self.cmb_design.findData(os.path.abspath(folder))
        if i < 0:
            self.cmb_design.insertItem(self.cmb_design.count() - 1, os.path.basename(folder), os.path.abspath(folder))
            i = self.cmb_design.findData(os.path.abspath(folder))
        self.cmb_design.setCurrentIndex(i)
        sha = self.design.file_sha256.get("reference_tags.json", "")[:10]
        self.lbl_design.setText(f"<small>{self.design.summary()}<br>reference_tags.json sha256 {sha}…</small>")
        proj = self.project_fn()
        if proj is not None:
            proj.design_folder = os.path.abspath(folder)
        self.designChanged.emit(os.path.abspath(folder))

    def _on_design_pick(self, idx):
        folder = self.cmb_design.itemData(idx)
        if not folder:
            folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Design folder (holding reference_tags.json)")
            if not folder:
                if self.design is not None:
                    self.set_design_folder(self.design.folder)
                return
        self.set_design_folder(folder)
        self.log(f"Detect: design -> {self.design.summary()}")

    # ---------------------------------------------------------------- params
    def params(self) -> ArucoParams:
        return ArucoParams(um_per_px=self.s_umpx.value(), psf_fwhm_um=self.s_psf.value(),
                           refine=self.cmb_refine.currentText(), noise_k=self.s_noise.value(),
                           edge_band_um=self.s_band.value(), mask_tags=self.chk_mask.isChecked(),
                           raw_pass=self.chk_raw.isChecked())

    def _umpx_to_meta(self):
        e = self.entry_fn()
        if e is None or self._loading:
            return
        v = round(self.s_umpx.value(), 6)
        if e.meta.um_per_px is None or abs(e.meta.um_per_px - v) > 1e-9:
            e.meta.set("um_per_px", v, "user"); e.save_meta()
            self.state.metaChanged.emit()

    def sync_from_meta(self):
        e = self.entry_fn()
        if e is None:
            return
        self._loading = True
        try:
            if e.meta.um_per_px:
                self.s_umpx.setValue(float(e.meta.um_per_px))
            det = e.pipeline.detection
            if det is not None and det.params:
                self.s_psf.setValue(float(det.params.get("psf_fwhm_um", self.s_psf.value())))
        finally:
            self._loading = False

    # ---------------------------------------------------------------- state
    def _clear(self, *_):
        self.summary.setText("New image — correct it in Stage 1, then Detect.")
        self.table.setRowCount(0)
        self.b_deskew.setEnabled(False)

    def load_from_state(self):
        self.sync_from_meta()
        det = self.state.pipeline.detection
        if det is None:
            self._clear(); return
        self._fill(det)

    def refresh_base_image(self):
        det = self.state.pipeline.detection
        img = self.state.working_image()
        if det is not None:
            self._redraw()
        elif img is not None:
            u8 = io.to_uint8_robust(img)
            h, w = u8.shape
            self.canvas.set_extent(w, h); self.canvas.clear_overlays()
            self.canvas.set_image(u8, levels=(0, 255))

    # ---------------------------------------------------------------- actions
    def run_detect(self):
        e = self.entry_fn()
        if e is None or self.state.pipeline.raw_image is None:
            self.log("Detect: add and select an image first."); return None
        if self.design is None:
            self.log("Detect: choose a design first."); return None
        self._umpx_to_meta()
        self.log(f"Detect: {e.name} with {self.design.name} …"); QtWidgets.QApplication.processEvents()
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            det = PJ.run_detect(e, self.design, self.params())
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.state.set_detection(det)
        self.state.metaChanged.emit()
        self._fill(det)
        self.log("Detect: " + det.model["summary"] if det.model.get("registered")
                 else "Detect: NOT registered — " + det.model.get("reason", ""))
        return det

    def run_deskew(self):
        det = self.state.pipeline.detection
        if det is None or not det.model.get("registered") or not np.isfinite(det.rot_raw_deg):
            self.log("Auto-deskew: run Detect first."); return
        new = round(-float(det.rot_raw_deg), 2)          # Stage 1 rotates by +deg (ccw): cancels the raw rotation
        self.log(f"Auto-deskew: raw rotation {det.rot_raw_deg:+.2f}° -> Stage-1 rotation {new:+.2f}°")
        self.deskewApplied.emit(new)
        self.run_detect()

    # ---------------------------------------------------------------- display
    def _fill(self, det):
        m = det.model or {}
        reg = m.get("registered", False)
        self.b_deskew.setEnabled(bool(reg))
        if not reg:
            self.summary.setText(f"<b>Not registered.</b> {m.get('reason', '')}<br><small>Check the "
                                 "exposure (dim tags), the pixel size, and that the right design is chosen.</small>")
            self.table.setRowCount(0); self._redraw(); return
        p = det.frame_pose
        rp = det.raw_pass or {}
        n_edge = int((det.dot_flag == "edge").sum()) if det.dot_flag is not None else 0
        lam_s = f" ± {det.lam_tags_sigma:.4f}" if np.isfinite(det.lam_tags_sigma) else ""
        txt = (f"<b>λ {det.lam_tags:.4f}{lam_s}</b> from {m['affine_info']['n_matched']} tags "
               f"({m['affine_info']['method']}) · dots say {det.lam_dots:.4f}<br>"
               f"rotation <b>{det.rot_raw_deg:+.2f}°</b> raw (ccw) · handedness "
               f"{'−1 (expected)' if m['sign'] < 0 else '<span style=color:#ff3c3c>+1 MIRRORED</span>'}<br>"
               f"tags: {p.n_tags} usable · {m['decode']['n_ambiguous']} ambiguous · "
               f"{sum(t.in_edge_band for t in det.tags.values())} at the edge"
               + (f" · unknown ids {p.unknown_ids}" if p.unknown_ids else "") + "<br>"
               f"dots: {len(det.dots)} ({n_edge} edge) · dashes {len(det.dashes_on_grid)}")
        if rp:
            txt += (f"<br>raw pass: {rp['dot_match_frac']:.1%} of dots re-found · median "
                    f"|raw det − mapped| {rp['median_det_minus_map_px']:.3f} px · {len(rp['tags_det'])} tags")
        self.summary.setText(txt)
        rows = [(N, r) for N, r in sorted(det.per_box.items()) if r["detected"] or r["design"]]
        self.table.setRowCount(len(rows))
        for i, (N, r) in enumerate(rows):
            vals = [str(N), f"{r['dot_um']:g}", f"{r['pitch_um']:g}", str(r["design"]), str(r["detected"]),
                    "—" if not np.isfinite(r["pitch_px"]) else f"{r['pitch_px']:.2f}",
                    "—" if not np.isfinite(r["lam"]) else f"{r['lam']:.4f}"]
            for c, v in enumerate(vals):
                self.table.setItem(i, c, QtWidgets.QTableWidgetItem(v))
        self._redraw()

    def _redraw(self, *_):
        det = self.state.pipeline.detection
        if det is None:
            return
        h, w = det.u8.shape
        self.canvas.set_extent(w, h)
        self.canvas.set_image(det.u8, levels=(0, 255))
        self.canvas.clear_overlays()
        reg = det.model.get("registered", False)
        if self.chk_box.isChecked() and reg and self.design is not None:
            quads, centres, labels = [], [], []
            for b in self.design.boxes:
                c = predicted_px([[b.x0_um, b.y0_um], [b.x0_um + b.side_um, b.y0_um],
                                  [b.x0_um + b.side_um, b.y0_um + b.side_um], [b.x0_um, b.y0_um + b.side_um]], det)
                if ((c[:, 0] > -50) & (c[:, 0] < w + 50) & (c[:, 1] > -50) & (c[:, 1] < h + 50)).any():
                    quads.append(c); centres.append(c.mean(0)); labels.append(str(b.N))
            self.canvas.add_polylines(quads, color=(0, 200, 255), width=1)
            self.canvas.add_labels(centres, labels, color=(255, 230, 0), anchor=(0.5, 0.5), size=12)
        if self.chk_dots.isChecked() and len(det.dots):
            edge = det.dot_flag == "edge" if det.dot_flag is not None else np.zeros(len(det.dots), bool)
            if reg and self.design is not None:
                par = np.array([(self.design.box(int(N)).col + self.design.box(int(N)).row) % 2 if N else 0
                                for N in det.dot_box])
            else:
                par = np.zeros(len(det.dots), int)
            self.canvas.add_points(det.dots[(~edge) & (par == 0)], color=_DOT_A, size=3)
            self.canvas.add_points(det.dots[(~edge) & (par == 1)], color=_DOT_B, size=3)
            if self.chk_edge.isChecked():
                self.canvas.add_points(det.dots[edge], color=_DOT_EDGE, size=5)
        if self.chk_dash.isChecked() and len(det.dashes_on_grid):
            self.canvas.add_points(det.dashes_on_grid, color=(255, 60, 180), size=8, symbol="t")
        if self.chk_tags.isChecked():
            for cls in _TAG_COLOR:
                sel = [t for t in det.tags.values()
                       if (("edge" if t.in_edge_band and cls == "edge" else None) or
                           (t.decode_class == cls and not t.in_edge_band and cls != "edge"))]
                if not sel:
                    continue
                self.canvas.add_polylines([t.corners_px for t in sel], color=_TAG_COLOR[cls], width=2)
                self.canvas.add_polylines([np.array([t.corners_px[0], t.corners_px[1]]) for t in sel],
                                          color=(255, 255, 255), width=3)
                self.canvas.add_labels([t.corners_px[3] for t in sel],
                                       [f"{t.aruco_id}  {t.rot_deg:+.1f}°" for t in sel],
                                       color=_TAG_COLOR[cls], anchor=(0.0, -0.2), size=10)
