"""Scan a date folder and group acquisitions that image the same field of view.

Every acquisition holds one wavelength, so a multi-colour image is assembled
from separate folders.  Folders whose stage X/Y (and Z, within z_tol) agree
are grouped into a FovSet; with the 16Oct26 data this recovers the 488/561/633
triplets without hand-pairing.
"""

from __future__ import annotations

import math
import os
import string
from dataclasses import dataclass, field

from .mm_dataset import MMDataset
from .naming import KNOWN_WAVELENGTHS

# The stage readback can disagree by a few um for the same FOV (4.2x set:
# 488 at Y=-2233.3, 561/633 at Y=-2237.4, yet images register at (0, 0) px),
# while distinct FOVs in 16Oct26 are >= 127 um apart.
DEFAULT_XY_TOL_UM = 10.0
# Refocusing between channels moved Z by up to ~13 um within one FOV
# (set B: 4860.96-4873.56), while distinct acquisitions at the same X/Y
# differ by >= 75 um, so 25 um separates them.
DEFAULT_Z_TOL_UM = 25.0


@dataclass
class ScanResult:
    root: str
    datasets: list[MMDataset]
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def samples(self) -> list[MMDataset]:
        return [d for d in self.datasets if d.name.kind == "sample"]

    @property
    def calibrations(self) -> list[MMDataset]:
        return [d for d in self.datasets if d.name.kind != "sample"]

    def dark(self) -> MMDataset | None:
        darks = [d for d in self.datasets if d.name.kind == "dark"]
        return darks[0] if darks else None


@dataclass
class FovSet:
    label: str
    members: list[MMDataset]

    @property
    def wavelengths(self) -> list[int]:
        return sorted({d.wavelength_nm for d in self.members if d.wavelength_nm})

    @property
    def is_complete(self) -> bool:
        return all(w in self.wavelengths for w in KNOWN_WAVELENGTHS)

    def by_wavelength(self) -> dict[int, list[MMDataset]]:
        out: dict[int, list[MMDataset]] = {}
        for d in sorted(self.members, key=lambda d: d.label):
            out.setdefault(d.wavelength_nm, []).append(d)
        return out

    @property
    def xyz_um(self) -> tuple[float, float, float]:
        pts = [d.stage_xyz_um for d in self.members if None not in d.stage_xyz_um]
        if not pts:
            return (math.nan, math.nan, math.nan)
        return tuple(sum(p[i] for p in pts) / len(pts) for i in range(3))

    @property
    def z_range_um(self) -> tuple[float, float]:
        zs = [d.stage_xyz_um[2] for d in self.members if d.stage_xyz_um[2] is not None]
        return (min(zs), max(zs)) if zs else (math.nan, math.nan)

    @property
    def notes(self) -> list[str]:
        out = []
        exps = {d.exposure_ms for d in self.members if d.exposure_ms is not None}
        if len(exps) > 1:
            out.append("mixed exposures: " + ", ".join(f"{e:g} ms" for e in sorted(exps)))
        zlo, zhi = self.z_range_um
        if zhi - zlo > 1.0:
            out.append(f"Z differs by {zhi - zlo:.1f} um")
        missing = [w for w in KNOWN_WAVELENGTHS if w not in self.wavelengths]
        if missing:
            out.append("missing " + "/".join(map(str, missing)))
        return out


def scan_folder(root: str) -> ScanResult:
    root = os.path.abspath(root)
    datasets, errors = [], {}
    for entry in sorted(os.scandir(root), key=lambda e: e.name):
        if not entry.is_dir():
            continue
        if not any(n.endswith(".ome.tif") for n in os.listdir(entry.path)):
            continue
        try:
            datasets.append(MMDataset.open(entry.path))
        except Exception as e:  # keep scanning; report bad folders
            errors[entry.name] = f"{type(e).__name__}: {e}"
    return ScanResult(root=root, datasets=datasets, errors=errors)


def group_by_position(
    datasets: list[MMDataset],
    xy_tol_um: float = DEFAULT_XY_TOL_UM,
    z_tol_um: float = DEFAULT_Z_TOL_UM,
) -> list[FovSet]:
    """Single-linkage grouping on stage position and objective.

    Datasets without stage metadata are skipped.  Sets are ordered by the
    earliest acquisition start time and labelled A, B, C, ...
    """
    items = [d for d in datasets if None not in d.stage_xyz_um]
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(items):
        ax, ay, az = a.stage_xyz_um
        for j in range(i + 1, len(items)):
            b = items[j]
            bx, by, bz = b.stage_xyz_um
            if (
                a.objective == b.objective
                and abs(ax - bx) <= xy_tol_um
                and abs(ay - by) <= xy_tol_um
                and abs(az - bz) <= z_tol_um
            ):
                parent[find(i)] = find(j)

    groups: dict[int, list[MMDataset]] = {}
    for i, d in enumerate(items):
        groups.setdefault(find(i), []).append(d)

    ordered = sorted(groups.values(), key=lambda g: min(d.start_time or "" for d in g))
    return [FovSet(label=_label(k), members=g) for k, g in enumerate(ordered)]


def _label(k: int) -> str:
    letters = string.ascii_uppercase
    return letters[k] if k < 26 else letters[k // 26 - 1] + letters[k % 26]
