"""Rough bead density from total light, and the 1x -> 11x comparison.

A blurred bead puts the same light on the camera as an in-focus one, so the
total light in an image, divided by the light of one bead, estimates how many
beads are in view, wherever they are in depth.  Per area:

  1. divide the dark-subtracted mean image by the illumination map;
  2. keep only the trusted region (map >= MIN_ILLUMINATION), the same for every image;
  3. subtract the gel's dark floor (a low percentile of the smoothed region), which removes
     uniform gel glow (and, unavoidably, any uniform haze from very blurred beads);
  4. sum the light, divide by the hydrogel's single-bead light (reference beads,
     corrected the same way) -> beads; divide by the region's area -> beads per mm².

The 1x areas are the base.  Linear expansion by E spreads the same beads over
E² times the area, so the ideal 11x density is base / 121 (per area of gel, seen
through its whole thickness).  If only a fixed in-focus slab counted, it would be
base / 1331, but total light counts every bead in the column.
"""

from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict, dataclass

import numpy as np
from scipy import ndimage as ndi
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from .flatfield import MIN_ILLUMINATION

FLOOR_PERCENTILE = 5
FLOOR_SMOOTH_PX = 4
BOOTSTRAP = 5000
EXCLUDED_BEAD_FLAGS = {"edge", "saturated", "crowded", "faint"}


@dataclass(frozen=True)
class AreaDensity:
    condition: str
    folder: str
    region_mm2: float
    total_light: float  # ADU, corrected, floor removed, summed over the region
    floor_adu: float  # per pixel, corrected units
    total_light_no_floor: float
    beads: float
    density_per_mm2: float
    density_no_floor_per_mm2: float


def area_light(img: np.ndarray, flat: np.ndarray, pixel_um: float) -> dict:
    """Corrected light summed over the trusted region, with and without the gel floor.

    The floor is a low percentile of the corrected image after smoothing: without smoothing, pixel
    noise (amplified where the illumination is dim) drags the percentile below the true glow, and the
    left-over glow is counted as beads - a large error in a sparse image (+50% in tests)."""
    region = flat >= MIN_ILLUMINATION
    full = img / np.maximum(flat, MIN_ILLUMINATION)
    corrected = full[region]
    smooth = ndi.gaussian_filter(full, FLOOR_SMOOTH_PX)[region]
    floor = float(np.percentile(smooth, FLOOR_PERCENTILE))
    return {"region_mm2": float(region.sum()) * (pixel_um / 1000) ** 2,
            "total": float((corrected - floor).sum()), "total_no_floor": float(corrected.sum()), "floor": floor}


def bead_lights(refs: dict, base: np.ndarray, gamma: float, condition_of: dict[str, str]) -> dict[str, np.ndarray]:
    """Corrected single-bead light per condition, from reference_beads.json picks (raw light, position)."""
    out: dict[str, list[float]] = {}
    h, w = base.shape
    for folder, beads in refs.get("areas", {}).items():
        cond = condition_of.get(folder)
        for b in beads:
            if cond is None or "light" not in b or set(b.get("flags", [])) & EXCLUDED_BEAD_FLAGS:
                continue
            il = float(base[int(np.clip(round(b["y"]), 0, h - 1)), int(np.clip(round(b["x"]), 0, w - 1))]) ** gamma
            if il < MIN_ILLUMINATION:
                continue
            out.setdefault(cond, []).append(b["light"] / il)
    return {k: np.asarray(v) for k, v in out.items()}


@dataclass
class Result:
    areas: list[AreaDensity]
    bead_light: dict[str, dict]  # condition -> n, mean, sd
    groups: list[dict]  # per preparation: base, ideal, measured, ratio, implied expansion
    settings: dict


