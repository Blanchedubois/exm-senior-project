"""Reference beads: the total light of one in-focus bead, measured on circles the user places.

A bead's light is the sum of (image - local background) inside its circle.  The
local background is the median of a ring just outside the circle, so haze from
out-of-focus beads and gel glow under the bead is removed.  In-focus 2 um beads
at 10x spread light out to a radius of about 14-20 px, so circles are sized from
each bead's own radial profile rather than a fixed small radius.

The saved file holds only what the user chose (centre, radius); every number is
recomputed from the image, so changing the method here updates old picks too.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

import numpy as np
from scipy import ndimage as ndi

ANNULUS_GAP_PX = 3
ANNULUS_WIDTH_PX = 8
MIN_RADIUS_PX = 4
MAX_RADIUS_PX = 30
SNAP_RADIUS_PX = 6
OFF_CENTRE_FRACTION = 0.35  # of the image width; used only when no illumination map is given
MIN_ILLUMINATION = 0.2  # matches flatfield.MIN_ILLUMINATION: dimmer than this, the correction isn't trusted
SATURATION_ADU = 65535


@dataclass(frozen=True)
class BeadPick:
    x: float
    y: float
    r: float


@dataclass(frozen=True)
class BeadMeasurement:
    pick: BeadPick
    light: float  # ADU summed over the circle, background removed
    background: float  # ADU per pixel, median of the ring
    peak: float  # brightest pixel above background
    n_px: int
    snr: float  # light / its noise from the ring's scatter
    centre_distance: float  # fraction of the image width from the centre
    flags: tuple[str, ...]
    illumination: float | None = None  # illumination map at the bead (peak = 1)
    light_corrected: float | None = None  # light / illumination: as if lit like the centre

    @property
    def usable_light(self) -> float:
        return self.light_corrected if self.light_corrected is not None else self.light

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(d.pop("pick"))
        d["flags"] = list(self.flags)
        return d


def snap_to_peak(img: np.ndarray, x: float, y: float, radius: int = SNAP_RADIUS_PX) -> tuple[float, float]:
    """The brightest point (lightly smoothed) within `radius` px of a click."""
    h, w = img.shape
    x0, x1 = max(0, int(x) - radius), min(w, int(x) + radius + 1)
    y0, y1 = max(0, int(y) - radius), min(h, int(y) + radius + 1)
    if x1 <= x0 or y1 <= y0:
        return float(x), float(y)
    patch = ndi.gaussian_filter(img[y0:y1, x0:x1].astype(np.float32), 1.0)
    iy, ix = np.unravel_index(np.argmax(patch), patch.shape)
    return float(x0 + ix), float(y0 + iy)


def _rings(img: np.ndarray, x: float, y: float, r_max: float):
    """Pixel distances from (x, y) in a box just big enough for radius r_max."""
    h, w = img.shape
    m = int(np.ceil(r_max)) + 1
    x0, x1 = max(0, int(x) - m), min(w, int(x) + m + 1)
    y0, y1 = max(0, int(y) - m), min(h, int(y) + m + 1)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    return img[y0:y1, x0:x1].astype(np.float64), np.hypot(xx - x, yy - y)


def radial_profile(img: np.ndarray, x: float, y: float, r_max: int = MAX_RADIUS_PX):
    """Mean of each 1 px ring, and the enclosed light, both above the ring background at r_max."""
    outer = r_max + ANNULUS_GAP_PX + ANNULUS_WIDTH_PX
    patch, rr = _rings(img, x, y, outer)
    ring = (rr >= r_max + ANNULUS_GAP_PX) & (rr < outer)
    bg = float(np.median(patch[ring])) if ring.any() else 0.0
    radii = np.arange(r_max + 1)
    prof = np.array([patch[(rr >= r) & (rr < r + 1)].mean() - bg if ((rr >= r) & (rr < r + 1)).any() else 0.0
                     for r in radii])
    cum = np.array([(patch[rr <= r] - bg).sum() for r in radii])
    return radii, prof, cum


def suggest_radius(img: np.ndarray, x: float, y: float, r_max: int = MAX_RADIUS_PX) -> float:
    """Where the bead's profile reaches background (1% of its peak) or starts to rise into a
    neighbour, plus a 2 px margin."""
    _, prof, _ = radial_profile(img, x, y, r_max)
    peak = max(prof[0], 1e-9)
    stop = r_max
    for r in range(3, r_max + 1):
        if prof[r] <= 0.01 * peak or prof[r] > 1.2 * prof[r - 1] + 0.005 * peak:
            stop = r
            break
    return float(np.clip(stop + 2, MIN_RADIUS_PX, r_max))


def measure(img: np.ndarray, pick: BeadPick, saturated: np.ndarray | None = None,
            illumination: float | None = None) -> BeadMeasurement:
    inner = pick.r + ANNULUS_GAP_PX
    outer = inner + ANNULUS_WIDTH_PX
    patch, rr = _rings(img, pick.x, pick.y, outer)
    disc = rr <= pick.r
    ring = (rr >= inner) & (rr < outer)
    bg = float(np.median(patch[ring]))
    above = patch[disc] - bg
    light = float(above.sum())
    n = int(disc.sum())
    ring_sd = 1.4826 * float(np.median(np.abs(patch[ring] - bg)))
    noise = ring_sd * np.sqrt(n) + np.sqrt(max(light, 0.0))
    h, w = img.shape
    centre = float(np.hypot(pick.x - (w - 1) / 2, pick.y - (h - 1) / 2) / w)

    flags = []
    if pick.x - outer < 0 or pick.y - outer < 0 or pick.x + outer > w - 1 or pick.y + outer > h - 1:
        flags.append("edge")
    if illumination is not None:
        if illumination < MIN_ILLUMINATION:
            flags.append("dim-light")
    elif centre > OFF_CENTRE_FRACTION:
        flags.append("off-centre")
    if saturated is not None:
        sub, srr = _rings(saturated.astype(np.float32), pick.x, pick.y, pick.r)
        if (sub[srr <= pick.r] > 0).any():
            flags.append("saturated")
    peak = float(above.max()) if above.size else 0.0
    snr = light / noise if noise > 0 else float("inf")
    if snr < 10:
        flags.append("faint")  # probably not a bead; "crowded" would be meaningless on noise
    elif np.mean(patch[ring] - bg > 0.1 * peak) > 0.05:
        # another bright object in the ring would raise the background and cut this bead's light
        flags.append("crowded")
    corrected = light / illumination if illumination else None
    return BeadMeasurement(pick, light, bg, peak, n, float(snr), centre, tuple(flags), illumination, corrected)


@dataclass
class RefStore:
    """Reference-bead picks per area (acquisition folder), saved as JSON."""
    path: str
    experiment: str = ""
    picks: dict[str, list[BeadPick]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str, experiment: str = "") -> "RefStore":
        store = cls(path, experiment)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            store.experiment = d.get("experiment", experiment)
            for folder, beads in d.get("areas", {}).items():
                store.picks[folder] = [BeadPick(b["x"], b["y"], b["r"]) for b in beads]
        return store

    def add(self, folder: str, pick: BeadPick) -> None:
        self.picks.setdefault(folder, []).append(pick)

    def replace(self, folder: str, index: int, pick: BeadPick) -> None:
        self.picks[folder][index] = pick

    def remove(self, folder: str, index: int) -> None:
        del self.picks[folder][index]

    def save(self, measurements: dict[str, list[BeadMeasurement]] | None = None,
             conditions: dict[str, str] | None = None) -> None:
        """Write picks; with measurements, also the numbers and per-hydrogel summaries (for reading)."""
        out = {"experiment": self.experiment,
               "method": {"light": "sum of (image - ring median) inside the circle",
                          "ring_px": [ANNULUS_GAP_PX, ANNULUS_WIDTH_PX],
                          "image": "mean of all frames minus median dark frame"},
               "areas": {}}
        for folder, picks in self.picks.items():
            ms = (measurements or {}).get(folder)
            out["areas"][folder] = ([m.to_dict() for m in ms] if ms and len(ms) == len(picks)
                                    else [asdict(p) for p in picks])
        if measurements and conditions:
            out["summary"] = {k: asdict(s) for k, s in summarise(measurements, conditions).items()}
            out["summary_light"] = ("corrected for illumination" if any(
                m.light_corrected is not None for ms in measurements.values() for m in ms) else "raw")
            out["conditions"] = conditions
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        os.replace(tmp, self.path)


@dataclass(frozen=True)
class Summary:
    n_beads: int
    n_areas: int
    mean_light: float
    sd_light: float
    sem_light: float
    median_light: float


def summarise(measurements: dict[str, list[BeadMeasurement]], conditions: dict[str, str],
              exclude_flags=("edge", "saturated", "crowded", "faint", "dim-light")) -> dict[str, Summary]:
    """Per hydrogel (condition key) and overall ("all"): one bead's light (corrected for illumination
    when measured with a map), from the usable picks.

    `conditions` maps area folder -> condition key."""
    groups: dict[str, list[float]] = {}
    areas: dict[str, set] = {}
    for folder, ms in measurements.items():
        key = conditions.get(folder)
        if key is None:
            continue
        for m in ms:
            if any(f in exclude_flags for f in m.flags):
                continue
            for k in (key, "all"):
                groups.setdefault(k, []).append(m.usable_light)
                areas.setdefault(k, set()).add(folder)
    out = {}
    for k, v in groups.items():
        a = np.asarray(v)
        sd = float(a.std(ddof=1)) if a.size > 1 else float("nan")
        out[k] = Summary(a.size, len(areas[k]), float(a.mean()), sd,
                         sd / np.sqrt(a.size) if a.size > 1 else float("nan"), float(np.median(a)))
    return out
