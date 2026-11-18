"""Export jobs: what to write for one set of channels, figures, movies, batch.

export_channels() is the one entry point the dialog and batch mode use.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import numpy as np

from ..io.mm_dataset import MMDataset
from ..io.scan import FovSet
from .display import DEFAULT_PRESET, auto_levels, format_um, nice_scale_length, wavelength_color
from .export import (
    ChannelData, burn_scale_bar, render_channel, render_merge, write_channel_tiff, write_hyperstack, write_movie,
    write_rgb, write_sidecar,
)
from .offsets import OffsetStore
from .processing import apply_processing
from .projection import project
from .settings_store import LevelStore, SettingsStore


@dataclass
class ExportOptions:
    aligned: bool = True
    raw_tiffs: bool = True
    dtype: str = "uint16"  # or "float32"
    hyperstack: bool = True
    ome: bool = False
    merged: bool = True
    merged_format: str = "png"  # png | jpg
    jpeg_quality: int = 95
    channel_images: bool = False  # each channel rendered as displayed
    scale_bar: bool = True
    pre_expansion: bool = False  # label scale bars in pre-expansion units (÷ expansion factor)
    figure: bool = True
    figure_format: str = "png"  # png | pdf | svg
    dpi: int = 300
    movie: bool = False
    movie_format: str = "gif"  # gif | mp4
    movie_source: str = "Merged"  # "Merged" or a channel name such as "561"
    fps: float = 10.0

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def safe_name(text: str) -> str:
    return re.sub(r"[^\w\-.]+", "_", text).strip("_") or "export"


def export_channels(channels: list[ChannelData], out_dir: str, base: str, opts: ExportOptions,
                    title: str = "", dark: np.ndarray | None = None, progress=None) -> list[str]:
    """Write every selected output for one set of channels; returns paths written."""
    os.makedirs(out_dir, exist_ok=True)
    base = safe_name(base)
    files: list[str] = []
    px = channels[0].ds.pixel_size_um
    expansion = channels[0].ds.expansion_factor if opts.pre_expansion else None
    multi = len(channels) > 1

    def path(suffix):
        return os.path.join(out_dir, f"{base}{suffix}")

    def step(msg):
        if progress:
            progress(msg)

    if opts.raw_tiffs:
        for ch in channels:
            step(f"Raw TIFF {ch.label}")
            files.append(write_channel_tiff(ch, path(f"_{safe_name(ch.name)}.tif"), opts.dtype, opts.aligned))
    if opts.hyperstack and multi:
        step("Hyperstack")
        suffix = "_stack.ome.tif" if opts.ome else "_stack.tif"
        files.append(write_hyperstack(channels, path(suffix), opts.dtype, opts.aligned, ome=opts.ome))
    if opts.channel_images:
        for ch in channels:
            step(f"Image {ch.label}")
            rgb = render_channel(ch, opts.aligned)
            if opts.scale_bar:
                rgb = burn_scale_bar(rgb, px, expansion=expansion)
            files.append(write_rgb(rgb, path(f"_{safe_name(ch.name)}.{opts.merged_format}"), opts.jpeg_quality))
    if opts.merged and sum(c.in_merge for c in channels) > 1:
        step("Merged image")
        rgb = render_merge(channels, opts.aligned)
        if opts.scale_bar:
            rgb = burn_scale_bar(rgb, px, expansion=expansion)
        files.append(write_rgb(rgb, path(f"_merged.{opts.merged_format}"), opts.jpeg_quality))
    if opts.figure:
        step("Figure")
        files.append(make_figure(channels, path(f"_figure.{opts.figure_format}"), title or base,
                                 opts.aligned, opts.dpi, expansion))
    if opts.movie:
        step("Movie")
        files.append(make_movie(channels, path(f"_movie.{opts.movie_format}"), opts, dark,
                                lambda i, n: step(f"Movie frame {i}/{n}")))
    files.append(write_sidecar(path(".json"), "set" if multi else "channel", channels, files, opts.to_dict()))
    return files


# ---- figure --------------------------------------------------------------
def make_figure(channels: list[ChannelData], path: str, title: str, aligned: bool = True, dpi: int = 300,
                expansion: float | None = None) -> str:
    """Channel panels (each with an ADU colour bar) plus the merge, with scale bars."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.cm import ScalarMappable
    from matplotlib.colors import ListedColormap, Normalize
    from matplotlib.figure import Figure
    from matplotlib.patches import Rectangle

    multi = sum(c.in_merge for c in channels) > 1
    n = len(channels) + (1 if multi else 0)
    fig = Figure(figsize=(3.2 * n, 3.6), dpi=dpi, layout="constrained")
    FigureCanvasAgg(fig)
    axes = fig.subplots(1, n, squeeze=False)[0]
    px = channels[0].ds.pixel_size_um
    h, w = channels[0].image.shape

    def scale_bar(ax):
        if not px:
            return
        f = expansion or 1.0
        length = nice_scale_length(w * px / f * 0.25)
        bar = length * f / px
        ax.add_patch(Rectangle((w * 0.95 - bar, h * 0.93), bar, h * 0.012, color="white"))
        ax.text(w * 0.95 - bar / 2, h * 0.91, format_um(length) + (" pre-exp." if expansion else ""),
                color="white", ha="center", va="bottom", fontsize=7)

    for ax, ch in zip(axes, channels):
        ax.imshow(render_channel(ch, aligned), interpolation="nearest")
        ax.set_title(ch.label, fontsize=9, color=tuple(min(1, c * 0.85) for c in ch.color) if ch.lut is None else "k")
        ax.set_axis_off()
        scale_bar(ax)
        cmap = ListedColormap(ch.display_lut()[:, :3] / 255.0)
        cb = fig.colorbar(ScalarMappable(Normalize(*ch.levels), cmap), ax=ax, orientation="horizontal",
                          fraction=0.05, pad=0.02)
        cb.set_label("Intensity (ADU)", fontsize=7)
        cb.ax.tick_params(labelsize=6)
    if multi:
        ax = axes[-1]
        ax.imshow(render_merge(channels, aligned), interpolation="nearest")
        ax.set_title("Merged" + (" (aligned)" if aligned else ""), fontsize=9)
        ax.set_axis_off()
        scale_bar(ax)
        # empty colour-bar slot keeps the merged image the same size as the others
        fig.colorbar(ScalarMappable(Normalize(0, 1), ListedColormap([[1, 1, 1]])), ax=ax, orientation="horizontal",
                     fraction=0.05, pad=0.02).ax.set_visible(False)
    shown = channels[0].mode if channels[0].mode != "Frame" else f"frame {channels[0].frame}"
    fig.suptitle(f"{title}   ·   {shown}", fontsize=10)
    fig.savefig(path, dpi=dpi, facecolor="white", bbox_inches="tight")
    return path


