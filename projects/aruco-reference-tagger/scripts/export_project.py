#!/usr/bin/env python3
"""
export_project.py — headless export of a saved project (docs/07 §4).

    python scripts/export_project.py PROJECT.rwproj.json [--out DIR] [--design FOLDER]
                                     [--raw] [--consecutive] [--pair A B ...] [--no-parquet]
                                     [--name NAME] [--boot 200]

Loads the project, runs stages 2-4 on every image with the settings stored in the
project (the ones the GUI last ran) and each image's own Stage-1 sidecar, applies
the series gates, and writes the bundle. Prints the bundle folder and row counts.
"""
from __future__ import annotations
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from rwtag import project as PJ, designs as DS, export as EX      # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project")
    ap.add_argument("--out", default=None, help="parent folder (default: the project folder)")
    ap.add_argument("--design", default=None, help="design folder (default: the project's)")
    ap.add_argument("--raw", action="store_true", help="copy the raw TIFFs into the bundle")
    ap.add_argument("--consecutive", action="store_true", help="also pair consecutive images")
    ap.add_argument("--pair", nargs=2, action="append", default=[], metavar=("REF", "CMP"),
                    help="extra pair by image stem (repeatable)")
    ap.add_argument("--no-parquet", action="store_true")
    ap.add_argument("--name", default=None, help="bundle folder name")
    ap.add_argument("--boot", type=int, default=200, help="bootstrap draws per alignment")
    a = ap.parse_args(argv)

    proj = PJ.Project.load(a.project)
    folder = a.design or proj.design_folder or DS.default_folder()
    design = DS.load(folder)
    proj.design_folder = proj.design_folder or os.path.abspath(folder)
    res = PJ.run_all(proj, design, log=print)
    for e in proj.images:
        e.unload_images()
    opts = EX.ExportOptions(include_raw=a.raw, consecutive_pairs=a.consecutive, extra_pairs=[tuple(p) for p in a.pair],
                            parquet=not a.no_parquet, n_boot=a.boot)
    out, b = EX.export_project(proj, design, a.out or proj.folder, opts, a.name)
    print(f"bundle -> {out}")
    for k, v in EX.row_counts(b).items():
        print(f"  {k:40s} {v:8d}")
    if b.rejected:
        print("rejected: " + "; ".join(f"{r['image']} ({r['reason']})" for r in b.rejected))
    return 0 if any(ok for ok, _m in res.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
