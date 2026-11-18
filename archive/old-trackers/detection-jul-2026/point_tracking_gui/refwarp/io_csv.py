"""
refwarp.io_csv
==============
CSV exports: one tagged table per image, and the wide tag-joined pairing table.
"""
from __future__ import annotations
import csv


def write_tagged(frame, path):
    """One row per tagged feature of one image: tag, category, x_px, y_px."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tag", "category", "x_px", "y_px"])
        for tag, (x, y) in sorted(frame.tags.items()):
            w.writerow([tag, tag.split("|")[0], round(x, 1), round(y, 1)])
    return path


def write_pairing(session, path):
    """Wide pairing: one row per tag (present in any accepted frame), with
    <label>x_x / _y / _present columns per expansion."""
    frames = [f for f in sorted(session.frames, key=lambda f: f.label) if f.ok]
    labels = [f.label for f in frames]
    table = session.pair_table()
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
