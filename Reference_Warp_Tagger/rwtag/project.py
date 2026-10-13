"""
rwtag.project
=============
Headless multi-image project model for the expansion-analysis workspace.

An ImageEntry owns one image's whole PipelineState (Stage 1-4 params + results)
plus its role and expected-expansion label. The Project keeps the ordered list,
designates the Initial image (lowest label automatically, user-overridable), and
persists to `project.rwproj.json` next to the images. Stage-1 tuning stays in the
existing per-image sidecar sessions; results are recomputable so only light state
(roles, labels, manual anchors, stage status) is persisted.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import json
import os

import numpy as np

from . import io, correct as C
from .types import PipelineState, CorrectionParams, LevelsParams

PROJECT_VERSION = 1
PROJECT_NAME = "project.rwproj.json"


@dataclass
class ImageEntry:
    path: str
    label: float                          # expected expansion factor (e.g. 1.5)
    role: str = "expanded"                # "initial" | "expanded"
    pipeline: PipelineState = field(default_factory=PipelineState)
    glyph_manual: dict = field(default_factory=lambda: {"numbers": [], "letters": []})

    @property
    def name(self):
        return os.path.basename(self.path)

    def stage_status(self):
        """(s1, s2, s3, s4) booleans — how far this image has been processed."""
        p = self.pipeline
        s2 = p.detection is not None and getattr(p.detection, "model", None) is not None \
            and p.detection.model.get("registered", False)
        return (p.raw_image is not None or os.path.exists(io.sidecar_path(self.path)),
                s2, p.features is not None, p.tagging is not None)

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

    # ------------------------------------------------------------ roles
    def initial(self):
        """The Initial image: the user's explicit choice, else the lowest label."""
        if self.manual_initial:
            marked = [e for e in self.images if e.role == "initial"]
            if marked:
                return marked[0]
        return min(self.images, key=lambda e: e.label) if self.images else None

    def expanded(self):
        init = self.initial()
        return [e for e in sorted(self.images, key=lambda e: e.label) if e is not init]

    def set_initial(self, entry):
        """User override: this image is the Initial regardless of label."""
        self.manual_initial = True
        for e in self.images:
            e.role = "expanded"
        entry.role = "initial"

    def refresh_roles(self):
        """Keep exactly one initial (auto = lowest label unless user-overridden)."""
        init = self.initial()
        for e in self.images:
            e.role = "initial" if e is init else "expanded"

    def add(self, path, label):
        e = ImageEntry(path=os.path.abspath(path), label=float(label))
        self.images.append(e)
        self.refresh_roles()
        return e

    def remove(self, entry):
        if entry.role == "initial":
            self.manual_initial = False            # fall back to auto (lowest label)
        self.images.remove(entry)
        self.refresh_roles()

    # ------------------------------------------------------------ persistence
    def save(self, path=None):
        path = path or os.path.join(self.folder, PROJECT_NAME)
        d = {"version": PROJECT_VERSION,
             "manual_initial": self.manual_initial,
             "images": [{"path": os.path.relpath(e.path, os.path.dirname(path)),
                         "label": e.label, "role": e.role,
                         "glyph_manual": {"numbers": [[list(n), N] for n, N in
                                                      e.glyph_manual["numbers"]],
                                          "letters": e.glyph_manual["letters"]}}
                        for e in self.images]}
        with open(path, "w") as f:
            json.dump(d, f, indent=1)
        return path

    @classmethod
    def load(cls, path):
        with open(path) as f:
            d = json.load(f)
        base = os.path.dirname(os.path.abspath(path))
        proj = cls(folder=base, manual_initial=bool(d.get("manual_initial", False)))
        for im in d.get("images", []):
            p = im["path"]
            full = p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p))
            e = ImageEntry(path=full, label=float(im["label"]),
                           role=im.get("role", "expanded"))
            gm = im.get("glyph_manual", {})
            e.glyph_manual = {"numbers": [(tuple(n), int(N)) for n, N in gm.get("numbers", [])],
                              "letters": list(gm.get("letters", []))}
            proj.images.append(e)
        proj.refresh_roles()
        return proj


