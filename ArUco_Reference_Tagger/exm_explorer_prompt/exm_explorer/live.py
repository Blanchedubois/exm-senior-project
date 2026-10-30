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


# ===================================================================== analysis job (milestone 4)
from . import analysis as an                                   # noqa: E402
from .frames import describe                                   # noqa: E402
from .render import psf_sigma_px, render_exact                 # noqa: E402
from .spatial import local_extrema as _extrema                 # noqa: E402

POST_VIEW_MAX_PX = 1400          # the post view is rendered at most this many px across


class Stale(Exception):
    """Raised inside a job when a newer request has arrived."""


def render_post_region(grid, scen, pos, region, max_px=POST_VIEW_MAX_PX):
    """Exact render of a region (x0, y0, w, h in post px) of the post image,
    decimated by an integer factor so that it is at most max_px across.
    Never renders the whole post image at native resolution. Returns the
    image (counts, with noise if on), the factor and the region actually used."""
    im = scen.imaging
    n = pos.post.size_px
    x0, y0, w, h = (int(round(v)) for v in region)
    x0, y0 = max(x0, 0), max(y0, 0)
    w, h = min(w, n - x0), min(h, n - y0)
    f = max(1, int(np.ceil(max(w, h) / max_px)))
    wd, hd = max(w // f, 8), max(h // f, 8)
    from .sim import rects
    cx, cy, hx, hy = rects(grid, pos.post_px, pos.post.theta_deg, im.um_px)
    # pixel (i, j) of the decimated grid sits at post px (x0 + f i, y0 + f j)
    img = render_exact(0, (cx - x0) / f, (cy - y0) / f, hx / f, hy / f, pos.post.theta_deg,
                       psf_sigma_px(im.psf_fwhm_um, im.um_px) / f, region=(0, 0, wd, hd))
    gain = im.lam ** im.post_gain_exp
    img = img * im.peak_e * gain + im.bg_e * gain
    if im.noise:
        rng = np.random.default_rng(im.seed + 31 * x0 + 17 * y0 + f)
        img = rng.poisson(np.maximum(img, 0)).astype(np.float32) + rng.normal(0, im.read_e, img.shape)
    return img.astype(np.float32), f, (x0, y0, wd * f, hd * f)


def windows_near(cs_x, cs_y, centre_px, radius_px):
    X, Y = np.meshgrid(cs_x, cs_y)
    return np.hypot(X - centre_px[0], Y - centre_px[1]) < radius_px


def analysis_job(scen, tier="fast", post_region=None, focus_site=None, extrema=None,
                 is_stale=lambda: False, acf_zoom_pitches=5.5):
    """Live ACF / CCF pipeline.

    tier        'fast': windowed CCF only around focus_site (plus a margin);
                'full': all windows
    post_region (x0, y0, w, h) in post px for the post view and its ACF;
                None = a central region
    focus_site  Site whose neighbourhood the fast tier analyses
    Returns plain data for the panels and the metrics."""
    T = {}
    t = time.perf_counter()

    def mark(name):
        nonlocal t
        if is_stale():
            raise Stale
        now = time.perf_counter()
        T[name] = now - t
        t = now

    grid = load_grid()
    a = scen.analysis
    im = scen.imaging
    fld = fieldmod.solve(scen.sites, scen.solver)
    pos = sim.island_positions(grid, scen, fld)
    ps = pipeline.pre_state(scen, grid)
    mark("solve + map")

    # ---- post region and its ACF (lattice -> global transform from the ACF)
    n_post = pos.post.size_px
    if post_region is None:
        s = min(n_post, 1600)
        post_region = ((n_post - s) / 2, (n_post - s) / 2, s, s)
    if tier == "full":
        cap = 4096                       # whole image up to lambda ~5, central crop above
        s = min(n_post, cap)
        full_region = ((n_post - s) / 2, (n_post - s) / 2, s, s)
        post_full, f_full, _ = render_post_region(grid, scen, pos, full_region, max_px=cap)
        L_acf = int(min(a.L_post * im.lam / 4.0, post_full.shape[0] / 3))
        acf_src, f_acf = post_full, f_full
        mark("post render (full)")
    post_img, f_view, reg = render_post_region(grid, scen, pos, post_region)
    mark("post render (view)")
    if tier != "full":
        acf_src, f_acf = post_img, f_view
        L_acf = int(min(acf_src.shape[0], acf_src.shape[1]) / 3)
    A_post = an.acf(acf_src, L_acf)
    acf_ok = True
    try:
        Bpost, _, _ = an.lattice_basis(A_post, L_acf)
        Bpost = Bpost * f_acf                                      # back to native post px
        Bpost, F_acf = an.match_bases(ps.Bpre, Bpost)
        H_post = an.peak_heights(A_post, L_acf, Bpost / f_acf)
        order, ratio = an.height_ratio(ps.heights, H_post)
    except Exception:                    # too few lattice peaks in a tiny view
        acf_ok = False
        Bpost = F_acf = None
        order = ratio = np.zeros(0)
    mark("post ACF + lattice")

    # ---- registration
    regs = {"tags": pipeline.simulated_tag_affine(grid, pos, a.tag_noise_px, im.seed),
            "truth": pos.true_affine()}
    if acf_ok:
        regs["acf"] = pipeline.acf_affine(F_acf, ps.pre.shape, (n_post, n_post))
    reg_name = a.registration if a.registration in regs else "tags"
    A, b = regs[reg_name]

    # ---- windowed CCF (restricted in the fast tier)
    which = None
    if tier == "fast" and focus_site is not None:
        c_px = pos.pre.design_to_px(np.array([[focus_site.cx, focus_site.cy]]))[0]
        rad = (max(focus_site.a, focus_site.b) * 1.6 + 60) / im.um_px
        cs_x, cs_y = an.window_centres(ps.pre.shape, a.win, a.step)
        which = windows_near(cs_x, cs_y, c_px, rad)
    shape = ps.pre.shape
    P = an.ccf_pipeline(ps.pre, lambda A_, b_: pipeline.corrected_fast(grid, scen, pos, A_, b_, shape),
                        A, b, ps.Bpre, pipeline.truth_dict(grid, pos), win=a.win, step=a.step,
                        S=a.search, Lg=a.L_global, pre_cache=ps.ccf_cache, which=which)
    mark("CCF")

    # ---- ACF(corrected post) - ACF(pre) in the pre frame, peak shifts and widening
    pitch = float(np.sqrt(abs(np.linalg.det(ps.Bpre))))
    Ld = int(np.ceil(acf_zoom_pitches * pitch)) + 4
    A_cor = an.acf(P["cor"], Ld)
    A_pre_small = ps.acf[ps.L - Ld:ps.L + Ld + 1, ps.L - Ld:ps.L + Ld + 1]
    shifts = an.acf_peak_shifts(A_cor, A_pre_small, Ld, ps.Bpre, K=4)
    mark("ACF difference")

    # ---- measured local maps on dot-only windows, and extrema
    lam_A = float(np.sqrt(abs(np.linalg.det(A))))
    dots = P.get("dots_only", P["valid"]) & P["valid"]
    unw = np.where(dots[..., None], P["unwrapped"], np.nan)
    scale, J = an.local_scale_fit(unw, a.step, lam_A)
    aniso = np.full(scale.shape, np.nan)
    ok = np.isfinite(J[..., 0, 0])
    if ok.any():
        S = np.linalg.svd(J[ok], compute_uv=False)
        aniso[ok] = S[:, 0] / S[:, 1]
    disp = P["unwrapped"] if a.lattice_aware else P["naive"]
    mag = np.hypot(disp[..., 0], disp[..., 1])
    ext = {}
    sep = (extrema or {}).get("min_separation_windows", 2)
    if extrema is not None:
        ext["ccf_magnitude"] = _extrema(mag, P["cs_x"], P["cs_y"], min_separation=sep,
                                        min_deviation=extrema.get("ccf_min_px", 0.5), reference=0.0)
        ext["measured_anisotropy"] = _extrema(aniso, P["cs_x"], P["cs_y"], min_separation=sep,
                                              min_deviation=extrema.get("aniso_min", 0.01), reference=1.0)
        ext["measured_expansion"] = _extrema(scale, P["cs_x"], P["cs_y"], min_separation=sep,
                                             min_deviation=extrema.get("expansion_min", 0.02),
                                             reference=float(np.nanmedian(scale)))
        Lg = a.L_global
        g_ext = _extrema(P["G"], np.arange(-Lg, Lg + 1), np.arange(-Lg, Lg + 1), min_separation=3,
                         reference=0.0, max_points=8)
        ext["global_ccf_peaks"] = [e for e in g_ext if e["kind"] == "max"]
    mark("maps + extrema")

    st = P["stats"]
    metrics = dict(
        truth=describe(regs["truth"][0]),
        tags=describe(regs["tags"][0]),
        acf=describe(F_acf) if acf_ok else None,
        registration=reg_name,
        ccf=dict(peak=st["ccf_peak"], next_best=st["next_best_peak"], next_best_at=st["next_best_at_px"],
                 ratio=st["ambiguity_ratio"], shift=st["global_shift_applied_px"]),
        windows=st,
        tier=tier,
        restricted=which is not None,
        timings=T, total_s=sum(T.values()))
    return dict(
        tier=tier, metrics=metrics,
        post=dict(img=post_img, factor=f_view, region=reg),
        acf_pre=ps.acf, L_pre=ps.L, Bpre=ps.Bpre,
        acf_post=A_post, L_post=L_acf, f_acf=f_acf, Bpost=Bpost,
        heights=dict(order=order, ratio=ratio),
        acf_diff=A_cor - A_pre_small, L_diff=Ld, shifts=shifts,
        G=P["G"], Lg=a.L_global, next_best_at=st["next_best_at_px"],
        cs_x=P["cs_x"], cs_y=P["cs_y"], valid=P["valid"], which=which,
        naive=P["naive"], unwrapped=P["unwrapped"], true_win=P.get("true_win"),
        meas_scale=scale, meas_aniso=aniso, extrema=ext,
        px_to_design=pos.pre.px_to_design, lam=im.lam)
