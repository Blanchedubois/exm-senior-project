"""The manifest of a bead-in-gel experiment, and checks of it against the data.

The manifest (experiments/<date>.json) says which acquisitions are the areas of
each hydrogel and why every other folder was left out.  check_experiment fails
loudly on anything that would make the areas incomparable.
"""

from __future__ import annotations

import itertools
import json
import os
from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage as ndi

from ..core.projection import project
from ..io.mm_dataset import MMDataset

# An area pair counts as the same piece of gel when a shift this far from the
# stage move lines their structure up this well.
OVERLAP_MIN_ZNCC = 0.5  # unrelated sparse bead fields reach ~0.4 by chance
OVERLAP_SHIFT_TOLERANCE = 0.1
MIN_AREAS = 3


@dataclass(frozen=True)
class Condition:
    key: str
    label: str
    preparation: str
    factor: float
    areas: tuple[str, ...]


@dataclass(frozen=True)
class Experiment:
    name: str
    data_root: str
    dark_folder: str
    wavelength_nm: int
    laser_power_mw: float
    bead: str
    nominal_expansion: float
    conditions: tuple[Condition, ...]
    excluded: dict[str, str]
    # "linear": the factor is per length (Magnify's 11x is linear, ~1,300x in volume), so area grows by
    # factor²; "area": the factor is already per area.
    expansion_basis: str = "linear"

    def area_factor(self, factor: float) -> float:
        return factor ** 2 if self.expansion_basis == "linear" else factor

    def path(self, folder: str) -> str:
        return os.path.join(self.data_root, folder)


def load_experiment(path: str, root: str | None = None) -> Experiment:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return Experiment(
        name=d["name"],
        data_root=root or d["data_root"],
        dark_folder=d["dark_folder"],
        wavelength_nm=d["wavelength_nm"],
        laser_power_mw=d["laser_power_mw"],
        bead=d["bead"],
        nominal_expansion=d["nominal_expansion"],
        conditions=tuple(
            Condition(c["key"], c["label"], c["preparation"], c["factor"], tuple(c["areas"]))
            for c in d["conditions"]
        ),
        excluded=d.get("excluded", {}),
        expansion_basis=_basis(d.get("expansion_basis", "linear")),
    )


def _basis(v: str) -> str:
    if v not in ("linear", "area"):
        raise ValueError(f'expansion_basis must be "linear" or "area", not {v!r}')
    return v


@dataclass(frozen=True)
class AreaPair:
    condition: str
    a: str
    b: str
    stage_distance_um: float
    expected_overlap: float  # fraction of the field shared, from the stage positions
    zncc: float | None = None  # similarity at the best non-zero image shift
    image_shift_um: float | None = None

    @property
    def confirmed(self) -> bool:
        """The images themselves show the same structure at the stage's offset."""
        if self.zncc is None or self.image_shift_um is None:
            return False
        close = abs(self.image_shift_um - self.stage_distance_um) <= OVERLAP_SHIFT_TOLERANCE * self.stage_distance_um
        return self.zncc >= OVERLAP_MIN_ZNCC and close


@dataclass
class Report:
    experiment: Experiment
    rows: list[dict] = field(default_factory=list)
    pairs: list[AreaPair] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def check_experiment(exp: Experiment, overlap: bool = True) -> Report:
    report = Report(exp)
    used = [a for c in exp.conditions for a in c.areas]
    if not os.path.isdir(exp.data_root):
        report.errors.append(f"Data folder is not available: {exp.data_root}")
        return report

    for folder in {f for f in used if used.count(f) > 1}:
        report.errors.append(f"{folder} is listed more than once")
    for folder in set(used) & set(exp.excluded):
        report.errors.append(f"{folder} is both used and excluded")
    present = {e.name for e in os.scandir(exp.data_root) if e.is_dir()}
    known = set(used) | set(exp.excluded) | {exp.dark_folder}
    for folder in sorted(present - known):
        report.errors.append(f"{folder} is neither used nor excluded in the manifest")
    for folder in sorted(known - present):
        report.errors.append(f"{folder} is in the manifest but not in the data folder")
    if report.errors:
        return report

    opened: dict[str, list[MMDataset]] = {}
    for c in exp.conditions:
        opened[c.key] = _open_condition(c, exp, report)
    all_ds = [d for ds in opened.values() for d in ds]
    _require_same(report, all_ds, "exposure", lambda d: d.exposure_ms)
    _require_same(report, all_ds, "objective", lambda d: d.objective)
    _require_same(report, all_ds, "image size", lambda d: d.shape_yx)
    for meta_key, what in (("Binning", "binning"), ("Camera-1-Gain", "camera gain")):
        _require_same(report, all_ds, what, lambda d: d.first_frame_meta.get(meta_key))
    _note_camera_processing(report, all_ds)
    if not os.path.isdir(exp.path(exp.dark_folder)):
        report.errors.append(f"Dark acquisition {exp.dark_folder} is missing")
    elif MMDataset.open(exp.path(exp.dark_folder)).name.kind != "dark":
        report.errors.append(f"{exp.dark_folder} does not look like a dark acquisition")

    for c in exp.conditions:
        if not opened[c.key]:
            continue
        report.pairs.extend(_pairs(c, opened[c.key], overlap))
    for p in report.pairs:
        if p.confirmed:
            report.notes.append(
                f"{p.condition}: {p.a} and {p.b} share about {p.expected_overlap:.0%} of the field "
                f"(same structure at {p.image_shift_um:.0f} µm, r = {p.zncc:.2f})")
    return report