# ---------------------------------------------------------------- batch runner
def run_stages(entry: ImageEntry, clf, dot_params=None, dash_params=None,
               auto_deskew=True, log=lambda *_: None):
    """Run Stages 2-4 headlessly for one image with ITS saved tuning + manual
    anchors, storing results into entry.pipeline. Stage 1 = the entry's params
    (auto-deskew fills rotation when untouched). Returns (ok, message)."""
    from dataclasses import replace
    from .glyph import detect as D, dotfilter as gdf, lattice as lt, reader as gr
    from .glyph.types import FilterResult
    from .refwarp import tagframe as TF

    dot_params = dot_params or gdf.DotFilterParams()
    dash_params = dash_params or gdf.DashFilterParams()
    p = entry.pipeline
    entry.ensure_loaded()
    if auto_deskew and not p.correction.rotate_deg:
        base = C.apply(p.raw_image, replace(p.correction, rotate_deg=0.0))
        p.correction.rotate_deg = round(float(gr.estimate_deskew(io.to_uint8(base), clf)), 1)
        p.corrected_image = C.process(p.raw_image, p.correction, p.levels)
        log(f"{entry.name}: auto-deskew {p.correction.rotate_deg:.1f} deg")
    u8 = io.to_uint8(p.corrected_image)
    det = D.detect(u8, clf, manual=entry.glyph_manual)
    p.detection = det
    if not (det.model and det.model.get("registered")):
        p.features = p.tagging = None
        return False, ("Stage 2 could not register — open the image and add a manual "
                       "box anchor in the Detect tab")
    drecs, dcounts = gdf.filter_dots(det.dots, det.basis, det.glyphs, det.glyph_h, dot_params)
    dash_grid = lt.grid_from_fit(det.fit) if det.fit is not None else det.grid
    hrecs, hcounts = gdf.filter_dashes(det.dashes_all, dash_grid, dash_params)
    kept_dots = np.array([[r["x"], r["y"]] for r in drecs if r["keep"]], float)
    kept_dashes = np.array([[r["x"], r["y"]] for r in hrecs if r["keep"]], float)
    p.features = FilterResult(dot_recs=drecs, dash_recs=hrecs, dot_counts=dcounts,
                              dash_counts=hcounts, kept_dots=kept_dots,
                              kept_dashes=kept_dashes,
                              dot_params=dot_params.__dict__, dash_params=dash_params.__dict__)
    tr = TF.tag_frame(det, p.features)
    if tr is None:
        p.tagging = None
        return False, "Stage 4 warp fit failed — check the registration"
    tr.label = entry.label
    p.tagging = tr
    return True, (f"{len(tr.tags)} tags · resid {tr.warp['per_det_median']:.1f}px · "
                  f"matched {tr.warp['matched_frac']:.0%}")


def run_stages_validated(entry: ImageEntry, accepted, clf, min_share=40,
                         max_resid=10.0, log=lambda *_: None):
    """run_stages + CROSS-FRAME VALIDATION against already-accepted entries.

    A frame's own registration can be confidently WRONG (periodic dot lattice ->
    a box-shifted fit with a tiny residual — the known high-expansion trap), so a
    standalone low residual proves nothing. If the direct tagging shares too few
    tags with the accepted frames, coreg auto-registration transfers box numbers
    from each accepted frame (FOV-constrained design overlap + handedness) and
    the best candidate wins; if nothing clears `min_share`, the frame is
    REJECTED LOUDLY (tagging=None) — rescue is a manual Stage-2 anchor."""
    from .refwarp import coreg, tagframe as TF
    ok, msg = run_stages(entry, clf, log=log)
    accepted = [a for a in accepted
                if a is not entry and a.pipeline.tagging is not None]
    if not accepted:                          # baseline / first frame: nothing to check against
        return ok, msg
    if not ok:
        return ok, msg
    p = entry.pipeline
    ref_tags_union = set().union(*[set(a.pipeline.tagging.tags) for a in accepted])
    ref_sign = coreg.homography_sign(accepted[0].pipeline.tagging.warp["H"])
    pitch = float(p.detection.basis["pitch"])

    def _share(tr):
        return len(set(tr.tags) & ref_tags_union)

    def _valid(tr):
        return (tr is not None and tr.warp.get("H") is not None
                and tr.warp["per_det_median"] < max_resid
                and coreg.homography_sign(tr.warp["H"]) == ref_sign)

    cands = []
    if _valid(p.tagging):
        cands.append((p.tagging, p.detection.model, "direct"))
    d = TF.detection_view(p.detection, p.features.kept_dots, p.features.kept_dashes)
    refdot = TF.ref_dots_um(TF.load_records())
    for a in sorted(accepted, key=lambda x: x.label):
        ad = TF.detection_view(a.pipeline.detection,
                               a.pipeline.features.kept_dots if a.pipeline.features else None,
                               a.pipeline.features.kept_dashes if a.pipeline.features else None)
        model2, _wm = coreg.auto_register(d, ad, refdot, ref_sign, pitch)
        if model2 is None:
            continue
        det2 = p.detection
        old_model = det2.model
        det2.model = model2                    # re-tag under the transferred numbering
        tr2 = TF.tag_frame(det2, p.features)
        if tr2 is not None and _valid(tr2):
            tr2.label = entry.label
            tr2.source = f"auto<-{a.label:g}x"
            cands.append((tr2, model2, tr2.source))
        det2.model = old_model                 # restore; winner reassigns below
    if not cands:
        p.tagging = None
        return False, ("no valid registration candidate — add a manual box anchor "
                       "in Stage 2 and re-run")
    best = max(cands, key=lambda c: _share(c[0]))
    tr, model, src = best
    share = _share(tr)
    if share < min_share:
        p.tagging = None
        return False, (f"only {share} tags shared with accepted frames (<{min_share}) — "
                       "likely wrong box numbering; add a manual Stage-2 anchor")
    p.detection.model = model
    tr.source = src
    tr.confidence = f"{share} shared tags · " + tr.confidence
    p.tagging = tr
    return True, (f"{len(tr.tags)} tags · {src} · {share} shared · "
                  f"resid {tr.warp['per_det_median']:.1f}px")
