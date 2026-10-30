"""Writing results to disk (Qt-free; the GUI and the CLI share it).

A bundle folder holds
  scenario.json          every site and parameter (reload with File > Open)
  pre.png / post.png     16-bit images (or .tif)
  features_truth.csv     true position of every feature, same columns as the
                         batch run's features_truth.csv
  metrics.json           the faithful run's numbers (keys as results.json)
  window.png             a snapshot of the GUI window (GUI only)
"""

import csv
import json
import os

import numpy as np
from PIL import Image

TRUTH_COLUMNS = ["tag", "category", "aruco_id", "x_design_um", "y_design_um",
                 "x_pre_px", "y_pre_px", "x_post_px", "y_post_px"]


def write_image(path, img):
    """16-bit PNG or TIFF, chosen by the extension."""
    img = np.asarray(img)
    if img.dtype != np.uint16:
        img = np.clip(np.round(img), 0, 65535).astype(np.uint16)
    ext = os.path.splitext(path)[1].lower()
    if ext in (".tif", ".tiff"):
        import tifffile
        tifffile.imwrite(path, img)
    elif ext == ".png":
        Image.fromarray(img).save(path)
    else:
        raise ValueError(f"unknown image format {ext}")
    return path


def write_truth_csv(path, grid, positions):
    """Per-feature truth table (exm_sim's features_truth.csv)."""
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(TRUTH_COLUMNS)
        for k in range(grid.n):
            w.writerow([grid.tag[k], grid.cat[k], grid.aruco_id[k], *np.round(grid.xy[k], 4),
                        *np.round(positions.pre_px[k], 3), *np.round(positions.post_px[k], 3)])
    return path


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return _jsonable(o.tolist())
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def write_json(path, obj):
    with open(path, "w") as fh:
        json.dump(_jsonable(obj), fh, indent=1)
    return path


def export_bundle(outdir, scen, results, simres, grid, image_format="png", extra_metrics=None):
    """Write the scenario, both images, the truth table and the metrics."""
    os.makedirs(outdir, exist_ok=True)
    ext = {"png": ".png", "tiff": ".tif", "tif": ".tif"}[image_format.lower()]
    paths = [os.path.join(outdir, "scenario.json")]
    scen.save(paths[0])
    paths.append(write_image(os.path.join(outdir, "pre" + ext), simres.pre))
    paths.append(write_image(os.path.join(outdir, "post" + ext), simres.post))
    paths.append(write_truth_csv(os.path.join(outdir, "features_truth.csv"), grid, simres.positions))
    metrics = dict(results)
    if extra_metrics:
        metrics.update(extra_metrics)
    paths.append(write_json(os.path.join(outdir, "metrics.json"), metrics))
    return paths
