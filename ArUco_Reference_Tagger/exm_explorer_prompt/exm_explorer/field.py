"""Eigenstrain sites, displacement solvers and ground-truth fields.

Everything here lives in the DESIGN frame (um, y up) on a padded periodic
grid: rows are y, columns are x, both sampled at xs.

Models
  navier     isotropic linear elasticity. sigma = C : (eps(u) - eps*), div sigma = 0
             -> per wavevector  [mu k^2 I + (lam_L + mu) k k^T] u^ = -i (C : eps*^) k
             with mu = 1 (it cancels). Plane strain lam_L = 2 mu nu / (1 - 2 nu),
             plane stress lam_L = 2 mu nu / (1 - nu).
  kinematic  exm_sim.lag_field: isotropic part only, u = grad phi, lap phi = 2 e.

Mean strain
  zero           u^(0) = 0 and no mean gradient: sites leave the global
                 expansion alone (exm_sim behaviour).
  traction_free  adds the homogeneous strain <eps*> over the padded domain,
                 i.e. zero average stress. A uniform eigenstrain then gives
                 grad u = eps*.
"""

from dataclasses import dataclass
from functools import cached_property, lru_cache

import numpy as np
from scipy import fft as sfft
from scipy import ndimage

from .frames import CENTRE_UM


# ===================================================================== sites
def site_envelope(site, X, Y, step):
    """Envelope f in [0, 1] of one site sampled at X, Y (design um)."""
    t = np.deg2rad(site.phi_deg)
    dx, dy = X - site.cx, Y - site.cy
    u = np.cos(t) * dx + np.sin(t) * dy
    v = -np.sin(t) * dx + np.cos(t) * dy
    r2 = (u / site.a) ** 2 + (v / site.b) ** 2
    if site.profile == "gaussian":
        return np.exp(-r2 / 2)
    # a sharp edge is drawn about one grid cell wide so it does not alias
    w = max(site.softness, 0.35 * step / min(site.a, site.b))
    return 0.5 * (1 - np.tanh((np.sqrt(r2) - 1) / w))


def site_reach(site, step):
    """Distance (um) beyond which the envelope is negligible."""
    if site.profile == "gaussian":
        return 8.5 * max(site.a, site.b)
    w = max(site.softness, 0.35 * step / min(site.a, site.b))
    return (1 + 9 * w) * max(site.a, site.b)


def eigenstrain_field(sites, xs):
    """Sum of the eigenstrain tensors of all enabled sites (overlaps add).
    Returns exx, eyy, exy on the xs x xs grid (rows = y)."""
    n, step = len(xs), xs[1] - xs[0]
    exx, eyy, exy = (np.zeros((n, n)) for _ in range(3))
    for s in sites:
        if not s.enabled:
            continue
        T = s.tensor()
        if not np.any(T):
            continue
        reach = site_reach(s, step)
        i0 = max(int(np.floor((s.cx - reach - xs[0]) / step)), 0)
        i1 = min(int(np.ceil((s.cx + reach - xs[0]) / step)) + 1, n)
        j0 = max(int(np.floor((s.cy - reach - xs[0]) / step)), 0)
        j1 = min(int(np.ceil((s.cy + reach - xs[0]) / step)) + 1, n)
        if i0 >= i1 or j0 >= j1:
            continue
        X, Y = np.meshgrid(xs[i0:i1], xs[j0:j1])
        f = site_envelope(s, X, Y, step)
        exx[j0:j1, i0:i1] += f * T[0, 0]
        eyy[j0:j1, i0:i1] += f * T[1, 1]
        exy[j0:j1, i0:i1] += f * T[0, 1]
    return exx, eyy, exy


# ===================================================================== solvers
def lame(nu, mode):
    """lam_L for mu = 1."""
    if mode == "plane_strain":
        return 2 * nu / (1 - 2 * nu)
    if mode == "plane_stress":
        return 2 * nu / (1 - nu)
    raise ValueError(mode)


@lru_cache(maxsize=8)
def navier_operator(n, step, nu, mode):
    """k-space pieces for an n x n grid: (kx, ky, gxx, gxy, gyy, lam_L) with
    G = M^-1 = (I - c k k^T / k^2) / k^2, c = (lam + mu) / (lam + 2 mu)."""
    lam = lame(nu, mode)
    kx = (2 * np.pi * sfft.rfftfreq(n, step))[None, :]
    ky = (2 * np.pi * sfft.fftfreq(n, step))[:, None]
    k2 = kx ** 2 + ky ** 2
    k2[0, 0] = 1.0
    c = (lam + 1) / (lam + 2)
    gxx = (1 - c * kx ** 2 / k2) / k2
    gyy = (1 - c * ky ** 2 / k2) / k2
    gxy = -c * kx * ky / k2 ** 2
    for g in (gxx, gyy, gxy):
        g[0, 0] = 0.0
    return kx, ky, gxx, gxy, gyy, lam


