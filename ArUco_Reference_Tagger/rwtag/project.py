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


def noise_model_for(entry, calib=None):
    """The NoiseModel for one image: its camera gain from the metadata, kappa and
    floor from the project's calibration (`Project.noise`)."""
    from .errors import NoiseModel
    c = dict(calib or {})
    c["gain_e_per_adu"] = entry.meta.gain_e_per_adu if entry.meta.gain_known else None
    return NoiseModel.from_dict(c)


def calibrate_noise_from_files(paths, correction, levels, design, params=None, gain=None, dot_params=None):
    """Repeat exposures of ONE static state -> kappa_dot / kappa_tag / kappa_rot.
    Each file goes through the given Stage-1 correction, detect (kappa 1, no
    floors), filter and tag; features are matched by tag. Returns the
    calibration dict (see errors.calibrate_from_repeats) with its source."""
    from . import correct as Cc, errors as ER
    from .aruco import detect as AD
    from .dotfilter import filter_frame
    from .refwarp import tagframe as TF
    res = []
    for p in paths:
        raw = io.load_tiff(p)
        corr = Cc.process(raw, correction, levels)
        det = AD.detect(corr, design, params, raw_img=raw, correction=correction, noise_model=ER.raw_model(gain))
        if not det.model.get("registered"):
            continue
        tr = TF.tag_frame(det, filter_frame(det, dot_params, None, design), design)
        if tr is not None:
            res.append((det, tr))
    if len(res) < 3:
        raise ValueError(f"need >= 3 registered repeat frames, got {len(res)}")
    cal = ER.calibrate_from_repeats(res)
    cal["kappa_source"] = f"repeat images: {len(res)} frames" + ("" if gain else " (relative, no gain)")
    return cal


def run_detect(entry, design, params=None, calib=None):
    """Stage 2 for one image, headless: Stage-1 corrected frame + raw frame ->
    DetectResult stored on the entry; derived expansion / rotation / handedness
    written into its metadata. Returns the DetectResult."""
    from .aruco import detect as AD
    from . import designs as DS
    entry.ensure_loaded()
    p = AD.params_for_meta(entry.meta, params)
    pl = entry.pipeline
    det = AD.detect(pl.corrected_image, design, p, raw_img=pl.raw_image, correction=pl.correction,
                    noise_model=noise_model_for(entry, calib))
    pl.detection = det
    pl.features = None
    pl.tagging = None
    AD.apply_to_meta(det, entry.meta)
    if design.folder:
        entry.meta.apply_auto({"print_design": DS.meta_name(design.folder)}, "pipeline")
    entry.save_meta()
    return det
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
        """(s1, s2, s3, s4) booleans — corrected · detected · filtered · tagged AND
        accepted (a rejected frame's results are kept for inspection, not counted)."""
        p = self.pipeline
        s2 = p.detection is not None and getattr(p.detection, "model", None) is not None \
            and p.detection.model.get("registered", False)
        s4 = p.tagging is not None and getattr(p.tagging, "accepted", True)
        s1 = (p.raw_image is not None or p.detection is not None
              or os.path.exists(io.sidecar_path(self.path)))
        return (s1, s2, p.features is not None, s4)

    def status_text(self):
        tr = self.pipeline.tagging
        if tr is None:
            return ""
        return "accepted" if tr.accepted else f"REJECTED: {tr.reason}"

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
        if not p.corrected_is_current():
            # (re)compute whenever the Stage-1 parameters differ from the ones that
            # produced the cached frame -- a stale corrected frame silently carries
            # the old (e.g. uncorrected) lens geometry into every later stage
            p.corrected_image = C.process(p.raw_image, p.correction, p.levels)
            p.corrected_key = p.stage1_key()

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
    noise: dict = field(default_factory=dict)      # error-model calibration: kappa_*, floor_px, sources (Phase 5)

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
             "noise": dict(self.noise),
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
                   design_folder=(os.path.normpath(os.path.join(base, df)) if df else ""),
                   noise=dict(d.get("noise", {})))
        for im in d.get("images", []):
            p = im["path"]
            full = p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p))
            e = ImageEntry(path=full, label=float(im["label"]), role=im.get("role", "expanded"))
            e.ensure_meta(im.get("meta"))
            proj.images.append(e)
        proj.refresh_roles()
        return proj


# ---------------------------------------------------------------- batch runner
def run_stages(entry, design, params=None, dot_params=None, dash_params=None, keep_images=None, calib=None):
    """Stages 2-4 for one image with ITS Stage-1 tuning (sidecar), headless:
    detect -> filter -> tag. No acceptance test here (see run_stages_validated).
    Returns (ok, message)."""
    from .dotfilter import filter_frame
    from .refwarp import tagframe as TF
    loaded = entry.pipeline.raw_image is not None
    det = run_detect(entry, design, params, calib)
    p = entry.pipeline
    try:
        if not det.model.get("registered"):
            return False, "Stage 2 could not register: " + det.model.get("reason", "")
        p.features = filter_frame(det, dot_params, dash_params, design)
        tr = TF.tag_frame(det, p.features, design)
        if tr is None:
            p.tagging = None
            return False, "Stage 4 warp fit failed (too few dots?)"
        tr.label = entry.label
        p.tagging = tr
        return True, (f"{len(tr.tags)} tags · λ {det.lam_tags:.4f} · resid {tr.warp['per_det_median']:.2f} px · "
                      f"matched {tr.warp['matched_frac']:.0%}")
    finally:
        if not loaded and not keep_images:
            entry.unload_images()


def run_stages_validated(entry, accepted, design, params=None, dot_params=None, dash_params=None,
                         max_resid=None, min_share=None, keep_images=None, calib=None):
    """run_stages + the series gates (rwtag.series.validate) against the already
    accepted entries. A rejected frame keeps its results, marked not accepted."""
    from . import series as SR
    ok, msg = run_stages(entry, design, params, dot_params, dash_params, keep_images, calib)
    tr = entry.pipeline.tagging
    if not ok:
        if tr is not None:
            tr.accepted, tr.reason = False, msg
        return False, msg
    acc = [a.pipeline.tagging for a in accepted if a is not entry and a.pipeline.tagging is not None]
    ok, reason, _share = SR.validate(tr, entry.pipeline.detection, entry.label, acc,
                                     max_resid or SR.MAX_RESID, min_share or SR.MIN_SHARE)
    tr.accepted, tr.reason = ok, ("" if ok else reason)
    tr.source = "baseline" if ok and not [a for a in acc if a.accepted] else "direct"
    tr.confidence = reason + " · " + tr.confidence
    return ok, (msg + f" · {reason}" if ok else f"REJECTED: {reason}")
