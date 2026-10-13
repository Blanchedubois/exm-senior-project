#!/usr/bin/env python3
"""
make_dummy_series.py — dummy expansion series with ground truth, for the
ArUco_Reference_Tagger port (docs/01_PHASE1_ARUCO_RECOGNITION.md §2.4).

Renders any of the four spacing-workshop designs through the Phase-B camera
model (simulate_v2.py) at a list of expansion factors, with per-frame rotation,
drift, an optional non-uniform warp, noise seeds, and writes:

  <out>/<design>/<run>/
    {lam}X_{design}_s{seed}.ome.tif   16-bit, OME-XML header with fabricated
                                      pixel size / objective / laser / exposure /
                                      gain / acquisition date
    truth.json                        per frame: lambda, rotation, drift, exposure,
                                      every tag's true centre + corners + rotation
                                      in RAW and UNDISTORTED px, warp description,
                                      the lens / vignette applied, in-frame masks
    truth_{frame}.csv                 every feature (tags, dashes, dots):
                                      tag, category, box, x_raw, y_raw, x_und, y_und, in_frame
    truth_meta.json                   the header values written per frame
    reference_tags.json               the design as built (same as the design folder's)
    README.md

Standard runs (docs §2.4): --preset opt_clean | opt_warp | opt_noise |
spectrum_clean | cons_dim | all.

Run:  python make_dummy_series.py --preset all
      python make_dummy_series.py --design optimistic --lams 1,2,4 --rot 0 --warp 0 --seeds 3 --run mytest
"""
from __future__ import annotations
import argparse
import contextlib
import csv
import datetime as dt
import io as _io
import json
import math
import os
import sys
from dataclasses import asdict

import numpy as np
import cv2
import tifffile

HERE = os.path.dirname(os.path.abspath(__file__))
V2 = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from aruco_grid import GridConfig, SPACING_DESIGNS, OPT_DASH_KEEPOUT, build      # noqa: E402
import simulate_v2 as V                                                          # noqa: E402
import spectrum_layout as SL                                                     # noqa: E402

DESIGN_FOLDERS = {"optimistic": "designs/1_optimistic", "medium": "designs/2_medium",
                  "conservative": "designs/3_conservative", "spectrum": "designs/4_spectrum"}
NOISE = dict(read_noise=6.0, full_well=240.0, background=14.0)                 # L2 "as designed"
DEFAULT_ROTS = [2.0, -3.0, 5.0, 1.0, -4.0, 3.0]

PRESETS = {
    "opt_clean":      dict(design="optimistic", lams="1,1.5,2,3,4,6", rot="0", warp=0.0, seeds=1),
    "opt_warp":       dict(design="optimistic", lams="1,1.5,2,3,4,6", rot="2,-3,5,1,-4,3", warp=2.0, seeds=1),
    "opt_noise":      dict(design="optimistic", lams="1,2,4", rot="2", warp=0.0, seeds=10),
    "spectrum_clean": dict(design="spectrum", lams="1,1.5", rot="0", warp=0.0, seeds=1),
    "cons_dim":       dict(design="conservative", lams="1,3,6", rot="1", warp=2.0, seeds=1),
    "opt_nolens":     dict(design="optimistic", lams="1,1.5,2,3,4,6", rot="2,-3,5,1,-4,3", warp=0.0, seeds=1, lens=False),
}


# ------------------------------------------------------------------ design
def design_cfg(design):
    if design == "spectrum":
        return GridConfig(tag_um=SL.TAG_UM, psf_fwhm_um=3.39, dot_pitch_override_um=7.0,
                          dash_keepout_um=OPT_DASH_KEEPOUT, box_specs=SL.box_specs(), variant="spectrum")
    return GridConfig(**SPACING_DESIGNS[design])


def build_design(design):
    cfg = design_cfg(design)
    with contextlib.redirect_stdout(_io.StringIO()):
        _rects, recs, info = build(cfg)
    ref = {"box_um": cfg.box_pitch, "grid_n": cfg.grid_n, "dot_pitch": cfg.dot_pitch_um,
           "dot_phase": info.get("dot_phase", 0.0), "dot_side_um": cfg.dot_side_um,
           "generator": "aruco_grid.py", "config": asdict(cfg), "records": recs}
    if cfg.box_specs and info.get("boxes"):
        ref["boxes"] = info["boxes"]
    return cfg, recs, info, ref


# ------------------------------------------------------------------ truth
def _canvas_to_px(P_um, sim):
    lo = (sim.fov_um * sim.render_margin - sim.fov_um) / 2.0
    return (P_um - lo) / sim.um_per_px - 0.5


