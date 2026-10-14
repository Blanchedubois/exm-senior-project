"""
rwtag.export_reader
===================
Read an export bundle back (docs/07 §4). This is the first thing a downstream
analysis script imports:

    from rwtag.export_reader import read_bundle
    b = read_bundle("export_myproject_20261014-120000")
    b.check()                                   # hashes + schema, raises on a problem
    dev = b.tables["deviation_from_design.csv"]
    b.pairs()                                   # {(ref, cmp): DataFrame}

Only pandas and the schema are needed (no OpenCV, no Qt).
"""
from __future__ import annotations
from dataclasses import dataclass, field
import glob
import hashlib
import json
import os

import pandas as pd

from . import export_schema as S


@dataclass
class ReadBundle:
    folder: str
    manifest: dict
    tables: dict
    alignments: dict = field(default_factory=dict)
    images: dict = field(default_factory=dict)
    rejected: list = field(default_factory=list)

    def check(self, raise_=True):
        """Every table's sha256 against the manifest, row counts, and the schema."""
        probs = []
        if self.manifest.get("bundle_version") != S.BUNDLE_VERSION:
            probs.append(f"bundle version {self.manifest.get('bundle_version')} != reader {S.BUNDLE_VERSION}")
        for name, rec in self.manifest.get("tables", {}).items():
            p = os.path.join(self.folder, name)
            if not os.path.exists(p):
                probs.append(f"{name}: missing"); continue
            if _sha(p) != rec["sha256"]:
                probs.append(f"{name}: sha256 differs from the manifest (file edited?)")
            if len(self.tables[name]) != rec["rows"]:
                probs.append(f"{name}: {len(self.tables[name])} rows, manifest says {rec['rows']}")
            probs += S.validate(name, self.tables[name])
        if raise_ and probs:
            raise ValueError("bundle check failed: " + "; ".join(probs))
        return probs

    def pairs(self):
        """{(reference short name, compared short name): pairs DataFrame}."""
        return {tuple(k[len("pairs_"):-4].split("_", 1)): v for k, v in self.tables.items() if k.startswith("pairs_")}

    def deformation(self):
        return {tuple(k[len("local_deformation_"):-4].split("_", 1)): v
                for k, v in self.tables.items() if k.startswith("local_deformation_")}


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_table(path):
    """One CSV with the schema's dtypes (nullable Int64 / boolean; text blanks -> "")."""
    name = os.path.basename(path)
    cols = S.TABLES[S.schema_key(name)]["cols"]
    dtypes = {}
    for n, dt, _u, _d in cols:
        dtypes[n] = {"float": "float64", "int": "Int64", "bool": "boolean", "str": object}[dt]
    df = pd.read_csv(path, dtype=dtypes, keep_default_na=False,
                     na_values={n: [""] for n, dt, _u, _d in cols if dt != "str"})
    for n, dt, _u, _d in cols:
        if dt == "str":
            df[n] = df[n].fillna("").astype(object)
    return df


def read_bundle(folder) -> ReadBundle:
    folder = os.path.abspath(folder)
    with open(os.path.join(folder, "manifest.json")) as f:
        man = json.load(f)
    tables = {name: read_table(os.path.join(folder, name)) for name in man.get("tables", {})}
    aligns = {}
    for p in sorted(glob.glob(os.path.join(folder, "alignment_*.json"))):
        with open(p) as f:
            aligns[os.path.basename(p)] = json.load(f)
    images = {}
    for p in sorted(glob.glob(os.path.join(folder, "images", "*.json"))):
        st, part, _ = os.path.basename(p).rsplit(".", 2)
        with open(p) as f:
            images.setdefault(st, {})[part] = json.load(f)
    rej = []
    rp = os.path.join(folder, "rejected.json")
    if os.path.exists(rp):
        with open(rp) as f:
            rej = json.load(f)
    return ReadBundle(folder, man, tables, aligns, images, rej)