def solve_navier(exx, eyy, exy, step, nu=0.3, mode="plane_strain"):
    n = exx.shape[0]
    kx, ky, gxx, gxy, gyy, lam = navier_operator(n, float(step), float(nu), mode)
    tr = exx + eyy
    Txx = sfft.rfft2(lam * tr + 2 * exx, workers=-1)
    Tyy = sfft.rfft2(lam * tr + 2 * eyy, workers=-1)
    Txy = sfft.rfft2(2 * exy, workers=-1)
    tx = -1j * (Txx * kx + Txy * ky)
    ty = -1j * (Txy * kx + Tyy * ky)
    ux = sfft.irfft2(gxx * tx + gxy * ty, s=(n, n), workers=-1)
    uy = sfft.irfft2(gxy * tx + gyy * ty, s=(n, n), workers=-1)
    return ux, uy


def solve_kinematic(exx, eyy, step):
    """exm_sim.lag_field, line for line: e is the isotropic part."""
    n = exx.shape[0]
    e = (exx + eyy) / 2
    src = 2 * e - (2 * e).mean()
    k = np.fft.fftfreq(n, step)
    KX, KY = np.meshgrid(k, k)
    k2 = (2 * np.pi) ** 2 * (KX ** 2 + KY ** 2)
    k2[0, 0] = 1
    ph = -np.fft.fft2(src) / k2
    ph[0, 0] = 0
    ux = np.real(np.fft.ifft2(1j * 2 * np.pi * KX * ph))
    uy = np.real(np.fft.ifft2(1j * 2 * np.pi * KY * ph))
    return ux, uy


# ===================================================================== field
@dataclass
class Field:
    """Displacement u(x) (design um, y up) and the eigenstrain behind it."""
    xs: np.ndarray
    ux: np.ndarray
    uy: np.ndarray
    exx: np.ndarray
    eyy: np.ndarray
    exy: np.ndarray

    @property
    def step(self):
        return float(self.xs[1] - self.xs[0])

    def interp(self, f, x, y, order=1):
        x, y = np.asarray(x, float), np.asarray(y, float)
        out = ndimage.map_coordinates(f, [np.atleast_1d(y - self.xs[0]) / self.step,
                                          np.atleast_1d(x - self.xs[0]) / self.step],
                                      order=order, mode="nearest")
        return out.reshape(x.shape)

    def u_at(self, xy):
        """u at design points (N, 2) -> (N, 2), bilinear as in exm_sim."""
        xy = np.asarray(xy, float)
        return np.c_[self.interp(self.ux, xy[:, 0], xy[:, 1]),
                     self.interp(self.uy, xy[:, 0], xy[:, 1])]

    @cached_property
    def grad(self):
        """(dux_dx, dux_dy, duy_dx, duy_dy), central differences."""
        dux_dy, dux_dx = np.gradient(self.ux, self.step)
        duy_dy, duy_dx = np.gradient(self.uy, self.step)
        return dux_dx, dux_dy, duy_dx, duy_dy

    def truth(self, lam=1.0):
        """Ground-truth maps on the grid (design frame):
        expansion   lam * sqrt(det(I + grad u))
        anisotropy  s_max / s_min of I + grad u
        aniso_dir   direction of the largest stretch (deg, design frame, 0..180)
        rotation    local rotation of I + grad u (deg, CCW in the design frame)"""
        a, b, c, d = self.grad
        J00, J01, J10, J11 = 1 + a, b, c, 1 + d
        det = J00 * J11 - J01 * J10
        fro = J00 ** 2 + J01 ** 2 + J10 ** 2 + J11 ** 2
        disc = np.sqrt(np.maximum(fro ** 2 - 4 * det ** 2, 0))
        s_max = np.sqrt((fro + disc) / 2)
        s_min = np.sqrt(np.maximum((fro - disc) / 2, 1e-30))
        p = J00 ** 2 + J10 ** 2          # J^T J
        q = J00 * J01 + J10 * J11
        r = J01 ** 2 + J11 ** 2
        return dict(expansion=lam * np.sqrt(np.abs(det)),
                    anisotropy=s_max / s_min,
                    aniso_dir=np.degrees(0.5 * np.arctan2(2 * q, p - r)) % 180,
                    rotation=np.degrees(np.arctan2(J10 - J01, J00 + J11)))


def make_grid(cfg):
    return np.arange(cfg.x0_um, cfg.x1_um, cfg.step_um)


def solve(sites, cfg):
    """Displacement field for a list of sites and a scenario.Solver."""
    xs = make_grid(cfg)
    exx, eyy, exy = eigenstrain_field(sites, xs)
    step = cfg.step_um
    if cfg.model == "kinematic":
        ux, uy = solve_kinematic(exx, eyy, step)
    elif cfg.model == "navier":
        ux, uy = solve_navier(exx, eyy, exy, step, cfg.nu, cfg.mode)
    else:
        raise ValueError(cfg.model)
    if cfg.mean_strain == "traction_free":
        E = np.array([[exx.mean(), exy.mean()], [exy.mean(), eyy.mean()]])
        if cfg.model == "kinematic":
            E = np.eye(2) * np.trace(E) / 2
        X, Y = np.meshgrid(xs - CENTRE_UM[0], xs - CENTRE_UM[1])
        ux = ux + E[0, 0] * X + E[0, 1] * Y
        uy = uy + E[1, 0] * X + E[1, 1] * Y
    elif cfg.mean_strain != "zero":
        raise ValueError(cfg.mean_strain)
    return Field(xs=xs, ux=ux, uy=uy, exx=exx, eyy=eyy, exy=exy)