def frame_truth(islands, recs, cfg, sim, lam, theta, drift, lobes, warped):
    """Every feature's centre (and tags' corners) in the undistorted frame px and
    in the raw (lens-distorted) frame px. Design y-up -> image y-down here."""
    rfov = sim.fov_um * sim.render_margin
    P0 = np.array([cfg.field_um / 2.0, cfg.field_um / 2.0])
    centre = np.array([rfov / 2.0, rfov / 2.0]) + np.asarray(drift, float)
    M = cv2.getRotationMatrix2D((rfov / 2, rfov / 2), theta, 1.0)
    C = np.array([[i["cx"], i["cy"]] for i in islands], float)
    w = V.warp_disp(C, lobes, sim.warp_sigma_um) * lam if warped else 0.0
    Cd = centre + lam * (C - P0) + w
    T = np.column_stack([Cd[:, 0], rfov - Cd[:, 1]])
    R = T @ M[:, :2].T + M[:, 2]
    px_und = _canvas_to_px(R, sim)
    W = sim.fov_px
    cpx = ((W - 1) / 2.0, (W - 1) / 2.0)
    px_raw = V.lens_forward(px_und, sim, W / 2.0, centre=cpx)
    band_px = abs(sim.lens_k1) * sim.fov_um / 2.0 * 1.4 / sim.um_per_px
    in_frame = ((px_und[:, 0] > band_px) & (px_und[:, 0] < W - 1 - band_px) &
                (px_und[:, 1] > band_px) & (px_und[:, 1] < W - 1 - band_px))
    # tags: rigid corners (printed size) around the moved centre
    tags = {}
    s = cfg.tag_um / 2.0
    for k, isl in enumerate(islands):
        if isl["kind"] != "aruco":
            continue
        cx, cy = Cd[k]
        dc = np.array([[cx - s, cy + s], [cx + s, cy + s], [cx + s, cy - s], [cx - s, cy - s]])
        Tc = np.column_stack([dc[:, 0], rfov - dc[:, 1]]) @ M[:, :2].T + M[:, 2]
        c_und = _canvas_to_px(Tc, sim)
        c_raw = V.lens_forward(c_und, sim, W / 2.0, centre=cpx)
        e = c_und[1] - c_und[0]
        tags[int(isl["aruco_id"])] = dict(
            x_und=float(px_und[k, 0]), y_und=float(px_und[k, 1]),
            x_raw=float(px_raw[k, 0]), y_raw=float(px_raw[k, 1]),
            corners_und=c_und.round(4).tolist(), corners_raw=c_raw.round(4).tolist(),
            rot_deg=float(np.degrees(np.arctan2(e[1], e[0]))),
            in_frame=bool(in_frame[k] and (c_und.min() > band_px) and (c_und.max() < W - 1 - band_px)))
    rows = []
    for k, (isl, r) in enumerate(zip(islands, recs)):
        rows.append((r["tag"], r["category"], r["meta"].get("box", ""), px_raw[k, 0], px_raw[k, 1],
                     px_und[k, 0], px_und[k, 1], int(in_frame[k])))
    return tags, rows, band_px


# ------------------------------------------------------------------ OME header
def ome_xml(shape, um_per_px, meta):
    H, W = shape
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
            f'<Instrument ID="Instrument:0"><Objective ID="Objective:0" NominalMagnification="{meta["magnification"]}" '
            f'LensNA="{meta["numerical_aperture"]}" Immersion="{meta["immersion"]}"/>'
            f'<Laser ID="LightSource:0" Wavelength="{meta["laser_wavelength_nm"]}" Power="{meta["laser_power_mw"]}"/>'
            f'<Detector ID="Detector:0" Gain="{meta["gain_e_per_adu"]}"/></Instrument>'
            f'<Image ID="Image:0" Name="{meta["name"]}" AcquisitionDate="{meta["date"]}T{meta["time"]}">'
            '<ObjectiveSettings ID="Objective:0"/>'
            f'<Pixels ID="Pixels:0" DimensionOrder="XYCZT" Type="uint16" SizeX="{W}" SizeY="{H}" SizeC="1" SizeZ="1" SizeT="1" '
            f'PhysicalSizeX="{um_per_px}" PhysicalSizeXUnit="&#181;m" PhysicalSizeY="{um_per_px}" PhysicalSizeYUnit="&#181;m">'
            f'<Channel ID="Channel:0:0" SamplesPerPixel="1" ExcitationWavelength="{meta["laser_wavelength_nm"]}" '
            f'EmissionWavelength="{meta["emission_nm"]}"><LightSourceSettings ID="LightSource:0"/>'
            f'<DetectorSettings ID="Detector:0" Gain="{meta["gain_e_per_adu"]}"/></Channel><TiffData/>'
            f'<Plane TheZ="0" TheT="0" TheC="0" ExposureTime="{meta["exposure_ms"]}" ExposureTimeUnit="ms"/>'
            '</Pixels></Image></OME>')


