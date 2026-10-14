"""
rwtag.dotfilter (Stage 3)
=========================
Quality-filter the Stage-2 dots and dashes. Ported from
Reference_Warp_Tagger/rwtag/glyph/dotfilter.py with the gates made PER BOX:

Dots, reason priority edge -> near_tag -> too_close -> off_lattice:
  edge         no real raw source (Stage 2's exact un-distortion test);
  near_tag     inside a decoded tag's quiet zone (replaces V1's on-glyph gate):
               Chebyshev distance in the tag's own frame < (0.5 + margin) x side;
  too_close    nearest neighbour < min_sep_frac x THIS BOX's dot pitch;
  off_lattice  farther than max_dev_frac x pitch from the nearest node of THIS
               BOX's refined lattice. V1 tested one global lattice; V2 boxes are
               not a whole number of pitches (and the spectrum print changes
               pitch box to box), so a global test culls good dots.

Dashes, reason priority edge -> off_grid -> intersection -> too_close, as V1,
with `dashes_per_edge` from the design. Every record keeps its index into the
DetectResult arrays so later stages can join photometry and the raw pass.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import numpy as np

from . import lattice as lt
from .types import FilterResult

DOT_REASONS = ("edge", "near_tag", "too_close", "off_lattice")
DASH_REASONS = ("edge", "off_grid", "intersection", "too_close")


@dataclass
class DotFilterParams:
    # Calibrated on V1's real frames: dots deviate from a single lattice by up to
    # ~0.5 pitch (p99) because the gel is warped -- that is the signal -- so the
    # off-lattice gate stays generous (0.60).
    edge_enable: bool = True
    tag_enable: bool = True
    tag_margin_frac: float = 0.25    # quiet zone beyond the tag edge, x tag side
    min_sep_enable: bool = True
    min_sep_frac: float = 0.50       # x box dot pitch
    dev_enable: bool = True
    max_dev_frac: float = 0.60       # x box dot pitch


@dataclass
class DashFilterParams:
    edge_enable: bool = True
    offgrid_enable: bool = True
    max_offgrid_frac: float = 0.15   # x box pitch
    minsep_enable: bool = True
    min_sep_frac: float = 0.50       # x dash pitch (box / dashes_per_edge)
    corner_enable: bool = True
    corner_radius_frac: float = 0.10  # x box pitch
    dashes_per_edge: int = 10


def _box_pitch_px(det, N):
    r = det.per_box.get(int(N)) if det.per_box else None
    if r is not None and np.isfinite(r.get("pitch_px", np.nan)):
        return float(r["pitch_px"])
    if r is not None:                                     # no lattice fit: design pitch x scale
        return float(r["pitch_um"]) * float(det.model.get("scale_px_per_um", 1.0))
    return float(det.basis["pitch"])


def _near_tag(dots, tags, margin_frac):
    """True where a dot lies within a tag's square quiet zone."""
    out = np.zeros(len(dots), bool)
    if not len(dots) or not tags:
        return out
    from scipy.spatial import cKDTree
    tree = cKDTree(dots)
    for t in tags.values():
        c = t.corners_px
        ex = (c[1] - c[0]); ex /= max(np.linalg.norm(ex), 1e-9)
        ey = (c[3] - c[0]); ey /= max(np.linalg.norm(ey), 1e-9)
        half = (0.5 + margin_frac) * t.side_px
        idx = tree.query_ball_point(t.centre_px, half * 1.5)
        if not idx:
            continue
        v = dots[idx] - t.centre_px
        cheb = np.maximum(np.abs(v @ ex), np.abs(v @ ey))
        out[np.asarray(idx)[cheb < half]] = True
    return out