# ---- movie ---------------------------------------------------------------
def make_movie(channels: list[ChannelData], path: str, opts: ExportOptions, dark=None, progress=None) -> str:
    """One movie frame per time point; each channel is re-read and re-processed
    per frame, then rendered with that channel's current levels."""
    if opts.movie_source == "Merged":
        use = channels
    else:
        use = [c for c in channels if c.name == opts.movie_source] or channels[:1]
    n = max(c.ds.n_frames for c in use)
    px = use[0].ds.pixel_size_um

    def frames():
        for t in range(n):
            frame_chs = []
            for c in use:
                img = c.ds.frame(min(t, c.ds.n_frames - 1))
                img = apply_processing(img, c.settings.processing, dark)
                frame_chs.append(ChannelData(c.ds, img, c.levels, c.settings, c.color, c.offset, "Frame", t, c.lut))
            for fc, c in zip(frame_chs, use):
                fc.in_merge = c.in_merge
            merge = opts.movie_source == "Merged" and sum(fc.in_merge for fc in frame_chs) > 1
            rgb = render_merge(frame_chs, opts.aligned) if merge else render_channel(frame_chs[0], opts.aligned)
            if opts.scale_bar:
                rgb = burn_scale_bar(rgb, px, expansion=use[0].ds.expansion_factor if opts.pre_expansion else None)
            yield rgb

    return write_movie(frames(), path, opts.fps, n, progress)


# ---- batch ---------------------------------------------------------------
def saved_levels(settings: SettingsStore, ds: MMDataset, mode: str, processing):
    """Contrast saved for this acquisition, mode and processing. A single frame
    falls back to the levels saved for the mean: same ADU scale, and usually
    the contrast someone actually chose."""
    for m in (mode, "Mean") if mode == "Frame" else (mode,):
        levels = settings.levels.get(LevelStore.key(ds, m, processing))
        if levels:
            return levels
    return None


def build_set_channels(fov: FovSet, mode: str, settings: SettingsStore, offsets: OffsetStore,
                       dark: np.ndarray | None = None, reference_nm: int = 561,
                       color_preset: str = DEFAULT_PRESET, frame: int = 0) -> list[ChannelData]:
    """Channels for a set as the viewer would show them by default: the replicate
    with most frames per wavelength, saved processing/levels/offsets, else auto."""
    by_wl: dict = {}
    for d in sorted(fov.members, key=lambda d: d.label):
        by_wl.setdefault(d.wavelength_nm or d.label, []).append(d)
    chosen = [max(by_wl[k], key=lambda d: d.n_frames)
              for k in sorted(by_wl, key=lambda k: (-k, "") if isinstance(k, int) else (1, k))]
    ref = next((d for d in chosen if d.wavelength_nm == reference_nm), chosen[0])
    out = []
    for ds in chosen:
        s = settings.get(ds)
        raw = project(ds, mode.lower(), frame=min(frame, ds.n_frames - 1))
        img = apply_processing(raw, s.processing, dark if s.processing.dark else None)
        levels = saved_levels(settings, ds, mode, s.processing) or auto_levels(img)
        color = s.color or wavelength_color(ds.wavelength_nm, color_preset)
        out.append(ChannelData(ds, img, tuple(levels), s, color, offsets.get(ds, ref), mode, frame))
    return out


def export_batch(sets: list[FovSet], out_dir: str, prefix: str, opts: ExportOptions, mode: str,
                 settings: SettingsStore, offsets: OffsetStore, dark=None, color_preset=DEFAULT_PRESET,
                 progress=None) -> list[str]:
    files = []
    for i, fov in enumerate(sets, 1):
        label = f"Set_{fov.label}"
        if progress:
            progress(f"[{i}/{len(sets)}] {label}: loading")
        chs = build_set_channels(fov, mode, settings, offsets, dark, color_preset=color_preset)
        files += export_channels(chs, os.path.join(out_dir, label), f"{prefix}_{label}_{mode}", opts,
                                 title=f"{prefix} Set {fov.label}", dark=dark,
                                 progress=lambda m, label=label: progress and progress(f"[{i}/{len(sets)}] {label}: {m}"))
    return files
