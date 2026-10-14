"""
rwtag.project
=============
Headless multi-image project model. Ported from Reference_Warp_Tagger/rwtag/project.py.

An ImageEntry owns one image's whole PipelineState (Stage 1-4 params + results +
the acquisition-metadata record) plus its role and expected-expansion label. The
Project keeps the ordered list, designates the Initial image (lowest label
automatically, user-overridable), records the print design, and persists to
`project.rwproj.json` next to the images.

Changes from V1: the Stage-2 manual box anchors (`glyph_manual`) are gone -- the
ArUco ids register every frame; each entry carries an ImageMeta, kept in its own
`<image>.rwmeta.json` sidecar AND embedded in the project file; the batch runner
returns in port Phase 4 on the ArUco path.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import json
import os

from . import io, correct as C, meta as M
from .types import PipelineState

PROJECT_VERSION = 2
PROJECT_NAME = "project.rwproj.json"


@dataclass
class ImageEntry:
    path: str
    label: float                          # expected expansion factor (e.g. 1.5)
    role: str = "expanded"                # "initial" | "expanded"
    pipeline: PipelineState = field(default_factory=PipelineState)

    @property
    def name(self):
        return os.path.basename(self.path)

    @property
    def meta(self) -> M.ImageMeta:
        return self.pipeline.meta

    def stage_status(self):
        """(s1, s2, s3, s4) booleans — how far this image has been processed."""
        p = self.pipeline
        s2 = p.detection is not None and getattr(p.detection, "model", None) is not None \
            and p.detection.model.get("registered", False)
        return (p.raw_image is not None or os.path.exists(io.sidecar_path(self.path)),
                s2, p.features is not None, p.tagging is not None)

    # ------------------------------------------------------------ metadata
    def ensure_meta(self, embedded: dict | None = None):
        """Metadata priority: the image's own sidecar (most recently edited) >
        the copy embedded in the project file > a fresh auto-fill from the TIFF
        header and filename (written to a new sidecar)."""
        side = M.load_meta(self.path)
        if side is not None:
            self.pipeline.meta = side
        elif embedded:
            self.pipeline.meta = M.ImageMeta.from_dict(embedded)
            self.save_meta()
        else:
            self.autofill_meta()
            self.save_meta()
        if self.meta.expansion_expected is None:
            self.meta.set("expansion_expected", self.label, "filename")
        return self.meta

    def autofill_meta(self):
        """(Re-)read the header + filename into the record; user edits are kept."""
        vals = io.auto_meta(self.path) if os.path.exists(self.path) else {}
        for k, (v, src) in vals.items():
            self.meta.apply_auto({k: v}, src)
        return len(vals)

    def save_meta(self):
        if os.path.isdir(os.path.dirname(self.path) or "."):
            try:
                M.save_meta(self.path, self.meta)
            except OSError:
                pass

    # ------------------------------------------------------------ image memory
    def ensure_loaded(self):
        """Load the raw image + apply Stage-1 params (sidecar-restored on first
        load) so corrected_image is available. Lazy: unselected images stay light."""
        p = self.pipeline
        if p.raw_image is None:
            p.source_path = self.path
            p.raw_image = io.load_tiff(self.path)
            side = io.sidecar_path(self.path)
            if os.path.exists(side) and not getattr(self, "_sidecar_loaded", False):
                _, corr, lv, _flags = io.load_session(side)
                for f in corr.__dataclass_fields__:
                    setattr(p.correction, f, getattr(corr, f))
                for f in lv.__dataclass_fields__:
                    setattr(p.levels, f, getattr(lv, f))
                self._sidecar_loaded = True
        if p.corrected_image is None:
            p.corrected_image = C.process(p.raw_image, p.correction, p.levels)

    def unload_images(self):
        """Drop the heavy raw/corrected arrays (results stay); reload on demand."""
        self.pipeline.raw_image = None
        self.pipeline.corrected_image = None

    def save_sidecar(self, shared_flags=None):
        io.save_session(io.sidecar_path(self.path), self.path,
                        self.pipeline.correction, self.pipeline.levels, shared_flags or {})


@dataclass
class Project:
    folder: str = ""
    images: list = field(default_factory=list)     # list[ImageEntry]
    manual_initial: bool = False                   # user explicitly chose the Initial
    design_folder: str = ""                        # the print's design folder (Phase 3)

    # ------------------------------------------------------------ roles
    def initial(self):
        if self.manual_initial:
            marked = [e for e in self.images if e.role == "initial"]
            if marked:
                return marked[0]
        return min(self.images, key=lambda e: e.label) if self.images else None

    def expanded(self):
        init = self.initial()
        return [e for e in sorted(self.images, key=lambda e: e.label) if e is not init]

    def set_initial(self, entry):
        self.manual_initial = True
        for e in self.images:
            e.role = "expanded"
        entry.role = "initial"

    def refresh_roles(self):
        init = self.initial()
        for e in self.images:
            e.role = "initial" if e is init else "expanded"

    def add(self, path, label, embedded_meta=None):
        e = ImageEntry(path=os.path.abspath(path), label=float(label))
        e.ensure_meta(embedded_meta)
        self.images.append(e)
        self.refresh_roles()
        return e

    def remove(self, entry):
        if entry.role == "initial":
            self.manual_initial = False
        self.images.remove(entry)
        self.refresh_roles()

    def apply_meta_groups_to_all(self, source: ImageEntry, groups=M.SHARED_GROUPS):
        """Copy the instrument groups of one image's metadata to every image."""
        n = 0
        for e in self.images:
            if e is not source:
                e.meta.copy_groups_from(source.meta, groups)
                e.save_meta(); n += 1
        return n

    # ------------------------------------------------------------ persistence
    def save(self, path=None):
        path = path or os.path.join(self.folder, PROJECT_NAME)
        base = os.path.dirname(os.path.abspath(path))
        d = {"version": PROJECT_VERSION, "manual_initial": self.manual_initial,
             "design_folder": (os.path.relpath(self.design_folder, base) if self.design_folder else ""),
             "images": [{"path": os.path.relpath(e.path, base), "label": e.label, "role": e.role,
                         "meta": e.meta.to_dict()} for e in self.images]}
        with open(path, "w") as f:
            json.dump(d, f, indent=1)
        for e in self.images:
            e.save_meta()
        return path

    @classmethod
    def load(cls, path):
        with open(path) as f:
            d = json.load(f)
        base = os.path.dirname(os.path.abspath(path))
        df = d.get("design_folder", "")
        proj = cls(folder=base, manual_initial=bool(d.get("manual_initial", False)),
                   design_folder=(os.path.normpath(os.path.join(base, df)) if df else ""))
        for im in d.get("images", []):
            p = im["path"]
            full = p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p))
            e = ImageEntry(path=full, label=float(im["label"]), role=im.get("role", "expanded"))
            e.ensure_meta(im.get("meta"))
            proj.images.append(e)
        proj.refresh_roles()
        return proj
