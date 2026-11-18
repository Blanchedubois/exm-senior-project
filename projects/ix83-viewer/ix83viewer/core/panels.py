"""Overview panels: one image per set with every channel and the overlay,
plus a 1x / 3.0x / 4.2x expansion comparison and a summary of how the
microscope was set up (read from the Micro-Manager metadata).

Used by Side by side ▸ "Export panels" and by tools/blog_figures.py.
"""

from __future__ import annotations

import json
import os
import re
import textwrap
from dataclasses import replace

import numpy as np

from ..io.mm_dataset import MMDataset
from ..io.scan import FovSet
from .adjust import tone_curve
from .display import DEFAULT_PRESET, auto_levels, format_um, nice_scale_length
from .export import ChannelData, render_channel, render_merge
from .export_jobs import build_set_channels, safe_name, saved_levels
from .offsets import OffsetStore
from .processing import apply_processing
from .projection import project
from .settings_store import LevelStore, SettingsStore

# Camera on-chip post-processing features (PVCAM "PP n" properties).
_PP_ENABLED = re.compile(r"Camera-1-PP\s+(\d+)\s+ENABLED")
_PP_NAME = re.compile(r"Camera-1-PP\s+(\d+)\s+([A-Z][A-Z ]+)$")


# Panel variants written by export_panels. Each set gets one image per variant.
# "lut": None keeps each channel's own colour; "gray" / "inferno" replace it.
VARIANTS = {
    "colour": {"exclude": (), "lut": None, "overlay": True, "suffix": "", "title": ""},
    "no633": {"exclude": (633,), "lut": None, "overlay": True, "suffix": "_no633", "title": " · without 633 nm"},
    "gray": {"exclude": (), "lut": "gray", "overlay": False, "suffix": "_gray", "title": " · grayscale, no overlay"},
    "inferno": {"exclude": (), "lut": "inferno", "overlay": False, "suffix": "_inferno",
                "title": " · inferno, no overlay"},
}


def lut_table(name: str, gamma: float = 1.0, invert: bool = False) -> np.ndarray:
    """256 x 3 uint8 table for "gray" or a matplotlib colour map, with gamma/invert."""
    t = tone_curve(np.linspace(0, 1, 256), gamma, invert)
    if name == "gray":
        return np.repeat((t * 255).round().astype(np.uint8)[:, None], 3, axis=1)
    from matplotlib import colormaps
    return (colormaps[name](t)[:, :3] * 255).round().astype(np.uint8)


def variant_channels(chs: list[ChannelData], exclude=(), lut: str | None = None) -> list[ChannelData]:
    """Drop excluded wavelengths; with `lut` ("gray", "inferno"), swap each
    channel's colour for that map (keeping its levels, gamma and invert)."""
    out = [c for c in chs if c.ds.wavelength_nm not in exclude]
    if lut:
        out = [replace(c, lut=lut_table(lut, c.settings.gamma, c.settings.invert)) for c in out]
    return out


