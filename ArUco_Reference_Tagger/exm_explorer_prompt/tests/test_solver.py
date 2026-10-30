"""Acceptance tests 2-4: the displacement solver."""

import numpy as np
import pytest

from exm_explorer import field
from exm_explorer.scenario import Site, Solver


def _at(fld, arr, x, y):
    i = int(round((x - fld.xs[0]) / fld.step))
    j = int(round((y - fld.xs[0]) / fld.step))
    return arr[j, i]


# ------------------------------------------------------------------ test 2
@pytest.mark.parametrize("eps1,eps2,ang", [(-0.1, -0.1, 0.0), (0.05, -0.03, 30.0)])
@pytest.mark.parametrize("model", ["navier", "kinematic"])
def test_uniform_site_gives_grad_u_equal_eps(eps1, eps2, ang, model):
    if model == "kinematic" and eps1 != eps2:
        pytest.skip("kinematic keeps the isotropic part only")
    site = Site(cx=375, cy=375, a=1e4, b=1e4, eps1=eps1, eps2=eps2, eps_angle_deg=ang, softness=0.1)
    cfg = Solver(model=model, mean_strain="traction_free")
    fld = field.solve([site], cfg)
    a, b, c, d = fld.grad
    T = site.tensor()
    inner = slice(50, -50)        # away from the boundary
    assert np.allclose(a[inner, inner], T[0, 0], atol=1e-6)
    assert np.allclose(d[inner, inner], T[1, 1], atol=1e-6)
    assert np.allclose(b[inner, inner] + c[inner, inner], 2 * T[0, 1], atol=1e-6)
    # with the default zero-mean strain a uniform eigenstrain moves nothing
    fld0 = field.solve([site], Solver(model=model))
    assert np.abs(fld0.ux).max() < 1e-6 and np.abs(fld0.uy).max() < 1e-6   # tanh tail only


# ------------------------------------------------------------------ test 3
@pytest.mark.parametrize("nu", [0.3, 0.0, 0.45])
def test_eshelby_circular_inclusion(nu):
    R, eps = 60.0, -0.1
    site = Site(cx=375, cy=375, a=R, b=R, eps1=eps, eps2=eps, softness=0.0)
    fld = field.solve([site], Solver(nu=nu, mode="plane_strain"))
    a, b, c, d = fld.grad
    expect = eps / (2 * (1 - nu))
    X, Y = np.meshgrid(fld.xs - 375, fld.xs - 375)
    r = np.hypot(X, Y)
    inside = r < 0.8 * R
    for comp in (a, d):
        assert np.all(np.abs(comp[inside] / expect - 1) < 0.03)
    assert np.abs(b[inside] + c[inside]).max() < 0.03 * abs(expect)
    # outside: u_r = expect R^2 / r, i.e. decays as 1/r. The periodic images
    # add a uniform strain of about (area fraction) * expect, so fit
    # u_r = A / r + B r and check A, and that B is that small image term.
    rows, ur_all = [], []
    for rr in (90.0, 120.0, 180.0, 240.0, 300.0):
        for t in np.deg2rad([0, 37, 90, 145, 210, 300]):
            x, y = 375 + rr * np.cos(t), 375 + rr * np.sin(t)
            ux, uy = fld.interp(fld.ux, x, y), fld.interp(fld.uy, x, y)
            ur = ux * np.cos(t) + uy * np.sin(t)
            ut = -ux * np.sin(t) + uy * np.cos(t)
            assert abs(ut) < 0.01 * abs(ur)
            rows.append((1 / rr, rr)); ur_all.append(ur)
    (A, B), *_ = np.linalg.lstsq(np.array(rows), np.array(ur_all), rcond=None)
    assert abs(A / (expect * R * R) - 1) < 0.03
    frac = np.pi * R * R / (fld.xs[-1] - fld.xs[0] + fld.step) ** 2
    assert abs(B) < 2 * frac * abs(expect)
    resid = np.array(ur_all) - np.array(rows) @ [A, B]
    assert np.abs(resid).max() < 0.01 * abs(expect) * R


# ------------------------------------------------------------------ test 4
def _centre_stretch(fld, x, y):
    a, b, c, d = fld.grad
    J = np.eye(2) + np.array([[_at(fld, a, x, y), _at(fld, b, x, y)],
                              [_at(fld, c, x, y), _at(fld, d, x, y)]])
    U, S, Vt = np.linalg.svd(J)
    return S[0] / S[1], np.degrees(np.arctan2(Vt[0, 1], Vt[0, 0])) % 180


def _angdiff(a, b):
    return abs((a - b + 90) % 180 - 90)


@pytest.mark.parametrize("phi", [0.0, 30.0, 75.0, 140.0])
def test_anisotropic_site_aligned_with_axis(phi):
    site = Site(cx=375, cy=375, a=60, b=30, phi_deg=phi, eps1=0.05, eps2=-0.05, softness=0.1)
    fld = field.solve([site], Solver())
    aniso, ang = _centre_stretch(fld, 375, 375)
    assert aniso > 1.02
    assert _angdiff(ang, phi) < 2.0
    # the truth map agrees with the direct SVD
    tr = fld.truth()
    assert _angdiff(_at(fld, tr["aniso_dir"], 375, 375), phi) < 2.0
    assert abs(_at(fld, tr["anisotropy"], 375, 375) - aniso) < 1e-9


def test_rotating_site_rotates_field():
    base = Site(cx=375, cy=375, a=60, b=30, phi_deg=0, eps1=0.05, eps2=-0.05, softness=0.1)
    rotd = Site(cx=375, cy=375, a=60, b=30, phi_deg=90, eps1=0.05, eps2=-0.05, softness=0.1)
    f0 = field.solve([base], Solver())
    f1 = field.solve([rotd], Solver())
    # rotating by 90 deg about the centre: u1(R x) = R u0(x)
    rng = np.random.default_rng(3)
    pts = rng.uniform(-150, 150, (200, 2))
    u0 = f0.u_at(pts + 375)
    Rq = np.array([[0, -1], [1, 0]])
    u1 = f1.u_at(pts @ Rq.T + 375)
    assert np.abs(u1 - u0 @ Rq.T).max() < 1e-3 * np.abs(u0).max() + 1e-6


def test_shape_and_strain_proportion_controls():
    s = Site(a=60, b=30, eps1=0.05, eps2=-0.05)
    area = s.a * s.b
    s.set_shape_aspect(3.0)
    assert np.isclose(s.shape_aspect, 3.0) and np.isclose(s.a * s.b, area)
    s.set_strain_anisotropy(1.2)
    assert np.isclose(s.strain_anisotropy, 1.2)
    assert np.isclose((1 + s.eps1) * (1 + s.eps2), 1.05 * 0.95)


def test_plane_stress_inclusion():
    """Plane stress: interior strain = eps* (1 + nu) / 2."""
    nu, eps = 0.3, -0.1
    site = Site(cx=375, cy=375, a=60, b=60, eps1=eps, eps2=eps, softness=0.0)
    fld = field.solve([site], Solver(nu=nu, mode="plane_stress"))
    a = fld.grad[0]
    assert abs(_at(fld, a, 375, 375) / (eps * (1 + nu) / 2) - 1) < 0.03
