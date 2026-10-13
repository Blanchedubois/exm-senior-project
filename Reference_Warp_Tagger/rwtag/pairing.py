"""
rwtag.pairing
=============
Cross-image analysis over tagged frames (the workspace phases B-D).

Phase B: pair the features of the Initial image with each Expanded image by
shared reference tag — the positions of every paired point in BOTH frames,
exported as CSV. Because both frames were tagged from the same STL reference,
pairing is a pure tag join; no re-matching, no ambiguity.

Headless: numpy + csv only.
"""
from __future__ import annotations
import csv

import numpy as np


def category(tag: str) -> str:
    return tag.split("|")[0]


def pair_tags(init_tags: dict, exp_tags: dict, kinds=None) -> dict:
    """Join two frames' {tag: (x,y)} by shared tag. Returns
    {tag: (x_init, y_init, x_exp, y_exp)}, optionally restricted to `kinds`
    (e.g. ("dot",))."""
    out = {}
    for tag, (xe, ye) in exp_tags.items():
        if kinds is not None and category(tag) not in kinds:
            continue
        p0 = init_tags.get(tag)
        if p0 is not None:
            out[tag] = (float(p0[0]), float(p0[1]), float(xe), float(ye))
    return out


def pair_counts(init_tags: dict, exp_tags: dict, pairs: dict) -> dict:
    """Summary numbers for the Pair view (dot-centric, as dots are the
    measurement tier)."""
    n_dot_init = sum(1 for t in init_tags if category(t) == "dot")
    n_dot_exp = sum(1 for t in exp_tags if category(t) == "dot")
    n_dot_pair = sum(1 for t in pairs if category(t) == "dot")
    denom = min(n_dot_init, n_dot_exp)
    by_cat = {}
    for t in pairs:
        by_cat[category(t)] = by_cat.get(category(t), 0) + 1
    return {"n_init": len(init_tags), "n_exp": len(exp_tags), "n_pairs": len(pairs),
            "n_dot_init": n_dot_init, "n_dot_exp": n_dot_exp, "n_dot_pairs": n_dot_pair,
            "dot_pair_frac": (n_dot_pair / denom) if denom else 0.0,
            "by_category": by_cat}


def pairs_xy(pairs: dict, kinds=("dot",)):
    """(P_init (N,2), P_exp (N,2), tags list) arrays from a pair dict."""
    tags = [t for t in sorted(pairs) if kinds is None or category(t) in kinds]
    if not tags:
        return np.zeros((0, 2)), np.zeros((0, 2)), []
    a = np.array([pairs[t] for t in tags], float)
    return a[:, :2], a[:, 2:], tags


