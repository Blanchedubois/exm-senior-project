"""Every frame conversion in one place.

Frames
  design   um, origin at the bottom-left of the print, x right, y UP
  sample   um, the print as the camera sees it before any stage motion:
           x right, y DOWN, same origin corner flipped (y_s = FIELD - y_d)
  pre px   pixels of the pre (1x) image, y down
  post px  pixels of the post (lambda x) image, y down

design -> sample is a reflection (det = -1). sample -> image is a similarity
about the grid centre: p_px = (s * R(theta) (x_s - c) + offset) / um_px + n/2,
which is exactly exm_sim.place().
"""

from dataclasses import dataclass

import numpy as np

FIELD_UM = 750.0
UM_PX = 0.51
CENTRE_UM = np.array([FIELD_UM / 2, FIELD_UM / 2])


def rot(deg):
    t = np.deg2rad(deg)
    return np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])


# ----------------------------------------------------------------- design <-> sample
def design_to_sample(xy):
    """Positions (N, 2) design um (y up) -> sample um (y down)."""
    xy = np.asarray(xy, float)
    return np.stack([xy[..., 0], FIELD_UM - xy[..., 1]], -1)


sample_to_design = design_to_sample          # the reflection is its own inverse


def vec_design_to_sample(v):
    """Displacements / offsets (no origin shift): flip the y component."""
    v = np.asarray(v, float)
    return np.stack([v[..., 0], -v[..., 1]], -1)


vec_sample_to_design = vec_design_to_sample


def angle_design_to_sample(deg):
    """An angle measured CCW from +x in the design frame, as seen in an image
    (y down, so angles change sign)."""
    return -np.asarray(deg, float)


# ----------------------------------------------------------------- sample <-> image
@dataclass(frozen=True)
class Placement:
    """Similarity from sample um to image px about the grid centre."""
    scale: float
    theta_deg: float
    offset_um: tuple
    size_px: int
    um_px: float = UM_PX

    @property
    def matrix(self):
        """Linear part, sample um -> px."""
        return self.scale * rot(self.theta_deg) / self.um_px

    def to_px(self, xy_sample_um, jitter_um=None):
        p = (np.asarray(xy_sample_um, float) - CENTRE_UM) @ (self.scale * rot(self.theta_deg)).T
        off = np.asarray(self.offset_um, float)
        p = p + (off if jitter_um is None else off + jitter_um)   # same order as exm_sim
        return p / self.um_px + self.size_px / 2.0

    def to_sample(self, px):
        """Inverse of to_px (without jitter)."""
        p = (np.asarray(px, float) - self.size_px / 2.0) * self.um_px - np.asarray(self.offset_um, float)
        return p @ np.linalg.inv(self.scale * rot(self.theta_deg)).T + CENTRE_UM

    def design_to_px(self, xy_design_um):
        return self.to_px(design_to_sample(xy_design_um))

    def px_to_design(self, px):
        return sample_to_design(self.to_sample(px))

    def design_affine(self):
        """(A, b) with px = A @ xy_design + b. det(A) < 0."""
        A = self.matrix @ np.diag([1.0, -1.0])
        b = self.design_to_px(np.zeros(2))
        return A, b


def handedness(placement):
    """Sign of det of design -> image px. Always -1 for a real image."""
    return int(np.sign(np.linalg.det(placement.design_affine()[0])))


def pre_size_px(margin_um=25.0, um_px=UM_PX):
    return int(np.ceil((FIELD_UM + 2 * margin_um) / um_px))


def post_size_px(lam, theta_deg, offset_um, margin_um=50.0, um_px=UM_PX):
    """Square post image that holds the rotated, expanded grid (exm_sim)."""
    t = np.deg2rad(theta_deg)
    ext = lam * FIELD_UM / 2 * (abs(np.cos(t)) + abs(np.sin(t)))
    return int(np.ceil(2 * (ext + margin_um + max(map(abs, offset_um))) / um_px))


# ----------------------------------------------------------------- affines
def fit_affine(src, dst):
    """Least-squares dst = A src + b. Returns (A, b)."""
    src, dst = np.asarray(src, float), np.asarray(dst, float)
    T, *_ = np.linalg.lstsq(np.c_[src, np.ones(len(src))], dst, rcond=None)
    return T[:2].T, T[2]


def describe(F):
    """Scale, anisotropy, stretch direction and rotation of a 2x2 linear map
    (exm_analysis.describe)."""
    U, S, Vt = np.linalg.svd(F)
    R = U @ Vt
    return dict(scale=float(np.sqrt(S[0] * S[1])), s_max=float(S[0]), s_min=float(S[1]),
                anisotropy=float(S[0] / S[1]),
                stretch_dir_deg=float(np.degrees(np.arctan2(Vt[0, 1], Vt[0, 0])) % 180),
                rotation_deg=float(np.degrees(np.arctan2(R[1, 0], R[0, 0]))))
