"""Data sanity checks for a scanned date folder (Tools ▸ Data check) and
thumbnail rendering for the folder list."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

import numpy as np
from PIL import Image

from ..io.mm_dataset import MMDataset
from ..io.scan import ScanResult, group_by_position
from .display import auto_levels

MAX_PLAUSIBLE_EXPANSION = 15.0  # the Magnify kit targets ~11x; above this is probably a typo
THUMB_SIZE = 176


@dataclass(frozen=True)
class Finding:
    level: str  # "warning" | "info"
    subject: str
    message: str


def check_scan(scan: ScanResult) -> list[Finding]:
    """Warnings first, then notes; identical pixel-size notes are merged."""
    out: list[Finding] = []
    pixel_mismatch: dict[tuple, list[str]] = {}
    for name, err in scan.errors.items():
        out.append(Finding("warning", name, f"Could not be read: {err}"))
    for ds in scan.datasets:
        for w in ds.warnings:
            out.append(Finding("warning", ds.label, w))
        f = ds.name.factor
        if f and f > MAX_PLAUSIBLE_EXPANSION:
            out.append(Finding("warning", ds.label,
                               f"Expansion factor {f:g}× in the name looks implausible (typo?). "
                               "Correct it in the Info panel's Expansion box."))
        rep, px = ds.reported_pixel_size_um, ds.pixel_size_um
        if rep and px and abs(rep - px) / px > 0.2:
            pixel_mismatch.setdefault((rep, ds.objective, px), []).append(ds.label)
    for (rep, objective, px), labels in pixel_mismatch.items():
        subject = labels[0] if len(labels) == 1 else f"{len(labels)} acquisitions"
        out.append(Finding("info", subject, f"Metadata pixel size {rep:g} µm does not match {objective}; "
                                            f"{px:.3g} µm/px is used (camera pixel ÷ magnification)."))
    for s in group_by_position(scan.samples):
        for note in s.notes:
            # a missing wavelength is expected for single-channel sets; mixed exposure/Z is worth a look
            out.append(Finding("info" if note.startswith("missing") else "warning", f"Set {s.label}", note))
    if scan.dark() is None:
        out.append(Finding("info", "Calibration", "No DarkCount acquisition: dark subtraction unavailable."))
    beads = [d for d in scan.calibrations if d.name.kind == "beads"]
    if not beads:
        out.append(Finding("info", "Calibration", "No bead acquisition for channel registration."))
    elif not any(d.wavelength_nm for d in beads):
        out.append(Finding("info", "Calibration",
                           "Bead images have no wavelength in their name; image multi-colour beads in each "
                           "channel (e.g. 488-Beads_1, 561-Beads_1, 633-Beads_1) to calibrate channel offsets."))
    return sorted(out, key=lambda f: f.level != "warning")  # stable: keeps order within each level


def thumbnail_path(ds: MMDataset, cache: str, color) -> str:
    key = repr((ds.file_signature, tuple(round(c, 3) for c in color), THUMB_SIZE))
    return os.path.join(cache, "thumb_" + hashlib.sha1(key.encode()).hexdigest()[:16] + ".png")


def make_thumbnail(ds: MMDataset, cache: str, color=(1.0, 1.0, 1.0)) -> str:
    """PNG of frame 0 (cheap: one page read), coloured, about THUMB_SIZE px wide."""
    path = thumbnail_path(ds, cache, color)
    if os.path.exists(path):
        return path
    img = ds.frame(0).astype(np.float32)
    f = max(1, img.shape[1] // THUMB_SIZE)
    h, w = img.shape[0] // f * f, img.shape[1] // f * f
    small = img[:h, :w].reshape(h // f, f, w // f, f).mean(axis=(1, 3))
    lo, hi = auto_levels(small, 0.5, 99.8)
    t = np.clip((small - lo) / (hi - lo), 0, 1)
    rgb = (t[..., None] * np.asarray(color)[None, None, :] * 255).astype(np.uint8)
    os.makedirs(cache, exist_ok=True)
    Image.fromarray(rgb).save(path)
    return path
