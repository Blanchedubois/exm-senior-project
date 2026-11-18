"""Export: quantitative TIFFs, Fiji hyperstacks, rendered PNG/JPEG, figures, movies.

Two kinds of output, kept apart on purpose:
- Quantitative (raw channel TIFFs, hyperstack, OME-TIFF): pixel values are
  the processed image (dark/background/denoise if enabled) with NO contrast
  stretch, gamma or colour.  Display levels and colours are stored only as
  metadata (ImageJ LUTs/ranges), so Fiji opens them looking right while the
  numbers stay intact.
- Rendered (PNG/JPEG, figures, movies): 8-bit RGB exactly as displayed.
Every export writes a <name>.json sidecar recording sources and settings.

Nothing here imports Qt, so batch exports can run without the GUI.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field

import numpy as np
import tifffile
from PIL import Image, ImageDraw, ImageFont

from .. import __version__
from ..io.mm_dataset import MMDataset
from .adjust import ChannelSettings, tone_curve
from .display import format_um, nice_scale_length
from .offsets import ZERO, Offset
from .registration import apply_shift


@dataclass
class ChannelData:
    """Everything needed to export one channel, detached from the GUI."""
    ds: MMDataset
    image: np.ndarray  # processed image (what the viewer shows)
    levels: tuple[float, float]
    settings: ChannelSettings = field(default_factory=ChannelSettings)
    color: tuple[float, float, float] = (1.0, 1.0, 1.0)
    offset: Offset = ZERO
    mode: str = "Mean"
    frame: int = 0
    lut: np.ndarray | None = None  # 256x3 uint8 as displayed; None = colour ramp
    in_merge: bool = True  # the panel's "Merge" tick

    @property
    def name(self) -> str:
        return str(self.ds.wavelength_nm) if self.ds.wavelength_nm else self.ds.label

    @property
    def label(self) -> str:
        return f"{self.ds.wavelength_nm} nm" if self.ds.wavelength_nm else self.ds.label

    def color_lut(self) -> np.ndarray:
        """256x3 LUT in this channel's colour with gamma/invert (used for merges)."""
        t = tone_curve(np.linspace(0, 1, 256), self.settings.gamma, self.settings.invert)
        return np.round(t[:, None] * np.asarray(self.color)[None, :] * 255).astype(np.uint8)

    def display_lut(self) -> np.ndarray:
        return self.lut if self.lut is not None else self.color_lut()


# ---- rendering -----------------------------------------------------------
def normalize(img: np.ndarray, levels: tuple[float, float]) -> np.ndarray:
    lo, hi = levels
    span = hi - lo if hi > lo else 1.0
    return np.clip((img.astype(np.float32) - lo) / span, 0.0, 1.0)


def _index(img, levels) -> np.ndarray:
    return np.round(normalize(img, levels) * 255).astype(np.uint8)


def render_channel(ch: ChannelData, aligned: bool = False) -> np.ndarray:
    """H x W x 3 uint8, as the channel panel displays it."""
    img = apply_shift(ch.image.astype(np.float32), ch.offset.dy, ch.offset.dx) if aligned else ch.image
    return ch.display_lut()[_index(img, ch.levels)][..., :3]


def render_merge(channels: list[ChannelData], aligned: bool = True) -> np.ndarray:
    """Additive merge like the Merged panel: colour LUT x merge weight, summed, clipped."""
    channels = [c for c in channels if c.in_merge]
    if not channels:
        raise ValueError("No channels to merge")
    acc = np.zeros((*channels[0].image.shape, 3), np.float32)
    for ch in channels:
        idx = _index(ch.image, ch.levels)
        rgb = ch.color_lut()[idx].astype(np.float32) * ch.settings.opacity
        if aligned and not ch.offset.is_zero:
            rgb = apply_shift(rgb, ch.offset.dy, ch.offset.dx)
        acc += rgb
    return np.clip(acc, 0, 255).astype(np.uint8)


