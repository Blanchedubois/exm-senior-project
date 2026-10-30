#!/usr/bin/env python3
"""Test workshop: can the pipeline detect spatial structure in a distortion?

Simulated images only. Every run goes through the faithful path (exact
render with noise, OpenCV tag detection, tag-centre affine, resampling,
windowed lattice-aware CCF). Measured maps use windows holding only dots.

  1. correlation length of the local expansion factor (truth and measured),
     and how much distortion is left after correcting from reference points
     of spacing d, against d / correlation length
  2. directions of maximum stretch: aligned or random?
  3. RMS length error against measurement length
  4. detection limit: no-site controls set the noise floor, then single
     sites of decreasing strength and size are tested against it

Writes figures to blog/images/2026-10-30-*.png and numbers to
studies/results/spatial_structure.json.

    python studies/spatial_structure.py
"""

import copy
import json
import os
import sys
import time

import numpy as np
from scipy import ndimage

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.ticker import FormatStrFormatter, NullFormatter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from exm_explorer import analysis as an          # noqa: E402
from exm_explorer import pipeline, spatial       # noqa: E402
from exm_explorer.grid import load_grid          # noqa: E402
from exm_explorer.scenario import Scenario, Site, legacy_scenario   # noqa: E402

REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
IMG = os.path.join(REPO, "blog", "images")
OUT = os.path.join(HERE, "results")
PREFIX = "2026-10-30-"

# reference palette, light mode
C = dict(blue="#2a78d6", orange="#eb6834", aqua="#1baf7a", yellow="#eda100", violet="#6250d6",
         grey="#52514e", ink="#0b0b0b", muted="#8a8984")
DIV = LinearSegmentedColormap.from_list("div", [C["blue"], "#f1f0ec", C["orange"]])
SEQ = LinearSegmentedColormap.from_list("seq", ["#f1f0ec", "#123a6b"])
plt.rcParams.update({"font.size": 10, "axes.edgecolor": C["grey"], "axes.labelcolor": C["ink"],
                     "xtick.color": C["grey"], "ytick.color": C["grey"], "axes.spines.top": False,
                     "axes.spines.right": False, "figure.dpi": 110})

BOX_CENTRES = 11.5 + 145.4 * (np.arange(5) + 0.5)       # away from tags and dashes


# ===================================================================== scenarios
def scen(sites, seed=1, name=""):
    s = Scenario(sites=sites, name=name)
    s.imaging.seed = seed
    return s


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
    for i, x in enumerate(BOX_CENTRES):
        for j, y in enumerate(BOX_CENTRES):
            ang = 30.0 if aligned else float(rng.uniform(0, 180))
            out.append(Site(cx=x, cy=y, a=45, b=45, eps1=0.06, eps2=-0.06, eps_angle_deg=ang,
                            softness=0.3, name=f"aniso {i}{j}"))
    return out