def write_pairs_csv(pairs: dict, path: str, init_label=None, exp_label=None) -> str:
    """One row per paired feature: both frames' pixel positions."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        if init_label is not None and exp_label is not None:
            w.writerow([f"# initial {init_label:g}x vs expanded {exp_label:g}x"])
        w.writerow(["tag", "category", "x_init_px", "y_init_px", "x_exp_px", "y_exp_px"])
        for tag in sorted(pairs):
            xi, yi, xe, ye = pairs[tag]
            w.writerow([tag, category(tag), round(xi, 1), round(yi, 1),
                        round(xe, 1), round(ye, 1)])
    return path


# ================================================================ Phase C
# Rigid (rotation + translation, NO scaling) alignment of the expanded frame
# onto the initial about a common box centre, and the cyan/red overlay.

def tag_box(tag: str):
    """Box number N from a box-scoped tag ('dot|B13|4_7' -> 13), else None."""
    parts = tag.split("|")
    if len(parts) >= 2 and parts[1].startswith("B"):
        try:
            return int(parts[1][1:])
        except ValueError:
            return None
    return None


def common_boxes(pairs: dict):
    """[(N, paired_dot_count)] for boxes with paired dots, best first."""
    counts = {}
    for t in pairs:
        if category(t) == "dot":
            N = tag_box(t)
            if N is not None:
                counts[N] = counts.get(N, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def kabsch_rotation(P_move: np.ndarray, P_target: np.ndarray) -> np.ndarray:
    """Least-squares rotation R (2x2, det=+1, NO scale) minimising
    ||R·p_move − p_target|| over already-CENTRED point sets. Insensitive to a
    uniform scale difference, so the expansion growth does not bias it."""
    H = P_move.T @ P_target
    U, _S, Vt = np.linalg.svd(H)
    V = Vt.T
    d = np.sign(np.linalg.det(V @ U.T)) or 1.0
    return V @ np.diag([1.0, d]) @ U.T


def rigid_align(pairs: dict, box_n: int, c_init, c_exp) -> dict:
    """Rigid map expanded->initial: p' = R·(p − c_exp) + c_init, where R is the
    Kabsch rotation of ALL paired dots about the two common-box centres and the
    translation pins the centres together. Scale is deliberately UNTOUCHED."""
    P0, P1, _tags = pairs_xy(pairs, kinds=("dot",))
    if len(P0) < 3:
        return {"ok": False, "reason": f"only {len(P0)} paired dots"}
    c0 = np.asarray(c_init, float)
    c1 = np.asarray(c_exp, float)
    R = kabsch_rotation(P1 - c1, P0 - c0)
    t = c0 - R @ c1
    ang = float(np.degrees(np.arctan2(R[1, 0], R[0, 0])))
    return {"ok": True, "R": R, "t": t, "angle_deg": ang, "box": int(box_n),
            "c_init": c0, "c_exp": c1, "n_pairs": int(len(P0))}


def apply_rigid(points, align) -> np.ndarray:
    """Expanded-frame px -> initial-aligned px."""
    P = np.asarray(points, float).reshape(-1, 2)
    return P @ align["R"].T + align["t"]


def overlay_composite(img_init_u8, img_exp_u8, align,
                      cyan_gain=1.0, red_gain=1.0):
    """Additive cyan/red composite on a canvas holding BOTH frames.
    initial -> cyan (G+B), rigidly-aligned expanded -> red (R); grey where they
    coincide. Returns (rgb HxWx3 uint8, origin (x0,y0)) — subtract `origin` from
    initial-frame coordinates to draw overlays on the composite."""
    import cv2
    H0, W0 = img_init_u8.shape[:2]
    H1, W1 = img_exp_u8.shape[:2]
    corners = np.array([[0, 0], [W1, 0], [0, H1], [W1, H1]], float)
    tc = apply_rigid(corners, align)
    x_lo = min(0.0, tc[:, 0].min()); y_lo = min(0.0, tc[:, 1].min())
    x_hi = max(float(W0), tc[:, 0].max()); y_hi = max(float(H0), tc[:, 1].max())
    origin = np.array([np.floor(x_lo), np.floor(y_lo)])
    W = int(np.ceil(x_hi - origin[0])); H = int(np.ceil(y_hi - origin[1]))
    # aligned expanded on the big canvas
    M = np.hstack([align["R"], (align["t"] - origin).reshape(2, 1)])
    exp_big = cv2.warpAffine(img_exp_u8, M, (W, H), flags=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    init_big = np.zeros((H, W), img_init_u8.dtype)
    ox, oy = int(-origin[0]), int(-origin[1])
    init_big[oy:oy + H0, ox:ox + W0] = img_init_u8
    rgb = np.zeros((H, W, 3), np.uint8)
    rgb[..., 0] = np.clip(exp_big.astype(np.float32) * red_gain, 0, 255)     # red = expanded
    cy = np.clip(init_big.astype(np.float32) * cyan_gain, 0, 255)
    rgb[..., 1] = cy                                                          # cyan = initial
    rgb[..., 2] = cy
    return rgb, origin


# ================================================================ Phase D
# Displacement / strain field from the paired dots, in the rigidly-aligned
# (unscaled) frame: u = p_exp_aligned - p_init per pair, plus the local linear
# expansion from k-NN neighbours (rotation-invariant, so the rigid alignment
# does not bias it).

def displacement_field(pairs: dict, align: dict, k=8) -> dict:
    """Per-paired-dot displacement + local strain. Returns dict with:
    tags, P0 (init px), P1 (exp px), P1a (exp aligned px), U (P1a-P0),
    umag, lin (local linear expansion per dot; NaN where the fit fails)."""
    from .refwarp.strain import _local_F
    P0, P1, tags = pairs_xy(pairs, kinds=("dot",))
    if len(P0) == 0:
        return {"tags": [], "P0": P0, "P1": P1, "P1a": P1, "U": P1,
                "umag": np.zeros(0), "lin": np.zeros(0)}
    P1a = apply_rigid(P1, align)
    U = P1a - P0
    _J, lin = _local_F(P0, P1, k=k)         # raw pairs: alignment-independent
    return {"tags": tags, "P0": P0, "P1": P1, "P1a": P1a, "U": U,
            "umag": np.hypot(U[:, 0], U[:, 1]), "lin": lin}


def field_stats(field: dict) -> dict:
    lin = field["lin"]; lin = lin[np.isfinite(lin)]
    um = field["umag"]
    return {"n": int(len(field["P0"])),
            "lin_median": float(np.median(lin)) if len(lin) else float("nan"),
            "lin_mean": float(np.mean(lin)) if len(lin) else float("nan"),
            "lin_sigma": float(np.std(lin)) if len(lin) else float("nan"),
            "umag_median": float(np.median(um)) if len(um) else float("nan"),
            "umag_p90": float(np.percentile(um, 90)) if len(um) else float("nan")}


def write_field_csv(field: dict, path: str, init_label=None, exp_label=None,
                    align=None) -> str:
    """One row per paired dot: both positions, the aligned position, the
    displacement vector and the local linear expansion."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        if init_label is not None and exp_label is not None:
            hdr = f"# displacement field: initial {init_label:g}x -> expanded {exp_label:g}x"
            if align is not None and align.get("ok"):
                hdr += (f" · aligned about B{align['box']} · "
                        f"rotation {align['angle_deg']:.2f} deg · scale untouched")
            w.writerow([hdr])
        w.writerow(["tag", "x_init_px", "y_init_px", "x_exp_px", "y_exp_px",
                    "x_exp_aligned_px", "y_exp_aligned_px",
                    "u_x_px", "u_y_px", "u_mag_px", "local_linear_expansion"])
        for i, t in enumerate(field["tags"]):
            lin = field["lin"][i]
            w.writerow([t,
                        round(field["P0"][i, 0], 1), round(field["P0"][i, 1], 1),
                        round(field["P1"][i, 0], 1), round(field["P1"][i, 1], 1),
                        round(field["P1a"][i, 0], 1), round(field["P1a"][i, 1], 1),
                        round(field["U"][i, 0], 2), round(field["U"][i, 1], 2),
                        round(field["umag"][i], 2),
                        "" if not np.isfinite(lin) else round(float(lin), 4)])
    return path


