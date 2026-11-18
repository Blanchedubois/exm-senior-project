"""Copy exported panels into a blog's images folder, resized and as WebP.

    python3 tools/prepare_blog_images.py <exported panels folder> <blog/images folder> \\
        [--date 2026-11-03] [--extra E:gray ...] [--max-width 1800]

Always takes the expansion comparison (every variant exported) and the panels
of the sets it used. --extra SET:VARIANT adds other panels, e.g. E:gray for
Set E in grayscale (variants: colour, no633, gray).

Writes <date>-ix83-expansion-comparison[-no633|-gray].webp and
<date>-ix83-set-<x>-<factor>[-no633|-gray].webp. By default images keep their
full size (export panels at "Full camera resolution" for every camera pixel;
about 0.3-2 MB each as WebP at quality 88); --max-width scales wider ones down.
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os

from PIL import Image

SUFFIX = {"colour": "", "no633": "_no633", "gray": "_gray", "inferno": "_inferno"}


def convert(src: str, dst: str, max_width: int = 0) -> str:
    with Image.open(src) as im:
        im = im.convert("RGB")
        if max_width and im.width > max_width:
            im = im.resize((max_width, round(im.height * max_width / im.width)), Image.LANCZOS)
        im.save(dst, "WEBP", quality=88, method=6)
    return dst


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("panels_dir")
    ap.add_argument("images_dir")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--extra", nargs="*", default=[], help="SET:VARIANT, e.g. E:gray")
    ap.add_argument("--max-width", type=int, default=0, help="scale wider images down (0 = keep full size)")
    args = ap.parse_args(argv)

    sidecars = glob.glob(os.path.join(args.panels_dir, "*_panels.json"))
    if not sidecars:
        raise SystemExit(f"No *_panels.json in {args.panels_dir}: export panels first")
    with open(sidecars[0], encoding="utf-8") as f:
        info = json.load(f)
    variants = info.get("variants", ["colour"])
    factor_of = {v.split()[-1]: k for k, v in info["sets"].get("expansion_comparison", {}).items()}  # "B" -> "1x"
    for name, rec in info["sets"].items():
        if name.startswith("Set "):
            factor_of.setdefault(name.split()[-1], f"{rec['expansion'] or 1:g}x")
    os.makedirs(args.images_dir, exist_ok=True)

    wanted = [(s, v) for s in factor_of if s in {x.split()[-1] for x in info["sets"].get("expansion_comparison", {}).values()}
              for v in variants]
    wanted += [tuple(e.split(":")) for e in args.extra]
    written = []
    for v in variants:
        for src in glob.glob(os.path.join(args.panels_dir, f"*_expansion_comparison_*{SUFFIX[v]}.png")):
            if v == "colour" and any(src.endswith(f"{s}.png") for s in ("_no633", "_gray", "_inferno")):
                continue
            dst = os.path.join(args.images_dir, f"{args.date}-ix83-expansion-comparison{SUFFIX[v].replace('_', '-')}.webp")
            written.append(convert(src, dst, args.max_width))
    for set_label, v in wanted:
        srcs = glob.glob(os.path.join(args.panels_dir, f"*_Set_{set_label}_*{SUFFIX[v]}_panel.png"))
        srcs = [s for s in srcs if v != "colour" or not any(s.endswith(f"{x}_panel.png")
                                                            for x in ("_no633", "_gray", "_inferno"))]
        for src in srcs:
            dst = os.path.join(args.images_dir, f"{args.date}-ix83-set-{set_label.lower()}-{factor_of[set_label]}"
                                                f"{SUFFIX[v].replace('_', '-')}.webp")
            written.append(convert(src, dst, args.max_width))
    for w in sorted(set(written)):
        print(f"{os.path.getsize(w) / 1e3:7.0f} kB  {os.path.basename(w)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
