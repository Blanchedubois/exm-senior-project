"""Illumination (flat-field) map estimated from the images themselves, and a bead check of it.

The 10x field is lit unevenly: the corners get about a tenth of the centre's
light.  Every area's background glow (gel and out-of-focus haze, with beads and
blur discs removed by a rolling low percentile) is lit by the same light, so
the median of those backgrounds across all areas gives the shape of the
illumination; it is smoothed and scaled so its peak is 1.

The glow is mostly out-of-focus light, spread sideways, so it falls off more
gently than the light an in-focus bead receives (4 Nov: beads followed the
glow map to the power ~1.6).  When reference beads exist, that power (gamma)
is fitted from them and the map becomes glow_map ** gamma.  Dividing an image
by the map makes every position look as if it were lit like the centre.

This is a rough correction: areas differ in gel glow, so the per-area curves
scatter about the median.  A uniform fluorescent slide would give a real flat field.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import numpy as np
import tifffile
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from scipy import ndimage as ndi

DOWNSAMPLE = 4
BACKGROUND_PERCENTILE = 20
BACKGROUND_WINDOW = 31  # downsampled px (124 camera px): wider than any blur disc
SMOOTH_SIGMA = 12  # downsampled px (48 camera px): removes leftover bead lumps, keeps the shape
BOOTSTRAP = 2000
MIN_ILLUMINATION = 0.2  # below this the correction multiplies noise by 5x or more; don't trust it
PROFILE_RADII = (0, 200, 400, 600, 800, 950)


@dataclass
class FlatField:
    base: np.ndarray  # glow map at full resolution, float32, peak 1
    measured: np.ndarray  # downsampled median background, peak-normalised
    per_area: dict[str, np.ndarray]  # downsampled background of each area
    centre_xy: tuple[float, float]
    fit_rms: float  # rms of (measured - smoothed map) where lit
    gamma: float = 1.0  # power fitted from reference beads; 1 = the glow map as measured
    gamma_ci: tuple[float, float] | None = None
    gamma_beads: int = 0

    @property
    def flat(self) -> np.ndarray:
        return self.base if self.gamma == 1.0 else (self.base ** self.gamma).astype(np.float32)

    def with_gamma(self, gamma: float, ci=None, n_beads: int = 0) -> "FlatField":
        return FlatField(self.base, self.measured, self.per_area, self.centre_xy, self.fit_rms, gamma, ci, n_beads)

    def base_at(self, x: float, y: float) -> float:
        h, w = self.base.shape
        return float(self.base[int(np.clip(round(y), 0, h - 1)), int(np.clip(round(x), 0, w - 1))])

    def at(self, x: float, y: float) -> float:
        return self.base_at(x, y) ** self.gamma

    def correct(self, img: np.ndarray) -> np.ndarray:
        return img / np.maximum(self.flat, MIN_ILLUMINATION)

    def usable(self) -> np.ndarray:
        return self.flat >= MIN_ILLUMINATION

    def radial(self, radii=PROFILE_RADII) -> list[dict]:
        h, w = self.flat.shape
        yy, xx = np.indices((h, w))
        r = np.hypot(xx - self.centre_xy[0], yy - self.centre_xy[1])
        out = []
        for R in radii:
            ring = (r >= R - 25) & (r < R + 25)
            if ring.any():
                out.append({"radius_px": R, "illumination": round(float(self.flat[ring].mean()), 3)})
        return out


def background(img: np.ndarray, factor: int = DOWNSAMPLE) -> np.ndarray:
    """Smooth background glow of one image, downsampled by `factor`, with beads and discs removed."""
    h, w = (s // factor * factor for s in img.shape)
    small = img[:h, :w].reshape(h // factor, factor, w // factor, factor).mean(axis=(1, 3))
    bg = ndi.percentile_filter(small, BACKGROUND_PERCENTILE, size=BACKGROUND_WINDOW)
    return ndi.gaussian_filter(bg, 8)


def estimate(images: dict[str, np.ndarray]) -> FlatField:
    """images: area name -> dark-subtracted mean image (all the same shape)."""
    per_area = {}
    for name, img in images.items():
        bg = background(img)
        per_area[name] = bg / np.percentile(bg, 99)
    measured = np.median(np.stack(list(per_area.values())), axis=0)
    measured = measured / measured.max()
    smooth = ndi.gaussian_filter(measured, SMOOTH_SIGMA, mode="nearest")
    full_shape = next(iter(images.values())).shape
    zoom = (full_shape[0] / measured.shape[0], full_shape[1] / measured.shape[1])
    base = ndi.zoom(smooth, zoom, order=1, mode="nearest")[: full_shape[0], : full_shape[1]]
    peak = float(base.max())
    base = (base / peak).astype(np.float32)
    cy, cx = np.unravel_index(np.argmax(base), base.shape)
    resid = (measured - smooth / peak)[measured > MIN_ILLUMINATION]
    return FlatField(base, measured, per_area, (float(cx), float(cy)), float(np.sqrt(np.mean(resid ** 2))))


def fit_gamma(beads: list[dict], seed: int = 0) -> tuple[float, tuple[float, float], int]:
    """Power linking bead light to the glow map: log(light) = gamma * log(base) + one offset per hydrogel.

    beads: dicts with condition, base_illumination and light (raw).  Returns gamma, a 95% bootstrap
    interval (resampling beads) and the number of beads used."""
    rows = [b for b in beads if b.get("base_illumination", 0) > 0 and b.get("light", 0) > 0 and b.get("condition")]
    if len(rows) < 6:
        return 1.0, None, len(rows)
    conds = sorted({b["condition"] for b in rows})
    x = np.log([b["base_illumination"] for b in rows])
    y = np.log([b["light"] for b in rows])
    c = np.array([conds.index(b["condition"]) for b in rows])

    def solve(idx):
        A = np.column_stack([x[idx]] + [(c[idx] == k).astype(float) for k in range(len(conds))])
        keep = A[:, 1:].any(axis=0)
        A = np.column_stack([A[:, 0], A[:, 1:][:, keep]])
        return np.linalg.lstsq(A, y[idx], rcond=None)[0][0]

    g = float(solve(np.arange(len(rows))))
    rng = np.random.default_rng(seed)
    boots = [solve(rng.integers(0, len(rows), len(rows))) for _ in range(BOOTSTRAP)]
    lo, hi = np.percentile(boots, (2.5, 97.5))
    return g, (round(float(lo), 3), round(float(hi), 3)), len(rows)


def load(path_tif: str) -> np.ndarray:
    return tifffile.imread(path_tif).astype(np.float32)


def save(ff: FlatField, out_dir: str, label: str = "") -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    tif = os.path.join(out_dir, "flat.tif")
    tifffile.imwrite(tif, ff.flat)
    tifffile.imwrite(os.path.join(out_dir, "glow_map.tif"), ff.base)
    info = {
        "method": "median over areas of the background glow (rolling 20th percentile, beads removed), "
                  f"smoothed (sigma {SMOOTH_SIGMA * DOWNSAMPLE} px), peak = 1; flat.tif = glow map ** gamma",
        "gamma": round(ff.gamma, 3),
        "gamma_95ci": ff.gamma_ci,
        "gamma_from_beads": ff.gamma_beads,
        "areas": list(ff.per_area),
        "brightest_point_px": [round(v, 1) for v in ff.centre_xy],
        "fit_rms": round(ff.fit_rms, 4),
        "min_illumination_trusted": MIN_ILLUMINATION,
        "usable_fraction_of_field": round(float(ff.usable().mean()), 3),
        "mean_illumination": round(float(ff.flat.mean()), 3),
        "radial_profile": ff.radial(),
    }
    js = os.path.join(out_dir, "flat.json")
    with open(js, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)
    return [tif, os.path.join(out_dir, "glow_map.tif"), js, plot_map(ff, os.path.join(out_dir, "flat.png"), label)]


def plot_map(ff: FlatField, path: str, label: str = "") -> str:
    fig = Figure(figsize=(12, 5), layout="constrained")
    ax_map, ax_r = fig.subplots(1, 2, gridspec_kw={"width_ratios": [1, 1.25]})
    h, w = ff.flat.shape
    im = ax_map.imshow(ff.flat, cmap="viridis", vmin=0, vmax=1, extent=(0, w, h, 0))
    cs = ax_map.contour(ff.flat, levels=[MIN_ILLUMINATION, 0.5, 0.8], colors="white", linewidths=1,
                        extent=(0, w, 0, h), origin="upper")
    ax_map.clabel(cs, fmt="%.1f", fontsize=8)
    ax_map.plot(*ff.centre_xy, "+", color="white", ms=10, mew=1.5)
    cb = fig.colorbar(im, ax=ax_map, fraction=0.046)
    cb.set_label("illumination (peak = 1)")
    ax_map.set_title("Illumination map" + (f" (glow map ^ {ff.gamma:.2f}, from beads)" if ff.gamma != 1 else ""))
    ax_map.set_xlabel("x (px)")
    ax_map.set_ylabel("y (px)")

    ds = h / ff.measured.shape[0]
    yy, xx = np.indices(ff.measured.shape)
    r = np.hypot(xx * ds - ff.centre_xy[0], yy * ds - ff.centre_xy[1]).ravel()
    step = 5
    for i, bg in enumerate(ff.per_area.values()):
        ax_r.plot(r[::step], bg.ravel()[::step], ".", ms=1.2, color="#9ca3af", alpha=0.35,
                  label="each area's background" if i == 0 else None, rasterized=True)
    order = np.argsort(r)
    ax_r.plot(r[order][::step], ff.measured.ravel()[order][::step], ".", ms=1.5, color="#374151",
              label="median of the 12 areas", rasterized=True)
    base_small = ff.base[:: int(ds), :: int(ds)][: ff.measured.shape[0], : ff.measured.shape[1]]
    ax_r.plot(r[order][::step], base_small.ravel()[order][::step], ".", ms=1.5, color="#2563eb",
              label="glow map (smoothed median)", rasterized=True)
    if ff.gamma != 1:
        ax_r.plot(r[order][::step], (base_small ** ff.gamma).ravel()[order][::step], ".", ms=1.5,
                  color="#d97706", label=f"map used: glow ^ {ff.gamma:.2f} (bead-calibrated)", rasterized=True)
    ax_r.axhline(MIN_ILLUMINATION, color="#6b7280", lw=1, ls="--")
    ax_r.text(r.max(), MIN_ILLUMINATION + 0.02, f"below {MIN_ILLUMINATION:g}: not trusted", ha="right",
              fontsize=8, color="#4b5563")
    ax_r.set_xlabel("distance from the brightest point (px)")
    ax_r.set_ylabel("relative illumination")
    ax_r.set_ylim(0, 1.25)
    ax_r.set_title("Fall-off with distance")
    ax_r.legend(loc="upper right", frameon=False, markerscale=6)
    for a in (ax_r,):
        a.spines[["top", "right"]].set_visible(False)
        a.grid(alpha=0.2)
    fig.suptitle(f"Illumination estimated from the background glow{(' · ' + label) if label else ''}")
    FigureCanvasAgg(fig)
    fig.savefig(path, dpi=150, facecolor="white")
    return path


def bead_check(beads: list[dict], gamma: float, path: str, label: str = "") -> dict:
    """Do reference beads get equally bright once corrected?

    beads: dicts with condition, base_illumination and light (raw).  Light is divided by its
    hydrogel's mean so hydrogels can share one plot.  Shown raw, divided by the glow map, and
    divided by the bead-calibrated map (glow ** gamma).  A good map leaves no trend.  With gamma
    fitted from these same beads the last panel is flat by construction: it is not an independent test."""
    rows = [b for b in beads if b.get("base_illumination") and b.get("light") and b.get("condition")]
    if len(rows) < 4:
        return {"n_beads": len(rows), "note": "too few reference beads for a check"}
    illum = np.array([b["base_illumination"] for b in rows])
    light = np.array([b["light"] for b in rows])
    cond = np.array([b["condition"] for b in rows])

    def normed(v):
        return np.array([v[i] / v[cond == cond[i]].mean() for i in range(v.size)])

    versions = [("Raw", normed(light), illum),
                ("÷ glow map", normed(light / illum), illum),
                (f"÷ glow map ^ {gamma:.2f}", normed(light / illum ** gamma), illum)]
    result = {"n_beads": int(illum.size), "gamma": round(gamma, 3), "versions": {}}
    fig = Figure(figsize=(15, 4.6), layout="constrained")
    axes = fig.subplots(1, 3, sharey=True)
    for ax, (name, y, x) in zip(axes, versions):
        slope = float(np.polyfit(x, y, 1)[0])
        rho = _spearman(x, y)
        cv = float(y.std(ddof=1) / y.mean())
        result["versions"][name] = {"slope": round(slope, 3), "spearman": round(rho, 3), "cv": round(cv, 3)}
        ax.plot(x, y, "o", ms=6, color="#2563eb", mec="white", mew=1)
        xs = np.linspace(x.min(), x.max(), 2)
        ax.plot(xs, np.polyval(np.polyfit(x, y, 1), xs), "-", lw=2, color="#374151")
        ax.axhline(1, color="#9ca3af", lw=1, ls="--")
        ax.set_title(f"{name}\nslope {slope:+.2f} · Spearman ρ {rho:+.2f} · spread (CV) {cv:.0%}", fontsize=10)
        ax.set_xlabel("glow-map illumination at the bead (peak = 1)")
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(alpha=0.2)
    axes[0].set_ylabel("bead light ÷ its hydrogel's mean")
    fig.suptitle(f"Bead check{(' · ' + label) if label else ''} · {illum.size} beads "
                 "(the right panel uses gamma fitted from these beads, so it is flat by construction)")
    FigureCanvasAgg(fig)
    fig.savefig(path, dpi=150, facecolor="white")
    result["plot"] = path
    return result


def _spearman(a, b) -> float:
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])