def burn_scale_bar(rgb: np.ndarray, pixel_size_um: float | None, fraction: float = 0.2,
                   expansion: float | None = None) -> np.ndarray:
    """Draw a white scale bar with label in the bottom-right corner. With
    `expansion`, the label gives the pre-expansion (biological) length."""
    if not pixel_size_um:
        return rgb
    h, w = rgb.shape[:2]
    f = expansion or 1.0
    length_um = nice_scale_length(w * pixel_size_um / f * fraction)
    bar_px = int(round(length_um * f / pixel_size_um))
    im = Image.fromarray(rgb)
    draw = ImageDraw.Draw(im)
    margin, thick = max(8, w // 60), max(3, h // 150)
    x1, y1 = w - margin, h - margin
    draw.rectangle([x1 - bar_px, y1 - thick, x1, y1], fill=(255, 255, 255))
    font = _font(max(12, h // 40))
    text = format_um(length_um) + (" pre-expansion" if expansion else "")
    tw = draw.textlength(text, font=font)
    draw.text((x1 - bar_px / 2 - tw / 2, y1 - thick - 4 - font.size), text, fill=(255, 255, 255), font=font)
    return np.asarray(im)


def _font(size: int):
    for path in ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Supplemental/Arial.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


# ---- quantitative files --------------------------------------------------
def quantitative(img: np.ndarray, dtype: str = "uint16") -> np.ndarray:
    if dtype == "float32":
        return img.astype(np.float32)
    if img.dtype == np.uint16:
        return img
    return np.clip(np.round(img), 0, 65535).astype(np.uint16)


def _resolution(ds: MMDataset):
    px = ds.pixel_size_um
    return ((1 / px, 1 / px), {"unit": "um"}) if px else (None, {})


def _maybe_aligned(ch: ChannelData, aligned: bool) -> np.ndarray:
    if aligned and not ch.offset.is_zero:
        return apply_shift(ch.image.astype(np.float32), ch.offset.dy, ch.offset.dx)
    return ch.image


def write_channel_tiff(ch: ChannelData, path: str, dtype: str = "uint16", aligned: bool = False) -> str:
    data = quantitative(_maybe_aligned(ch, aligned), dtype)
    resolution, meta = _resolution(ch.ds)
    lut = ch.color_lut().T.copy()  # ImageJ wants 3 x 256
    meta.update({"LUTs": [lut], "Ranges": tuple(map(float, ch.levels)), "min": float(ch.levels[0]),
                 "max": float(ch.levels[1]), "Info": _info_text(ch)})
    tifffile.imwrite(path, data, imagej=True, resolution=resolution, metadata=meta)
    return path


def write_hyperstack(channels: list[ChannelData], path: str, dtype: str = "uint16", aligned: bool = True,
                     ome: bool = False) -> str:
    """C x Y x X stack. ImageJ flavour opens in Fiji as a coloured composite."""
    stack = np.stack([quantitative(_maybe_aligned(ch, aligned), dtype) for ch in channels])
    ds = channels[0].ds
    if ome:
        md = {"axes": "CYX", "Channel": {"Name": [c.label for c in channels]}}
        if ds.pixel_size_um:
            md.update(PhysicalSizeX=ds.pixel_size_um, PhysicalSizeXUnit="µm",
                      PhysicalSizeY=ds.pixel_size_um, PhysicalSizeYUnit="µm")
        tifffile.imwrite(path, stack, ome=True, metadata=md)
        return path
    resolution, meta = _resolution(ds)
    ranges = []
    for c in channels:
        ranges.extend(float(v) for v in c.levels)
    meta.update({"axes": "CYX", "mode": "composite", "LUTs": [c.color_lut().T.copy() for c in channels],
                 "Ranges": tuple(ranges), "Labels": [c.label for c in channels],
                 "Info": "\n\n".join(_info_text(c) for c in channels)})
    tifffile.imwrite(path, stack, imagej=True, resolution=resolution, metadata=meta)
    return path


def write_rgb(rgb: np.ndarray, path: str, quality: int = 95) -> str:
    im = Image.fromarray(rgb)
    if path.lower().endswith((".jpg", ".jpeg")):
        im.save(path, quality=quality, subsampling=0)
    else:
        im.save(path)
    return path


# ---- sidecar -------------------------------------------------------------
def channel_record(ch: ChannelData) -> dict:
    ds = ch.ds
    return {
        "channel": ch.label,
        "folder": ds.folder,
        "file": os.path.basename(ds.tif_path),
        "wavelength_nm": ds.wavelength_nm,
        "exposure_ms": ds.exposure_ms,
        "objective": ds.objective,
        "pixel_size_um": ds.pixel_size_um,
        "frames_in_stack": ds.n_frames,
        "shown": ch.mode if ch.mode != "Frame" else f"Frame {min(ch.frame, ds.n_frames - 1)}",
        "processing": ch.settings.processing.to_dict(),
        "processing_key": ch.settings.processing.key(),
        "display": {"levels": list(map(float, ch.levels)), "gamma": ch.settings.gamma,
                    "invert": ch.settings.invert, "color": list(ch.color), "merge_weight": ch.settings.opacity},
        "offset_px": {"dy": ch.offset.dy, "dx": ch.offset.dx, "source": ch.offset.source,
                      "confidence": ch.offset.confidence},
    }


def write_sidecar(path: str, kind: str, channels: list[ChannelData], files: list[str], options: dict) -> str:
    data = {
        "exported_by": f"ix83viewer {__version__}",
        "exported_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "kind": kind,
        "options": options,
        "files": [os.path.basename(f) for f in files],
        "channels": [channel_record(c) for c in channels],
        "notes": ["Quantitative TIFFs hold processed pixel values with no contrast stretch; "
                  "display levels, gamma and colours apply only to rendered PNG/JPEG/figures/movies."],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    return path


def _info_text(ch: ChannelData) -> str:
    r = channel_record(ch)
    return "\n".join(f"{k} = {v}" for k, v in r.items())


# ---- movies --------------------------------------------------------------
def ffmpeg_path() -> str | None:
    for p in (shutil.which("ffmpeg"), "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if p and os.path.exists(p):
            return p
    return None


def write_movie(frames, path: str, fps: float = 10.0, n_frames: int | None = None, progress=None) -> str:
    """frames: iterable of H x W x 3 uint8. .gif via Pillow, .mp4 via ffmpeg (H.264)."""
    if path.lower().endswith(".gif"):
        images = []
        for i, f in enumerate(frames):
            images.append(Image.fromarray(f).quantize(colors=256, method=Image.Quantize.MEDIANCUT))
            if progress:
                progress(i + 1, n_frames)
        images[0].save(path, save_all=True, append_images=images[1:], duration=int(1000 / fps), loop=0)
        return path
    exe = ffmpeg_path()
    if exe is None:
        raise RuntimeError("MP4 needs ffmpeg (brew install ffmpeg); choose GIF instead")
    proc = None
    try:
        for i, f in enumerate(frames):
            h, w = f.shape[:2]
            if proc is None:
                # libx264 + yuv420p need even dimensions.
                proc = subprocess.Popen(
                    [exe, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                     "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                     "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", path],
                    stdin=subprocess.PIPE)
            proc.stdin.write(np.ascontiguousarray(f).tobytes())
            if progress:
                progress(i + 1, n_frames)
    finally:
        if proc is not None:
            proc.stdin.close()
            if proc.wait() != 0:
                raise RuntimeError("ffmpeg failed to write the movie")
    return path
