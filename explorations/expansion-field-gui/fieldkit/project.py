"""
fieldkit.project
================
ExpansionProject: the image set (initial + expansions), the SHARED processing
parameters (optics correction, detection, filters), the output directory, and
the batch runner over all images. Headless.
"""
from __future__ import annotations
import os
import copy
import json
from dataclasses import dataclass, field, asdict

from gridtrack import reference as refmod
from gridtrack.types import CorrectionParams, MeasureParams, FilterParams, LevelsParams
from . import pipeline, pairing, strain, io_csv

_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_META = os.path.normpath(os.path.join(
    _ROOT, "..", "..", "hydrogel_marker_analysis", "toolkit", "grid_metadata.json"))


@dataclass
class ImageParams:
    """Per-image parameters: the Stage-1 contrast/levels (per image) plus Stages
    2-5 (the shared vignette/lens/low-pass optics stay on the project)."""
    levels: LevelsParams = field(default_factory=LevelsParams)
    measure: MeasureParams = field(default_factory=MeasureParams)
    filters: FilterParams = field(default_factory=FilterParams)
    transform_model: str = "similarity"
    ransac_px: float = 4.0

    def to_dict(self):
        return {"levels": self.levels.to_dict(),
                "measure": asdict(self.measure), "filters": asdict(self.filters),
                "transform_model": self.transform_model, "ransac_px": self.ransac_px}

    @classmethod
    def from_dict(cls, d):
        return cls(levels=LevelsParams.from_dict(d.get("levels", {})),
                   measure=MeasureParams(**d["measure"]), filters=FilterParams(**d["filters"]),
                   transform_model=d.get("transform_model", "similarity"),
                   ransac_px=d.get("ransac_px", 4.0))


@dataclass
class ExpansionProject:
    initial_path: str = None
    expansion_paths: list = field(default_factory=list)
    reference_path: str = DEFAULT_META
    out_dir: str = None
    # SHARED across all images (same microscope / same pattern)
    correction: CorrectionParams = field(default_factory=CorrectionParams)
    measure: MeasureParams = field(default_factory=MeasureParams)
    filters: FilterParams = field(default_factory=FilterParams)
    transform_model: str = "similarity"
    ransac_px: float = 4.0
    strain_k: int = 8
    image_params: dict = field(default_factory=dict)    # path -> ImageParams (per-image overrides)
    # runtime
    reference: object = None
    results: dict = field(default_factory=dict)         # path -> ImageResult
    pairings: dict = field(default_factory=dict)        # expansion path -> PairingResult
    strains: dict = field(default_factory=dict)         # expansion path -> strain DataFrame

    def params_for(self, path) -> "ImageParams":
        """Per-image params, initialised from the project defaults on first use."""
        if path not in self.image_params:
            self.image_params[path] = ImageParams(
                measure=copy.deepcopy(self.measure), filters=copy.deepcopy(self.filters),
                transform_model=self.transform_model, ransac_px=self.ransac_px)
        return self.image_params[path]

    # ---------------------------------------------------------------- images
    def all_paths(self):
        return ([self.initial_path] if self.initial_path else []) + list(self.expansion_paths)

    def set_initial(self, path):
        self.initial_path = path

    def add_expansions(self, paths):
        for p in paths:
            if p not in self.expansion_paths and p != self.initial_path:
                self.expansion_paths.append(p)

    # ---------------------------------------------------------------- run
    def load_reference(self):
        self.reference = refmod.load(self.reference_path)
        return self.reference

    def process_one(self, path):
        if self.reference is None:
            self.load_reference()
        res = pipeline.process_image(path, self)
        self.results[path] = res
        return res

    def process_all(self, progress=None):
        """Run stages 1-5 on the initial image + every expansion, writing CSVs.
        `progress(k, n, path, result)` is called after each image."""
        if self.out_dir is None:
            raise ValueError("project.out_dir is not set")
        if self.reference is None:
            self.load_reference()
        paths = self.all_paths()
        for k, p in enumerate(paths):
            res = self.process_one(p)
            if progress:
                progress(k + 1, len(paths), p, res)
        self.save_project_json()
        return self.results

    # ---------------------------------------------------------------- pairing
    def pair_one(self, expansion_path):
        """Pair one expansion image to the initial; writes its pairing CSV."""
        init = self.results.get(self.initial_path)
        exp = self.results.get(expansion_path)
        if init is None or exp is None:
            raise ValueError("process the initial + this expansion image first")
        pr = pairing.pair(init.markers, exp.markers, io_csv.image_name(expansion_path),
                          ransac_thresh=self.ransac_px)
        io_csv.write_pairing(self.out_dir, pr)               # displacement field (PAIRING_COLS)
        # strain / areal expansion field from u_full -> its own CSV
        sdf = strain.compute(pr.field, k=self.strain_k)
        io_csv.write_strain(self.out_dir, pr.expansion_name, sdf)
        pr.field = strain.merge_into_field(pr.field, sdf)    # attach J/E in memory (GUI heatmap)
        self.pairings[expansion_path] = pr
        self.strains[expansion_path] = sdf
        return pr

    def pair_all(self, progress=None):
        """Pair every expansion image to the initial; writes each pairing CSV +
        the summary CSV. `progress(path, pairing_result)` per expansion."""
        rows = []
        for p in self.expansion_paths:
            pr = self.pair_one(p)
            rows.append(pr.summary_row())
            if progress:
                progress(p, pr)
        io_csv.write_pairing_summary(self.out_dir, rows)
        return self.pairings

    # ---------------------------------------------------------------- io
    def save_project_json(self):
        os.makedirs(self.out_dir, exist_ok=True)
        doc = {"initial_path": self.initial_path,
               "expansion_paths": list(self.expansion_paths),
               "reference_path": self.reference_path,
               "transform_model": self.transform_model,
               "correction": asdict(self.correction),
               "measure": asdict(self.measure),
               "filters": asdict(self.filters),
               "image_params": {p: ip.to_dict() for p, ip in self.image_params.items()},
               "processed": [os.path.basename(p) for p in self.results]}
        with open(os.path.join(self.out_dir, "project.json"), "w") as f:
            json.dump(doc, f, indent=2)

    @classmethod
    def load_project_json(cls, out_dir):
        with open(os.path.join(out_dir, "project.json")) as f:
            d = json.load(f)
        pr = cls(initial_path=d["initial_path"], expansion_paths=d["expansion_paths"],
                 reference_path=d["reference_path"], out_dir=out_dir,
                 transform_model=d.get("transform_model", "similarity"),
                 correction=CorrectionParams.from_dict(d["correction"]),
                 measure=MeasureParams(**d["measure"]), filters=FilterParams(**d["filters"]))
        pr.image_params = {p: ImageParams.from_dict(v)
                           for p, v in d.get("image_params", {}).items()}
        return pr