# ================================================================ distributions
# Per-dot distributions for the Summary tab: the spread of local linear
# expansion, and the WARP RESIDUAL — each dot's distance (px) from the best-fit
# SIMILARITY (uniform expansion + rotation + translation) initial->expanded.
# Removing the similarity leaves pure non-uniform warpage; its RMS is the
# classic registration error. Pixel sizes are identical across frames (same
# microscope), so residual px compare directly between images.

def similarity_residuals(pairs: dict) -> dict:
    """Fit p_exp ≈ s·R·p_init + t over the paired dots (Kabsch rotation +
    least-squares scale) and return per-dot residuals. Returns
    {tags, resid (px), scale, angle_deg, rms} — empty arrays if <3 pairs."""
    P0, P1, tags = pairs_xy(pairs, kinds=("dot",))
    if len(P0) < 3:
        return {"tags": [], "resid": np.zeros(0), "scale": float("nan"),
                "angle_deg": float("nan"), "rms": float("nan")}
    c0, c1 = P0.mean(0), P1.mean(0)
    A, B = P0 - c0, P1 - c1
    R = kabsch_rotation(A, B)                       # rotation taking A toward B
    RA = A @ R.T
    s = float((RA * B).sum() / max((RA * RA).sum(), 1e-12))
    res = np.hypot(*(B - s * RA).T)
    return {"tags": tags, "resid": res, "scale": s,
            "angle_deg": float(np.degrees(np.arctan2(R[1, 0], R[0, 0]))),
            "rms": float(np.sqrt(np.mean(res ** 2)))}


def expansion_distributions(init_tags: dict, init_label: float, expanded) -> list:
    """Per-dot distribution data per expanded image (the Summary tab's histogram
    and box+jitter modes). `expanded` = [(name, label, tags_or_None)]. Returns
    [{name, label, expected, lin (finite per-dot local linear expansion),
      resid (per-dot similarity residual px), sim_scale, rms}] — untagged images
    are skipped (the summary table still reports them)."""
    from .refwarp.strain import _local_F
    out = []
    for name, label, tags in expanded:
        if not tags:
            continue
        pairs = pair_tags(init_tags, tags)
        P0, P1, _t = pairs_xy(pairs, kinds=("dot",))
        if len(P0) < 3:
            continue
        _J, lin = _local_F(P0, P1)
        sim = similarity_residuals(pairs)
        out.append({"name": name, "label": float(label),
                    "expected": float(label) / float(init_label),
                    "lin": lin[np.isfinite(lin)], "resid": sim["resid"],
                    "sim_scale": sim["scale"], "rms": sim["rms"]})
    return out


