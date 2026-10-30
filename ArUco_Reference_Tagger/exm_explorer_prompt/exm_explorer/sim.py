"""Scenario -> island positions -> images (the exm_sim pipeline).

Random numbers are drawn in exactly the order of exm_sim.simulate so that the
same seed reproduces the batch run: print jitter, pre jitter (sigma 0, but it
still consumes draws), gel jitter, then pre noise and post noise. The jitter
draws are standard normals kept per seed, so moving a site never reshuffles
them.
"""

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from . import field as fieldmod
from .frames import Placement, design_to_sample, fit_affine, post_size_px, pre_size_px, rot, \
    vec_design_to_sample
from .grid import load_grid
from .render import expose, expose_clean, psf_sigma_px, render_exact


@dataclass(frozen=True)
class Draws:
    z_print: np.ndarray
    z_pre: np.ndarray
    z_gel: np.ndarray
    noise_state: dict            # bit generator state after the jitter draws

    def noise_rng(self):
        rng = np.random.default_rng()
        rng.bit_generator.state = self.noise_state
        return rng


@lru_cache(maxsize=4)
def draws(seed, n):
    rng = np.random.default_rng(seed)
    z_print = rng.standard_normal((n, 2))
    z_pre = rng.standard_normal((n, 2))
    z_gel = rng.standard_normal((n, 2))
    return Draws(z_print, z_pre, z_gel, rng.bit_generator.state)


@dataclass
class Positions:
    pre_px: np.ndarray           # (N, 2) island centres in the pre image
    post_px: np.ndarray          # (N, 2) island centres in the post image
    xy_print: np.ndarray         # (N, 2) design um incl. print jitter
    u_design: np.ndarray         # (N, 2) displacement at each island, design um
    pre: Placement
    post: Placement

    def true_affine(self):
        """Least-squares pre px -> post px over all islands: (A, b)."""
        return fit_affine(self.pre_px, self.post_px)


def placements(im):
    n_pre = pre_size_px(im.margin_pre_um, im.um_px)
    n_post = post_size_px(im.lam, im.theta_post_deg, im.offset_post_um, im.margin_post_um, im.um_px)
    return (Placement(1.0, im.theta_pre_deg, tuple(im.offset_pre_um), n_pre, im.um_px),
            Placement(im.lam, im.theta_post_deg, tuple(im.offset_post_um), n_post, im.um_px))


def island_positions(grid, scen, fld):
    im = scen.imaging
    dr = draws(im.seed, grid.n)
    xy = grid.xy + im.print_jitter_um * dr.z_print          # same print, pre and post
    u = fld.u_at(grid.xy)                                     # lag acts on the design
    pre, post = placements(im)
    pre_px = pre.to_px(design_to_sample(xy), 0.0 * dr.z_pre)
    post_px = post.to_px(design_to_sample(xy + u), im.gel_jitter_um * dr.z_gel)
    return Positions(pre_px=pre_px, post_px=post_px, xy_print=xy, u_design=u, pre=pre, post=post)


def rects(grid, isl_px, theta_deg, um_px):
    """Rectangle centres and half sizes in px for islands at isl_px. Islands
    are rigid: offsets rotate with the stage only and keep the printed size."""
    off = vec_design_to_sample(grid.rect_off) @ rot(theta_deg).T / um_px
    p = isl_px[grid.rect_isl] + off
    h = grid.rect_half / um_px
    return p[:, 0], p[:, 1], h[:, 0], h[:, 1]


def render_clean(grid, isl_px, placement, psf_fwhm_um, region=None):
    um_px = placement.um_px
    return render_exact(placement.size_px, *rects(grid, isl_px, placement.theta_deg, um_px),
                        placement.theta_deg, psf_sigma_px(psf_fwhm_um, um_px), region=region)


@dataclass
class SimResult:
    scenario: object
    field: object
    positions: Positions
    pre: np.ndarray              # uint16
    post: np.ndarray             # uint16


def simulate(scen, grid=None, fld=None):
    """Full exact render of pre and post (the faithful path)."""
    grid = grid or load_grid()
    fld = fld or fieldmod.solve(scen.sites, scen.solver)
    pos = island_positions(grid, scen, fld)
    im = scen.imaging
    pre_clean = render_clean(grid, pos.pre_px, pos.pre, im.psf_fwhm_um)
    post_clean = render_clean(grid, pos.post_px, pos.post, im.psf_fwhm_um)
    gain = im.lam ** im.post_gain_exp
    if im.noise:
        rng = draws(im.seed, grid.n).noise_rng()
        pre = expose(pre_clean, im.peak_e, im.bg_e, im.read_e, rng)
        del pre_clean
        post = expose(post_clean, im.peak_e * gain, im.bg_e * gain, im.read_e, rng)
    else:
        pre = expose_clean(pre_clean, im.peak_e, im.bg_e)
        post = expose_clean(post_clean, im.peak_e * gain, im.bg_e * gain)
    return SimResult(scenario=scen, field=fld, positions=pos, pre=pre, post=post)
