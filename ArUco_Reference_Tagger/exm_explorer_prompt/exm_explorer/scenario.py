"""Scenario: every site and parameter, as dataclasses with JSON I/O."""

import json
from dataclasses import asdict, dataclass, field, fields
from typing import Optional

import numpy as np

LAMBDA_PRESETS = {"TExM": 3.3, "ExM": 4.0, "MAGNIFY": 10.0}


@dataclass
class Site:
    """Elliptical region carrying an eigenstrain. Design frame (um, y up);
    angles in degrees CCW from +x in the design frame."""
    cx: float = 375.0
    cy: float = 375.0
    a: float = 40.0                 # semi-axis along phi (um); sigma for 'gaussian'
    b: float = 40.0                 # semi-axis across phi (um)
    phi_deg: float = 0.0            # ellipse orientation
    eps1: float = -0.12             # principal eigenstrain along the eigenstrain angle
    eps2: float = -0.12             # ... and across it
    eps_angle_deg: Optional[float] = None   # None: follows phi
    lock_isotropic: bool = False    # eps2 follows eps1
    softness: float = 0.15          # tanh edge width as a fraction of the size
    profile: str = "tanh"           # 'tanh' or 'gaussian' (legacy patches)
    enabled: bool = True
    name: str = "site"
    color: str = "#ff9f1c"

    # ---- derived quantities shown in the editor
    @property
    def strain_angle_deg(self):
        return self.phi_deg if self.eps_angle_deg is None else self.eps_angle_deg

    @property
    def eps(self):
        """(eps1, eps2) with the isotropic lock applied."""
        return (self.eps1, self.eps1) if self.lock_isotropic else (self.eps1, self.eps2)

    @property
    def shape_aspect(self):
        """'site shape a/b'."""
        return self.a / self.b

    def set_shape_aspect(self, r):
        """Change a/b keeping the area."""
        ab = self.a * self.b
        self.a, self.b = float(np.sqrt(ab * r)), float(np.sqrt(ab / r))

    @property
    def strain_anisotropy(self):
        """'strain anisotropy (1+eps1)/(1+eps2)'."""
        e1, e2 = self.eps
        return (1 + e1) / (1 + e2)

    def set_strain_anisotropy(self, r):
        """Change (1+e1)/(1+e2) keeping the area change (1+e1)(1+e2)."""
        e1, e2 = self.eps
        area = (1 + e1) * (1 + e2)
        self.eps1, self.eps2 = float(np.sqrt(area * r) - 1), float(np.sqrt(area / r) - 1)
        self.lock_isotropic = False

    def tensor(self):
        """Eigenstrain tensor (design frame) at full strength."""
        e1, e2 = self.eps
        t = np.deg2rad(self.strain_angle_deg)
        R = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
        return R @ np.diag([e1, e2]) @ R.T


@dataclass
class Imaging:
    lam: float = 4.0
    theta_post_deg: float = 4.0
    theta_pre_deg: float = 0.6
    offset_pre_um: tuple = (6.0, -4.0)
    offset_post_um: tuple = (30.0, -20.0)
    gel_jitter_um: float = 0.40     # rms, post um
    print_jitter_um: float = 0.08   # rms, shared by pre and post
    psf_fwhm_um: float = 1.91
    um_px: float = 0.51
    noise: bool = True
    peak_e: float = 600.0
    bg_e: float = 100.0
    read_e: float = 4.0
    post_gain_exp: float = 0.16     # post signal x lambda^0.16
    margin_pre_um: float = 25.0
    margin_post_um: float = 50.0
    seed: int = 7


@dataclass
class Solver:
    model: str = "navier"           # 'navier' or 'kinematic' (legacy exm_sim)
    nu: float = 0.3
    mode: str = "plane_strain"      # or 'plane_stress'
    mean_strain: str = "zero"       # 'zero' (u periodic, zero mean strain) or 'traction_free'
    step_um: float = 2.0
    x0_um: float = -400.0           # padded grid [x0, x1), same as exm_sim.lag_field
    x1_um: float = 1150.0


@dataclass
class Analysis:
    registration: str = "tags"      # 'tags', 'acf' or 'truth'
    tag_noise_px: float = 0.3       # simulated tag detection noise (live mode)
    win: int = 64
    step: int = 24
    search: int = 12
    lattice_aware: bool = True
    L_pre: int = 330
    L_post: int = 1250
    L_global: int = 300


