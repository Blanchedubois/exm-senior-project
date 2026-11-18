"""pairkit.io_csv — per-image tagged CSV + the wide pairing CSV (tag-joined)."""
from __future__ import annotations
import csv


def write_tagged(table, path):
    """One row per point of one image: its canonical tag + box + position."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tag", "type", "box_number", "char", "x_px", "y_px", "fx", "fy"])
        for p in table.points:
            if p.tag is None:
                continue
            w.writerow([p.tag, p.type, p.box_number, p.char,
                        round(p.x, 1), round(p.y, 1), round(p.fx, 4), round(p.fy, 4)])
    return path


def write_pairing(result, path):
    """One row per tagged initial point (the join key is its canonical tag).
    Columns: tag, type, box_number, char, init_x, init_y, then
    <label>x_x, <label>x_y, <label>x_present per expansion (blank when absent)."""
    labels = [f"{t.label:g}x" for t in result.expansions]
    header = ["tag", "type", "box_number", "char", "init_x", "init_y"]
    for lab in labels:
        header += [f"{lab}_x", f"{lab}_y", f"{lab}_present"]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for i, ip in enumerate(result.initial.points):
            if not ip.tag:                       # identity is the tag; skip untagged
                continue
            row = [ip.tag, ip.type, ip.box_number, ip.char,
                   round(ip.x, 1), round(ip.y, 1)]
            for e in range(len(result.expansions)):
                mp = result.matches[e][i]
                if mp is None:
                    row += ["", "", 0]
                else:
                    row += [round(mp.x, 1), round(mp.y, 1), 1]
            w.writerow(row)
    return path
