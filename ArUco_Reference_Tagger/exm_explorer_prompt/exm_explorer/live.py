"""Compute jobs for the live GUI (Qt-free, so tests can call them directly).

Every job takes plain data (dataclass copies) and returns plain data. They run
on worker threads; numpy and scipy.fft release the GIL.
"""

import copy
import time

import numpy as np

from . import field as fieldmod
from . import pipeline, sim
from .frames import Placement
from .grid import load_grid
from .spatial import local_extrema

FIELD_BOX_UM = (-25.0, 775.0)        # region of the solver grid shown in the GUI

# extrema reference value and default threshold per truth map
EXTREMA_MAPS = {
    "expansion": dict(label="local expansion", reference="lam"),
    "anisotropy": dict(label="local anisotropy", reference=1.0),
    "rotation": dict(label="local rotation (deg)", reference=0.0),
}


def field_job(sites, solver, lam, arrow_step=25.0, extrema=None):
    """Solve the displacement field and build the truth overlays.

    extrema: dict(map=name, min_separation_um, min_deviation) or None.
    Returns crop extent, truth maps (design frame, rows = y up), arrow
    segments, extrema and timings."""
    t0 = time.perf_counter()
    fld = fieldmod.solve(sites, solver)
    t1 = time.perf_counter()
    tr = fld.truth(lam)
    xs = fld.xs
    k = np.nonzero((xs >= FIELD_BOX_UM[0]) & (xs <= FIELD_BOX_UM[1]))[0]
    sl = slice(k[0], k[-1] + 1)
    maps = {name: np.ascontiguousarray(v[sl, sl], np.float32) for name, v in tr.items()}
    xc = xs[sl]
    xa = np.arange(0.0, 750.0 + 1e-9, arrow_step)
    AX, AY = np.meshgrid(xa, xa)
    P = np.c_[AX.ravel(), AY.ravel()]
    U = fld.u_at(P)
    out = dict(x=xc, step=fld.step, maps=maps, arrow_xy=P, arrow_u=U,
               u_max=float(np.hypot(fld.ux[sl, sl], fld.uy[sl, sl]).max()),
               stats={name: (float(np.nanmin(v)), float(np.nanmax(v))) for name, v in maps.items()},
               extrema=[], t_solve=t1 - t0)
    if extrema and extrema.get("map") in maps:
        name = extrema["map"]
        ref = EXTREMA_MAPS[name]["reference"]
        ref = lam if ref == "lam" else ref
        sep = max(1, int(round(extrema.get("min_separation_um", 20.0) / fld.step)))
        out["extrema"] = local_extrema(maps[name], xc, xc, min_separation=sep,
                                       min_deviation=extrema.get("min_deviation", 0.0),
                                       reference=ref)
        out["extrema_map"] = name
    out["t_total"] = time.perf_counter() - t0
    return out


def pre_job(scen):
    """Pre image (as simulated, with noise) and a clean design render (no
    jitter, no noise), both in pre px, plus the affine px -> design um."""
    t0 = time.perf_counter()
    grid = load_grid()
    scen = copy.deepcopy(scen)
    empty = fieldmod.solve([], scen.solver)
    pos = sim.island_positions(grid, scen, empty)
    pre = pipeline.render_pre(grid, scen, pos)
    pl: Placement = pos.pre
    design_px = pl.design_to_px(grid.xy)
    clean = sim.render_clean(grid, design_px, pl, scen.imaging.psf_fwhm_um)
    # px -> design is affine; get it from three points
    P = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    D = pl.px_to_design(P)
    Ad = np.c_[D[1] - D[0], D[2] - D[0]]
    return dict(pre=pre.astype(np.float32), design=clean.astype(np.float32), px_to_design=(Ad, D[0]),
                tag_xy=grid.xy[grid.tags], tag_id=grid.aruco_id[grid.tags],
                node_pitch=grid.node_pitch_um, t_total=time.perf_counter() - t0)