def analyse(images: dict[str, tuple[str, np.ndarray, float]], refs: dict, base: np.ndarray, gamma: float,
            pairs: list[tuple[str, str, str, float]], nominal: float, seed: int = 0,
            expansion_basis: str = "linear",
            gamma_range: tuple[float, float] | None = None, pooled_bead_light: bool = False) -> Result:
    """images: folder -> (condition, image, pixel_um).
    pairs: (preparation label, 1x condition, expanded condition, nominal factor)."""
    condition_of = {f: c for f, (c, _, _) in images.items()}
    flat = (base ** gamma).astype(np.float32)
    lights = bead_lights(refs, base, gamma, condition_of)
    pooled = np.concatenate(list(lights.values())) if lights else np.array([])
    light_for = {c: (pooled if pooled_bead_light or c not in lights or lights[c].size < 2 else lights[c])
                 for c in set(condition_of.values())}

    per_area_light = {f: area_light(img, flat, px) for f, (c, img, px) in images.items()}
    areas = []
    for f, (c, img, px) in images.items():
        a = per_area_light[f]
        L = float(light_for[c].mean())
        beads = a["total"] / L
        areas.append(AreaDensity(c, f, a["region_mm2"], a["total"], a["floor"], a["total_no_floor"], beads,
                                 beads / a["region_mm2"], a["total_no_floor"] / L / a["region_mm2"]))

    rng = np.random.default_rng(seed)

    def dens(cond, area_idx=None, bead_idx=None, which="density_per_mm2"):
        rows = [a for a in areas if a.condition == cond]
        vals = np.array([getattr(a, which) for a in rows])
        if area_idx is not None:
            vals = vals[area_idx]
        if bead_idx is not None:  # re-scale by a resampled single-bead light
            L = light_for[cond]
            vals = vals * L.mean() / L[bead_idx].mean()
        return vals

    groups = []
    for label, c1, cx, factor in pairs:
        d1, dx = dens(c1), dens(cx)
        # Magnify's factor is linear: the same beads spread over factor² the area
        ideal_factor = factor ** 2 if expansion_basis == "linear" else factor
        ratios, base_b, meas_b = [], [], []
        n1, nx = d1.size, dx.size
        for _ in range(BOOTSTRAP):
            b1 = dens(c1, rng.integers(0, n1, n1), rng.integers(0, light_for[c1].size, light_for[c1].size)).mean()
            bx = dens(cx, rng.integers(0, nx, nx), rng.integers(0, light_for[cx].size, light_for[cx].size)).mean()
            ratios.append(b1 / bx)
            base_b.append(b1)
            meas_b.append(bx)
        ratios = np.asarray(ratios)
        ratio = d1.mean() / dx.mean()
        nf1, nfx = dens(c1, which="density_no_floor_per_mm2"), dens(cx, which="density_no_floor_per_mm2")
        groups.append({
            "preparation": label, "base_condition": c1, "expanded_condition": cx, "nominal_factor": factor,
            "base_density": _stats(d1), "ideal_density": _stats(d1 / ideal_factor),
            "measured_density": _stats(dx),
            # inverse of density: gel area per bead (mm²), from each area's own density
            "base_area_per_bead": _stats(1 / d1), "ideal_area_per_bead": _stats(ideal_factor / d1),
            "measured_area_per_bead": _stats(1 / dx),
            "measured_over_ideal": round(float(dx.mean() / (d1.mean() / ideal_factor)), 2),
            "density_drop": round(float(ratio), 2),
            "density_drop_95ci": [round(float(v), 2) for v in np.percentile(ratios, (2.5, 97.5))],
            "ideal_drop": ideal_factor,
            "implied_linear_expansion": round(float(np.sqrt(ratio)), 2),
            "expansion_basis": expansion_basis,
            "implied_linear_expansion_95ci": [round(float(np.sqrt(v)), 2) for v in np.percentile(ratios, (2.5, 97.5))],
            "implied_linear_expansion_no_floor": round(float(np.sqrt(nf1.mean() / nfx.mean())), 2),
            "base_density_95ci": [round(float(v), 1) for v in np.percentile(base_b, (2.5, 97.5))],
            "measured_density_95ci": [round(float(v), 2) for v in np.percentile(meas_b, (2.5, 97.5))],
        })
    bead_light = {c: {"n": int(v.size), "mean": float(v.mean()), "sd": float(v.std(ddof=1)) if v.size > 1 else None,
                      "source": "pooled (all hydrogels)" if v is pooled else "this hydrogel"}
                  for c, v in light_for.items()}
    settings = {"gamma": gamma, "min_illumination": MIN_ILLUMINATION, "floor_percentile": FLOOR_PERCENTILE,
                "bootstrap": BOOTSTRAP, "pooled_bead_light": pooled_bead_light, "nominal_expansion": nominal,
                "expansion_basis": expansion_basis}
    if gamma_range:
        settings["gamma_range"] = list(gamma_range)
    return Result(areas, bead_light, groups, settings)


def _stats(v: np.ndarray) -> dict:
    return {"mean": float(v.mean()), "sd": float(v.std(ddof=1)) if v.size > 1 else 0.0,
            "min": float(v.min()), "max": float(v.max()), "values": [float(x) for x in v]}


