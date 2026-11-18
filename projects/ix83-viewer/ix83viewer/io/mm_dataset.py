"""Lazy access to one Micro-Manager MMStack acquisition folder.

Each folder holds a single-channel T x Y x X uint16 stack
(<prefix>_MMStack_Pos0.ome.tif) plus <prefix>_MMStack_Pos0_metadata.txt.
Stacks can be 400 MB - 4 GB and live in iCloud, so frames are read one page
at a time and the file handle is opened only while reading.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
from dataclasses import dataclass, field
from functools import cached_property

import numpy as np
import tifffile

from .naming import AcquisitionName, parse_name

# tifffile logs "MMStack series is missing files" for truncated stacks; MMDataset
# reports truncation itself (see .warnings), so keep that noise off the console.
logging.getLogger("tifffile").setLevel(logging.ERROR)

# Photometrics Prime 95B (GSENSE400BSI, 1412x1412) has 11 um pixels.  The
# "PixelSizeUm" Micro-Manager stored (0.102) is the 100x calibration and is
# wrong for the 10x data, so pixel size is derived from the objective.
CAMERA_PIXEL_UM = 11.0
_MAG_RE = re.compile(r"(\d+(?:\.\d+)?)X", re.IGNORECASE)


@dataclass(frozen=True)
class FrameInfo:
    index: int
    elapsed_ms: float | None
    exposure_ms: float | None
    x_um: float | None
    y_um: float | None
    z_um: float | None


@dataclass
class MMDataset:
    folder: str
    tif_path: str
    metadata_path: str | None
    name: AcquisitionName
    summary: dict = field(repr=False)
    frames: list[FrameInfo] = field(repr=False)
    first_frame_meta: dict = field(repr=False)
    n_frames: int = 0
    shape_yx: tuple[int, int] = (0, 0)
    dtype: np.dtype = np.dtype("uint16")
    warnings: list[str] = field(default_factory=list)
    pixel_size_override_um: float | None = None
    expansion_override: float | None = None

    # ---- construction -------------------------------------------------
    @classmethod
    def open(cls, folder: str) -> "MMDataset":
        folder = os.path.abspath(folder.rstrip(os.sep))
        tifs = sorted(glob.glob(os.path.join(folder, "*.ome.tif")))
        if not tifs:
            raise FileNotFoundError(f"No .ome.tif in {folder}")
        metas = sorted(glob.glob(os.path.join(folder, "*_metadata.txt")))
        notes: list[str] = []
        if len(tifs) > 1:
            notes.append(f"{len(tifs)} .ome.tif files; using {os.path.basename(tifs[0])}")

        summary: dict = {}
        frame_meta: list[tuple[int, dict]] = []
        if metas:
            with open(metas[0], encoding="utf-8") as f:
                meta = json.load(f)
            summary = meta.get("Summary", {})
            for key, value in meta.items():
                if key.startswith("FrameKey-"):
                    t = int(key.split("-")[1])
                    frame_meta.append((t, value))
            frame_meta.sort(key=lambda kv: kv[0])
        else:
            notes.append("No _metadata.txt; stage position and exposure unknown")

        with tifffile.TiffFile(tifs[0]) as tf:
            series = tf.series[0]
            n_frames = len(series.pages)
            page0 = series.pages[0]
            shape_yx = tuple(page0.shape[-2:])
            dtype = page0.dtype

        name = parse_name(os.path.basename(folder))
        intended = summary.get("IntendedDimensions", {}).get("time") or name.counts
        if intended and n_frames < intended:
            notes.append(f"Truncated stack: {n_frames} of {intended} frames present")
        if frame_meta and len(frame_meta) != n_frames:
            notes.append(f"Metadata lists {len(frame_meta)} frames but TIFF has {n_frames}")
        prefix = summary.get("Prefix")
        if prefix and prefix != name.raw:
            notes.append(f"File prefix '{prefix}' differs from folder name; folder name is used")

        frames = [
            FrameInfo(
                index=t,
                elapsed_ms=_f(m.get("ElapsedTime-ms")),
                exposure_ms=_f(m.get("Exposure-ms")),
                x_um=_f(m.get("XPositionUm")),
                y_um=_f(m.get("YPositionUm")),
                z_um=_f(m.get("ZPositionUm")),
            )
            for t, m in frame_meta
        ]
        return cls(
            folder=folder,
            tif_path=tifs[0],
            metadata_path=metas[0] if metas else None,
            name=name,
            summary=summary,
            frames=frames,
            first_frame_meta=frame_meta[0][1] if frame_meta else {},
            n_frames=n_frames,
            shape_yx=shape_yx,
            dtype=dtype,
            warnings=notes,
        )

    # ---- convenience properties --------------------------------------
    @property
    def label(self) -> str:
        return self.name.raw

    @property
    def wavelength_nm(self) -> int | None:
        return self.name.wavelength_nm

    @property
    def exposure_ms(self) -> float | None:
        if self.frames and self.frames[0].exposure_ms is not None:
            return self.frames[0].exposure_ms
        return self.name.exposure_ms

    @property
    def objective(self) -> str | None:
        return self.first_frame_meta.get("Objective-Label")

    @cached_property
    def magnification(self) -> float | None:
        m = _MAG_RE.search(self.objective or "")
        return float(m.group(1)) if m else None

    @property
    def reported_pixel_size_um(self) -> float | None:
        return _f(self.first_frame_meta.get("PixelSizeUm"))

    @property
    def pixel_size_um(self) -> float | None:
        """Pixel size at the sample, derived from the objective unless overridden."""
        if self.pixel_size_override_um is not None:
            return self.pixel_size_override_um
        if self.magnification:
            return CAMERA_PIXEL_UM / self.magnification
        return self.reported_pixel_size_um

    @property
    def expansion_factor(self) -> float | None:
        """Gel expansion factor: user override, else the "3.0x" field of the folder name."""
        return self.expansion_override or self.name.factor

    @property
    def stage_xyz_um(self) -> tuple[float | None, float | None, float | None]:
        # Per-frame positions are used: Summary.StagePositions can be stale
        # (488-Sample1-3.0x-100cts-400ms_1 reports Y=-1763.5 there, -2233.3 per frame).
        if not self.frames:
            return (None, None, None)
        f0 = self.frames[0]
        return (f0.x_um, f0.y_um, f0.z_um)

    @property
    def start_time(self) -> str | None:
        return self.summary.get("StartTime")

    @property
    def comment(self) -> str | None:
        path = os.path.join(self.folder, "comments.txt")
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            return d["map"]["General annotation"]["scalar"]["comments"]["scalar"]
        except (OSError, KeyError, ValueError, TypeError):
            return None

    # ---- pixel access -------------------------------------------------
    def frame(self, index: int) -> np.ndarray:
        """Return one raw frame (uint16, Y x X)."""
        if not -self.n_frames <= index < self.n_frames:
            raise IndexError(f"Frame {index} out of range (0..{self.n_frames - 1})")
        with self._open() as tf:
            return tf.series[0].pages[index % self.n_frames].asarray()

    def iter_frames(self, indices=None):
        """Yield raw frames, keeping the file open across reads."""
        if indices is None:
            indices = range(self.n_frames)
        with self._open() as tf:
            pages = tf.series[0].pages
            for i in indices:
                yield pages[i].asarray()

    def _open(self):
        return tifffile.TiffFile(self.tif_path)

    @cached_property
    def file_signature(self) -> tuple[str, int, float]:
        st = os.stat(self.tif_path)
        return (os.path.realpath(self.tif_path), st.st_size, st.st_mtime)


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
