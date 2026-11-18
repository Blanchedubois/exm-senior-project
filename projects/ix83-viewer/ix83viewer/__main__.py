"""Command line for the IX83 data layer.

    python3 -m ix83viewer gui     [date or acquisition folder]
    python3 -m ix83viewer scan    <date folder>
    python3 -m ix83viewer info    <acquisition folder>
    python3 -m ix83viewer project <acquisition folder> [-m mean] [-o out.tif] [--dark <dark folder>]
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

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