def write_outputs(res: Result, out_dir: str, labels: dict[str, str], title: str, sensitivity: dict | None = None) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "density_areas.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["condition", "area", "region_mm2", "floor_adu_per_px", "total_light_adu", "beads",
                    "beads_per_mm2", "beads_per_mm2_without_floor"])
        for a in res.areas:
            w.writerow([a.condition, a.folder, f"{a.region_mm2:.4f}", f"{a.floor_adu:.2f}", f"{a.total_light:.0f}",
                        f"{a.beads:.1f}", f"{a.density_per_mm2:.2f}", f"{a.density_no_floor_per_mm2:.2f}"])
    js_path = os.path.join(out_dir, "density_summary.json")
    with open(js_path, "w", encoding="utf-8") as f:
        json.dump({"settings": res.settings, "bead_light": res.bead_light, "groups": res.groups,
                   "areas": [asdict(a) for a in res.areas], "sensitivity": sensitivity or {}}, f, indent=2,
                  ensure_ascii=False)
    return [csv_path, js_path, plot_candles(res, os.path.join(out_dir, "density_candles.png"), labels, title),
            plot_comparison(res, os.path.join(out_dir, "density_comparison.png"), title),
            plot_expansion_vs_ideal(res, os.path.join(out_dir, "expansion_vs_ideal.png"), title),
            plot_area_per_bead(res, os.path.join(out_dir, "area_per_bead_candles.png"), title),
            plot_expansion(res, os.path.join(out_dir, "implied_expansion.png"), title, sensitivity)]


GRAY, BLUE, INK, MUTED = "#6b7280", "#2563eb", "#1f2937", "#9ca3af"


CANDLE_NOTE = ("Candle: line = min–max of the 3 areas, box = mean ± SD, thick tick = mean, dots = areas.\n"
               "Ideal = 1× ÷ (expansion)² because the same beads spread over (expansion)² the area.")


def _candle(ax, x: float, s: dict, kind: str, colour: str, width: float = 0.42, label: str | None = None,
            fmt=None):
    """One candle on a linear axis: min-max line, mean ± SD box, mean tick, area dots (not for ideal)."""
    ideal = kind == "ideal"
    lo, hi = max(s["mean"] - s["sd"], s["min"]), min(s["mean"] + s["sd"], s["max"])
    ax.vlines(x, s["min"], s["max"], color=colour, lw=1.5)
    ax.bar(x, max(hi - lo, 1e-9), bottom=lo, width=width, color="white" if ideal else colour,
           edgecolor=colour, lw=1.5, ls="--" if ideal else "-", alpha=1 if ideal else 0.85, label=label)
    ax.hlines(s["mean"], x - width * 0.62, x + width * 0.62, color=colour if ideal else INK, lw=2.5)
    if not ideal:
        ax.plot([x] * len(s["values"]), s["values"], "o", ms=6, color="white", mec=INK, mew=1.2, zorder=4)
    ax.annotate((fmt or _fmt)(s["mean"]), (x + width * 0.7, s["mean"]), va="bottom", fontsize=9, color=INK)


def _columns(g: dict):
    f = g["nominal_factor"]
    return [("1× measured\n(base)", g["base_density"], "solid", GRAY),
            (f"{f:g}× ideal\n(base ÷ {g['ideal_drop']:g})", g["ideal_density"], "ideal", BLUE),
            (f"~{f:g}× measured", g["measured_density"], "solid", BLUE)]


def _subtitle(g: dict) -> str:
    lo, hi = g["implied_linear_expansion_95ci"]
    return (f"~{g['nominal_factor']:g}× measured is {g['measured_over_ideal']:.0f}× the ideal · "
            f"implied expansion ≈ {g['implied_linear_expansion']:.1f}× ({lo:.1f}–{hi:.1f})")


def _style(ax):
    ax.set_ylim(bottom=0)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.15)


def plot_candles(res: Result, path: str, labels: dict[str, str], title: str) -> str:
    """Per preparation (own linear y-axis): 1x measured (base), ideal 11x (base / 121), 11x measured."""
    n = len(res.groups)
    fig = Figure(figsize=(5.4 * n + 0.6, 5.6), layout="constrained")
    axes = fig.subplots(1, n, squeeze=False)[0]
    for ax, g in zip(axes, res.groups):
        cols = _columns(g)
        for x, (_, s, kind, colour) in enumerate(cols):
            _candle(ax, x, s, kind, colour)
        ax.set_xticks(range(3), [c[0] for c in cols])
        ax.set_xlim(-0.6, 2.8)
        ax.set_title(f"{g['preparation']}\n{_subtitle(g)}", fontsize=10)
        ax.set_ylabel("beads per mm² of gel (seen through its thickness)")
        _style(ax)
    fig.suptitle(f"Bead density from total light · {title} (each panel has its own scale)", fontsize=12)
    fig.supxlabel(CANDLE_NOTE, fontsize=8, x=0.01, ha="left")
    FigureCanvasAgg(fig)
    fig.savefig(path, dpi=170, facecolor="white")
    return path


