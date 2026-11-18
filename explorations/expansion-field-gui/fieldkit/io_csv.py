"""
fieldkit.io_csv
===============
Standardised per-stage CSV output. Owns the on-disk layout so every stage of
every image is inspectable as a CSV:

  <out_dir>/<image_name>/
      stage1_correction.csv   stage2_tags.csv   stage3_nodes.csv
      stage4_features.csv     stage5_features_filtered.csv   markers.csv
"""
from __future__ import annotations
import os
from dataclasses import asdict
import pandas as pd


def image_name(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def image_dir(out_dir: str, path: str) -> str:
    d = os.path.join(out_dir, image_name(path))
    os.makedirs(d, exist_ok=True)
    return d


def write_correction(d, correction):
    pd.DataFrame([asdict(correction)]).to_csv(os.path.join(d, "stage1_correction.csv"), index=False)


def write_tags(d, det):
    rows = []
    for i in det.ids:
        i = int(i)
        c = det.corners[i]
        rows.append({"aruco_id": i,
                     "c0x": c[0, 0], "c0y": c[0, 1], "c1x": c[1, 0], "c1y": c[1, 1],
                     "c2x": c[2, 0], "c2y": c[2, 1], "c3x": c[3, 0], "c3y": c[3, 1],
                     "cx": det.centers[i][0], "cy": det.centers[i][1],
                     "theta_deg": det.theta_deg})
    pd.DataFrame(rows).to_csv(os.path.join(d, "stage2_tags.csv"), index=False)


def write_nodes(d, grid):
    rows = []
    for n in grid.nodes:
        rows.append({"aruco_id": n.aruco_id, "node_i": n.node_i, "node_j": n.node_j,
                     "ref_x_um": n.ref_xy_um[0], "ref_y_um": n.ref_xy_um[1],
                     "img_x_px": n.img_xy_px[0], "img_y_px": n.img_xy_px[1],
                     "status": n.status, "residual_px": n.residual_px})
    df = pd.DataFrame(rows)
    df.attrs = {}
    df.to_csv(os.path.join(d, "stage3_nodes.csv"), index=False)
    # transform + scale metadata alongside
    pd.DataFrame([{"px_per_um": grid.px_per_um, "rms_residual_px": grid.rms_residual_px,
                   "n_detected": grid.n_detected, "n_total": grid.n_total}]).to_csv(
        os.path.join(d, "stage3_meta.csv"), index=False)


def write_features(d, feats, stage):
    fn = "stage4_features.csv" if stage == 4 else "stage5_features_filtered.csv"
    feats.to_csv(os.path.join(d, fn), index=False)


def write_markers(d, markers_df):
    markers_df.to_csv(os.path.join(d, "markers.csv"), index=False)


def pairing_dir(out_dir):
    d = os.path.join(out_dir, "pairing")
    os.makedirs(d, exist_ok=True)
    return d


def write_pairing(out_dir, pairing_result):
    d = pairing_dir(out_dir)
    fn = f"pairing_{pairing_result.expansion_name}_vs_initial.csv"
    pairing_result.field.to_csv(os.path.join(d, fn), index=False)


def write_pairing_summary(out_dir, summary_rows):
    d = pairing_dir(out_dir)
    pd.DataFrame(summary_rows).to_csv(os.path.join(d, "pairing_summary.csv"), index=False)


def write_strain(out_dir, expansion_name, strain_df):
    d = pairing_dir(out_dir)
    strain_df.to_csv(os.path.join(d, f"strain_{expansion_name}_vs_initial.csv"), index=False)


def write_all(d, correction, det, grid, feats4, feats5, markers_df):
    write_correction(d, correction)
    write_tags(d, det)
    write_nodes(d, grid)
    write_features(d, feats4, 4)
    write_features(d, feats5, 5)
    write_markers(d, markers_df)
