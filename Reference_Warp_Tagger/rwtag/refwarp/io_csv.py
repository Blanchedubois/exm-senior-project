"""
rwtag.refwarp.io_csv
====================
CSV exports: one tagged table per image, and the wide tag-joined pairing table.
Ported from the old refwarp; write_pairing adapted to the new series API.
"""
from __future__ import annotations
import csv

from . import series as S


def write_tagged(tags, path):
    """One row per tagged feature of one image. `tags` = {tag: (x_px, y_px)}."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tag", "category", "x_px", "y_px"])
        for tag, (x, y) in sorted(tags.items()):
            w.writerow([tag, tag.split("|")[0], round(x, 1), round(y, 1)])
    return path


def write_pairing(frames, path):
    """Wide pairing over accepted frames: one row per tag, with
    <label>x_x / _y / _present columns per expansion."""
    ok = [f for f in sorted(frames, key=lambda f: f.label) if f.ok]
    labels = [f.label for f in ok]
    table = S.pair_table(ok)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        header = ["tag", "category"]
        for lab in labels:
            header += [f"{lab:g}x_x", f"{lab:g}x_y", f"{lab:g}x_present"]
        w.writerow(header)
        for tag in sorted(table):
            row = [tag, tag.split("|")[0]]
            per = table[tag]
            for lab in labels:
                if lab in per:
                    x, y = per[lab]; row += [round(x, 1), round(y, 1), 1]
                else:
                    row += ["", "", 0]
            w.writerow(row)
    return path