def write_distributions_csv(dists: list, path: str, init_label: float) -> str:
    """Long-format per-dot distributions: one row per (image, dot)."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([f"# per-dot distributions · initial = {init_label:g}x · "
                    "warp_residual = distance from best-fit similarity (px)"])
        w.writerow(["image_label", "expected_vs_initial",
                    "local_linear_expansion", "warp_residual_px"])
        for d in dists:
            lin, res = d["lin"], d["resid"]
            n = max(len(lin), len(res))
            for i in range(n):
                w.writerow([d["label"], round(d["expected"], 4),
                            round(float(lin[i]), 4) if i < len(lin) else "",
                            round(float(res[i]), 2) if i < len(res) else ""])
    return path


# ================================================================ Phase E
# Expansion summary: average measured expansion of every expanded image vs its
# expected expansion (the label ratio), noted per image.

def expansion_rows(init_tags: dict, init_label: float, expanded) -> list:
    """One summary row per expanded image. `expanded` = [(name, label, tags)]
    where tags may be None for untagged/rejected frames (reported, not hidden).
    Measured = mean ± σ of the per-dot local linear expansion over tag-paired
    dots (the validated strain.py maths); expected = label / init_label."""
    from .refwarp import strain as ST
    rows = []
    for name, label, tags in expanded:
        row = {"name": name, "label": float(label),
               "expected": float(label) / float(init_label),
               "status": "ok" if tags else "untagged/rejected",
               "measured": float("nan"), "sigma": float("nan"),
               "median": float("nan"), "n": 0, "n_dot_pairs": 0, "pair_frac": 0.0}
        if tags:
            r = ST.strain(init_tags, tags, init_label, label)
            pairs = pair_tags(init_tags, tags)
            c = pair_counts(init_tags, tags, pairs)
            row.update(measured=r["mean"], sigma=r["sigma"], median=r["median"],
                       n=r["n"], n_dot_pairs=c["n_dot_pairs"],
                       pair_frac=c["dot_pair_frac"])
        rows.append(row)
    return rows


def write_summary_csv(rows: list, path: str, init_label: float, init_name="") -> str:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([f"# expansion summary · initial = {init_label:g}x {init_name}"])
        w.writerow(["image", "expected_x_absolute", "expected_vs_initial",
                    "measured_vs_initial", "sigma", "median", "n_strain_points",
                    "n_dot_pairs", "dot_pair_frac", "status"])
        for r in rows:
            w.writerow([r["name"], r["label"], round(r["expected"], 4),
                        "" if not np.isfinite(r["measured"]) else round(r["measured"], 4),
                        "" if not np.isfinite(r["sigma"]) else round(r["sigma"], 4),
                        "" if not np.isfinite(r["median"]) else round(r["median"], 4),
                        r["n"], r["n_dot_pairs"], round(r["pair_frac"], 3), r["status"]])
    return path


def heat_grid(P0: np.ndarray, values: np.ndarray, shape, step=24, max_dist=None):
    """Interpolate scattered per-dot values onto a regular grid over the initial
    frame. Linear interpolation is only trusted NEAR actual paired dots: cells
    farther than `max_dist` px from the nearest dot are masked NaN — otherwise
    the convex hull bridges unpaired voids (glyph keep-outs, coverage edges)
    with invented values. Returns (grid, extent=(W, H))."""
    from scipy.interpolate import griddata
    from scipy.spatial import cKDTree
    H, W = shape[:2]
    ok = np.isfinite(values)
    if ok.sum() < 4:
        return np.full((max(1, H // step), max(1, W // step)), np.nan), (W, H)
    xs = np.arange(step / 2, W, step)
    ys = np.arange(step / 2, H, step)
    GX, GY = np.meshgrid(xs, ys)
    pts = P0[ok]
    grid = griddata(pts, values[ok], (GX, GY), method="linear")
    if max_dist is None:
        # default support: ~2 median nearest-neighbour spacings of the paired dots
        d_nn, _ = cKDTree(pts).query(pts, k=2)
        max_dist = 2.0 * float(np.median(d_nn[:, 1]))
    gd, _ = cKDTree(pts).query(np.column_stack([GX.ravel(), GY.ravel()]))
    grid[gd.reshape(GX.shape) > max_dist] = np.nan
    return grid, (W, H)