def _open_condition(c: Condition, exp: Experiment, report: Report) -> list[MMDataset]:
    out = []
    if len(c.areas) < MIN_AREAS:
        report.errors.append(f"{c.key}: only {len(c.areas)} areas, need at least {MIN_AREAS}")
    for folder in c.areas:
        d = MMDataset.open(exp.path(folder))
        if d.name.kind != "sample" or d.name.sample != c.preparation or d.name.factor != c.factor:
            report.errors.append(f"{folder}: name does not match condition {c.key}")
            continue
        for w in d.warnings:
            report.errors.append(f"{folder}: {w}")
        x, y, z = d.stage_xyz_um
        report.rows.append({"condition": c.key, "folder": folder, "frames": d.n_frames,
                            "exposure_ms": d.exposure_ms, "x_um": x, "y_um": y, "z_um": z})
        out.append(d)
    return out


def _require_same(report: Report, datasets: list[MMDataset], what: str, get) -> None:
    values = {str(get(d)) for d in datasets}
    if len(values) > 1:
        report.errors.append(f"Areas differ in {what}: {sorted(values)}")


def _note_camera_processing(report: Report, datasets: list[MMDataset]) -> None:
    def enabled(d: MMDataset) -> list[str]:
        return sorted(k for k, v in d.first_frame_meta.items() if k.endswith("ENABLED") and v == "Yes")
    states = {tuple(enabled(d)) for d in datasets}
    if len(states) > 1:
        report.errors.append("Camera processing differs between areas")
    elif states and next(iter(states)):
        report.notes.append(f"Camera on-chip processing was on: {len(next(iter(states)))} features enabled")


def _pairs(c: Condition, datasets: list[MMDataset], overlap: bool) -> list[AreaPair]:
    out = []
    for a, b in itertools.combinations(datasets, 2):
        dx, dy = (a.stage_xyz_um[0] - b.stage_xyz_um[0]), (a.stage_xyz_um[1] - b.stage_xyz_um[1])
        height, width = a.shape_yx
        px = a.pixel_size_um
        share = max(0.0, 1 - abs(dx) / (width * px)) * max(0.0, 1 - abs(dy) / (height * px))
        zncc = shift_um = None
        if overlap and share > 0:
            zncc, shift_px = best_nonzero_shift(project(a, "mean"), project(b, "mean"))
            shift_um = shift_px * px
        out.append(AreaPair(c.key, a.label, b.label, float(np.hypot(dx, dy)), share, zncc, shift_um))
    return out


def _structure(img: np.ndarray) -> np.ndarray:
    """Beads and blur discs without the illumination, compressed so the brightest beads don't dominate."""
    fine = ndi.gaussian_filter(img.astype(np.float32), 1.5) - ndi.gaussian_filter(img.astype(np.float32), 15)
    scale = 1.4826 * np.median(np.abs(fine - np.median(fine))) or 1.0
    return np.arcsinh(fine / scale)


def best_nonzero_shift(a: np.ndarray, b: np.ndarray, min_shift_px: int = 10,
                       min_overlap: float = 0.25) -> tuple[float, float]:
    """Best alignment of two images, ignoring near-zero shifts (fixed camera and optical patterns).

    Returns the correlation inside the overlap at that shift, and the shift length in pixels.
    """
    sa, sb = _structure(a), _structure(b)
    sa, sb = sa - sa.mean(), sb - sb.mean()
    height, width = sa.shape
    pad = (2 * height, 2 * width)
    corr = np.fft.irfft2(np.fft.rfft2(sa, pad) * np.conj(np.fft.rfft2(sb, pad)), pad)
    dy = np.fft.fftfreq(pad[0], 1 / pad[0]).astype(int)[:, None]
    dx = np.fft.fftfreq(pad[1], 1 / pad[1]).astype(int)[None, :]
    shared = np.clip(height - np.abs(dy), 0, None) * np.clip(width - np.abs(dx), 0, None)
    allowed = (shared >= min_overlap * height * width) & (np.hypot(dy, dx) >= min_shift_px)
    score = np.where(allowed, corr / np.maximum(shared, 1), -np.inf)
    iy, ix = np.unravel_index(np.argmax(score), score.shape)
    sy, sx = int(dy[iy, 0]), int(dx[0, ix])
    overlap_a = sa[max(0, sy):height + min(0, sy), max(0, sx):width + min(0, sx)]
    overlap_b = sb[max(0, -sy):height + min(0, -sy), max(0, -sx):width + min(0, -sx)]
    return float(np.corrcoef(overlap_a.ravel(), overlap_b.ravel())[0, 1]), float(np.hypot(sy, sx))


def format_report(report: Report) -> str:
    exp = report.experiment
    lines = [exp.name, f"{exp.wavelength_nm} nm, {exp.laser_power_mw:g} mW, {exp.bead} beads, "
                       f"nominal {exp.nominal_expansion:g}× expansion", ""]
    for r in report.rows:
        lines.append(f"{r['condition']:<7} {r['folder']:<34} {r['frames']:>3} fr  {r['exposure_ms']:g} ms  "
                     f"XYZ ({r['x_um']:.0f}, {r['y_um']:.0f}, {r['z_um']:.0f}) µm")
    if report.pairs:
        lines += ["", "Area pairs (stage distance, expected shared field, image match):"]
        for p in report.pairs:
            match = "not tested" if p.zncc is None else f"r = {p.zncc:.2f} at {p.image_shift_um:.0f} µm"
            lines.append(f"{p.condition:<7} {p.a} / {p.b}: {p.stage_distance_um:.0f} µm, "
                         f"{p.expected_overlap:.0%}, {match}{'  OVERLAPS' if p.confirmed else ''}")
    for title, items in (("Notes", report.notes), ("ERRORS", report.errors)):
        if items:
            lines += ["", title + ":"] + [f"  {i}" for i in items]
    if not report.errors:
        lines += ["", "Manifest OK."]
    return "\n".join(lines)
