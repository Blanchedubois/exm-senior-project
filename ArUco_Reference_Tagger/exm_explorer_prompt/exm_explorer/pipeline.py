"""Scenario -> numbers, without Qt. Two paths:

faithful  render the real post image (exact), detect ArUco tags with OpenCV,
          fit the affine from tag centres (or use the ACF / truth), resample
          the post into the pre frame, ACF + CCF (what exm_analysis does)
fast      render the corrected post directly in the pre frame from the mapped
          island positions (render.render_corrected_fast); registration from
          simulated tag detection (true centres + noise), the ACF of the pre
          image or the truth. Pre-only work is cached.
"""

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from . import analysis as an
from . import field as fieldmod
from . import sim, tags
from .frames import describe, fit_affine
from .grid import load_grid
from .render import faithful_sigma_post_px, render_corrected_fast


# ===================================================================== pre side (cached)
@dataclass
class PreState:
    pre: np.ndarray              # float32 image
    acf: np.ndarray
    L: int
    Bpre: np.ndarray
    p_pre: float
    heights: dict
    ccf_cache: dict              # 'Fa', 'contrast' for ccf_pipeline


def _pre_key(scen):
    im = scen.imaging
    a = scen.analysis
    return (im.seed, im.print_jitter_um, im.theta_pre_deg, tuple(im.offset_pre_um), im.psf_fwhm_um,
            im.um_px, im.noise, im.peak_e, im.bg_e, im.read_e, im.margin_pre_um,
            a.L_pre, a.L_global, a.win, a.step)


_PRE = {}


def pre_state(scen, grid=None, pre_img=None):
    """Pre image, its ACF and lattice, and CCF caches. None of this depends on
    the sites or the post imaging, so it is computed once per pre setting."""
    key = _pre_key(scen)
    if key in _PRE:
        return _PRE[key]
    grid = grid or load_grid()
    if pre_img is None:
        pos = sim.island_positions(grid, scen, fieldmod.solve([], scen.solver))
        pre_img = render_pre(grid, scen, pos)
    pre = np.asarray(pre_img, np.float32)
    L = scen.analysis.L_pre
    A = an.acf(pre, L)
    Bpre, _, p_pre = an.lattice_basis(A, L)
    st = PreState(pre=pre, acf=A, L=L, Bpre=Bpre, p_pre=p_pre,
                  heights=an.peak_heights(A, L, Bpre), ccf_cache={})
    if len(_PRE) > 4:
        _PRE.clear()
    _PRE[key] = st
    return st


def render_pre(grid, scen, pos):
    """Pre image alone, with the same noise draws as sim.simulate."""
    from .render import expose, expose_clean
    im = scen.imaging
    clean = sim.render_clean(grid, pos.pre_px, pos.pre, im.psf_fwhm_um)
    if im.noise:
        return expose(clean, im.peak_e, im.bg_e, im.read_e, sim.draws(im.seed, grid.n).noise_rng())
    return expose_clean(clean, im.peak_e, im.bg_e)


# ===================================================================== registration
def simulated_tag_affine(grid, pos, noise_px, seed):
    """Affine pre px -> post px from the true tag centres plus detection noise
    (deterministic per seed)."""
    rng = np.random.default_rng(seed + 7919)
    k = grid.tags
    p0 = pos.pre_px[k] + rng.normal(0, noise_px, (len(k), 2))
    p1 = pos.post_px[k] + rng.normal(0, noise_px, (len(k), 2))
    return fit_affine(p0, p1)


def detected_tag_affine(pre, post):
    """Affine from tag centres decoded by OpenCV in both images."""
    d0 = tags.centres(tags.detect(pre, 0.01))
    d1 = tags.centres(tags.detect(post, 0.003))
    common = sorted(set(d0) & set(d1))
    if len(common) < 3:
        raise RuntimeError(f"only {len(common)} tags decoded in both images")
    A, b = fit_affine([d0[i] for i in common], [d1[i] for i in common])
    return A, b, len(common)


def acf_affine(F, pre_shape, post_shape):
    """Linear map from the ACF; translation puts image centre on image centre
    (the global CCF then finds the residual shift)."""
    c_pre = np.array(pre_shape[::-1]) / 2.0
    c_post = np.array(post_shape[::-1]) / 2.0
    return F, c_post - F @ c_pre


# ===================================================================== fast render
@lru_cache(maxsize=4)
def _noise_field(seed, shape):
    return np.random.default_rng(seed + 1_000_003).standard_normal(shape).astype(np.float32)


def kind_halves_post(grid, um_px):
    out = {}
    for k in range(4):
        h = grid.rect_half[grid.rect_kind == k]
        if len(h):
            out[k] = tuple(h[0] / um_px)
    return out


