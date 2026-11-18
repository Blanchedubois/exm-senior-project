"""
glyphtrack.dotfilter
==================
Stage 4 — quality-filter the fill dots (the tracking points):
  1. too close to another dot   (threshold = fraction of the DOT pitch, which is
     the box pitch / 18.75 — the grid-to-dot ratio);
  2. sitting on a number/letter  (within a radius of a detected glyph);
  3. deviating too far from its ideal lattice position (adjustable).
Headless: numpy + scipy KDTree.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np


@dataclass
class DotFilterParams:
    min_sep_enable: bool = True
    min_sep_frac: float = 0.55      # × dot pitch — drop dots closer than this to a neighbour
    glyph_enable: bool = True
    glyph_radius_frac: float = 0.80  # × glyph height — drop dots within this of a glyph
    dev_enable: bool = True
    max_dev_frac: float = 0.35      # × dot pitch — drop dots this far off their lattice node


def _ideal_deviation(dots, basis):
    """Distance of each dot from its nearest node of the refined dot lattice."""
    B = np.column_stack([basis["v1"], basis["v2"]])
    ij = np.round((dots - basis["origin"]) @ np.linalg.inv(B).T)
    ideal = basis["origin"] + ij @ B.T
    return np.hypot(*(dots - ideal).T)


@dataclass
class DashFilterParams:
    offgrid_enable: bool = True
    max_offgrid_frac: float = 0.12   # × box pitch — reject dashes far from a grid line
    minsep_enable: bool = True
    min_sep_frac: float = 0.50       # × dash pitch (box/dashes_per_edge) — too close to a neighbour
    corner_enable: bool = True
    corner_radius_frac: float = 0.10  # × box pitch — reject dashes at grid intersections
    dashes_per_edge: int = 10


def filter_dashes(dashes, grid, params: DashFilterParams):
    """Filter boundary dashes. Returns (records, counts). Each record: x, y, keep,
    reason ('off_grid' | 'intersection' | 'too_close' | '')."""
    from scipy.spatial import cKDTree
    dashes = np.asarray(dashes, float)
    n = len(dashes)
    P = grid["box_pitch"]
    pu = dashes @ grid["u"] - grid["phase_u"]
    pv = dashes @ grid["v"] - grid["phase_v"]
    du = np.abs((pu + P / 2) % P - P / 2)                # perp dist to nearest u-line
    dv = np.abs((pv + P / 2) % P - P / 2)                # perp dist to nearest v-line

    off_grid = np.zeros(n, bool); at_corner = np.zeros(n, bool); too_close = np.zeros(n, bool)
    if params.offgrid_enable and n:
        off_grid = np.minimum(du, dv) > params.max_offgrid_frac * P
    if params.corner_enable and n:
        at_corner = np.hypot(du, dv) < params.corner_radius_frac * P
    if params.minsep_enable and n > 1:
        dash_pitch = P / max(params.dashes_per_edge, 1)
        d, _ = cKDTree(dashes).query(dashes, k=2)
        too_close = d[:, 1] < params.min_sep_frac * dash_pitch

    recs = []
    counts = {"kept": 0, "off_grid": 0, "intersection": 0, "too_close": 0}
    for i in range(n):
        if off_grid[i]:
            reason = "off_grid"
        elif at_corner[i]:
            reason = "intersection"
        elif too_close[i]:
            reason = "too_close"
        else:
            reason = ""
        keep = reason == ""
        counts["kept" if keep else reason] += 1
        recs.append({"x": float(dashes[i, 0]), "y": float(dashes[i, 1]),
                     "keep": keep, "reason": reason})
    return recs, counts


def filter_dots(dots, basis, glyph_pos, glyph_h, params: DotFilterParams):
    """Return (records, counts). Each record: x, y, keep, reason
    ('too_close' | 'on_glyph' | 'off_lattice' | '')."""
    from scipy.spatial import cKDTree
    dots = np.asarray(dots, float)
    n = len(dots)
    pitch = float(basis["pitch"])
    too_close = np.zeros(n, bool)
    on_glyph = np.zeros(n, bool)
    off_lat = np.zeros(n, bool)

    if params.min_sep_enable and n > 1:
        d, _ = cKDTree(dots).query(dots, k=2)
        too_close = d[:, 1] < params.min_sep_frac * pitch      # both members of a close pair

    if params.glyph_enable and glyph_pos is not None and len(glyph_pos):
        gd, _ = cKDTree(np.asarray(glyph_pos, float)).query(dots, k=1)
        on_glyph = gd < params.glyph_radius_frac * float(glyph_h)

    if params.dev_enable and n:
        off_lat = _ideal_deviation(dots, basis) > params.max_dev_frac * pitch

    recs = []
    counts = {"kept": 0, "too_close": 0, "on_glyph": 0, "off_lattice": 0}
    for i in range(n):
        if too_close[i]:
            reason = "too_close"
        elif on_glyph[i]:
            reason = "on_glyph"
        elif off_lat[i]:
            reason = "off_lattice"
        else:
            reason = ""
        keep = reason == ""
        counts["kept" if keep else reason] += 1
        recs.append({"x": float(dots[i, 0]), "y": float(dots[i, 1]),
                     "keep": keep, "reason": reason})
    return recs, counts
