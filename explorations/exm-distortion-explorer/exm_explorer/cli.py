"""Headless runner: scenario JSON in, the same outputs as the GUI's export.

    python -m exm_explorer.cli scenario.json --out results/
    python -m exm_explorer.cli --preset "exm_sim batch run" --out batch/
    python -m exm_explorer.cli s.json --out sweep/ --set imaging.lam=3.3,4,10 --set solver.nu=0.2,0.45

Each --set takes a dotted field and comma-separated values; several --set
options make the full grid of combinations, one subfolder each. A summary of
every run goes to <out>/summary.csv.
"""

import argparse
import copy
import csv
import itertools
import os
import sys
import time

from . import export, pipeline
from .grid import load_grid
from .scenario import PRESETS, Scenario


def _parse_value(text, current):
    if isinstance(current, bool):
        return text.lower() in ("1", "true", "yes", "on")
    if isinstance(current, int):
        return int(float(text))
    if isinstance(current, float):
        return float(text)
    return text


def apply_setting(scen, key, text):
    """Set a dotted field ('imaging.lam', 'solver.nu', 'sites.0.eps1')."""
    parts = key.split(".")
    obj = scen
    for p in parts[:-1]:
        obj = obj[int(p)] if isinstance(obj, list) else getattr(obj, p)
    last = parts[-1]
    if isinstance(obj, list):
        obj[int(last)] = _parse_value(text, obj[int(last)])
    else:
        if not hasattr(obj, last):
            raise SystemExit(f"--set: no field '{key}'")
        setattr(obj, last, _parse_value(text, getattr(obj, last)))


def run_one(scen, outdir, grid, registrations, image_format, images=True):
    t0 = time.perf_counter()
    res, ex = pipeline.run_faithful(scen, grid, registrations=registrations)
    if images:
        export.export_bundle(outdir, scen, res, ex["sim"], grid, image_format)
    else:
        os.makedirs(outdir, exist_ok=True)
        scen.save(os.path.join(outdir, "scenario.json"))
        export.write_json(os.path.join(outdir, "metrics.json"), res)
    return res, time.perf_counter() - t0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="exm-explorer-cli", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenarios", nargs="*", help="scenario JSON files")
    ap.add_argument("--preset", action="append", default=[], choices=sorted(PRESETS),
                    help="a built-in scenario instead of / as well as files")
    ap.add_argument("--out", required=True, help="output folder")
    ap.add_argument("--set", action="append", default=[], metavar="FIELD=V1,V2",
                    help="override a field; several values make a sweep")
    ap.add_argument("--registrations", default="tags", help="comma list of tags, acf, truth")
    ap.add_argument("--format", default="png", choices=["png", "tiff"], help="image format")
    ap.add_argument("--no-images", action="store_true", help="only scenario.json and metrics.json")
    a = ap.parse_args(argv)

    bases = [(os.path.splitext(os.path.basename(p))[0], Scenario.load(p)) for p in a.scenarios]
    bases += [(name.replace(" ", "_"), PRESETS[name]()) for name in a.preset]
    if not bases:
        ap.error("give a scenario file or --preset")
    sweeps = []
    for item in a.set:
        if "=" not in item:
            ap.error(f"--set {item}: expected FIELD=V1,V2")
        k, v = item.split("=", 1)
        sweeps.append((k, v.split(",")))
    regs = tuple(r.strip() for r in a.registrations.split(",") if r.strip())
    grid = load_grid()
    rows = []
    for name, base in bases:
        combos = list(itertools.product(*[[(k, v) for v in vals] for k, vals in sweeps])) or [()]
        for combo in combos:
            scen = copy.deepcopy(base)
            for k, v in combo:
                apply_setting(scen, k, v)
            tag = "_".join(f"{k.split('.')[-1]}-{v}" for k, v in combo)
            outdir = os.path.join(a.out, name if not tag else f"{name}__{tag}")
            res, secs = run_one(scen, outdir, grid, regs, a.format, images=not a.no_images)
            row = dict(run=os.path.basename(outdir), seconds=round(secs, 1),
                       acf_scale=res["acf_global"]["scale"], tag_scale=res["aruco_tags"]["global_"]["scale"],
                       truth_scale=res["truth_global"]["scale"], n_tags=res["aruco_tags"]["n_tags"])
            for r in regs:
                st = res[f"ccf_after_{r}_correction"]
                for key in ("ccf_peak", "next_best_peak", "unwrapped_rms_err_px", "unwrapped_frac_off_by_a_cell",
                            "dots_only_unwrapped_rms_err_px", "local_scale_corr"):
                    row[f"{r}_{key}"] = st.get(key)
            rows.append(row)
            print(f"{row['run']}: {secs:.1f} s, tags {row['n_tags']}, scale ACF {row['acf_scale']:.4f} "
                  f"tags {row['tag_scale']:.4f} truth {row['truth_scale']:.4f}", flush=True)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "summary.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
