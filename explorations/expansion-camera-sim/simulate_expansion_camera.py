#!/usr/bin/env python3
"""
simulate_expansion_camera.py
============================
Simulated microscope images of the hydrogel marker grid as it is *gradually
expanded*, imaged through a FIXED microscope (fixed field of view / fixed
magnification), with rigid ArUco markers and a realistic camera model.

Physical model
--------------------------------------------------------------------------------
* FIXED ZOOM. The microscope FOV is a fixed `fov_um` window at a fixed pixel
  size, so every frame has the SAME pixel dimensions and the ArUco markers stay
  a CONSTANT size in pixels. As the gel swells the features spread apart WITHIN
  this fixed frame, and peripheral markers move out of view.
* RIGID ISLANDS. Each tag and dot keeps its exact printed size and internal
  pattern (a rigid stamp that only translates); only the spacing grows:

        X' = fov_centre + drift + lambda*(X - pattern_centre) + warp(X)*lambda

* MINIMAL DISTORTION THROUGHOUT. `warp(X)` is a smooth sum of many small lobes
  spread across the field (not one localized bulge) -> a little non-uniform
  distortion everywhere.
* FRAME DRIFT. A small random (x,y) shift of the whole sample each frame
  (stage repositioning error).

Camera model (per frame): supersampled render -> slight rigid rotation ->
downsample to the camera grid -> invert to fluorescence contrast -> Gaussian PSF
blur -> optical vignetting -> Poisson shot + Gaussian read noise.

Outputs (all under this script's folder)
--------------------------------------------------------------------------------
  pngs/expansion_l<lam>x.png     one 8-bit PNG per expansion level
  tiffs/expansion_l<lam>x.tif    the same frames as 8-bit TIFF (separately)
  tiffs/expansion_stack.tif      multipage TIFF (all frames, identical size)
  montage.png                    contact sheet + in-FOV decode count

Requires: opencv-contrib-python, numpy, matplotlib   (Pillow optional, for stack)
The reusable conjoined-marker geometry is imported from the sibling
hydrogel_marker_analysis/toolkit so the markers match the real "new" design.
"""
from __future__ import annotations
import os, sys, json
from dataclasses import dataclass, replace
import numpy as np
import cv2

# --- import the toolkit (single source of truth for the marker geometry) ------
HERE = os.path.dirname(os.path.abspath(__file__))
TOOLKIT = os.path.normpath(os.path.join(HERE, "..", "hydrogel_marker_analysis", "toolkit"))
sys.path.insert(0, TOOLKIT)
from conjoined_lib import (marker_primitives, circle_primitive,      # noqa: E402
                           render_png, make_detector)
import generate_grid as gg                                            # noqa: E402


# ------------------------------------------------------------------ config
@dataclass(frozen=True)
class DegradationLevel:
    """One fidelity-test point: a blur (PSF FWHM) + sensor-noise setting.

    The scene geometry (warp / drift / rotation / optics) is IDENTICAL across all
    levels -- only the optical blur and camera noise change -- so a downstream tool
    can be scored against progressively worse images of the *same* sample.
    """
    name: str                # folder name under degradations/
    psf_fwhm_um: float        # optical blur FWHM in um (larger = blurrier)
    read_noise: float         # Gaussian read noise (grey levels, 0..255)
    full_well_photons: float  # photons at full white (smaller = stronger shot noise)
    background_level: float   # dark-background pedestal (raises the noise floor)