def plot_comparison(res: Result, path: str, title: str) -> str:
    """Both preparations on one linear axis: 1x measured, ideal 11x and ~11x measured side by side."""
    fig = Figure(figsize=(9, 5.8), layout="constrained")
    ax = fig.subplots()
    offsets, width = (-0.27, 0.0, 0.27), 0.22
    names = []
    for gx, g in enumerate(res.groups):
        cols = _columns(g)
        for k, (name, s, kind, colour) in enumerate(cols):
            _candle(ax, gx + offsets[k], s, kind, colour, width, label=name.replace("\n", " ") if gx == 0 else None)
        names.append(f"{g['preparation']}\n{_subtitle(g).replace(' · ', chr(10))}")
    ax.set_xticks(range(len(res.groups)), names, fontsize=9)
    ax.set_xlim(-0.6, len(res.groups) - 0.25)
    ax.set_ylabel("beads per mm² of gel (seen through its thickness)")
    ax.legend(frameon=False, loc="upper left")
    _style(ax)
    ax.set_title(f"1× vs ideal 11× vs measured ~11× · {title}", fontsize=12)
    fig.supxlabel(CANDLE_NOTE, fontsize=8, x=0.01, ha="left")
    FigureCanvasAgg(fig)
    fig.savefig(path, dpi=170, facecolor="white")
    return path


SERIES = ("#2563eb", "#d97706")  # homogenized, non-homogenized: fixed order, same in every plot


def plot_area_per_bead(res: Result, path: str, title: str) -> str:
    """Inverse of density (gel area per bead) per preparation, own linear axis: 1x, ideal 11x, ~11x.
    Linear expansion by E should make each bead's share of gel E² times larger."""
    n = len(res.groups)
    fig = Figure(figsize=(5.4 * n + 0.6, 5.8), layout="constrained")
    axes = fig.subplots(1, n, squeeze=False)[0]
    for ax, g in zip(axes, res.groups):
        f, drop = g["nominal_factor"], g["ideal_drop"]
        cols = [("1× measured\n(base)", g["base_area_per_bead"], "solid", GRAY),
                (f"{f:g}× ideal\n(base × {drop:g})", g["ideal_area_per_bead"], "ideal", BLUE),
                (f"~{f:g}× measured", g["measured_area_per_bead"], "solid", BLUE)]
        for x, (_, st, kind, colour) in enumerate(cols):
            _candle(ax, x, st, kind, colour, fmt=_fmt_area)
        ax.set_xticks(range(3), [c[0] for c in cols])
        ax.set_xlim(-0.6, 2.8)
        share = g["measured_area_per_bead"]["mean"] / g["ideal_area_per_bead"]["mean"]
        lo, hi = g["implied_linear_expansion_95ci"]
        ax.set_title(f"{g['preparation']}\n~{f:g}× measured: {share:.1%} of the ideal area per bead\n"
                     f"implied expansion ≈ {g['implied_linear_expansion']:.1f}× (95%: {lo:.1f}–{hi:.1f})", fontsize=10)
        ax.set_ylabel("gel area per bead (mm²)")
        _style(ax)
    fig.suptitle(f"Gel area per bead (inverse of density) · {title} (each panel has its own scale)", fontsize=12)
    fig.supxlabel("Candle: line = min–max of the 3 areas, box = mean ± SD, thick tick = mean, dots = areas.\n"
                  "Ideal = 1× × (expansion)²: linear expansion gives each bead (expansion)² times more gel area.",
                  fontsize=8, x=0.01, ha="left")
    FigureCanvasAgg(fig)
    fig.savefig(path, dpi=170, facecolor="white")
    return path


def _fmt_area(v: float) -> str:
    return f"{v:.2f}" if v >= 0.1 else f"{v:.3f}"


