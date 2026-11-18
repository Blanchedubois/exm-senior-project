"""
rwtag.pairing
=============
Cross-image comparison of tagged frames (docs/06). Ported from
reference-warp-tagger/rwtag/pairing.py, now carrying covariances.

  pair_frames      identity join of any two accepted TagResults (A <-> B), both
                   positions and both covariances per shared tag
  rigid_align      V1's alignment: Kabsch rotation of all paired dots about a
                   common box centre, translation pinning the centres, scale
                   UNTOUCHED (growth stays visible); rotation sigma by bootstrap
  similarity_align uniform scale + rotation + translation (scale removed: only
                   the non-uniform part remains); parameter covariance by bootstrap
  overlay_composite cyan / red composite under either alignment
  field            displacement u = aligned compared - reference per paired dot,
                   with its covariance, plus the local deformation gradient
                   (rwtag.deformation) and the compared frame's deviation from
                   its own uniform-expansion model
  heat_grid        V1's masked interpolation onto a regular grid

Dropped from V1: expansion_rows / distributions / summary CSV writers (the
Summary tab; analysis is downstream). NO Qt.
"""
from __future__ import annotations
import csv
from dataclasses import dataclass, field
import math
import numpy as np

from . import deformation as DF
from .refwarp import warp as W


def category(tag: str) -> str:
    return tag.split("|")[0]


def tag_box(tag: str):
    parts = tag.split("|")
    if len(parts) >= 2 and parts[1].startswith("B"):
        try:
            return int(parts[1][1:])
        except ValueError:
            return None
    return None


def _cov(tr, tag):
    c = (tr.cov or {}).get(tag)
    if c is None:
        return np.full((2, 2), np.nan)
    return np.array([[c[0], c[2]], [c[2], c[1]]])


@dataclass
class Pairs:
    tags: list
    P0: np.ndarray                  # (n,2) reference frame (corrected px)
    P1: np.ndarray                  # (n,2) compared frame
    C0: np.ndarray                  # (n,2,2)
    C1: np.ndarray
    label0: float = None
    label1: float = None
    cats: list = field(default_factory=list)

    def select(self, kinds):
        m = np.array([c in kinds for c in self.cats], bool)
        return Pairs([t for t, k in zip(self.tags, m) if k], self.P0[m], self.P1[m], self.C0[m], self.C1[m],
                     self.label0, self.label1, [c for c, k in zip(self.cats, m) if k])

    def as_dict(self):
        return {t: (*self.P0[i], *self.P1[i]) for i, t in enumerate(self.tags)}


def pair_frames(tr0, tr1, kinds=None) -> Pairs:
    """Join two TagResults on tag identity."""
    tags = sorted(t for t in tr1.tags if t in tr0.tags and (kinds is None or category(t) in kinds))
    P0 = np.array([tr0.tags[t] for t in tags], float).reshape(-1, 2)
    P1 = np.array([tr1.tags[t] for t in tags], float).reshape(-1, 2)
    C0 = np.array([_cov(tr0, t) for t in tags]).reshape(-1, 2, 2)
    C1 = np.array([_cov(tr1, t) for t in tags]).reshape(-1, 2, 2)
    return Pairs(tags, P0, P1, C0, C1, tr0.label, tr1.label, [category(t) for t in tags])


def pair_tags(init_tags: dict, exp_tags: dict, kinds=None) -> dict:
    """V1 API: {tag: (x0, y0, x1, y1)}."""
    return {t: (float(init_tags[t][0]), float(init_tags[t][1]), float(xy[0]), float(xy[1]))
            for t, xy in exp_tags.items() if t in init_tags and (kinds is None or category(t) in kinds)}


