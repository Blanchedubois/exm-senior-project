"""
rwtag.refwarp.io_csv
====================
Quick per-frame export of one TagResult (the full, versioned bundle is port
Phase 7). Ported from Reference_Warp_Tagger/rwtag/refwarp/io_csv.py.
"""
from __future__ import annotations
import csv


def write_tagged(tr, path):
    """One row per tagged feature: tag, category, box, x_px, y_px (corrected
    frame), residual_px (distance to its warped reference)."""
    tags = tr.tags if hasattr(tr, "tags") else tr
    res = getattr(tr, "residuals", None) or {}
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tag", "category", "box", "x_px", "y_px", "residual_px"])
        for tag, (x, y) in sorted(tags.items()):
            parts = tag.split("|")
            box = parts[1][1:] if parts[0] == "dot" else ""
            w.writerow([tag, parts[0], box, round(x, 3), round(y, 3),
                        round(res[tag], 3) if tag in res else ""])
    return path
