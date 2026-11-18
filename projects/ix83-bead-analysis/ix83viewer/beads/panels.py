"""Image panels for a bead-in-gel experiment.

For each hydrogel, one row with every area; a 2x2 comparison of the four
hydrogels; and a grid of every area.  Every image is the mean of its stack
minus the master dark frame, without clipping, so the saved TIFFs keep the
values the density analysis needs.  Display contrast is linear and set from
percentiles; it never changes the saved values.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import numpy as np
import tifffile
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

from ..core.corrections import build_dark_frame
from ..core.display import format_um
from ..core.projection import project
from ..io.mm_dataset import MMDataset
from .experiment import Condition, Experiment

LEVEL_PERCENTILES = (0.5, 99.8)
SCALE_BAR_UM = 200.0  # in the gel, as imaged
CMAP = "viridis"  # perceptually uniform: equal steps in ADU look like equal steps in colour
SATURATION_ADU = 65535
PANEL_INCHES = 5.0
DPI = 283  # 5 in x 283 dpi = 1415 px: each panel at about the camera's 1412 px


@dataclass
class AreaImage:
    condition: Condition
    ds: MMDataset
    image: np.ndarray  # float32, mean of all frames minus dark, not clipped
    saturated_px: int  # pixels that reached the camera maximum in at least one frame
    saturated_mask: np.ndarray | None = None

    @property
    def folder(self) -> str:
        return self.ds.label

    @property
    def short_label(self) -> str:
        return f"Area {self.ds.name.rep}"


def load_area_images(exp: Experiment, check_saturation: bool = True) -> dict[str, list[AreaImage]]:
    dark = build_dark_frame(MMDataset.open(exp.path(exp.dark_folder)))
    out: dict[str, list[AreaImage]] = {}
    for c in exp.conditions:
        out[c.key] = []
        for folder in c.areas:
            ds = MMDataset.open(exp.path(folder))
            img = project(ds, "mean") - dark
            mask = project(ds, "max") >= SATURATION_ADU if check_saturation else None
            sat = int(np.count_nonzero(mask)) if mask is not None else 0
            out[c.key].append(AreaImage(c, ds, img.astype(np.float32), sat, mask))
    return out


def levels_for(images: list[np.ndarray], pct=LEVEL_PERCENTILES) -> tuple[float, float]:
    """Linear display range shared by `images`: percentiles of all their pixels."""
    flat = np.concatenate([im[::4, ::4].ravel() for im in images])
    lo, hi = np.percentile(flat, pct)
    return float(lo), float(max(hi, lo + 1))


def representative(areas: list[AreaImage]) -> AreaImage:
    """The area whose mean brightness is the median of its hydrogel's areas (not hand-picked)."""
    order = sorted(areas, key=lambda a: float(a.image.mean()))
    return order[(len(order) - 1) // 2]


def _expansion_note(c: Condition, exp: Experiment) -> str:
    if c.factor <= 1:
        return ""
    return f" ≈ {SCALE_BAR_UM / c.factor:.0f} µm before {c.factor:g}× (nominal)"


def draw_area(ax, a: AreaImage, levels, exp: Experiment, title: str, colorbar_fig=None):
    img = a.image
    im = ax.imshow(img, cmap=CMAP, vmin=levels[0], vmax=levels[1], interpolation="nearest")
    ax.set_xticks([]), ax.set_yticks([])
    ax.set_title(title, fontsize=10)
    h, w = img.shape
    px = a.ds.pixel_size_um
    bar = SCALE_BAR_UM / px
    ax.add_patch(Rectangle((w * 0.96 - bar, h * 0.94), bar, h * 0.012, color="white"))
    ax.text(w * 0.96, h * 0.92, format_um(SCALE_BAR_UM) + " in gel" + _expansion_note(a.condition, exp),
            color="white", ha="right", va="bottom", fontsize=7)
    if a.saturated_px:
        ax.text(w * 0.03, h * 0.04, f"{a.saturated_px} px saturated", color="#ffb000", fontsize=7, va="top")
    if colorbar_fig is not None:
        cb = colorbar_fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02)
        cb.set_label("ADU above dark", fontsize=7)
        cb.ax.tick_params(labelsize=7)
    return im