def pair_counts(pairs: Pairs, tr0, tr1) -> dict:
    n0 = sum(1 for t in tr0.tags if category(t) == "dot"); n1 = sum(1 for t in tr1.tags if category(t) == "dot")
    nd = sum(1 for c in pairs.cats if c == "dot")
    by = {}
    for c in pairs.cats:
        by[c] = by.get(c, 0) + 1
    return {"n_ref": len(tr0.tags), "n_cmp": len(tr1.tags), "n_pairs": len(pairs.tags), "n_dot_ref": n0,
            "n_dot_cmp": n1, "n_dot_pairs": nd, "dot_pair_frac": nd / min(n0, n1) if min(n0, n1) else 0.0,
            "by_category": by}


def common_boxes(pairs: Pairs):
    """[(N, paired dot count)] best first."""
    counts = {}
    for t, c in zip(pairs.tags, pairs.cats):
        if c == "dot":
            N = tag_box(t)
            if N is not None:
                counts[N] = counts.get(N, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def kabsch_rotation(P_move, P_target):
    """Least-squares rotation (det +1, no scale) of centred point sets."""
    H = np.asarray(P_move).T @ np.asarray(P_target)
    U, _S, Vt = np.linalg.svd(H)
    V = Vt.T
    d = np.sign(np.linalg.det(V @ U.T)) or 1.0
    return V @ np.diag([1.0, d]) @ U.T


def rigid_align(pairs: Pairs, box_n, c0, c1, n_boot=200, seed=0) -> dict:
    """Compared -> reference: p' = R (p - c1) + c0; R = Kabsch of all paired dots
    about the two box centres; scale untouched. angle_sigma by bootstrap."""
    d = pairs.select(("dot",))
    if len(d.tags) < 3:
        return {"ok": False, "reason": f"only {len(d.tags)} paired dots"}
    c0 = np.asarray(c0, float); c1 = np.asarray(c1, float)
    R = kabsch_rotation(d.P1 - c1, d.P0 - c0)
    ang = math.degrees(math.atan2(R[1, 0], R[0, 0]))
    rng = np.random.default_rng(seed)
    boots, fits = [], []
    for _ in range(n_boot):
        k = rng.integers(0, len(d.P0), len(d.P0))
        Rb = kabsch_rotation(d.P1[k] - c1, d.P0[k] - c0)
        boots.append(math.degrees(math.atan2(Rb[1, 0], Rb[0, 0])))
        fits.append((1.0, Rb, c0 - Rb @ c1))
    return {"ok": True, "kind": "rigid", "R": R, "s": 1.0, "t": c0 - R @ c1, "box": int(box_n), "c0": c0, "c1": c1,
            "angle_deg": -ang, "angle_sigma_deg": float(np.std(boots)), "n_pairs": int(len(d.P0)), "fits": fits}


def similarity_align(pairs: Pairs, n_boot=200, seed=0) -> dict:
    """Compared -> reference with the uniform scale removed: p' = s R p + t over all
    paired dots (rotation proper; both frames share handedness). Bootstrap
    covariance of (angle, x, y at the reference centroid, s)."""
    from .errors import bootstrap_alignment
    d = pairs.select(("dot",))
    if len(d.tags) < 3:
        return {"ok": False, "reason": f"only {len(d.tags)} paired dots"}
    b = bootstrap_alignment(d.P1, d.P0, kind="similarity", n_boot=n_boot, seed=seed)
    return {"ok": True, "kind": "similarity", "R": b["R"], "s": b["s"], "t": b["t"], "fits": b["fits"],
            "angle_deg": -float(b["params"][0]), "angle_sigma_deg": float(math.sqrt(b["cov"][0, 0])),
            "s_sigma": float(math.sqrt(b["cov"][3, 3])), "cov": b["cov"], "cov_names": b["names"],
            "n_pairs": int(len(d.P0)), "expansion": 1.0 / b["s"]}


def apply_align(points, align):
    """Compared-frame px -> reference frame px under either alignment."""
    P = np.asarray(points, float).reshape(-1, 2)
    return align.get("s", 1.0) * P @ np.asarray(align["R"]).T + np.asarray(align["t"])


apply_rigid = apply_align


def align_point_cov(points, align):
    """(n,2,2) covariance of each mapped point due to the ALIGNMENT's own
    uncertainty: the spread of the point under the bootstrap fits."""
    P = np.asarray(points, float).reshape(-1, 2)
    fits = align.get("fits") or []
    if len(fits) < 3 or not len(P):
        return np.zeros((len(P), 2, 2))
    Q = np.stack([s * P @ np.asarray(R).T + np.asarray(t) for s, R, t in fits])     # (b, n, 2)
    d = Q - Q.mean(0)
    return np.einsum("bni,bnj->nij", d, d) / (len(fits) - 1)


def affine_align(pairs: Pairs, n_boot=200, seed=0) -> dict:
    """Compared -> reference general affine over the paired dots, with bootstrap
    covariance of its six parameters (a11 a12 a21 a22 tx ty)."""
    d = pairs.select(("dot",))
    if len(d.tags) < 3:
        return {"ok": False}
    X = np.column_stack([d.P1, np.ones(len(d.P1))])
    sol, *_ = np.linalg.lstsq(X, d.P0, rcond=None)
    rng = np.random.default_rng(seed); boots = []
    for _ in range(n_boot):
        k = rng.integers(0, len(X), len(X))
        b, *_ = np.linalg.lstsq(X[k], d.P0[k], rcond=None)
        boots.append(np.r_[b[:2].T.ravel(), b[2]])
    A = np.column_stack([sol[:2].T, sol[2]])
    return {"ok": True, "kind": "affine", "A": A, "cov": np.cov(np.asarray(boots).T),
            "cov_names": ["a11", "a12", "a21", "a22", "tx", "ty"], "n_pairs": int(len(d.P0))}


def overlay_composite(img0_u8, img1_u8, align, cyan_gain=1.0, red_gain=1.0):
    """Cyan (reference) / red (aligned compared) composite on a canvas holding both.
    Returns (rgb uint8, origin): subtract `origin` from reference coordinates."""
    import cv2
    H0, W0 = img0_u8.shape[:2]; H1, W1 = img1_u8.shape[:2]
    tc = apply_align(np.array([[0, 0], [W1, 0], [0, H1], [W1, H1]], float), align)
    x_lo = min(0.0, tc[:, 0].min()); y_lo = min(0.0, tc[:, 1].min())
    x_hi = max(float(W0), tc[:, 0].max()); y_hi = max(float(H0), tc[:, 1].max())
    origin = np.array([np.floor(x_lo), np.floor(y_lo)])
    Wc = int(np.ceil(x_hi - origin[0])); Hc = int(np.ceil(y_hi - origin[1]))
    A = align.get("s", 1.0) * np.asarray(align["R"])
    M = np.hstack([A, (np.asarray(align["t"]) - origin).reshape(2, 1)])
    big1 = cv2.warpAffine(img1_u8, M, (Wc, Hc), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    big0 = np.zeros((Hc, Wc), img0_u8.dtype)
    ox, oy = int(-origin[0]), int(-origin[1])
    big0[oy:oy + H0, ox:ox + W0] = img0_u8
    rgb = np.zeros((Hc, Wc, 3), np.uint8)
    rgb[..., 0] = np.clip(big1.astype(np.float32) * red_gain, 0, 255)
    cy = np.clip(big0.astype(np.float32) * cyan_gain, 0, 255)
    rgb[..., 1] = cy; rgb[..., 2] = cy
    return rgb, origin


def field(pairs: Pairs, align, k=8, tr1=None, design=None):
    """Per paired dot: displacement under `align` with covariance, the local
    deformation gradient, and (with tr1 + design) the compared frame's own
    deviation from its uniform-expansion model. Returns a dict of arrays."""
    d = pairs.select(("dot",))
    n = len(d.tags)
    out = {"tags": d.tags, "P0": d.P0, "P1": d.P1, "C0": d.C0, "C1": d.C1, "n": n}
    if n == 0:
        return out
    P1a = apply_align(d.P1, align)
    A = align.get("s", 1.0) * np.asarray(align["R"])
    U = P1a - d.P0
    Cu = d.C0 + np.einsum("ab,nbc,dc->nad", A, d.C1, A)
    out.update(P1a=P1a, U=U, Cu=Cu, umag=np.hypot(U[:, 0], U[:, 1]))
    with np.errstate(invalid="ignore", divide="ignore"):
        tr_ = Cu[:, 0, 0] + Cu[:, 1, 1]
        out["umag_sigma"] = np.sqrt(np.where(out["umag"] > 0,
                                             np.einsum("ni,nij,nj->n", U, Cu, U) / np.maximum(out["umag"] ** 2, 1e-12),
                                             tr_ / 2))
    out.update(DF.local_gradient(d.P0, d.P1, d.C0, d.C1, k=k))
    if tr1 is not None and design is not None and tr1.similarity:
        pos = {r["tag"]: (r["x_um"], r["y_um"]) for r in design.records}
        dev = d.P1 - W.similarity_points([pos[t] for t in d.tags], tr1.similarity)
        out["dev1"] = dev; out["dev1_mag"] = np.hypot(dev[:, 0], dev[:, 1])
    return out


def field_stats(f: dict) -> dict:
    def med(k):
        v = f.get(k); v = v[np.isfinite(v)] if v is not None else np.zeros(0)
        return float(np.median(v)) if len(v) else float("nan")
    lin = f.get("lin", np.zeros(0)); lin = lin[np.isfinite(lin)]
    um = f.get("umag", np.zeros(0))
    return {"n": int(f["n"]), "lin_median": med("lin"), "lin_mean": float(np.mean(lin)) if len(lin) else float("nan"),
            "lin_sigma": float(np.std(lin)) if len(lin) else float("nan"), "aniso_median": med("anisotropy"),
            "umag_median": float(np.median(um)) if len(um) else float("nan"),
            "umag_p90": float(np.percentile(um, 90)) if len(um) else float("nan"), "resid_median": med("resid_rms")}


def heat_grid(P0, values, shape, step=24, max_dist=None):
    """Interpolate per-dot values onto a grid over the reference frame; cells
    farther than max_dist from any dot are NaN (no invented values in voids)."""
    from scipy.interpolate import griddata
    from scipy.spatial import cKDTree
    H, Wd = shape[:2]
    values = np.asarray(values, float)
    ok = np.isfinite(values)
    if ok.sum() < 4:
        return np.full((max(1, H // step), max(1, Wd // step)), np.nan), (Wd, H)
    xs = np.arange(step / 2, Wd, step); ys = np.arange(step / 2, H, step)
    GX, GY = np.meshgrid(xs, ys)
    pts = np.asarray(P0, float)[ok]
    grid = griddata(pts, values[ok], (GX, GY), method="linear")
    if max_dist is None:
        d_nn, _ = cKDTree(pts).query(pts, k=2)
        max_dist = 2.0 * float(np.median(d_nn[:, 1]))
    gd, _ = cKDTree(pts).query(np.column_stack([GX.ravel(), GY.ravel()]))
    grid[gd.reshape(GX.shape) > max_dist] = np.nan
    return grid, (Wd, H)


def write_pairs_csv(pairs: Pairs, path):
    """Quick per-pair export (the full bundle is port Phase 7)."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([f"# reference {pairs.label0:g}x vs compared {pairs.label1:g}x · corrected-frame px"])
        w.writerow(["tag", "category", "x0", "y0", "sxx0", "syy0", "sxy0", "x1", "y1", "sxx1", "syy1", "sxy1"])
        for i, t in enumerate(pairs.tags):
            c0, c1 = pairs.C0[i], pairs.C1[i]
            w.writerow([t, pairs.cats[i], round(pairs.P0[i, 0], 3), round(pairs.P0[i, 1], 3),
                        f"{c0[0, 0]:.3g}", f"{c0[1, 1]:.3g}", f"{c0[0, 1]:.3g}",
                        round(pairs.P1[i, 0], 3), round(pairs.P1[i, 1], 3),
                        f"{c1[0, 0]:.3g}", f"{c1[1, 1]:.3g}", f"{c1[0, 1]:.3g}"])
    return path