@dataclass
class SimConfig:
    # expansion sweep (linear factor lambda); 1.0 = unexpanded reference
    expansions: tuple = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0)

    # FIXED microscope FOV (um) and pixel size -> fixed frame size, fixed zoom.
    # Fixed zoom means fewer markers stay in view as the gel expands; larger FOV
    # keeps more markers at high lam but leaves more empty margin at lam=1.
    fov_um: float = 200.0
    camera_px_per_um: float = 8.0    # effective pixel size = 1/8 = 0.125 um/px
    supersample: int = 2             # render this-x finer, then area-downsample
    render_margin: float = 1.18      # render a bit beyond the FOV so rotation
                                     # fills the corners with real sample content
    psf_fwhm_um: float = 0.30        # optical blur FWHM (confocal-ish, "slight")
    invert: bool = True              # fluorescence-style bright pattern on dark bg

    # rigid rotation of the whole sample under the scope, ACCUMULATING per stage:
    # stage k is rotated  rotation_deg + k * rotation_step_deg  (slowly more each
    # expansion step, as if the sample drifts a little more every acquisition).
    rotation_deg: float = 2.0        # rotation of the first stage (lambda=1)
    rotation_step_deg: float = 3.0   # extra rotation added at each later stage

    # per-frame drift: small random (x,y) shift of the whole sample (um)
    drift_um: float = 3.0
    drift_seed: int = 3

    # MINIMAL distortion spread over MULTIPLE areas: many small warp lobes
    warp_amp_um: float = 1.2         # per-lobe displacement scale (small)
    n_warp_lobes: int = 12           # number of lobes across the field
    warp_sigma_um: float = 28.0      # lobe width (smooth, overlapping)
    warp_seed: int = 7

    # lens (optical) geometric distortion, Brown-Conrady radial model, centred on
    # the optical axis. Negative k1 = barrel (straight lines bow outward, typical
    # of a microscope objective); positive = pincushion. Same for every frame.
    lens_k1: float = -0.05
    lens_k2: float = -0.01

    # optical vignetting (radial brightness falloff toward the edges). This is a
    # microscope-optics property, applied identically to every frame (the FOV is
    # fixed, so the mask is the same on every image, centred on the sensor).
    vignette_strength: float = 0.88
    vignette_power: float = 1.8

    # camera noise
    read_noise: float = 4.0          # Gaussian read noise (grey levels, 0..255)
    full_well_photons: float = 350.0 # photons at full white -> Poisson shot noise
    background_level: float = 14.0   # dark-background pedestal (bias / faint
                                     # autofluorescence) -> lifts the noise floor
    seed: int = 12345                # reproducible noise

    # ---- fidelity degradation sweep -------------------------------------------
    # Each level re-uses the SAME rendered scene (identical warp/drift/rotation/
    # optics) but applies a progressively BLURRIER PSF and NOISIER sensor, and is
    # written to its own folder under `degradations/<name>/`. Blur climbs gently
    # (0.30 -> 0.50 um FWHM, "slightly more blurry"); noise climbs hard (read noise
    # 4 -> 30, full well 350 -> 60, "much noisier"). L0 mirrors the baseline params
    # above and is also written to the legacy tiffs/ + pngs/ so the existing
    # downstream project keeps working. Edit / extend this tuple to taste.
    degradations: tuple = (
        DegradationLevel("L0_baseline", 0.30,  4.0, 350.0, 14.0),
        DegradationLevel("L1_mild",     0.34,  8.0, 240.0, 16.0),
        DegradationLevel("L2_moderate", 0.38, 14.0, 160.0, 18.0),
        DegradationLevel("L3_strong",   0.44, 20.0, 100.0, 20.0),
        DegradationLevel("L4_severe",   0.50, 30.0,  60.0, 24.0),
    )

    render_px_cap: int = 13000       # auto-reduce supersample above this dimension


# ------------------------------------------------------------------ warp field
def make_warp_lobes(meta, cfg: SimConfig):
    """Many small, randomly-oriented Gaussian lobes spread across the field."""
    Wum, Hum = meta["field_um"]
    rng = np.random.default_rng(cfg.warp_seed)
    lobes = []
    for _ in range(cfg.n_warp_lobes):
        C = np.array([rng.uniform(0, Wum), rng.uniform(0, Hum)])
        ang = rng.uniform(0, 2 * np.pi)
        mag = cfg.warp_amp_um * rng.uniform(0.5, 1.0)
        lobes.append((C, np.array([mag * np.cos(ang), mag * np.sin(ang)])))
    return lobes


def warp_disp(P, lobes, sigma):
    """Sum of lobe displacements at points P (N,2). Smooth, minimal, everywhere."""
    disp = np.zeros_like(P)
    inv = 1.0 / (2.0 * sigma ** 2)
    for C, A in lobes:
        w = np.exp(-((P - C) ** 2).sum(1) * inv)
        disp += w[:, None] * A[None, :]
    return disp


