"""
gui.meta_panel
==============
The metadata dock: a form over the selected image's `rwtag.meta.ImageMeta`,
generated from `rwtag.meta.FIELDS`. Each row shows where its value came from
("file", "name", "you", "pipeline"). Editing a header value turns its source to
"you". Derived fields are read-only. "Cells present" enables the "Which cells"
box. Every edit is written straight to the image's `.rwmeta.json` sidecar.
"""
from __future__ import annotations
from PySide6 import QtWidgets, QtCore, QtGui

from rwtag import meta as M

_BADGE = {"header": ("file", "#5aa0ff"), "filename": ("name", "#b08cff"),
          "user": ("you", "#3ce65a"), "pipeline": ("pipeline", "#ffbe00"), "": ("", "#777")}


class MetaPanel(QtWidgets.QWidget):
    metaEdited = QtCore.Signal(str)            # field name
    applyToAll = QtCore.Signal()               # copy the instrument groups to every image

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entry = None
        self._loading = False
        self._editors = {}                     # name -> widget
        self._badges = {}                      # name -> QLabel

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        self.title = QtWidgets.QLabel("<b>Image metadata</b> — no image selected")
        self.title.setWordWrap(True)
        outer.addWidget(self.title)
        self.gain_warn = QtWidgets.QLabel(
            "<small><span style='color:#ffbe00'>Camera gain not set:</span> dot position "
            "errors will be exported as <i>relative</i> (correct between dots, unknown "
            "absolute scale) until it is entered or calibrated.</small>")
        self.gain_warn.setWordWrap(True)
        outer.addWidget(self.gain_warn)

        scroll = QtWidgets.QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        body = QtWidgets.QWidget(); lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        for g in M.GROUPS:
            box = QtWidgets.QGroupBox(g.replace("&", "&&"))     # '&' is a Qt mnemonic marker
            form = QtWidgets.QFormLayout(box)
            form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
            for grp, name, kind, label, unit, ro, choices in M.FIELDS:
                if grp != g:
                    continue
                ed = self._make_editor(name, kind, unit, ro, choices)
                badge = QtWidgets.QLabel(""); badge.setMinimumWidth(48)
                row = QtWidgets.QHBoxLayout(); row.setContentsMargins(0, 0, 0, 0)
                row.addWidget(ed, 1); row.addWidget(badge)
                w = QtWidgets.QWidget(); w.setLayout(row)
                form.addRow(label + (f" ({unit})" if unit and kind not in ("date", "time") else ""), w)
                self._editors[name] = ed; self._badges[name] = badge
            lay.addWidget(box)
        lay.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        row = QtWidgets.QHBoxLayout()
        self.b_reread = QtWidgets.QPushButton("Re-read file header")
        self.b_all = QtWidgets.QPushButton("Apply optics && camera to all")
        self.b_all.setToolTip("Copy the Optics and Illumination & camera groups of this image "
                              "to every image in the project (sample and state stay per image).")
        row.addWidget(self.b_reread); row.addWidget(self.b_all)
        _w = QtWidgets.QWidget(); _w.setLayout(row); outer.addWidget(_w)
        self.b_all.clicked.connect(self.applyToAll)
        self.b_reread.clicked.connect(self._reread)
        self._editors["cells_present"].toggled.connect(
            lambda on: self._editors["cells_description"].setEnabled(on))
        self.setEnabled(False)

    # ---------------------------------------------------------------- editors
    def _make_editor(self, name, kind, unit, ro, choices):
        if kind == "bool":
            ed = QtWidgets.QCheckBox()
            ed.toggled.connect(lambda on, n=name: self._commit(n, on))
        elif kind == "choice":
            ed = QtWidgets.QComboBox(); ed.setEditable(True)
            ed.addItem(""); ed.addItems(choices or [])
            ed.currentTextChanged.connect(lambda t, n=name: self._commit(n, t))
        else:
            ed = QtWidgets.QLineEdit()
            if kind == "float":
                v = QtGui.QDoubleValidator(); v.setNotation(QtGui.QDoubleValidator.StandardNotation)
                ed.setValidator(v)
            elif kind == "int":
                ed.setValidator(QtGui.QIntValidator())
            elif kind in ("date", "time"):
                ed.setPlaceholderText(unit)
            if name == "notes":
                ed.setPlaceholderText("free text")
            ed.editingFinished.connect(lambda n=name, e=ed: self._commit(n, e.text()))
        ed.setMinimumWidth(60)
        ed.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        if ro:
            ed.setEnabled(False)
            ed.setToolTip("Derived by the pipeline (Detect stage); read-only.")
        return ed

    # ---------------------------------------------------------------- binding
    def set_entry(self, entry):
        self._entry = entry
        self.setEnabled(entry is not None)
        self.refresh()

    def refresh(self):
        e = self._entry
        self._loading = True
        try:
            if e is None:
                self.title.setText("<b>Image metadata</b> — no image selected")
                return
            self.title.setText(f"<b>Image metadata</b> — {e.name}")
            m = e.meta
            for name, ed in self._editors.items():
                v = getattr(m, name)
                if isinstance(ed, QtWidgets.QCheckBox):
                    ed.setChecked(bool(v))
                elif isinstance(ed, QtWidgets.QComboBox):
                    ed.setCurrentText("" if v is None else str(v))
                else:
                    ed.setText("" if v is None else (f"{v:g}" if isinstance(v, float) else str(v)))
                self._set_badge(name)
            self._editors["cells_description"].setEnabled(bool(m.cells_present))
            self.gain_warn.setVisible(not m.gain_known)
        finally:
            self._loading = False

    def _set_badge(self, name):
        src = self._entry.meta.source(name) if self._entry else ""
        text, col = _BADGE.get(src, (src, "#777"))
        b = self._badges[name]
        b.setText(f"<small><span style='color:{col}'>{text}</span></small>")
        b.setToolTip({"header": "read from the TIFF header", "filename": "parsed from the file name",
                      "user": "entered by you", "pipeline": "derived by the analysis"}.get(src, "not set"))

    def _commit(self, name, value):
        if self._loading or self._entry is None:
            return
        m = self._entry.meta
        new = M.coerce(name, value)
        if new == getattr(m, name):
            return
        m.set(name, new, "user")
        self._entry.save_meta()
        self._set_badge(name)
        if name == "gain_e_per_adu":
            self.gain_warn.setVisible(not m.gain_known)
        self.metaEdited.emit(name)

    def _reread(self):
        if self._entry is None:
            return
        n = self._entry.autofill_meta()
        self._entry.save_meta()
        self.refresh()
        self.metaEdited.emit("")
        self.title.setText(self.title.text() + f"  <small>({n} value(s) from file/name; your edits kept)</small>")