def filter_dots(det, params: DotFilterParams):
    """(records, counts). Record: {i, x, y, box, keep, reason}."""
    from scipy.spatial import cKDTree
    dots = np.asarray(det.dots, float).reshape(-1, 2)
    n = len(dots)
    box = det.dot_box if det.dot_box is not None else np.zeros(n, int)
    pitch = np.array([_box_pitch_px(det, N) if N else float(det.basis["pitch"]) for N in box]) if n else np.zeros(0)
    edge = (det.dot_flag == "edge") if (params.edge_enable and det.dot_flag is not None) else np.zeros(n, bool)
    near = _near_tag(dots, det.tags, params.tag_margin_frac) if params.tag_enable else np.zeros(n, bool)
    close = np.zeros(n, bool)
    if params.min_sep_enable and n > 1:
        dd, _ = cKDTree(dots).query(dots, k=2)
        close = dd[:, 1] < params.min_sep_frac * pitch
    off = np.zeros(n, bool)
    if params.dev_enable and n:
        for N, b in (det.basis_by_box or {}).items():
            m = box == N
            if m.any():
                off[m] = lt.lattice_deviation(dots[m], b) > params.max_dev_frac * pitch[m]
    recs, counts = [], {k: 0 for k in ("kept",) + DOT_REASONS}
    for i in range(n):
        reason = ("edge" if edge[i] else "near_tag" if near[i] else "too_close" if close[i]
                  else "off_lattice" if off[i] else "")
        counts["kept" if not reason else reason] += 1
        recs.append({"i": i, "x": float(dots[i, 0]), "y": float(dots[i, 1]), "box": int(box[i]),
                     "keep": not reason, "reason": reason})
    return recs, counts


def filter_dashes(det, params: DashFilterParams):
    """(records, counts). Record: {i, x, y, keep, reason}."""
    from scipy.spatial import cKDTree
    dashes = np.asarray(det.dashes_all, float).reshape(-1, 2)
    n = len(dashes)
    recs, counts = [], {k: 0 for k in ("kept",) + DASH_REASONS}
    if n == 0 or det.grid is None:
        return recs, counts
    grid = det.grid
    P = grid["box_pitch"]
    pu = dashes @ grid["u"] - grid["phase_u"]
    pv = dashes @ grid["v"] - grid["phase_v"]
    du = np.abs((pu + P / 2) % P - P / 2)
    dv = np.abs((pv + P / 2) % P - P / 2)
    edge = (det.dash_flag == "edge") if (params.edge_enable and det.dash_flag is not None) else np.zeros(n, bool)
    off = np.minimum(du, dv) > params.max_offgrid_frac * P if params.offgrid_enable else np.zeros(n, bool)
    corner = np.hypot(du, dv) < params.corner_radius_frac * P if params.corner_enable else np.zeros(n, bool)
    close = np.zeros(n, bool)
    if params.minsep_enable and n > 1:
        d, _ = cKDTree(dashes).query(dashes, k=2)
        close = d[:, 1] < params.min_sep_frac * P / max(params.dashes_per_edge, 1)
    for i in range(n):
        reason = ("edge" if edge[i] else "off_grid" if off[i] else "intersection" if corner[i]
                  else "too_close" if close[i] else "")
        counts["kept" if not reason else reason] += 1
        recs.append({"i": i, "x": float(dashes[i, 0]), "y": float(dashes[i, 1]), "keep": not reason, "reason": reason})
    return recs, counts


def filter_frame(det, dot_params: DotFilterParams = None, dash_params: DashFilterParams = None,
                 design=None) -> FilterResult:
    dot_params = dot_params or DotFilterParams()
    dash_params = dash_params or DashFilterParams()
    if design is not None:
        dash_params.dashes_per_edge = int(design.dashes_per_edge)
    drecs, dcounts = filter_dots(det, dot_params)
    hrecs, hcounts = filter_dashes(det, dash_params)
    ki = np.array([r["i"] for r in drecs if r["keep"]], int)
    hi = np.array([r["i"] for r in hrecs if r["keep"]], int)
    return FilterResult(dot_recs=drecs, dash_recs=hrecs, dot_counts=dcounts, dash_counts=hcounts,
                        kept_dots=np.asarray(det.dots, float).reshape(-1, 2)[ki] if len(ki) else np.zeros((0, 2)),
                        kept_dashes=np.asarray(det.dashes_all, float).reshape(-1, 2)[hi] if len(hi) else np.zeros((0, 2)),
                        dot_params=asdict(dot_params), dash_params=asdict(dash_params),
                        kept_dot_index=ki, kept_dash_index=hi)