# ------------------------------------------------------------------ geometry
def build_frame_prims(meta, node_lut, lam, cfg: SimConfig, lobes, drift):
    """Deform features into the fixed render canvas; return (prims, node_xy, ids).
    Coordinates are in the render canvas (fov_um*render_margin), pattern centred."""
    gc = meta["config"]
    Wum, Hum = meta["field_um"]
    P0 = np.array([Wum / 2.0, Hum / 2.0])            # undeformed pattern centre
    rfov = cfg.fov_um * cfg.render_margin
    fov_c = np.array([rfov / 2.0, rfov / 2.0]) + np.asarray(drift, float)

    def place(P):                                    # undeformed -> render coords
        return fov_c + lam * (P - P0) + warp_disp(P, lobes, cfg.warp_sigma_um) * lam

    nodes = meta["nodes"]
    node_ids = [n["aruco_id"] for n in nodes]
    node_U = np.array([[n["x_um"], n["y_um"]] for n in nodes])
    node_D = place(node_U)
    node_Dlut = {(n["node_i"], n["node_j"]): node_D[k] for k, n in enumerate(nodes)}

    dot_U = np.array([[d["x_um"], d["y_um"]] for b in meta["boxes"] for d in b["dots"]])
    dot_D = place(dot_U)

    # drop dots that warpage pushes into a rigid tag's keep-out (occluded by it)
    marker_um = gc["marker_um"]
    keepout = marker_um / 2.0 + gc["quiet_um"]
    d2 = ((dot_D[:, None, 0] - node_D[None, :, 0]) ** 2 +
          (dot_D[:, None, 1] - node_D[None, :, 1]) ** 2)
    dot_D = dot_D[d2.min(1) >= keepout ** 2]

    # dashed boundary. Each dash is an INDIVIDUAL rigid printed mark: its centre is
    # deformed through place() just like every dot, so the (non-isotropic) warp
    # moves each dash on its own and the boundary bends with the field instead of
    # staying a perfectly straight line. Each dash keeps its fixed printed length
    # (rigid: only translates + rotates, never stretches). The NUMBER of dashes per
    # edge is LOCKED to its unexpanded (lam=1) count and stays constant at every
    # expansion; only the gaps grow. Trimmed clear of each tag's quiet zone.
    dashed = []
    bw = gc["boundary_width_um"]
    bdash = gc["boundary_dash_um"]                                   # rigid: fixed
    off = marker_um / 2 + 2 * gc["quiet_um"] + bw / 2
    period_ref = gc["boundary_dash_um"] + gc["boundary_gap_um"]      # lam=1 period

    def add_dashed_edge(key0, key1):
        pa = np.array([node_lut[key0]["x_um"], node_lut[key0]["y_um"]])  # undeformed
        pb = np.array([node_lut[key1]["x_um"], node_lut[key1]["y_um"]])
        L = float(np.hypot(pb[0] - pa[0], pb[1] - pa[1]))
        u = (pb - pa) / L
        # fixed dash count from the lam=1 trimmed length -> constant for every lam
        n = max(1, int(round((L - 2 * off) / period_ref)))
        # trim in undeformed param by off/lam so the DEFORMED clearance from each
        # tag stays ~off (place() scales spacing by lam) -> matches the dots' gap.
        s0, s1 = off / lam, L - off / lam
        if s1 <= s0:
            return
        s = s0 + (s1 - s0) * (np.arange(n) + 0.5) / n               # dash-centre params
        eps = min(bdash, s1 - s0) * 0.5                            # tangent probe (um)
        Cd = place(pa[None, :] + s[:, None] * u[None, :])          # (n,2) dash centres
        # local deformed tangent per dash (finite diff) -> rigid dash orientation
        Tp = place(pa[None, :] + (s + eps)[:, None] * u[None, :])
        Tm = place(pa[None, :] + (s - eps)[:, None] * u[None, :])
        t = Tp - Tm
        tn = np.hypot(t[:, 0], t[:, 1])[:, None]
        td = np.divide(t, tn, out=np.tile(u, (n, 1)), where=tn > 1e-9)
        h = (bdash / 2.0) * td                                     # rigid half-dash
        for kk in range(n):                                        # one prim per dash
            p0, p1 = Cd[kk] - h[kk], Cd[kk] + h[kk]
            dashed.append(("dline", p0[0], p0[1], p1[0], p1[1], bw, bdash, bdash))

    nnx, nny = gc["n_boxes_x"] + 1, gc["n_boxes_y"] + 1
    for j in range(nny):
        for i in range(nnx - 1):
            add_dashed_edge((i, j), (i + 1, j))
    for i in range(nnx):
        for j in range(nny - 1):
            add_dashed_edge((i, j), (i, j + 1))

    rdot = gc["dot_diameter_um"] / 2.0
    dot_prims = [circle_primitive(p[0], p[1], rdot) for p in dot_D]

    marker_prims = []
    for k, n in enumerate(nodes):
        p = node_D[k]
        marker_prims += marker_primitives(n["aruco_id"], p[0], p[1], marker_um,
                                          strut_w_um=gc["strut_w_um"])

    return dashed + dot_prims + marker_prims, node_D, node_ids


