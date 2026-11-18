"""
pairkit.project
==============
The multi-image project: the initial expansion image + a series of more-expanded
images (each with an expansion-factor label), and their processed PointTables.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field

from . import process, pair as pairmod, io_csv, strain as strainmod, coreg
from .types import PointTable

_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL = os.path.normpath(os.path.join(
    _ROOT, "..", "..", "point_tracking_gui", "reference", "glyph_knn.yml"))


@dataclass
class ImageEntry:
    path: str
    label: float                 # expansion factor, e.g. 1.2, 2.0
    role: str                    # "initial" | "expansion"


@dataclass
class StrainProject:
    model_path: str = DEFAULT_MODEL
    initial: ImageEntry = None
    expansions: list = field(default_factory=list)     # [ImageEntry]
    results: dict = field(default_factory=dict)        # path -> PointTable
    manual: dict = field(default_factory=dict)         # path -> {"numbers":[(node,N)],"letters":[]}
    corrections: dict = field(default_factory=dict)    # path -> CorrectionParams (interactive deskew)
    out_dir: str = None
    _clf: object = None

    def anchors(self, path):
        """Per-image manual box/letter anchors (created empty on first access)."""
        return self.manual.setdefault(path, {"numbers": [], "letters": []})

    # ---------------------------------------------------------------- images
    def set_initial(self, path, label):
        self.initial = ImageEntry(path, float(label), "initial")

    def add_expansion(self, path, label):
        self.expansions.append(ImageEntry(path, float(label), "expansion"))

    def entries(self):
        return ([self.initial] if self.initial else []) + list(self.expansions)

    def entry_for(self, path):
        for e in self.entries():
            if e.path == path:
                return e
        return None

    # ---------------------------------------------------------------- process
    def clf(self):
        if self._clf is None:
            self._clf = process._clf(self.model_path)
        return self._clf

    def process_one(self, path, **kw):
        e = self.entry_for(path)
        man = self.manual.get(path)                      # per-image box anchors
        if man and (man.get("numbers") or man.get("letters")):
            kw.setdefault("manual", man)
        if path in self.corrections:                     # exact interactive deskew
            kw.setdefault("correction", self.corrections[path])
            kw.setdefault("auto_deskew", False)
        table = process.process_image(path, self.clf(), **kw)
        if e is not None:
            table.label = e.label
            table.role = e.role
        self.results[path] = table
        return table

    def process_all(self, progress=None, **kw):
        for k, e in enumerate(self.entries()):
            self.process_one(e.path, **kw)
            if progress:
                progress(k + 1, len(self.entries()), e.path, self.results[e.path])
        return self.results

    def auto_register(self, path, ref_path=None):
        """Register a (mis-numbered) high-expansion image by aligning it to an
        already-correct LOWER expansion and transferring box numbers — no digit
        reading. Tries candidate (orientation, offset) mappings, reprocesses with
        the resulting anchors, and ACCEPTS only when the reprocessed image pairs to
        the reference with a proper (det>0) deformation. Returns (ok, ref_label,
        info). Restores the plain auto result if nothing validates."""
        if path not in self.results:
            self.process_one(path)
        target = self.entry_for(path)
        tlab = target.label if target else float("inf")
        refs = [e for e in self.entries()
                if e.path != path and e.path in self.results
                and self.results[e.path].registered and e.label < tlab]
        refs.sort(key=lambda e: tlab - e.label)          # nearest lower first
        if ref_path:
            refs = [e for e in self.entries() if e.path == ref_path] + refs
        high0 = self.results[path]                        # the plain-auto table (to align from)
        for e in refs:
            ref_table = self.results[e.path]
            for score, S, t in coreg.candidates(ref_table, high0):
                anchors = coreg.anchors_for(high0, S, t)
                if not anchors:
                    continue
                self.anchors(path)["numbers"] = anchors
                self.corrections.pop(path, None)          # keep auto-deskew
                self.process_one(path)
                ok, npairs = coreg.strain_is_proper(ref_table, self.results[path])
                if ok:
                    return True, e.label, {"score": score, "pairs": npairs}
        self.anchors(path)["numbers"] = []                # nothing validated -> revert
        self.process_one(path)
        return False, None, None

    # ---------------------------------------------------------------- pairing
    def pair(self, tol_frac=0.4):
        """Pair every processed expansion to the initial. Needs the initial + at
        least one expansion processed."""
        if self.initial is None or self.initial.path not in self.results:
            raise ValueError("process the initial image first")
        init = self.results[self.initial.path]
        exps = [self.results[e.path] for e in self.expansions if e.path in self.results]
        if not exps:
            raise ValueError("process at least one expansion image first")
        self.pairing = pairmod.pair(init, exps, tol_frac=tol_frac)
        return self.pairing

    def write_pairing_csv(self, path):
        return io_csv.write_pairing(self.pairing, path)

    def write_tagged_csvs(self, out_dir):
        """One tagged CSV per processed image into `out_dir`. Returns [paths]."""
        os.makedirs(out_dir, exist_ok=True)
        written = []
        for e in self.entries():
            t = self.results.get(e.path)
            if t is None:
                continue
            stem = os.path.splitext(os.path.basename(e.path))[0]
            p = os.path.join(out_dir, f"{e.label:g}x_{stem}_tagged.csv")
            io_csv.write_tagged(t, p)
            written.append(p)
        return written

    # ---------------------------------------------------------------- strain
    def strain(self, e, **kw):
        """Strain field for expansion index `e` (into self.pairing.expansions)."""
        return strainmod.compute_strain(self.pairing, e, **kw)

    def strain_all(self, **kw):
        return [self.strain(e, **kw) for e in range(len(self.pairing.expansions))]