# ---- microscope / acquisition summary -----------------------------------
def acquisition_summary(ds: MMDataset) -> dict:
    """The settings that matter for interpreting an image, from its metadata."""
    m = ds.first_frame_meta
    names = {}
    for k, v in m.items():
        mm = _PP_NAME.match(k)
        if mm and v == mm.group(2).strip():
            names.setdefault(mm.group(1), mm.group(2).strip().title())
    enabled = []
    for k, v in m.items():
        mm = _PP_ENABLED.match(k)
        if mm and v == "Yes":
            enabled.append(mm.group(1))
    enabled.sort()
    elapsed = [f.elapsed_ms for f in ds.frames if f.elapsed_ms is not None]
    return {
        "acquisition": ds.label,
        "wavelength_nm": ds.wavelength_nm,
        "expansion": ds.expansion_factor,
        "objective": ds.objective,
        "magnification": ds.magnification,
        "pixel_size_um": ds.pixel_size_um,
        "pixel_size_metadata_um": ds.reported_pixel_size_um,
        "field_of_view_um": ds.pixel_size_um * ds.shape_yx[1] if ds.pixel_size_um else None,
        "image_px": list(ds.shape_yx[::-1]),
        "exposure_ms": ds.exposure_ms,
        "frames": ds.n_frames,
        "frames_intended": ds.summary.get("IntendedDimensions", {}).get("time"),
        "duration_s": (elapsed[-1] - elapsed[0]) / 1000 if len(elapsed) > 1 else None,
        "stage_xyz_um": list(ds.stage_xyz_um),
        "started": ds.start_time,
        "camera_chip": m.get("Camera-1-ChipName"),
        "camera_gain": m.get("Camera-1-Gain"),
        "readout": m.get("Camera-1-ReadoutRate"),
        "sensor_temp_c": _num(m.get("Camera-1-CCDTemperature")),
        "camera_offset_adu": _num(m.get("Camera-1-Offset")),
        "binning": m.get("Camera-1-Binning"),
        "light_path": m.get("Light Path-Label"),
        "camera_processing_on": [names.get(n, f"PP {n}") for n in enabled],
        "micromanager": ds.summary.get("MicroManagerVersion"),
    }


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def caption_for(channels: list[ChannelData]) -> str:
    """Two to four lines describing how the panel was acquired and displayed."""
    s = acquisition_summary(channels[0].ds)
    exp = s["expansion"]
    line1 = (f"Olympus IX83 · {s['objective']} ({s['magnification']:g}×) · "
             f"{s['camera_chip']} camera, {s['readout']}, gain {s['camera_gain']}, "
             f"{s['sensor_temp_c']:.0f} °C · {s['pixel_size_um']:.3g} µm/px, "
             f"field {s['field_of_view_um']:.0f} µm"
             + (f" (≈{s['field_of_view_um'] / exp:.0f} µm before {exp:g}× expansion)" if exp else ""))
    parts = []
    for c in channels:
        a = acquisition_summary(c.ds)
        shown = c.mode if c.mode != "Frame" else f"frame {c.frame}"
        proc = c.settings.processing.key()
        off = "" if c.offset.is_zero else f", shift ({c.offset.dx:+.1f}, {c.offset.dy:+.1f}) px"
        parts.append(f"{c.label}: {a['exposure_ms']:g} ms × {a['frames']} frames ({shown}), "
                     f"levels {c.levels[0]:.0f}–{c.levels[1]:.0f} ADU"
                     + ("" if proc == "raw" else f", {proc}") + off)
    pp = s["camera_processing_on"]
    line3 = ("Camera on-chip processing on: " + ", ".join(pp)) if pp else "Camera on-chip processing off"
    return "\n".join([line1, " · ".join(parts), line3])