def rotate_points(P, center, angle_deg):
    """Apply the same rotation cv2 applies to the image, to points P (N,2)."""
    M = cv2.getRotationMatrix2D((float(center[0]), float(center[1])), angle_deg, 1.0)
    return P @ M[:, :2].T + M[:, 2]


# ------------------------------------------------------------------ camera model
def rotate_fixed(img, theta_deg, border):
    """Rotate about the centre, keeping the SAME frame size (fixed sensor)."""
    if not theta_deg:
        return img
    h, w = img.shape
    M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), theta_deg, 1.0)
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR, borderValue=border)


def _radial_remap(img, k1, k2, fnorm):
    """Radial remap: a destination pixel at radius r samples the source at
    r*(1 + k1 r^2 + k2 r^4). fnorm normalizes radius (FOV half-width, px)."""
    if k1 == 0 and k2 == 0:
        return img
    h, w = img.shape
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    xs, ys = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    nx, ny = (xs - cx) / fnorm, (ys - cy) / fnorm
    r2 = nx * nx + ny * ny
    factor = 1.0 + k1 * r2 + k2 * r2 * r2
    mapx = (cx + nx * factor * fnorm).astype(np.float32)
    mapy = (cy + ny * factor * fnorm).astype(np.float32)
    return cv2.remap(img, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def apply_lens_distortion(img, cfg: SimConfig, fnorm):
    """Brown-Conrady radial lens distortion about the image centre (optical axis).
    Negative k1 = barrel, positive = pincushion."""
    return _radial_remap(img, cfg.lens_k1, cfg.lens_k2, fnorm)


def undistort_lens(img, cfg: SimConfig, fnorm):
    """Remove the lens distortion for detection, as a calibrated pipeline does.
    Exact radial inverse of _radial_remap via a 1-D lookup (numerically invert
    h(r) = r*(1 + k1 r^2 + k2 r^4))."""
    k1, k2 = cfg.lens_k1, cfg.lens_k2
    if k1 == 0 and k2 == 0:
        return img
    r_s = np.linspace(0.0, 3.0, 4000)
    g = r_s * (1.0 + k1 * r_s ** 2 + k2 * r_s ** 4)
    mono = int(np.argmin(np.diff(g) > 0)) if not np.all(np.diff(g) > 0) else len(g)
    r_s, g = r_s[:mono], g[:mono]                        # keep the monotonic branch
    h, w = img.shape
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    xs, ys = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    nx, ny = (xs - cx) / fnorm, (ys - cy) / fnorm
    rho = np.sqrt(nx * nx + ny * ny)
    scale = np.where(rho > 1e-6, np.interp(rho, g, r_s) / np.maximum(rho, 1e-6), 1.0)
    mapx = (cx + nx * scale * fnorm).astype(np.float32)
    mapy = (cy + ny * scale * fnorm).astype(np.float32)
    return cv2.remap(img, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def vignette_mask(shape, cfg: SimConfig):
    """Radial optical falloff map in [0,1], 1 at centre; None if disabled."""
    if cfg.vignette_strength <= 0:
        return None
    h, w = shape
    yy, xx = np.ogrid[0:h, 0:w]
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / np.hypot(cx, cy)
    return np.clip(1.0 - cfg.vignette_strength * r ** cfg.vignette_power, 0.0, 1.0)


def apply_vignette(img, cfg: SimConfig):
    mask = vignette_mask(img.shape, cfg)
    if mask is None:
        return img
    return np.clip(img.astype(np.float32) * mask, 0, 255).astype(np.uint8)


def flat_field(img, cfg: SimConfig):
    """Undo the known vignette (divide by the flat field) for detection only."""
    mask = vignette_mask(img.shape, cfg)
    if mask is None:
        return img
    return np.clip(img.astype(np.float32) / np.clip(mask, 0.10, 1.0), 0, 255).astype(np.uint8)


def add_camera_noise(img, cfg: SimConfig, rng):
    """Poisson shot noise + Gaussian read noise on an 8-bit grey image."""
    f = img.astype(np.float32)
    if cfg.full_well_photons > 0:
        photons = f / 255.0 * cfg.full_well_photons
        f = rng.poisson(photons).astype(np.float32) / cfg.full_well_photons * 255.0
    f = f + cfg.background_level                          # lift the noise floor
    if cfg.read_noise > 0:
        f = f + rng.normal(0.0, cfg.read_noise, f.shape).astype(np.float32)
    return np.clip(f, 0, 255).astype(np.uint8)


def render_scene(prims, cfg: SimConfig, theta_deg):
    """Render the scene into the FIXED FOV up to (but NOT including) blur and noise:
    supersample render -> rigid rotation (by theta_deg) -> lens distortion -> crop to
    FOV -> downsample -> fluorescence invert.

    This is the part that is IDENTICAL across degradation levels, so it is rendered
    once per frame and reused for every (blur, noise) level. Returns an 8-bit image
    (bright pattern on dark background when `invert`)."""
    fov, rfov = cfg.fov_um, cfg.fov_um * cfg.render_margin
    ss = cfg.supersample
    while ss > 1 and rfov * cfg.camera_px_per_um * ss > cfg.render_px_cap:
        ss -= 1
    ppu = cfg.camera_px_per_um * ss

    hi = render_png(prims, rfov, rfov, ppu)          # black on white
    hi = rotate_fixed(hi, theta_deg, border=255)
    # optical lens distortion (about the optical axis = render centre = FOV centre)
    hi = apply_lens_distortion(hi, cfg, fnorm=fov * ppu / 2.0)

    # crop the central FOV out of the (larger) rotated render
    o = int(round((rfov - fov) / 2.0 * ppu))
    n = int(round(fov * ppu))
    hi = hi[o:o + n, o:o + n]

    cam = max(1, int(round(fov * cfg.camera_px_per_um)))
    img = cv2.resize(hi, (cam, cam), interpolation=cv2.INTER_AREA) if ss > 1 else hi

    if cfg.invert:
        img = 255 - img
    return img


def apply_camera_effects(base, cfg: SimConfig, rng):
    """Optical blur -> vignette -> sensor noise on a pre-blur scene (from
    `render_scene`). Reads cfg.psf_fwhm_um and the noise params, so the SAME `base`
    yields a different fidelity for each degradation level."""
    img = base
    sigma_px = (cfg.psf_fwhm_um / 2.35482) * cfg.camera_px_per_um
    if sigma_px > 0:
        img = cv2.GaussianBlur(img, (0, 0), sigma_px)
    img = apply_vignette(img, cfg)
    return add_camera_noise(img, cfg, rng)


def render_camera_frame(prims, cfg: SimConfig, rng, theta_deg):
    """Full single-frame pipeline (scene -> blur/vignette/noise). Kept as a
    convenience wrapper; the main sweep uses render_scene + apply_camera_effects so
    the scene is rendered once and degraded many times."""
    return apply_camera_effects(render_scene(prims, cfg, theta_deg), cfg, rng)


# ------------------------------------------------------------------ detection
def decode_frame(img, cfg: SimConfig, detector, clahe, fov_px, in_fov):
    """Calibrated detection pipeline: un-distort the lens + flat-field the vignette,
    restore contrast, CLAHE, then decode. Returns (n_decoded_in_fov, n_in_fov)."""
    det = undistort_lens(img, cfg, fov_px / 2.0)     # calibrate out lens distortion
    det = flat_field(det, cfg)                       # divide out the known vignette
    det = (255 - det) if cfg.invert else det
    det = clahe.apply(det)
    _, ids, _ = detector.detectMarkers(det)
    found = {int(i) for i in ids.flatten()} if ids is not None else set()
    return len(found & in_fov), len(in_fov)


# ------------------------------------------------------------------ IO helpers
def save_multipage_tiff(frames, path):
    """All frames are the same size now -> straight multipage TIFF."""
    try:
        from PIL import Image
    except Exception:
        print("  (Pillow not installed -> skipping multipage stack expansion_stack.tif)")
        return
    pages = [Image.fromarray(f) for f in frames]
    pages[0].save(path, save_all=True, append_images=pages[1:], compression="tiff_lzw")


def save_montage(items, path, subtitle=None):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    n = len(items)
    ncol = min(4, n)
    nrow = (n + ncol - 1) // ncol
    fig, axes = plt.subplots(nrow, ncol, figsize=(4 * ncol, 4.4 * nrow), dpi=110)
    axes = np.atleast_1d(axes).ravel()
    for ax, (lam, img, dec, nfov, theta) in zip(axes, items):
        ax.imshow(img, cmap="gray", vmin=0, vmax=255)
        ok = "OK" if dec == nfov else "!!"
        ax.set_title(f"lambda = {lam:.2f}x   rot {theta:.0f} deg   "
                     f"(fixed FOV {img.shape[1]}x{img.shape[0]} px)\n"
                     f"{dec}/{nfov} in-frame tags decoded  {ok}", fontsize=9)
        ax.axis("off")
    for ax in axes[n:]:
        ax.axis("off")
    title = ("Fixed-zoom microscope: gel expands in a fixed FOV (rigid markers) "
             "+ multi-area warp + rotation + drift, lens distortion, vignette, "
             "blur + noise")
    if subtitle:
        title += f"\n{subtitle}"
    fig.suptitle(title, fontsize=12)
    fig.tight_layout(); fig.savefig(path); plt.close(fig)


# ------------------------------------------------------------------ main
def main(cfg: SimConfig = None):
    cfg = cfg or SimConfig()
    os.makedirs(os.path.join(HERE, "pngs"), exist_ok=True)
    os.makedirs(os.path.join(HERE, "tiffs"), exist_ok=True)

    ids_path = os.path.join(TOOLKIT, "conjoined_marker_ids.json")
    if os.path.exists(ids_path):
        pool = json.load(open(ids_path))["conjoinable_ids"]
    else:
        from conjoined_lib import scan_conjoinable
        pool = scan_conjoinable(1000)["conjoinable_ids"]
    _, _, _, meta = gg.build(gg.GridConfig(), pool)
    node_lut = {(n["node_i"], n["node_j"]): n for n in meta["nodes"]}
    total = meta["n_nodes"]
    gc = meta["config"]

    lobes = make_warp_lobes(meta, cfg)
    drng = np.random.default_rng(cfg.drift_seed)
    detector = make_detector()
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    # accumulating rotation per stage; auto-size the render margin so the largest
    # rotation (plus drift) never crops blank corners into the fixed FOV.
    thetas = [cfg.rotation_deg + k * cfg.rotation_step_deg for k in range(len(cfg.expansions))]
    th = np.radians(max(abs(t) for t in thetas))
    need = float(np.cos(th) + np.sin(th)) + 2 * cfg.drift_um / cfg.fov_um + 0.02
    cfg.render_margin = max(cfg.render_margin, need)

    rfov = cfg.fov_um * cfg.render_margin
    lo, hi = (rfov - cfg.fov_um) / 2.0, (rfov + cfg.fov_um) / 2.0
    m = gc["marker_um"] / 2.0
    center = (rfov / 2.0, rfov / 2.0)
    fov_px = int(round(cfg.fov_um * cfg.camera_px_per_um))

    print(f"Grid          : {gc['n_boxes_x']}x{gc['n_boxes_y']} boxes, {total} conjoined "
          f"tags ({gc['marker_um']} um), {meta['boxes'][0]['n_dots']} dots/box")
    print(f"Fixed FOV     : {cfg.fov_um} um -> {fov_px}x{fov_px} px @ "
          f"{cfg.camera_px_per_um} px/um (markers stay {gc['marker_um']*cfg.camera_px_per_um:.0f} px)")
    print(f"Effects       : {cfg.n_warp_lobes} warp lobes ~{cfg.warp_amp_um} um, "
          f"rotation {thetas[0]:.0f}->{thetas[-1]:.0f} deg (accumulating), "
          f"drift +-{cfg.drift_um} um, vignette {cfg.vignette_strength}, "
          f"PSF FWHM {cfg.psf_fwhm_um} um")
    print(f"Degradation   : {len(cfg.degradations)} fidelity levels -> degradations/"
          f"<name>/ (blur {cfg.degradations[0].psf_fwhm_um}->{cfg.degradations[-1].psf_fwhm_um} "
          f"um FWHM, read noise {cfg.degradations[0].read_noise:.0f}->"
          f"{cfg.degradations[-1].read_noise:.0f}, well {cfg.degradations[0].full_well_photons:.0f}"
          f"->{cfg.degradations[-1].full_well_photons:.0f})")

    # ---- pass 1: render the shared blur/noise-free scene once per lambda ---------
    # Geometry (warp/drift/rotation/optics) is identical for every degradation level,
    # so render it a single time and reuse it. `drift` is drawn per lambda here so the
    # per-frame drift matches the original single-run behaviour exactly.
    scenes = []
    for k, lam in enumerate(cfg.expansions):
        theta = thetas[k]
        drift = drng.uniform(-cfg.drift_um, cfg.drift_um, 2)
        prims, node_D, node_ids = build_frame_prims(meta, node_lut, lam, cfg, lobes, drift)
        base = render_scene(prims, cfg, theta)             # pre-blur, pre-noise

        # which markers are inside the (rotated) FOV -- geometry only, level-independent
        disp = rotate_points(node_D, center, theta)
        in_fov = {node_ids[j] for j in range(len(node_ids))
                  if lo + m <= disp[j, 0] <= hi - m and lo + m <= disp[j, 1] <= hi - m}
        scenes.append({"lam": lam, "theta": theta, "base": base, "in_fov": in_fov})

    # ---- pass 2: degrade each scene per level, into its own folder ---------------
    deg_root = os.path.join(HERE, "degradations")
    os.makedirs(deg_root, exist_ok=True)
    for li, level in enumerate(cfg.degradations):
        # a per-level cfg with only blur + noise overridden (optics/geometry unchanged)
        lcfg = replace(cfg, psf_fwhm_um=level.psf_fwhm_um, read_noise=level.read_noise,
                       full_well_photons=level.full_well_photons,
                       background_level=level.background_level)
        rng = np.random.default_rng(cfg.seed)              # reseed -> correlated noise
        out_dir = os.path.join(deg_root, level.name)       #          fields across levels
        os.makedirs(out_dir, exist_ok=True)
        is_baseline = (li == 0)

        print(f"\n[{level.name}]  PSF FWHM {level.psf_fwhm_um} um, read noise "
              f"{level.read_noise:.0f}, full well {level.full_well_photons:.0f}, "
              f"background {level.background_level:.0f}")
        print(f"{'lambda':>7} {'rot':>6}  {'in-frame tags decoded':>22}")

        frames, montage_items = [], []
        for sc in scenes:
            img = apply_camera_effects(sc["base"], lcfg, rng)
            dec, nfov = decode_frame(img, lcfg, detector, clahe, fov_px, sc["in_fov"])

            tag = f"l{sc['lam']:.2f}x".replace(".", "p")
            cv2.imwrite(os.path.join(out_dir, f"expansion_{tag}.tif"), img)
            if is_baseline:                                # mirror L0 to legacy dirs
                cv2.imwrite(os.path.join(HERE, "pngs", f"expansion_{tag}.png"), img)
                cv2.imwrite(os.path.join(HERE, "tiffs", f"expansion_{tag}.tif"), img)
            frames.append(img)
            montage_items.append((sc["lam"], img, dec, nfov, sc["theta"]))
            print(f"{sc['lam']:>6.2f}x {sc['theta']:>4.0f} deg   {dec:>3}/{nfov} in frame  "
                  f"({total} total)")

        subtitle = (f"{level.name}: PSF FWHM {level.psf_fwhm_um} um, read noise "
                    f"{level.read_noise:.0f}, full well {level.full_well_photons:.0f} e-, "
                    f"background {level.background_level:.0f}")
        save_multipage_tiff(frames, os.path.join(out_dir, "expansion_stack.tif"))
        save_montage(montage_items, os.path.join(out_dir, "montage.png"), subtitle=subtitle)
        if is_baseline:
            save_multipage_tiff(frames, os.path.join(HERE, "tiffs", "expansion_stack.tif"))
            save_montage(montage_items, os.path.join(HERE, "montage.png"))

    n_lvl, n_lam = len(cfg.degradations), len(cfg.expansions)
    print("\nOutputs:")
    print(f"  degradations/<name>/   {n_lvl} folders x {n_lam} TIFF frames "
          f"+ expansion_stack.tif + montage.png each")
    print(f"    levels: {', '.join(l.name for l in cfg.degradations)}")
    print(f"  pngs/ + tiffs/ + montage.png   baseline ({cfg.degradations[0].name}) "
          f"mirror for the existing downstream project")


if __name__ == "__main__":
    main()