# ------------------------------------------------------------------ main
def make_run(design, lams, rots, warp_amp, seeds, run, out_root, psf=None, um_per_px=0.51,
             exposure="compensated", noise=None, quiet=False, lens=True):
    cfg, recs, info, ref = build_design(design)
    islands = info["islands"]
    assert len(islands) == len(recs), "islands and records must align one-to-one"
    sim = V.SimConfig()
    sim.um_per_px = um_per_px
    sim.warp_amp_um = float(warp_amp)
    sim.signal_exp = 0.0 if exposure == "compensated" else -1.84
    if not lens:
        sim.lens_k1 = sim.lens_k2 = 0.0
    psf = psf or cfg.psf_fwhm_um
    nz = noise or NOISE
    lv = V.Level("dummy", psf, nz["read_noise"], nz["full_well"], nz["background"])
    thetas = [rots[k % len(rots)] for k in range(len(lams))]
    th = math.radians(max(abs(t) for t in thetas) if thetas else 0.0)
    sim.render_margin = max(sim.render_margin,
                            float(math.cos(th) + math.sin(th)) + 2 * sim.drift_um / sim.fov_um + 0.02)
    lobes = V.make_lobes(cfg.field_um, sim)
    drng = np.random.default_rng(sim.drift_seed + 11)

    out = os.path.join(out_root, design, run)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "reference_tags.json"), "w") as f:
        json.dump(ref, f)
    lam_min = min(lams)
    frames, meta_all = [], {}
    t_ref_ms = 200.0
    t0 = dt.datetime(2026, 10, 13, 10, 0, 0)
    for k, lam in enumerate(lams):
        theta = thetas[k]
        drift = drng.uniform(-sim.drift_um, sim.drift_um, 2)
        warped = warp_amp > 0 and lam > lam_min            # reference frame unwarped (Phase D)
        s_ = sim if warped else _nowarp(sim)
        # place() warps with whatever lobes it is given, so an unwarped frame gets NO lobes
        rects, _tc, _tid = V.place(islands, lam, s_, lobes if warped else [], cfg.field_um, drift)
        base = V.render_scene(rects, s_, theta)
        tags, rows, band_px = frame_truth(islands, recs, cfg, s_, lam, theta, drift, lobes, warped)
        exp_ms = t_ref_ms * max(1.0, (lam / 1.5) ** 2) if exposure == "compensated" else t_ref_ms
        names = []
        for seed in range(seeds):
            img8 = V.degrade(base, s_, lv, np.random.default_rng(1000 * k + seed), lam=lam)
            img16 = (img8.astype(np.uint16) * 4)
            name = f"{lam:g}X_{design}_s{seed}"
            when = t0 + dt.timedelta(minutes=10 * k + seed)
            meta = dict(name=name, magnification=20, numerical_aperture=0.75, immersion="Air",
                        laser_wavelength_nm=488, laser_power_mw=10.0, emission_nm=520,
                        exposure_ms=round(exp_ms, 1), gain_e_per_adu=2.0,
                        date=when.strftime("%Y-%m-%d"), time=when.strftime("%H:%M:%S"),
                        um_per_px=um_per_px)
            tifffile.imwrite(os.path.join(out, name + ".ome.tif"), img16,
                             description=ome_xml(img16.shape, um_per_px, meta))
            meta_all[name] = meta
            names.append(name)
        with open(os.path.join(out, f"truth_{lam:g}X.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["tag", "category", "box", "x_raw", "y_raw", "x_und", "y_und", "in_frame"])
            for r in rows:
                w.writerow([r[0], r[1], r[2], f"{r[3]:.4f}", f"{r[4]:.4f}", f"{r[5]:.4f}", f"{r[6]:.4f}", r[7]])
        n_in = sum(1 for t in tags.values() if t["in_frame"])
        frames.append(dict(label=lam, files=names, truth_csv=f"truth_{lam:g}X.csv", rotation_deg=theta,
                           drift_um=[float(d) for d in drift], warped=bool(warped),
                           exposure_ms=round(exp_ms, 1), signal_scale=V.signal_scale(s_, lam),
                           tags=tags, n_tags_in_frame=n_in, n_features_in_frame=int(sum(r[7] for r in rows)),
                           edge_band_px=float(band_px)))
        if not quiet:
            print(f"  {design}/{run}: lambda {lam:g}  rot {theta:+.1f}  warp {'on' if warped else 'off'}  "
                  f"{n_in}/36 tags in frame  x{seeds} seed(s)")
    truth = dict(design=design, design_folder=DESIGN_FOLDERS[design], run=run,
                 camera=dict(um_per_px=um_per_px, fov_px=sim.fov_px, lens=bool(lens), lens_k1=sim.lens_k1, lens_k2=sim.lens_k2,
                             vignette_strength=sim.vignette_strength, vignette_power=sim.vignette_power,
                             psf_fwhm_um=psf, noise=nz, bit_depth_scale=4, exposure_policy=exposure),
                 warp=dict(amp_um=float(warp_amp), n_lobes=sim.n_warp_lobes, sigma_um=sim.warp_sigma_um,
                           seed=sim.warp_seed, lobes=[[c.tolist(), a.tolist()] for c, a in lobes]),
                 design_summary=dict(tag_um=cfg.tag_um, box_pitch_um=cfg.box_pitch, origin_um=cfg.origin,
                                     n_records=len(recs)),
                 frames=frames, px_convention="OpenCV pixel centres; y down; raw = as in the TIFF, und = after exact lens un-distortion")
    with open(os.path.join(out, "truth.json"), "w") as f:
        json.dump(truth, f, indent=1)
    with open(os.path.join(out, "truth_meta.json"), "w") as f:
        json.dump(meta_all, f, indent=1)
    with open(os.path.join(out, "README.md"), "w") as f:
        f.write(f"# dummy run `{design}/{run}`\n\nGenerated by `tools/make_dummy_series.py`. "
                f"lams {lams} · rotations {thetas} · warp {warp_amp} um · seeds {seeds} · PSF {psf} um · "
                f"{um_per_px} um/px · exposure {exposure}.\n\nSee `truth.json` for every frame's ground truth "
                "and `truth_<lam>X.csv` for every feature's true position (raw and undistorted px).\n")
    return out


def _nowarp(sim):
    s = V.SimConfig(**{k: v for k, v in asdict(sim).items()})
    s.warp_amp_um = 0.0
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", choices=list(PRESETS) + ["all"])
    ap.add_argument("--design", choices=list(DESIGN_FOLDERS), default="optimistic")
    ap.add_argument("--lams", default="1,2,4")
    ap.add_argument("--rot", default=",".join(str(r) for r in DEFAULT_ROTS), help="per-frame rotation deg, cycled")
    ap.add_argument("--warp", type=float, default=0.0, help="warp amplitude um (0 = off); never on the lowest frame")
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--psf", type=float, default=None, help="PSF FWHM um (default: the design's)")
    ap.add_argument("--um-per-px", type=float, default=0.51)
    ap.add_argument("--exposure", choices=["compensated", "fixed"], default="compensated")
    ap.add_argument("--no-lens", action="store_true", help="no lens distortion (vignette kept)")
    ap.add_argument("--run", default=None)
    ap.add_argument("--out", default=os.path.join(V2, "dummy"))
    a = ap.parse_args(argv)

    runs = [(a.preset, PRESETS[a.preset])] if a.preset and a.preset != "all" else \
           (list(PRESETS.items()) if a.preset == "all" else
            [(a.run or f"{a.design}_custom", dict(design=a.design, lams=a.lams, rot=a.rot, warp=a.warp, seeds=a.seeds, lens=not a.no_lens))])
    for run, p in runs:
        lams = [float(x) for x in str(p["lams"]).split(",")]
        rots = [float(x) for x in str(p["rot"]).split(",")]
        out = make_run(p["design"], lams, rots, p["warp"], int(p["seeds"]), run, a.out,
                       psf=a.psf, um_per_px=a.um_per_px, exposure=a.exposure, lens=p.get("lens", True))
        print(f"wrote {out}")
    _index(a.out)


def _index(root):
    lines = ["# Dummy series", "", "Synthetic expansion frames with ground truth, generated by "
             "`tools/make_dummy_series.py`. TIFFs are gitignored; regenerate with "
             "`python tools/make_dummy_series.py --preset all`.", "", "| design | run | frames | README |", "|---|---|---|---|"]
    for d in sorted(os.listdir(root)):
        dd = os.path.join(root, d)
        if not os.path.isdir(dd):
            continue
        for r in sorted(os.listdir(dd)):
            rd = os.path.join(dd, r)
            if os.path.isdir(rd):
                n = len([f for f in os.listdir(rd) if f.endswith(".ome.tif")])
                lines.append(f"| {d} | {r} | {n} | [{r}]({d}/{r}/README.md) |")
    with open(os.path.join(root, "README.md"), "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