# ---- one panel per set ---------------------------------------------------
def make_set_panel(channels: list[ChannelData], path: str, title: str, aligned: bool = True,
                   pre_expansion: bool = False, dpi: int = 200, overlay: bool = True) -> str:
    """All channels and the overlay of one set in a single image, with ADU
    colour bars, scale bars and an acquisition caption."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.cm import ScalarMappable
    from matplotlib.colors import ListedColormap, Normalize
    from matplotlib.figure import Figure

    merge = overlay and sum(c.in_merge for c in channels) > 1
    n = len(channels) + (1 if merge else 0)
    fig = Figure(figsize=(3.0 * max(n, 2), 4.0), dpi=dpi, layout="constrained")
    FigureCanvasAgg(fig)
    axes = fig.subplots(1, n, squeeze=False)[0]
    ds = channels[0].ds
    expansion = ds.expansion_factor if pre_expansion else None
    for ax, ch in zip(axes, channels):
        ax.imshow(render_channel(ch, aligned), interpolation="antialiased")
        ax.set_title(ch.label, fontsize=9)
        ax.set_axis_off()
        _scale_bar(ax, ch.image.shape, ds.pixel_size_um, expansion)
        cb = fig.colorbar(ScalarMappable(Normalize(*ch.levels), ListedColormap(ch.display_lut()[:, :3] / 255)),
                          ax=ax, orientation="horizontal", fraction=0.05, pad=0.02)
        cb.set_label("ADU", fontsize=6)
        cb.ax.tick_params(labelsize=6)
    if merge:
        ax = axes[-1]
        ax.imshow(render_merge(channels, aligned), interpolation="antialiased")
        names = " + ".join(c.name for c in channels if c.in_merge)
        ax.set_title(f"Overlay ({names})", fontsize=9)
        ax.set_axis_off()
        _scale_bar(ax, channels[0].image.shape, ds.pixel_size_um, expansion)
        fig.colorbar(ScalarMappable(Normalize(0, 1), ListedColormap([[1, 1, 1]])), ax=ax,
                     orientation="horizontal", fraction=0.05, pad=0.02).ax.set_visible(False)
    fig.suptitle(textwrap.fill(title, int(fig.get_figwidth() * 10)), fontsize=11, fontweight="bold")
    # wrap to the figure width (about 18 characters per inch at 6 pt) so nothing is cut off
    width = int(fig.get_figwidth() * 18)
    caption = "\n".join(textwrap.fill(line, width) for line in caption_for(channels).splitlines())
    fig.supxlabel(caption, fontsize=6, ha="left", x=0.005, linespacing=1.5)
    fig.savefig(path, dpi=dpi, facecolor="white")
    return path


def _scale_bar(ax, shape, px, expansion=None, length_um=None, suffix=True):
    """White bar bottom right; with `expansion`, labelled in pre-expansion µm.
    `length_um` fixes the (pre-expansion) length instead of choosing one."""
    from matplotlib.patches import Rectangle

    if not px:
        return
    h, w = shape
    f = expansion or 1.0
    length = length_um or nice_scale_length(w * px / f * 0.25)
    bar = length * f / px
    ax.add_patch(Rectangle((w * 0.95 - bar, h * 0.93), bar, h * 0.014, color="white"))
    # right-aligned with the bar so a label longer than the bar stays inside the image
    ax.text(w * 0.95, h * 0.91, format_um(length) + (" pre-exp." if expansion and suffix else ""),
            color="white", ha="right", va="bottom", fontsize=7)


def with_dark(ch: ChannelData, dark, settings: SettingsStore) -> ChannelData:
    """The channel re-processed with dark subtraction on (other processing kept);
    levels come from those saved for that processing, else auto."""
    if ch.settings.processing.dark or dark is None:
        return ch
    s = ch.settings.with_(processing=replace(ch.settings.processing, dark=True))
    raw = project(ch.ds, ch.mode.lower(), frame=min(ch.frame, ch.ds.n_frames - 1))
    img = apply_processing(raw, s.processing, dark)
    levels = saved_levels(settings, ch.ds, ch.mode, s.processing) or auto_levels(img)
    return replace(ch, image=img, settings=s, levels=tuple(levels))


# Each image is about 2.3-2.7 in wide in the figures, so 600 dpi keeps all
# 1412 camera pixels (200 dpi shows about 600 px of them).
FULL_RES_DPI = 600


def export_panels(sets: list[FovSet], out_dir: str, prefix: str, mode: str, settings: SettingsStore,
                  offsets: OffsetStore, dark=None, color_preset: str = DEFAULT_PRESET,
                  pre_expansion: bool = False, current: tuple[FovSet, list[ChannelData]] | None = None,
                  progress=None, comparison: bool = True, force_dark: bool = False,
                  variants=("colour",), expanded_frame: int | None = 0, inferno: bool = False,
                  dpi: int = 200) -> list[str]:
    """One panel PNG per set and variant (see VARIANTS) into out_dir, plus an
    expansion comparison per variant and a JSON with every set's acquisition
    settings. `current` (set, channels) replaces the saved settings for the set
    on screen with what is shown. `force_dark` subtracts the dark frame in
    every channel (needs `dark`).

    `expanded_frame`: expanded gels keep moving while a stack is recorded
    (16Oct26: 16-33 px drift over 3.0x/4.2x stacks, vs <1 px at 1x), so a mean
    blurs them; expanded sets use this single frame instead of `mode`
    (None = use `mode` everywhere). `inferno` also writes one inferno image per
    channel, exactly as used in the panels, into out_dir/inferno. `dpi`: 200
    gives about 600 px per image; FULL_RES_DPI keeps every camera pixel."""
    os.makedirs(out_dir, exist_ok=True)
    files, record, built = [], {}, {}
    for i, fov in enumerate(sets, 1):
        if progress:
            progress(f"Panel {i}/{len(sets)}: Set {fov.label}")
        expanded = any((m.expansion_factor or 1.0) > 1.0 for m in fov.members)
        set_mode, set_frame = ("Frame", expanded_frame) if (expanded and expanded_frame is not None) else (mode, 0)
        shown_ok = current is not None and current[0] is fov and current[1][0].mode == set_mode \
            and (set_mode != "Frame" or current[1][0].frame == set_frame)
        if shown_ok:
            chs = current[1]
        else:
            chs = build_set_channels(fov, set_mode, settings, offsets, dark, color_preset=color_preset,
                                     frame=set_frame)
        if force_dark and dark is not None:
            chs = [with_dark(c, dark, settings) for c in chs]
        built[fov.label] = chs
        for name in variants:
            v = VARIANTS[name]
            vchs = variant_channels(chs, v["exclude"], v["lut"])
            if not vchs or (v["exclude"] and len(vchs) == len(chs)):
                continue  # nothing left, or nothing was excluded (same as the colour panel)
            title = f"{prefix} · Set {fov.label} · {_expansion_label(chs[0].ds)} · {shown_label(chs)}{v['title']}"
            path = os.path.join(out_dir, f"{safe_name(prefix)}_Set_{fov.label}_{mode}{v['suffix']}_panel.png")
            files.append(make_set_panel(vchs, path, title, pre_expansion=pre_expansion, dpi=dpi,
                                        overlay=v["overlay"]))
        record[f"Set {fov.label}"] = {"expansion": chs[0].ds.expansion_factor, "shown": shown_label(chs),
                                      "channels": [acquisition_summary(c.ds) for c in chs]}
        if inferno:
            for ch in chs:
                files.append(make_channel_image(
                    ch, os.path.join(out_dir, "inferno", f"{safe_name(prefix)}_Set_{fov.label}_{ch.name}_inferno.png"),
                    f"{prefix} · Set {fov.label} · {ch.label} · {_expansion_label(ch.ds)} · {shown_label([ch])}",
                    pre_expansion=pre_expansion, dpi=dpi))
    if comparison:
        picks = pick_expansion_sets(sets)
        if len(picks) > 1:
            if progress:
                progress("Expansion comparison")
            for name in variants:
                v = VARIANTS[name]
                rows = [(f, variant_channels(built[s.label], v["exclude"], v["lut"]), s) for f, s in picks]
                path = os.path.join(out_dir, f"{safe_name(prefix)}_expansion_comparison_{mode}{v['suffix']}.png")
                files.append(make_expansion_comparison(rows, path, f"{prefix} · expansion comparison{v['title']}",
                                                       dpi=dpi, overlay=v["overlay"]))
            record["expansion_comparison"] = {f"{f:g}x": f"Set {s.label}" for f, s in picks}
    side = os.path.join(out_dir, f"{safe_name(prefix)}_panels.json")
    with open(side, "w", encoding="utf-8") as fh:
        json.dump({"mode": mode, "expanded_sets_frame": expanded_frame,
                   "dark_subtracted_everywhere": bool(force_dark and dark is not None),
                   "variants": list(variants),
                   "sets": record, "files": [os.path.basename(f) for f in files]}, fh, indent=1)
    files.append(side)
    return files


def shown_label(chs: list[ChannelData]) -> str:
    """'mean of 100 frames' or 'frame 0 (single frame)' for a panel title."""
    c = chs[0]
    if c.mode == "Frame":
        return f"frame {min(c.frame, c.ds.n_frames - 1)} (single frame)"
    n = max(ch.ds.n_frames for ch in chs)
    return f"{c.mode.lower()} of {n} frames"


def make_channel_image(ch: ChannelData, path: str, title: str, cmap: str = "inferno",
                       pre_expansion: bool = False, dpi: int = 200) -> str:
    """One channel with a perceptual colour map (inferno), an ADU colour bar and
    a scale bar. Uses the channel's levels and gamma; native pixel positions."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.cm import ScalarMappable
    from matplotlib.colors import ListedColormap, Normalize
    from matplotlib.figure import Figure

    os.makedirs(os.path.dirname(path), exist_ok=True)
    lut = lut_table(cmap, ch.settings.gamma, ch.settings.invert)
    c = replace(ch, lut=lut)
    fig = Figure(figsize=(5.2, 5.6), dpi=dpi, layout="constrained")
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    ax.imshow(render_channel(c, aligned=False), interpolation="antialiased")
    ax.set_axis_off()
    _scale_bar(ax, c.image.shape, c.ds.pixel_size_um, c.ds.expansion_factor if pre_expansion else None)
    cb = fig.colorbar(ScalarMappable(Normalize(*c.levels), ListedColormap(lut / 255)), ax=ax,
                      orientation="horizontal", fraction=0.04, pad=0.02)
    cb.set_label("ADU", fontsize=7)
    cb.ax.tick_params(labelsize=7)
    fig.suptitle(textwrap.fill(title, int(fig.get_figwidth() * 14)), fontsize=8)
    fig.savefig(path, dpi=dpi, facecolor="white")
    return path