# ===================================================================== one run
def run(sc, grid):
    t0 = time.perf_counter()
    res, ex = pipeline.run_faithful(sc, grid)
    P = ex["runs"]["tags"]
    pos, fld = ex["sim"].positions, ex["sim"].field
    a = sc.analysis
    um = sc.imaging.um_px
    A = ex["registrations"]["tags"][0]
    lam_A = float(np.sqrt(abs(np.linalg.det(A))))
    dots = P["dots_only"] & P["valid"]
    unw = np.where(dots[..., None], P["unwrapped"], np.nan)
    scale, J = an.local_scale_fit(unw, a.step, lam_A)
    delta = scale / np.nanmedian(scale) - 1

    # measured anisotropy and stretch direction, image frame -> design frame
    ok = np.isfinite(J[..., 0, 0])
    aniso = np.full(ok.shape, np.nan)
    ang = np.full(ok.shape, np.nan)
    U, S, Vt = np.linalg.svd(J[ok])
    aniso[ok] = S[:, 0] / S[:, 1]
    ang_img = np.degrees(np.arctan2(Vt[:, 0, 1], Vt[:, 0, 0]))
    ang[ok] = (-(ang_img - sc.imaging.theta_pre_deg)) % 180

    # truth at the window centres (design frame)
    cx, cy = np.meshgrid(P["cs_x"], P["cs_y"])
    D = pos.pre.px_to_design(np.c_[cx.ravel(), cy.ravel()])
    tr = fld.truth(sc.imaging.lam)
    ti = {k: fld.interp(v, D[:, 0], D[:, 1]).reshape(cx.shape) for k, v in tr.items()}
    t_delta = ti["expansion"] / sc.imaging.lam - 1

    # dot residuals for RMS vs length (pre-sample um)
    d = grid.cat == "dot"
    r_true, _ = spatial.remove_similarity(pos.pre_px[d] * um, pos.post_px[d] * um)
    xy_w = np.c_[cx[dots], cy[dots]] * um
    r_meas, _ = spatial.remove_similarity(xy_w, xy_w + unw[dots] * um)
    return dict(sc=sc, res=res, P=P, fld=fld, tr=tr, design_xy=D.reshape(cx.shape + (2,)),
                delta=delta, aniso=aniso, ang=ang, t_delta=t_delta, t_aniso=ti["anisotropy"],
                t_ang=ti["aniso_dir"], dots=dots, step_um=a.step * um, r_true=r_true,
                xy_true=pos.pre_px[d] * um, r_meas=r_meas, xy_meas=xy_w, secs=time.perf_counter() - t0)


def field_box(fld, tr_key, lam):
    xs = fld.xs
    k = np.nonzero((xs >= 0) & (xs <= 750))[0]
    m = fld.truth(lam)[tr_key][k[0]:k[-1] + 1, k[0]:k[-1] + 1]
    return m, xs[k]


