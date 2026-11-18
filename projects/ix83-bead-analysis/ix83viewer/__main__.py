"""Command line for the IX83 data layer.

    python3 -m ix83viewer gui     [date or acquisition folder]
    python3 -m ix83viewer scan    <date folder>
    python3 -m ix83viewer info    <acquisition folder>
    python3 -m ix83viewer project <acquisition folder> [-m mean] [-o out.tif] [--dark <dark folder>]
    python3 -m ix83viewer beads-check <experiment.json> [--root <date folder>] [--no-overlap]
    python3 -m ix83viewer beads-panels <experiment.json> [-o <output folder>] [--root <date folder>]
    python3 -m ix83viewer beads-refs <experiment.json> [-o <reference_beads.json>] [--root <date folder>]
    python3 -m ix83viewer beads-flat <experiment.json> [--root <date folder>] [--no-gamma]
    python3 -m ix83viewer beads-density <experiment.json> [--root <date folder>] [--pooled-bead-light]
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np

from .core.corrections import build_dark_frame, subtract_dark
from .core.projection import METHODS, project
from .io.mm_dataset import MMDataset
from .io.scan import DEFAULT_XY_TOL_UM, DEFAULT_Z_TOL_UM, group_by_position, scan_folder


def cmd_scan(args) -> int:
    res = scan_folder(args.folder)
    sets = group_by_position(res.samples, args.xy_tol, args.z_tol)
    print(f"{res.root}\n{len(res.samples)} sample acquisitions, {len(res.calibrations)} calibration, {len(sets)} fields of view\n")
    for s in sets:
        x, y, _ = s.xyz_um
        zlo, zhi = s.z_range_um
        z = f"{zlo:.1f}" if zhi - zlo < 0.05 else f"{zlo:.1f}-{zhi:.1f}"
        tag = "RGB complete" if s.is_complete else "incomplete"
        print(f"Set {s.label}  XY ({x:.1f}, {y:.1f}) um  Z {z} um  [{tag}]")
        for wl, members in s.by_wavelength().items():
            for d in members:
                print(f"    {wl}  {_row(d)}")
        for n in s.notes:
            print(f"    note: {n}")
        print()
    if res.calibrations:
        print("Calibration")
        for d in res.calibrations:
            print(f"    {d.name.kind:<5} {_row(d)}")
        print()
    flagged = [d for d in res.datasets if d.warnings]
    if flagged:
        print("Warnings")
        for d in flagged:
            for w in d.warnings:
                print(f"    {d.label}: {w}")
    for name, err in res.errors.items():
        print(f"    ERROR {name}: {err}")
    return 0


def _row(d: MMDataset) -> str:
    px = f"{d.pixel_size_um:.3g} um/px" if d.pixel_size_um else "? um/px"
    return f"{d.label:<36} {d.n_frames:>4} fr  {d.exposure_ms:g} ms  {d.objective}  {px}"


def cmd_info(args) -> int:
    d = MMDataset.open(args.folder)
    x, y, z = d.stage_xyz_um
    rows = [
        ("Folder", d.folder),
        ("Kind", d.name.kind),
        ("Wavelength", f"{d.wavelength_nm} nm" if d.wavelength_nm else "-"),
        ("Factor", f"{d.name.factor:g}x" if d.name.factor else "-"),
        ("Frames", f"{d.n_frames} (intended {d.summary.get('IntendedDimensions', {}).get('time', '?')})"),
        ("Image", f"{d.shape_yx[1]} x {d.shape_yx[0]} px, {d.dtype}"),
        ("Exposure", f"{d.exposure_ms:g} ms"),
        ("Objective", d.objective),
        ("Pixel size", f"{d.pixel_size_um:.4g} um (metadata says {d.reported_pixel_size_um})"),
        ("Stage XYZ", f"({x}, {y}, {z}) um"),
        ("Started", d.start_time),
        ("Comment", d.comment),
    ]
    for k, v in rows:
        print(f"{k:>11}: {v}")
    for w in d.warnings:
        print(f"    warning: {w}")
    return 0


def cmd_project(args) -> int:
    import tifffile

    d = MMDataset.open(args.folder)
    img = project(d, args.method, args.start, args.stop, args.frame, use_cache=not args.no_cache)
    if args.dark:
        img = subtract_dark(img, build_dark_frame(MMDataset.open(args.dark)))
    print(f"{d.label} {args.method}: shape {img.shape} {img.dtype} "
          f"min {img.min():.1f} median {np.median(img):.1f} p99.9 {np.percentile(img, 99.9):.1f} max {img.max():.1f}")
    if args.output:
        tifffile.imwrite(args.output, img, imagej=img.dtype != np.float64,
                         resolution=(1 / d.pixel_size_um,) * 2 if d.pixel_size_um else None,
                         metadata={"unit": "um"})
        print(f"wrote {os.path.abspath(args.output)}")
    return 0


def cmd_beads_check(args) -> int:
    from .beads.experiment import check_experiment, format_report, load_experiment

    report = check_experiment(load_experiment(args.experiment, args.root), overlap=not args.no_overlap)
    print(format_report(report))
    return 1 if report.errors else 0


def cmd_beads_panels(args) -> int:
    from .beads.experiment import check_experiment, format_report, load_experiment
    from .beads.panels import export_panels

    exp = load_experiment(args.experiment, args.root)
    report = check_experiment(exp, overlap=False)
    if report.errors:
        print(format_report(report))
        return 1
    out = args.output or os.path.join("outputs", os.path.splitext(os.path.basename(args.experiment))[0], "panels")
    for path in export_panels(exp, out):
        print(f"wrote {path}")
    return 0


def cmd_beads_refs(args) -> int:
    from .beads.experiment import load_experiment
    from .beads.refbeads_window import run

    exp = load_experiment(args.experiment, args.root)
    out = args.output or os.path.join("outputs", os.path.splitext(os.path.basename(args.experiment))[0],
                                      "reference_beads.json")
    print(f"Reference beads are saved to {os.path.abspath(out)} after every change")
    return run(exp, out)


def cmd_beads_flat(args) -> int:
    import json

    from .beads.experiment import load_experiment
    from .beads.flatfield import bead_check, estimate, fit_gamma, save
    from .beads.panels import load_area_images

    exp = load_experiment(args.experiment, args.root)
    out = os.path.join("outputs", os.path.splitext(os.path.basename(args.experiment))[0])
    areas = load_area_images(exp)
    ff = estimate({a.folder: a.image for lst in areas.values() for a in lst})
    refs = os.path.join(out, "reference_beads.json")
    beads = []
    if os.path.exists(refs):
        with open(refs, encoding="utf-8") as f:
            d = json.load(f)
        cond = {fo: c.key for c in exp.conditions for fo in c.areas}
        for folder, bs in d.get("areas", {}).items():
            for b in bs:
                if "light" in b and not set(b.get("flags", [])) & {"edge", "saturated", "crowded", "faint"}:
                    beads.append({"condition": cond.get(folder), "light": b["light"],
                                  "base_illumination": ff.base_at(b["x"], b["y"])})
    gamma, ci, n = fit_gamma(beads)
    if ci is not None and not args.no_gamma:
        ff = ff.with_gamma(gamma, ci, n)
        print(f"gamma from {n} reference beads: {gamma:.2f} (95% interval {ci[0]:.2f}-{ci[1]:.2f})")
    else:
        print(f"Using the glow map as measured (gamma 1): {n} usable reference beads"
              + ("" if args.no_gamma else ", need at least 6 to fit gamma"))
    for path in save(ff, os.path.join(out, "flatfield"), exp.name):
        print(f"wrote {path}")
    print(f"brightest point {ff.centre_xy}, smoothing rms {ff.fit_rms:.3f}, "
          f"{ff.usable().mean():.0%} of the field at or above {0.2:g} illumination")
    if len(beads) >= 4:
        result = bead_check(beads, ff.gamma, os.path.join(out, "flatfield", "bead_check.png"), exp.name)
        with open(os.path.join(out, "flatfield", "bead_check.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(json.dumps(result["versions"], indent=2, ensure_ascii=False))
    return 0


def cmd_beads_density(args) -> int:
    import json

    import tifffile

    from .beads.density import analyse, write_outputs
    from .beads.experiment import load_experiment
    from .beads.panels import load_area_images

    exp = load_experiment(args.experiment, args.root)
    out = os.path.join("outputs", os.path.splitext(os.path.basename(args.experiment))[0])
    flat_dir = os.path.join(out, "flatfield")
    refs_path = os.path.join(out, "reference_beads.json")
    if not (os.path.exists(os.path.join(flat_dir, "glow_map.tif")) and os.path.exists(refs_path)):
        print("Needs reference beads (beads-refs) and the illumination map (beads-flat) first.")
        return 1
    base = tifffile.imread(os.path.join(flat_dir, "glow_map.tif")).astype("float32")
    with open(os.path.join(flat_dir, "flat.json"), encoding="utf-8") as f:
        flat_info = json.load(f)
    with open(refs_path, encoding="utf-8") as f:
        refs = json.load(f)
    gamma, ci = flat_info.get("gamma", 1.0), flat_info.get("gamma_95ci")
    areas = load_area_images(exp)
    images = {a.folder: (a.condition.key, a.image, a.ds.pixel_size_um) for lst in areas.values() for a in lst}
    labels = {"Homogenized": "Homogenized", "NonHomogenized": "Non-homogenized"}
    pairs = []
    for prep in sorted({c.preparation for c in exp.conditions}, key=lambda p: (p != "Homogenized", p)):
        cs = sorted((c for c in exp.conditions if c.preparation == prep), key=lambda c: c.factor)
        if len(cs) == 2:
            pairs.append((labels.get(prep, prep), cs[0].key, cs[1].key, float(cs[1].factor)))

    def run(g, pooled=False):
        return analyse(images, refs, base, g, pairs, exp.nominal_expansion, expansion_basis=exp.expansion_basis,
                       gamma_range=tuple(ci) if ci else None,
                       pooled_bead_light=pooled)

    res = run(gamma, args.pooled_bead_light)
    sens = {}
    variants = {"gamma low": run(ci[0]), "gamma high": run(ci[1])} if ci else {}
    variants["pooled bead light"] = run(gamma, True)
    for g in res.groups:
        s = {"main": g["implied_linear_expansion"]}  # "no floor" counts gel glow as beads: reported, not plotted
        for name, r in variants.items():
            s[name] = next(x for x in r.groups if x["preparation"] == g["preparation"])["implied_linear_expansion"]
        sens[g["preparation"]] = s
    for path in write_outputs(res, os.path.join(out, "density"), labels, exp.name, sens):
        print(f"wrote {path}")
    for g in res.groups:
        b, i, m = g["base_density"]["mean"], g["ideal_density"]["mean"], g["measured_density"]["mean"]
        print(f"{g['preparation']}: 1x {b:.1f}/mm², ideal 11x {i:.2f}/mm², measured 11x {m:.1f}/mm² "
              f"(x{g['measured_over_ideal']} of ideal); density drop {g['density_drop']} "
              f"({g['density_drop_95ci'][0]}-{g['density_drop_95ci'][1]}), ideal {g['ideal_drop']:g}; "
              f"implied expansion {g['implied_linear_expansion']}x {g['implied_linear_expansion_95ci']}; "
              f"sensitivity {sens[g['preparation']]}")
    return 0


def cmd_gui(args) -> int:
    from .app import run

    return run(args.folder)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ix83viewer")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("gui", help="open the viewer")
    s.add_argument("folder", nargs="?")
    s.set_defaults(func=cmd_gui)

    s = sub.add_parser("scan", help="group a date folder's acquisitions by field of view")
    s.add_argument("folder")
    s.add_argument("--xy-tol", type=float, default=DEFAULT_XY_TOL_UM, help="stage X/Y tolerance, um")
    s.add_argument("--z-tol", type=float, default=DEFAULT_Z_TOL_UM, help="stage Z tolerance, um")
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("info", help="show one acquisition's metadata")
    s.add_argument("folder")
    s.set_defaults(func=cmd_info)

    s = sub.add_parser("project", help="collapse a stack to one image")
    s.add_argument("folder")
    s.add_argument("-m", "--method", choices=METHODS, default="mean")
    s.add_argument("--start", type=int, default=0)
    s.add_argument("--stop", type=int)
    s.add_argument("--frame", type=int, default=0, help="frame index for --method frame")
    s.add_argument("--dark", help="dark acquisition folder to subtract")
    s.add_argument("--no-cache", action="store_true")
    s.add_argument("-o", "--output", help="write result as TIFF")
    s.set_defaults(func=cmd_project)

    s = sub.add_parser("beads-check", help="validate a bead-in-gel experiment manifest against its data")
    s.add_argument("experiment", help="experiment JSON, e.g. experiments/4Nov26.json")
    s.add_argument("--root", help="date folder, overriding the manifest's data_root")
    s.add_argument("--no-overlap", action="store_true", help="skip the image-based area overlap test")
    s.set_defaults(func=cmd_beads_check)

    s = sub.add_parser("beads-panels", help="image panels for a bead-in-gel experiment")
    s.add_argument("experiment")
    s.add_argument("-o", "--output", help="output folder (default outputs/<experiment>/panels)")
    s.add_argument("--root", help="date folder, overriding the manifest's data_root")
    s.set_defaults(func=cmd_beads_panels)

    s = sub.add_parser("beads-refs", help="click reference beads to measure one bead's light")
    s.add_argument("experiment")
    s.add_argument("-o", "--output", help="picks file (default outputs/<experiment>/reference_beads.json)")
    s.add_argument("--root", help="date folder, overriding the manifest's data_root")
    s.set_defaults(func=cmd_beads_refs)

    s = sub.add_parser("beads-flat", help="illumination map from the areas' background, plus the bead check")
    s.add_argument("experiment")
    s.add_argument("--root", help="date folder, overriding the manifest's data_root")
    s.add_argument("--no-gamma", action="store_true", help="use the glow map as measured, without bead calibration")
    s.set_defaults(func=cmd_beads_flat)

    s = sub.add_parser("beads-density", help="bead density from total light, 1x vs expanded vs ideal")
    s.add_argument("experiment")
    s.add_argument("--root", help="date folder, overriding the manifest's data_root")
    s.add_argument("--pooled-bead-light", action="store_true",
                   help="one single-bead light from all hydrogels instead of each hydrogel's own")
    s.set_defaults(func=cmd_beads_density)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