def _expansion_label(ds: MMDataset) -> str:
    f = ds.expansion_factor
    return f"{f:g}× expansion" if f else "not expanded (1×)"


# ---- expansion comparison ------------------------------------------------
def pick_expansion_sets(sets: list[FovSet], max_factor: float = 10.0) -> list[tuple[float, FovSet]]:
    """One set per expansion factor (1x = no factor in the name): prefer sets
    with the most wavelengths, then the most frames. Implausible factors
    (e.g. a 34.2x typo) are skipped."""
    best: dict[float, FovSet] = {}
    for s in sets:
        fs = {m.expansion_factor or 1.0 for m in s.members}
        if len(fs) != 1:
            continue
        f = fs.pop()
        if f > max_factor:
            continue
        score = (len(s.wavelengths), min(m.n_frames for m in s.members))
        cur = best.get(f)
        if cur is None or score > (len(cur.wavelengths), min(m.n_frames for m in cur.members)):
            best[f] = s
    return sorted(best.items())


def make_expansion_comparison(rows: list[tuple[float, list[ChannelData], FovSet]], path: str, title: str,
                              dpi: int = 200, overlay: bool = True) -> str:
    """Rows = expansion factors, columns = 633 / 561 / 488 / overlay. Scale bars
    are in pre-expansion µm, so the same bar length means the same biological
    distance in every row."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    wl_order = sorted({c.ds.wavelength_nm for _, chs, _ in rows for c in chs if c.ds.wavelength_nm}, reverse=True)
    # one biological length for every row: fits the most-expanded (smallest) field
    px0, w0 = rows[0][1][0].ds.pixel_size_um, rows[0][1][0].image.shape[1]
    bar_um = nice_scale_length(w0 * px0 / max(f for f, _, _ in rows) * 0.3) if px0 else None
    overlay = overlay and len(wl_order) > 1
    ncol = len(wl_order) + (1 if overlay else 0)
    fig = Figure(figsize=(2.6 * ncol + 1.0, 2.45 * len(rows) + 0.7), dpi=dpi, layout="constrained")
    FigureCanvasAgg(fig)
    axes = fig.subplots(len(rows), ncol, squeeze=False)
    for r, (factor, chs, fov) in enumerate(rows):
        by_wl = {c.ds.wavelength_nm: c for c in chs}
        ds = chs[0].ds
        for c, wl in enumerate(wl_order):
            ax = axes[r][c]
            ax.set_axis_off()
            ch = by_wl.get(wl)
            if ch is None:
                ax.text(0.5, 0.5, f"no {wl} nm", ha="center", va="center", transform=ax.transAxes, color="0.5")
                continue
            ax.imshow(render_channel(ch, True), interpolation="antialiased")
            _scale_bar(ax, ch.image.shape, ds.pixel_size_um, factor if factor != 1.0 else None, bar_um, suffix=False)
            if r == 0:
                ax.set_title(f"{wl} nm", fontsize=9)
        if overlay:
            ax = axes[r][-1]
            ax.set_axis_off()
            ax.imshow(render_merge(chs, True), interpolation="antialiased")
            _scale_bar(ax, chs[0].image.shape, ds.pixel_size_um, factor if factor != 1.0 else None, bar_um,
                       suffix=False)
            if r == 0:
                ax.set_title("Overlay", fontsize=9)
        fov_um = ds.pixel_size_um * chs[0].image.shape[1] if ds.pixel_size_um else None
        label = f"{factor:g}×  (Set {fov.label})\n{shown_label(chs)}"
        if fov_um:
            label += f"\nfield ≈ {fov_um / factor:.0f} µm\nof original tissue"
        axes[r][0].text(-0.06, 0.5, label, transform=axes[r][0].transAxes, ha="right", va="center", fontsize=8)
    fig.suptitle(textwrap.fill(title, int(fig.get_figwidth() * 10)), fontsize=11, fontweight="bold")
    ds0 = rows[0][1][0].ds
    note = (f"Same objective and camera in every row ({ds0.objective}, {ds0.pixel_size_um:.3g} µm/px). "
                  f"Every scale bar is {format_um(bar_um) if bar_um else '?'} of the original (pre-expansion) "
                  "sample, so it grows with the expansion factor. Each row says which frames it shows: expanded gels "
                  "keep moving during a stack,\nso they are shown as a single frame rather than an average. "
                  "Contrast is set per image, so brightness is not comparable between rows.")
    note = textwrap.fill(note.replace("\n", " "), int(fig.get_figwidth() * 17))
    fig.supxlabel(note, fontsize=6.5, ha="left", x=0.005)
    fig.savefig(path, dpi=dpi, facecolor="white")
    return path