@dataclass
class Scenario:
    sites: list = field(default_factory=list)
    imaging: Imaging = field(default_factory=Imaging)
    solver: Solver = field(default_factory=Solver)
    analysis: Analysis = field(default_factory=Analysis)
    name: str = "untitled"

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        def build(kind, dd):
            names = {f.name for f in fields(kind)}
            obj = kind(**{k: v for k, v in (dd or {}).items() if k in names})
            for k in ("offset_pre_um", "offset_post_um"):
                if hasattr(obj, k):
                    setattr(obj, k, tuple(getattr(obj, k)))
            return obj
        return cls(sites=[build(Site, s) for s in d.get("sites", [])],
                   imaging=build(Imaging, d.get("imaging")),
                   solver=build(Solver, d.get("solver")),
                   analysis=build(Analysis, d.get("analysis")),
                   name=d.get("name", "untitled"))

    def save(self, path):
        with open(path, "w") as fh:
            json.dump(self.to_dict(), fh, indent=1)

    @classmethod
    def load(cls, path):
        with open(path) as fh:
            return cls.from_dict(json.load(fh))


# exm_sim.PATCHES: x, y, sigma, deficit (design um)
LEGACY_PATCHES = [(230.0, 530.0, 35.0, 0.15),
                  (520.0, 260.0, 40.0, 0.12),
                  (560.0, 590.0, 28.0, 0.15)]


def legacy_scenario():
    """The batch run of exm_sim.py: kinematic model, three Gaussian patches."""
    sites = [Site(cx=x, cy=y, a=s, b=s, eps1=-d, eps2=-d, lock_isotropic=True,
                  profile="gaussian", name=f"patch {k + 1}")
             for k, (x, y, s, d) in enumerate(LEGACY_PATCHES)]
    return Scenario(sites=sites, solver=Solver(model="kinematic"), name="exm_sim batch run")


# ===================================================================== presets
BOX_CENTRES_UM = 11.5 + 145.4 * (np.arange(5) + 0.5)     # box centres, away from tags and dashes


def example_scenario():
    return Scenario(sites=[
        Site(cx=230, cy=530, a=40, b=40, eps1=-0.12, eps2=-0.12, lock_isotropic=True,
             name="lagging patch", color="#d95926"),
        Site(cx=520, cy=260, a=60, b=30, phi_deg=30, eps1=0.05, eps2=-0.05,
             name="anisotropic site", color="#3987e5")], name="example")


def smooth_sites():
    spec = [(200, 200, 170, -0.04), (560, 180, 140, 0.03), (380, 420, 200, -0.03),
            (180, 600, 150, 0.04), (600, 600, 160, -0.05)]
    return [Site(cx=x, cy=y, a=r, b=r, eps1=e, eps2=e, lock_isotropic=True, softness=0.5,
                 name=f"broad {k}") for k, (x, y, r, e) in enumerate(spec)]


def local_sites(n=30, seed=11):
    rng = np.random.default_rng(seed)
    return [Site(cx=float(x), cy=float(y), a=float(r), b=float(r), eps1=-0.12, eps2=-0.12,
                 lock_isotropic=True, softness=0.15, name=f"small {k}")
            for k, (x, y, r) in enumerate(zip(rng.uniform(40, 710, n), rng.uniform(40, 710, n),
                                              rng.uniform(12, 22, n)))]


def aniso_sites(aligned, seed=12):
    rng = np.random.default_rng(seed)
    out = []
    for i, x in enumerate(BOX_CENTRES_UM):
        for j, y in enumerate(BOX_CENTRES_UM):
            ang = 30.0 if aligned else float(rng.uniform(0, 180))
            out.append(Site(cx=x, cy=y, a=45, b=45, eps1=0.06, eps2=-0.06, eps_angle_deg=ang,
                            softness=0.3, name=f"aniso {i}{j}"))
    return out


def _workshop(sites, name):
    s = Scenario(sites=sites, name=name)
    s.imaging.seed = 1
    return s


PRESETS = {
    "example": example_scenario,
    "exm_sim batch run": legacy_scenario,
    "control (no sites)": lambda: Scenario(name="control"),
    "workshop: smooth": lambda: _workshop(smooth_sites(), "workshop smooth"),
    "workshop: local": lambda: _workshop(local_sites(), "workshop local"),
    "workshop: aligned": lambda: _workshop(aniso_sites(True), "workshop aligned"),
    "workshop: random": lambda: _workshop(aniso_sites(False), "workshop random"),
}
