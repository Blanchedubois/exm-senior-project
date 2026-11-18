"""
fieldkit.cli
============
Headless batch runner -- process an initial + expansion images and pair them,
writing all CSVs, without the GUI (reproducible / scriptable).

    python run_batch.py --initial init.tif --expansions e2.tif e3.tif --out OUT \
        --vig-strength 0.88 --vig-power 1.8 --k1 -0.05 --k2 -0.01
"""
from __future__ import annotations
import argparse
import os

from .project import ExpansionProject, DEFAULT_META
from gridtrack.types import CorrectionParams


def build_parser():
    ap = argparse.ArgumentParser(description="Batch expansion-field tracking + pairing.")
    ap.add_argument("--initial", required=True, help="initial (baseline) image")
    ap.add_argument("--expansions", nargs="+", required=True, help="expansion images")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--reference", default=DEFAULT_META, help="grid_metadata.json")
    ap.add_argument("--vig-strength", type=float, default=0.0)
    ap.add_argument("--vig-power", type=float, default=2.0)
    ap.add_argument("--k1", type=float, default=0.0)
    ap.add_argument("--k2", type=float, default=0.0)
    ap.add_argument("--transform", default="similarity",
                    choices=["similarity", "affine", "homography"])
    ap.add_argument("--no-pair", action="store_true", help="stages 1-5 only, skip pairing")
    return ap


def run(args) -> ExpansionProject:
    pr = ExpansionProject(
        initial_path=args.initial, expansion_paths=list(args.expansions),
        reference_path=args.reference, out_dir=args.out, transform_model=args.transform,
        correction=CorrectionParams(vig_strength=args.vig_strength, vig_power=args.vig_power,
                                    k1=args.k1, k2=args.k2))
    pr.process_all(progress=lambda k, n, p, r: print(
        f"[{k}/{n}] {os.path.basename(p)}: {r.grid.n_detected} tags, "
        f"{int((r.markers['type'] == 'dot').sum())} dots"))
    if not args.no_pair:
        pr.pair_all(progress=lambda p, prr: print(
            f"  pair {prr.expansion_name}: λ={prr.lambda_rel:.3f}, "
            f"{prr.n_tags} tags + {prr.n_dots} dots shared"))
    print(f"done -> {args.out}")
    return pr


def main(argv=None):
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    main()