# ===================================================================== main
def main():
    os.makedirs(IMG, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    grid = load_grid()
    out = {}
    R = {}
    t0 = time.perf_counter()

    def go(key, sc):
        R[key] = run(sc, grid)
        print(f"  {key:22s} {R[key]['secs']:5.1f} s", flush=True)

    print("controls")
    for s in range(1, 7):
        go(f"control {s}", scen([], seed=s, name=f"control {s}"))
    print("structured scenarios")
    go("smooth", scen(smooth_sites(), name="smooth"))
    go("local", scen(local_sites(), name="local"))
    go("aligned", scen(aniso_sites(True), name="aligned"))
    go("random", scen(aniso_sites(False), name="random"))
    leg = legacy_scenario()
    go("batch run", leg)
    print("detection sweep")
    iso_eps = [0.005, 0.01, 0.02, 0.04, 0.08]
    sizes = [20, 40, 80]
    for a in sizes:
        for e in iso_eps:
            go(f"iso a{a} e{e}", scen([Site(cx=BOX_CENTRES[2], cy=BOX_CENTRES[2], a=a, b=a, eps1=-e,
                                             eps2=-e, lock_isotropic=True, softness=0.3)],
                                       name=f"iso a{a} e{e}"))
    an_eps = [0.005, 0.01, 0.02, 0.04]
    for e in an_eps:
        go(f"aniso e{e}", scen([Site(cx=BOX_CENTRES[2], cy=BOX_CENTRES[2], a=60, b=60, eps1=e,
                                     eps2=-e, softness=0.3)], name=f"aniso e{e}"))
    out["runtime_s"] = time.perf_counter() - t0

    # ------------------------------------------------------------ 4. noise floor from controls
    ctrl = [R[f"control {s}"] for s in range(1, 7)]
    all_d = np.concatenate([np.abs(r["delta"][np.isfinite(r["delta"])]) for r in ctrl])
    all_a = np.concatenate([r["aniso"][np.isfinite(r["aniso"])] - 1 for r in ctrl])
    floor = dict(
        windows_per_map=int(np.mean([np.isfinite(r["delta"]).sum() for r in ctrl])),
        delta_rms=float(np.sqrt(np.mean(all_d ** 2))),
        delta_p999=float(np.percentile(all_d, 99.9)),
        delta_map_max=float(max(np.nanmax(np.abs(r["delta"])) for r in ctrl)),
        aniso_median=float(np.median(all_a)),
        aniso_p999=float(np.percentile(all_a, 99.9)),
        aniso_map_max=float(max(np.nanmax(r["aniso"] - 1) for r in ctrl)),
        ccf_rms_dots_only=[r["res"]["ccf_after_tags_correction"]["dots_only_unwrapped_rms_err_px"]
                           for r in ctrl])
    out["noise_floor"] = floor
    T_d, T_a = floor["delta_map_max"], floor["aniso_map_max"]

    def near(r, x, y, rad):
        D = r["design_xy"]
        return np.hypot(D[..., 0] - x, D[..., 1] - y) < rad

    sweep = {}
    for a in sizes:
        rows = []
        for e in iso_eps:
            r = R[f"iso a{a} e{e}"]
            m = near(r, BOX_CENTRES[2], BOX_CENTRES[2], a + 30)
            sig = float(-np.nanmin(np.where(m, r["delta"], np.nan)))
            tru = float(-np.nanmin(np.where(m, r["t_delta"], np.nan)))
            rows.append(dict(eps=e, measured=sig, true_at_windows=tru, detected=bool(sig > T_d)))
        sweep[f"isotropic a={a} um"] = rows
    rows = []
    for e in an_eps:
        r = R[f"aniso e{e}"]
        m = near(r, BOX_CENTRES[2], BOX_CENTRES[2], 90)
        sig = float(np.nanmax(np.where(m, r["aniso"], np.nan)) - 1)
        tru = float(np.nanmax(np.where(m, r["t_aniso"], np.nan)) - 1)
        rows.append(dict(eps=e, measured=sig, true_at_windows=tru, detected=bool(sig > T_a)))
    sweep["anisotropic a=60 um"] = rows
    out["detection_sweep"] = sweep

    def limit(rows):
        hit = [r["eps"] for r in rows if r["detected"]]
        return min(hit) if hit else None
    out["detection_limit"] = {k: limit(v) for k, v in sweep.items()}

    # ------------------------------------------------------------ 1. correlation length
    corr = {}
    prof = {}
    for key in ("smooth", "local", "batch run", "aligned", "control 1"):
        r = R[key]
        sc = r["sc"]
        m_t, xs = field_box(r["fld"], "expansion", sc.imaging.lam)
        if np.ptp(m_t) > 1e-9:
            xi_t, lt, pt = spatial.correlation_length(m_t, np.ones_like(m_t, bool), r["fld"].step,
                                                      maxlag=150)
        else:
            xi_t, lt, pt = np.nan, None, None
        dm = np.isfinite(r["delta"])
        xi_m, lm, pm = spatial.correlation_length(r["delta"], dm, r["step_um"], maxlag=25)
        corr[key] = dict(truth_um=float(xi_t), measured_um=float(xi_m))
        prof[key] = (lt, pt, lm, pm)
    out["correlation_length"] = corr

    spacings = [20, 30, 45, 60, 90, 145.4, 200, 300]
    refres = {}
    for key in ("smooth", "local", "batch run"):
        r = R[key]
        f = r["fld"]
        rows = []
        for d in spacings:
            left, total = spatial.reference_residual(f.xs, f.ux, f.uy, d)
            rows.append(dict(spacing_um=d, residual_um=left, distortion_um=total,
                             fraction_left=left / total))
        refres[key] = rows
    out["reference_spacing"] = refres

    # ------------------------------------------------------------ 2. directions
    dirs = {}
    for key in ("aligned", "random"):
        r = R[key]
        t_sel = np.isfinite(r["t_aniso"]) & (r["t_aniso"] - 1 > 0.01)
        m_sel = np.isfinite(r["aniso"]) & (r["aniso"] - 1 > T_a)
        st = r["step_um"]
        # independent directions: from the correlation area of the direction
        # field, not the number of windows (windows in one site agree)
        n_t = spatial.direction_samples(r["t_ang"], t_sel, st, 750 ** 2)
        n_m = spatial.direction_samples(r["ang"], m_sel, st, 750 ** 2)
        dirs[key] = dict(truth=spatial.axial_stats(r["t_ang"][t_sel], n_eff=n_t),
                         measured=spatial.axial_stats(r["ang"][m_sel], n_eff=n_m),
                         measured_if_windows_counted=spatial.axial_stats(r["ang"][m_sel]),
                         sites=25, _t=r["t_ang"][t_sel], _m=r["ang"][m_sel])
    out["directions"] = {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")}
                         for k, v in dirs.items()}

    # ------------------------------------------------------------ 3. RMS error vs length
    bins = np.arange(0, 615, 15.0)
    rmsl = {}
    for key in ("control 1", "smooth", "local", "batch run"):
        r = R[key]
        Lt, et, _ = spatial.rms_error_vs_length(r["xy_true"], r["r_true"], bins)
        Lm, em, nm = spatial.rms_error_vs_length(r["xy_meas"], r["r_meas"], bins)
        em = np.where(nm > 200, em, np.nan)
        rmsl[key] = dict(L=Lt.tolist(), truth_um=et.tolist(), measured_um=em.tolist())
    out["rms_vs_length"] = rmsl
    for key, v in rmsl.items():
        L = np.array(v["L"])
        for lab in ("truth_um", "measured_um"):
            e = np.array(v[lab], float)
            v[lab.replace("_um", "_pct_at")] = {f"{int(x)} um": float(100 * np.interp(x, L, e) / x)
                                                 for x in (25, 100, 300)}

    with open(os.path.join(OUT, "spatial_structure.json"), "w") as fh:
        json.dump(out, fh, indent=1, default=float)
    print(json.dumps({k: out[k] for k in ("noise_floor", "detection_limit", "correlation_length",
                                          "directions")}, indent=1, default=float))

    # ================================================================ figures
    def wmap(ax, r, img, cmap, lo, hi, title):
        P = r["P"]
        st = r["step_um"]
        x0 = P["cs_x"][0] * 0.51
        y0 = P["cs_y"][0] * 0.51
        ny, nx = img.shape
        # window grid is in pre px (y down); show in the image frame
        im = ax.imshow(img, cmap=cmap, vmin=lo, vmax=hi, origin="upper",
                       extent=[x0 - st / 2, x0 + (nx - 0.5) * st, y0 + (ny - 0.5) * st, y0 - st / 2])
        ax.set_title(title, fontsize=10)
        ax.set_xticks([]); ax.set_yticks([])
        return im

    def tmap(ax, r, key, cmap, lo, hi, title):
        m, xs = field_box(r["fld"], key, r["sc"].imaging.lam)
        if key == "expansion":
            m = m / r["sc"].imaging.lam - 1
        im = ax.imshow(m, cmap=cmap, vmin=lo, vmax=hi, origin="lower",
                       extent=[xs[0], xs[-1], xs[0], xs[-1]])
        ax.set_title(title, fontsize=10)
        ax.set_xticks([]); ax.set_yticks([])
        return im

    # figure 1: four simulated scenarios, truth vs measured
    fig, axs = plt.subplots(2, 4, figsize=(15, 7.6))
    for c, (key, kind) in enumerate((("smooth", "expansion"), ("local", "expansion"),
                                      ("aligned", "anisotropy"), ("random", "anisotropy"))):
        r = R[key]
        if kind == "expansion":
            v = 0.06
            im1 = tmap(axs[0, c], r, "expansion", DIV, -v, v, f"{key}: true local expansion − 1")
            im2 = wmap(axs[1, c], r, r["delta"], DIV, -v, v, "measured (CCF, dot windows)")
        else:
            im1 = tmap(axs[0, c], r, "anisotropy", SEQ, 1.0, 1.08, f"{key}: true local anisotropy")
            im2 = wmap(axs[1, c], r, r["aniso"], SEQ, 1.0, 1.08, "measured (CCF, dot windows)")
        fig.colorbar(im1, ax=axs[0, c], shrink=0.75)
        fig.colorbar(im2, ax=axs[1, c], shrink=0.75)
    fig.suptitle("Simulated test scenarios: ground truth (top, design frame) and what the pipeline "
                 "measures (bottom, image frame)", fontsize=11)
    plt.tight_layout()
    fig.savefig(os.path.join(IMG, PREFIX + "scenarios.png"), dpi=90)
    plt.close(fig)

    # figure 2: correlation length and reference spacing
    fig, axs = plt.subplots(1, 2, figsize=(12.5, 4.6))
    ax = axs[0]
    colors = {"smooth": C["blue"], "local": C["orange"], "batch run": C["aqua"], "control 1": C["grey"]}
    for key, col in colors.items():
        lt, pt, lm, pm = prof[key]
        if pt is not None:
            ax.plot(lt, pt, "-", color=col, lw=2, label=f"{key}: truth (ξ = {corr[key]['truth_um']:.0f} µm)")
        ax.plot(lm, pm, "--", color=col, lw=2, marker="o", ms=4,
                label=f"{key}: measured (ξ = {corr[key]['measured_um']:.0f} µm)")
    ax.axhline(np.exp(-1), color=C["muted"], lw=1, ls=":")
    ax.text(290, np.exp(-1) + 0.03, "1/e", color=C["muted"])
    ax.set_xlim(0, 300); ax.set_ylim(-0.4, 1.02)
    ax.set_xlabel("lag (µm)"); ax.set_ylabel("autocorrelation of local expansion")
    ax.set_title("Correlation length of the local expansion factor", fontsize=10)
    ax.legend(fontsize=8, frameon=False)
    ax = axs[1]
    for key, col in (("smooth", C["blue"]), ("local", C["orange"]), ("batch run", C["aqua"])):
        rows = refres[key]
        xi = corr[key]["truth_um"]
        ax.plot([q["spacing_um"] / xi for q in rows], [100 * q["fraction_left"] for q in rows], "-o",
                color=col, lw=2, ms=5, label=f"{key} (ξ = {xi:.0f} µm)")
    ax.set_xscale("log")
    ax.axvline(1, color=C["muted"], lw=1, ls=":")
    ax.set_xlabel("reference spacing d / correlation length ξ")
    ax.set_ylabel("distortion left after correction (%)")
    ax.set_title("Correcting from reference points on a grid of spacing d\n(thin-plate spline, truth fields)",
                 fontsize=10)
    ax.legend(fontsize=8, frameon=False)
    plt.tight_layout()
    fig.savefig(os.path.join(IMG, PREFIX + "correlation-length.png"), dpi=100)
    plt.close(fig)

    # figure 3: directions
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.2), sharey=False)
    b = np.arange(0, 181, 10)
    for ax, key in zip(axs, ("aligned", "random")):
        d = dirs[key]
        ax.hist(d["_t"], bins=b, density=True, histtype="step", lw=2, color=C["blue"],
                label=f"truth: R = {d['truth']['R']:.2f}, p = {d['truth']['p']:.1g}")
        ax.hist(d["_m"], bins=b, density=True, histtype="step", lw=2, color=C["orange"],
                label=f"measured: R = {d['measured']['R']:.2f}, p = {d['measured']['p']:.1g}")
        ax.axhline(1 / 180, color=C["muted"], ls=":", lw=1)
        ax.set_xlim(0, 180); ax.set_xticks(range(0, 181, 30))
        ax.set_xlabel("direction of maximum stretch (deg, design frame)")
        ax.set_ylabel("density")
        what = "all sites stretched along 30°" if key == "aligned" else "site directions drawn at random"
        ax.set_title(f"{key}: {what}\n(about {d['measured']['n_eff']:.0f} independent directions; "
                     f"25 sites)", fontsize=10)
        ax.legend(fontsize=8, frameon=False, loc="upper right")
    plt.tight_layout()
    fig.savefig(os.path.join(IMG, PREFIX + "stretch-directions.png"), dpi=100)
    plt.close(fig)

    # figure 4: RMS error vs length
    fig, axs = plt.subplots(1, 2, figsize=(12.5, 4.4))
    for key, col in colors.items():
        v = rmsl[key]
        L = np.array(v["L"])
        axs[0].plot(L, v["truth_um"], "-", color=col, lw=2, label=f"{key}: truth (all dots)")
        axs[0].plot(L, v["measured_um"], "--", color=col, lw=1.6, label=f"{key}: measured (CCF windows)")
        axs[1].plot(L, 100 * np.array(v["truth_um"]) / L, "-", color=col, lw=2)
        axs[1].plot(L, 100 * np.array(v["measured_um"], float) / L, "--", color=col, lw=1.6)
    axs[0].set_xlabel("measurement length (pre-expansion µm)"); axs[0].set_ylabel("RMS length error (µm)")
    axs[0].set_title("RMS length error vs measurement length", fontsize=10)
    axs[0].legend(fontsize=7.5, frameon=False, ncol=2)
    axs[1].axhline(1, color=C["ink"], lw=1, ls=":")
    axs[1].text(400, 1.08, "1 % (Chen et al. 2015 report < 1 %)", fontsize=8, color=C["ink"])
    axs[1].set_ylim(0, 4); axs[1].set_xlim(0, 600)
    axs[1].set_xlabel("measurement length (pre-expansion µm)"); axs[1].set_ylabel("RMS error (% of length)")
    axs[1].set_title("The same as a percentage of the length", fontsize=10)
    plt.tight_layout()
    fig.savefig(os.path.join(IMG, PREFIX + "rms-vs-length.png"), dpi=100)
    plt.close(fig)

    # figure 5: detection limit
    fig, axs = plt.subplots(1, 2, figsize=(12.5, 4.4))
    ax = axs[0]
    for a, col in zip(sizes, (C["orange"], C["blue"], C["aqua"])):
        rows = sweep[f"isotropic a={a} um"]
        e = [q["eps"] * 100 for q in rows]
        ax.plot(e, [100 * q["measured"] for q in rows], "-o", color=col, lw=2, ms=5, label=f"radius {a} µm: measured")
        ax.plot(e, [100 * q["true_at_windows"] for q in rows], ":", color=col, lw=1.5, label=f"radius {a} µm: truth")
    ax.axhline(100 * T_d, color=C["ink"], lw=1.2, ls="--")
    ax.text(0.55, 100 * T_d * 1.12, f"noise floor from 6 no-site controls ({100 * T_d:.2f} %)", fontsize=8)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("eigenstrain of a lagging site, |ε*| (%)")
    ax.set_ylabel("largest local expansion deficit (%)")
    ax.set_title("Detection limit, isotropic lagging site", fontsize=10)
    for axis in (ax.xaxis, ax.yaxis):
        axis.set_major_formatter(FormatStrFormatter("%g")); axis.set_minor_formatter(NullFormatter())
    ax.legend(fontsize=7.5, frameon=False)
    ax = axs[1]
    rows = sweep["anisotropic a=60 um"]
    e = [q["eps"] * 100 for q in rows]
    ax.plot(e, [100 * q["measured"] for q in rows], "-o", color=C["violet"], lw=2, ms=5, label="measured")
    ax.plot(e, [100 * q["true_at_windows"] for q in rows], ":", color=C["violet"], lw=1.5, label="truth")
    ax.axhline(100 * T_a, color=C["ink"], lw=1.2, ls="--")
    ax.text(0.55, 100 * T_a * 1.12, f"noise floor from controls ({100 * T_a:.2f} %)", fontsize=8)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("eigenstrain ε₁ = −ε₂ (%), radius 60 µm")
    ax.set_ylabel("largest local anisotropy − 1 (%)")
    ax.set_title("Detection limit, anisotropic site", fontsize=10)
    for axis in (ax.xaxis, ax.yaxis):
        axis.set_major_formatter(FormatStrFormatter("%g")); axis.set_minor_formatter(NullFormatter())
    ax.legend(fontsize=8, frameon=False)
    plt.tight_layout()
    fig.savefig(os.path.join(IMG, PREFIX + "detection-limit.png"), dpi=100)
    plt.close(fig)
    print(f"done in {time.perf_counter() - t0:.0f} s")


if __name__ == "__main__":
    main()