def plot_expansion_vs_ideal(res: Result, path: str, title: str) -> str:
    """Expansion on the vertical axis: each hydrogel from 1 (the 1x gel, by definition) to its measured
    expansion at ~11x, against the ideal line from 1 to the kit's nominal factor."""
    fig = Figure(figsize=(7.2, 5.6), layout="constrained")
    ax = fig.subplots()
    nominal = res.groups[0]["nominal_factor"] if res.groups else 11
    ax.plot([0, 1], [1, nominal], "--", color=GRAY, lw=2, label=f"ideal (kit's nominal {nominal:g}×)")
    ax.annotate(f"{nominal:g}× ideal", (1.06, nominal), va="center", fontsize=10, color=GRAY)
    dx = (-0.03, 0.03)
    for k, g in enumerate(res.groups):
        colour = SERIES[k % len(SERIES)]
        e, (lo, hi) = g["implied_linear_expansion"], g["implied_linear_expansion_95ci"]
        x1 = 1 + dx[k % 2]
        ax.plot([0, x1], [1, e], "-", color=colour, lw=2, label=f"{g['preparation']} (measured)")
        ax.vlines(x1, lo, hi, color=colour, lw=2)
        ax.hlines([lo, hi], x1 - 0.015, x1 + 0.015, color=colour, lw=2)
        ax.plot([0, x1], [1, e], "o", ms=8, color=colour, mec="white", mew=1.5, zorder=3)
        ax.annotate(f"{g['preparation']}: {e:.1f}× (95%: {lo:.1f}–{hi:.1f})", (1.06, e), va="center",
                    fontsize=10, color=INK)
    ax.set_xticks([0, 1], ["1× gel\n(reference)", f"~{nominal:g}× gel"])
    ax.set_xlim(-0.15, 1.75)
    ax.set_ylim(0, nominal * 1.12)
    ax.set_ylabel("linear expansion (×)")
    ax.set_title(f"Measured vs ideal expansion · {title}", fontsize=11)
    ax.legend(frameon=False, loc="upper left")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.15)
    fig.supxlabel("Measured expansion = √(1× bead density ÷ ~11× bead density). The 1× gel is the reference, "
                  "so it is 1 by definition.\nError bars: 95% interval from resampling areas and reference beads.",
                  fontsize=8, x=0.01, ha="left")
    FigureCanvasAgg(fig)
    fig.savefig(path, dpi=170, facecolor="white")
    return path


def plot_expansion(res: Result, path: str, title: str, sensitivity: dict | None = None) -> str:
    fig = Figure(figsize=(6.4, 4.6), layout="constrained")
    ax = fig.subplots()
    nominal = res.groups[0]["nominal_factor"] if res.groups else 11
    for x, g in enumerate(res.groups):
        e, (lo, hi) = g["implied_linear_expansion"], g["implied_linear_expansion_95ci"]
        ax.vlines(x, lo, hi, color=BLUE, lw=2)
        ax.plot(x, e, "o", ms=9, color=BLUE, mec="white", mew=1.5, zorder=3)
        ax.annotate(f"{e:.1f}×  (95%: {lo:.1f}–{hi:.1f})", (x + 0.08, e), va="center", fontsize=9, color=INK)
        if sensitivity and g["preparation"] in sensitivity:
            s = sensitivity[g["preparation"]]
            ax.plot([x - 0.12] * 2, [min(s.values()), max(s.values())], color=MUTED, lw=4, alpha=0.6,
                    solid_capstyle="butt")
    ax.axhline(nominal, color=GRAY, ls="--", lw=1.2)
    ax.annotate(f"kit's nominal {nominal:g}×", (len(res.groups) - 0.5, nominal), va="bottom", ha="right",
                fontsize=9, color=GRAY)
    ax.axhline(1, color=MUTED, ls=":", lw=1)
    ax.set_xticks(range(len(res.groups)), [g["preparation"] for g in res.groups])
    ax.set_xlim(-0.5, len(res.groups) - 0.2)
    ax.set_ylim(0, max(nominal * 1.15, max(g["implied_linear_expansion_95ci"][1] for g in res.groups) * 1.1))
    ax.set_ylabel("linear expansion implied by the density drop (×)")
    ax.set_title(f"Implied expansion = √(1× density ÷ ~11× density)\n{title}", fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.15)
    note = "Blue line: 95% interval from resampling areas and reference beads."
    if sensitivity:
        note += "\nGrey bar: range over the gamma interval and with one pooled single-bead light."
    fig.supxlabel(note, fontsize=8, x=0.01, ha="left")
    FigureCanvasAgg(fig)
    fig.savefig(path, dpi=170, facecolor="white")
    return path


def _fmt(v: float) -> str:
    return f"{v:,.0f}" if v >= 10 else f"{v:.2g}"