def _footer(exp: Experiment, a: AreaImage, levels_note: str) -> str:
    d = a.ds
    fov = d.pixel_size_um * d.shape_yx[1]
    return (f"Olympus IX83 · {d.objective} · {d.pixel_size_um:.3g} µm/px, field {fov:.0f} µm of gel · "
            f"{exp.wavelength_nm} nm at {exp.laser_power_mw:g} mW · {exp.bead} beads\n"
            f"Each image: mean of {d.n_frames} frames × {d.exposure_ms:g} ms, minus the median dark frame "
            f"({exp.dark_folder}) · camera despeckle/denoise on\n"
            f"{CMAP.capitalize()} colour scale, linear · {levels_note}")


def _save(fig: Figure, path: str) -> str:
    FigureCanvasAgg(fig)
    fig.savefig(path, dpi=DPI, facecolor="white")
    return path


def condition_row(exp: Experiment, areas: list[AreaImage], path: str) -> str:
    """One hydrogel: its areas side by side on one shared intensity scale."""
    levels = levels_for([a.image for a in areas])
    n = len(areas)
    fig = Figure(layout="constrained", figsize=(PANEL_INCHES * n + 0.9, PANEL_INCHES + 1.3))
    axes = fig.subplots(1, n, squeeze=False)[0]
    im = None
    for ax, a in zip(axes, areas):
        im = draw_area(ax, a, levels, exp, f"{a.short_label} ({a.folder})")
    cb = fig.colorbar(im, ax=list(axes), fraction=0.015, pad=0.01)
    cb.set_label("ADU above dark", fontsize=8)
    fig.suptitle(areas[0].condition.label, fontsize=13)
    fig.supxlabel(_footer(exp, areas[0], f"one intensity scale for the row, "
                                               f"{levels[0]:.0f}–{levels[1]:.0f} ADU"), x=0.01, ha="left", fontsize=7)
    return _save(fig, path)


def comparison_2x2(exp: Experiment, by_key: dict[str, list[AreaImage]], path: str, shared: bool) -> str:
    """Homogenized / non-homogenized (rows) by 1x / 11x (columns), one representative area each."""
    order = _grid_order(exp)
    picks = {k: representative(by_key[k]) for row in order for k in row if k}
    levels = levels_for([a.image for a in picks.values()]) if shared else None
    nrow, ncol = len(order), len(order[0])
    fig = Figure(layout="constrained", figsize=(ncol * PANEL_INCHES + (0.9 if shared else 1.4), nrow * PANEL_INCHES + 1.6))
    axes = fig.subplots(nrow, ncol, squeeze=False)
    im = None
    for r, row in enumerate(order):
        for col, key in enumerate(row):
            ax = axes[r, col]
            if not key:
                ax.axis("off")
                continue
            a = picks[key]
            lv = levels or levels_for([a.image])
            im = draw_area(ax, a, lv, exp, f"{a.condition.label} · {a.short_label}",
                           colorbar_fig=None if shared else fig)
    if shared:
        cb = fig.colorbar(im, ax=list(axes.ravel()), fraction=0.02, pad=0.01)
        cb.set_label("ADU above dark", fontsize=8)
        note = f"one intensity scale for all four, {levels[0]:.0f}–{levels[1]:.0f} ADU, so brightness compares"
    else:
        note = "each panel on its own intensity scale (see its colour bar), so brightness does not compare"
    fig.suptitle("Magnify kit bead gels: homogenized vs non-homogenized, 1× vs ~11×", fontsize=13)
    first = next(iter(picks.values()))
    fig.supxlabel(_footer(exp, first, note) +
             "\nEach panel is the area whose mean brightness is the middle of its hydrogel's three.",
             x=0.01, ha="left", fontsize=7)
    return _save(fig, path)