def corrected_fast(grid, scen, pos, A, b, shape):
    """Corrected post (post(A x + b)) rendered directly in the pre frame, in
    counts, with an approximate noise model: shot + read noise of the post
    pixels, reduced by the anti-alias blur (variance / (4 pi sigma_aa^2))."""
    im = scen.imaging
    Ainv = np.linalg.inv(A)
    th = pos.post.theta_deg
    from .frames import rot, vec_design_to_sample
    off_post = vec_design_to_sample(grid.rect_off) @ rot(th).T / im.um_px
    xy = (pos.post_px[grid.rect_isl] + off_post - b) @ Ainv.T
    lam_A = np.sqrt(abs(np.linalg.det(A)))
    sig = faithful_sigma_post_px(im.psf_fwhm_um, im.um_px, lam_A)
    clean = render_corrected_fast(xy, grid.rect_kind, kind_halves_post(grid, im.um_px), A, th, sig,
                                  shape)
    gain = im.lam ** im.post_gain_exp
    img = clean * im.peak_e * gain + im.bg_e * gain
    if im.noise:
        s_aa = max(round(0.45 * lam_A, 2), 0.5)
        sd = np.sqrt((np.maximum(img, 0) + im.read_e ** 2) / (4 * np.pi * s_aa ** 2))
        img = img + sd * _noise_field(im.seed, shape)
    return img.astype(np.float32)


# ===================================================================== runs
def truth_dict(grid, pos):
    dots = grid.cat == "dot"
    return dict(pre_px=pos.pre_px, post_px=pos.post_px, dots=dots, rigid_px=pos.pre_px[~dots])


def run_faithful(scen, grid=None, registrations=("tags",), simres=None, progress=None):
    """The batch pipeline on exact renders. Returns (results, extras) where
    results has the same keys as reference/results.json.

    progress(stage, fraction) is called between stages; it may raise to
    cancel the run."""
    def step(name, frac):
        if progress is not None:
            progress(name, frac)

    grid = grid or load_grid()
    step("rendering pre and post images", 0.0)
    s = simres or sim.simulate(scen, grid)
    step("ACF of the post image", 0.35)
    a = scen.analysis
    pre = s.pre.astype(np.float32)
    post = s.post.astype(np.float32)
    ps = pre_state(scen, grid, pre_img=s.pre)
    A_true, _ = s.positions.true_affine()
    res = {"truth_global": describe(A_true)}

    A_post = an.acf(post, a.L_post)
    Bpost, _, p_post = an.lattice_basis(A_post, a.L_post)
    Bpost, F_acf = an.match_bases(ps.Bpre, Bpost)
    um = scen.imaging.um_px
    res["acf_pre_basis_px"] = ps.Bpre.tolist()
    res["acf_post_basis_px"] = Bpost.tolist()
    res["acf_pitch_pre_um"] = float(np.sqrt(abs(np.linalg.det(ps.Bpre))) * um)
    res["acf_pitch_post_um"] = float(np.sqrt(abs(np.linalg.det(Bpost))) * um)
    res["acf_global"] = describe(F_acf)
    order, ratio = an.height_ratio(ps.heights, an.peak_heights(A_post, a.L_post, Bpost))

    step("decoding ArUco tags", 0.55)
    At, bt, ntag = detected_tag_affine(s.pre, s.post)
    res["aruco_tags"] = dict(n_tags=ntag, global_=describe(At))

    cor = an.Corrector(post)
    truth = truth_dict(grid, s.positions)
    regs = {"tags": (At, bt), "acf": acf_affine(F_acf, pre.shape, post.shape),
            "truth": s.positions.true_affine()}
    runs = {}
    for k, r in enumerate(registrations):
        step(f"resampling and CCF ({r})", 0.65 + 0.33 * k / len(registrations))
        A, b = regs[r]
        P = an.ccf_pipeline(pre, lambda A_, b_: cor(A_, b_, pre.shape), A, b, ps.Bpre, truth,
                            win=a.win, step=a.step, S=a.search, Lg=a.L_global,
                            pre_cache=ps.ccf_cache)
        res[f"ccf_after_{r}_correction"] = P["stats"]
        runs[r] = P
    step("done", 1.0)
    extras = dict(sim=s, pre_state=ps, acf_post=A_post, Bpost=Bpost, height_order=order,
                  height_ratio=ratio, runs=runs, registrations=regs)
    return res, extras


def run_fast(scen, grid=None, fld=None, which=None, registration=None, A_b=None):
    """Live-mode pipeline: field solve, island mapping, fast corrected post,
    global + windowed CCF (optionally restricted to `which` windows)."""
    grid = grid or load_grid()
    a = scen.analysis
    fld = fld or fieldmod.solve(scen.sites, scen.solver)
    pos = sim.island_positions(grid, scen, fld)
    ps = pre_state(scen, grid)
    reg = registration or a.registration
    if A_b is not None:
        A, b = A_b
    elif reg == "tags":
        A, b = simulated_tag_affine(grid, pos, a.tag_noise_px, scen.imaging.seed)
    elif reg == "truth":
        A, b = pos.true_affine()
    else:
        raise ValueError("ACF registration in live mode needs the post ACF (see run_faithful)")
    shape = ps.pre.shape
    P = an.ccf_pipeline(ps.pre, lambda A_, b_: corrected_fast(grid, scen, pos, A_, b_, shape),
                        A, b, ps.Bpre, truth_dict(grid, pos), win=a.win, step=a.step,
                        S=a.search, Lg=a.L_global, pre_cache=ps.ccf_cache, which=which)
    return dict(field=fld, positions=pos, pre_state=ps, ccf=P, A=A, b=b)