def all_areas_grid(exp: Experiment, by_key: dict[str, list[AreaImage]], path: str) -> str:
    """Every area: one row per hydrogel, each row on its own intensity scale."""
    keys = [c.key for c in exp.conditions]
    ncol = max(len(by_key[k]) for k in keys)
    fig = Figure(layout="constrained", figsize=(PANEL_INCHES * 0.7 * ncol + 1.2, PANEL_INCHES * 0.7 * len(keys) + 1.4))
    axes = fig.subplots(len(keys), ncol, squeeze=False)
    for r, k in enumerate(keys):
        areas = by_key[k]
        levels = levels_for([a.image for a in areas])
        im = None
        for col in range(ncol):
            ax = axes[r, col]
            if col >= len(areas):
                ax.axis("off")
                continue
            im = draw_area(ax, areas[col], levels, exp, f"{areas[col].condition.label} · {areas[col].short_label}")
        cb = fig.colorbar(im, ax=list(axes[r]), fraction=0.02, pad=0.01)
        cb.ax.tick_params(labelsize=6)
    fig.suptitle("Every imaged area (one intensity scale per row)", fontsize=12)
    fig.supxlabel(_footer(exp, by_key[keys[0]][0], "levels shared within each row"), x=0.01, ha="left", fontsize=6)
    return _save(fig, path)


def _grid_order(exp: Experiment) -> list[list[str | None]]:
    """Rows by preparation (homogenized first), columns by factor (1x first)."""
    preps = sorted({c.preparation for c in exp.conditions}, key=lambda p: (p != "Homogenized", p))
    factors = sorted({c.factor for c in exp.conditions})
    lookup = {(c.preparation, c.factor): c.key for c in exp.conditions}
    return [[lookup.get((p, f)) for f in factors] for p in preps]


def export_panels(exp: Experiment, out_dir: str, check_saturation: bool = True) -> list[str]:
    os.makedirs(os.path.join(out_dir, "images"), exist_ok=True)
    by_key = load_area_images(exp, check_saturation)
    written = []
    record = {"experiment": exp.name, "levels_percentiles": LEVEL_PERCENTILES,
              "image": "mean of all frames minus median dark frame, float32, not clipped", "areas": []}
    for k, areas in by_key.items():
        for a in areas:
            tif = os.path.join(out_dir, "images", f"{a.folder}.tif")
            tifffile.imwrite(tif, a.image, imagej=True, resolution=(1 / a.ds.pixel_size_um,) * 2,
                             metadata={"unit": "um"})
            written.append(tif)
            record["areas"].append({
                "condition": k, "folder": a.folder, "frames": a.ds.n_frames, "exposure_ms": a.ds.exposure_ms,
                "mean_adu": round(float(a.image.mean()), 3),
                "percentiles_adu": dict(zip(("p0.5", "p50", "p99.8"),
                                            [round(float(v), 2) for v in np.percentile(a.image, (0.5, 50, 99.8))])),
                "saturated_px": a.saturated_px, "tif": os.path.relpath(tif, out_dir)})
        written.append(condition_row(exp, areas, os.path.join(out_dir, f"row_{k}.png")))
    written.append(comparison_2x2(exp, by_key, os.path.join(out_dir, "comparison_2x2_shared.png"), shared=True))
    written.append(comparison_2x2(exp, by_key, os.path.join(out_dir, "comparison_2x2_own.png"), shared=False))
    written.append(all_areas_grid(exp, by_key, os.path.join(out_dir, "all_areas.png")))
    record["comparison_2x2_areas"] = {k: representative(v).folder for k, v in by_key.items()}
    record["files"] = [os.path.relpath(p, out_dir) for p in written]
    path = os.path.join(out_dir, "panels.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    return written + [path]
