"""
rwtag.export_schema
===================
The column dictionary of the export bundle (docs/07). One definition per column:
name, dtype, unit, frame, description. Used to validate every table before it is
written and to generate the bundle's README.md, so the documentation can never
drift from the files. NO Qt.

Frames (manifest.json repeats these):
  raw      px  the TIFF as acquired, y down, OpenCV pixel centres
  corr     px  after the Stage-1 geometric correction (lens un-distortion, deskew)
  init     px  the INITIAL image's corr frame, reached by the rigid (scale kept) or
               similarity (scale removed) alignment of each image onto it
  expected px  where a feature would be in this image's corr frame under uniform
               expansion: the image's own similarity fit of the design
  design   um  the print, origin bottom-left, x right, y UP
Covariances: sxx, syy (px^2 or um^2) and sxy, 1-sigma = sqrt(sxx).
"""
from __future__ import annotations

BUNDLE_VERSION = "1.0"

# (name, dtype, unit, description) -- dtype: str | float | int | bool
_ID = [
    ("image", "str", "", "image file stem"),
    ("label", "float", "×", "expected expansion (metadata)"),
    ("lam_derived", "float", "×", "expansion derived from this image's tag centres"),
    ("tag", "str", "", "design identity: aruco|N{i}_{j}|{id}, dash|H{j}|{m} / dash|V{i}|{m}, dot|B{N}|{di}_{dj}"),
    ("category", "str", "", "aruco | dash | dot"),
    ("box", "int", "", "box number N = col*5 + row + 1 from the bottom-left (dots; blank otherwise)"),
    ("node_i", "int", "", "grid node column (ArUco tags)"),
    ("node_j", "int", "", "grid node row (ArUco tags)"),
    ("di", "int", "", "dot column within its box"),
    ("dj", "int", "", "dot row within its box"),
    ("line", "str", "", "grid line of a dash: H{j} horizontal, V{i} vertical"),
    ("m", "int", "", "dash ordinal along its line"),
]


def _xy(prefix, unit="px", what=""):
    return [(f"x_{prefix}", "float", unit, f"x {what}".strip()), (f"y_{prefix}", "float", unit, f"y {what}".strip()),
            (f"sxx_{prefix}", "float", unit + "²", "variance of x"), (f"syy_{prefix}", "float", unit + "²", "variance of y"),
            (f"sxy_{prefix}", "float", unit + "²", "covariance of x and y")]


TABLES = {
    "features_raw.csv": dict(frame="raw", doc=(
        "One row per (accepted image, tagged feature): its position in the RAW frame, two ways. `_det` is the "
        "independent detection on the raw frame (blank where the raw pass found nothing); `_map` is the corrected-"
        "frame position mapped back through the exact inverse correction. Their difference measures what the "
        "correction does to the detector."),
        cols=_ID + _xy("raw_det", what="independently detected in the raw frame")
        + _xy("raw_map", what="corrected position mapped to the raw frame") + [
            ("raw_found", "bool", "", "the raw pass re-found this feature"),
            ("det_minus_map_px", "float", "px", "|raw_det - raw_map|"),
            ("relative_err", "bool", "", "camera gain unknown: covariances are relative, not absolute"),
            ("cov_flag", "str", "", "'' | border_estimate (photometry window left the frame: conservative 4x median variance)"),
            ("signal_adu", "float", "ADU", "dot: integrated signal above background, raw frame"),
            ("bg_adu", "float", "ADU", "dot: background per pixel, raw frame"),
            ("sigma_px", "float", "px", "dot: measured spot sigma"),
            ("decode_class", "str", "", "ArUco: clean | corrected | ambiguous | duplicate")]),
    "features_corr.csv": dict(frame="corr", doc=(
        "One row per (accepted image, tagged feature): position and covariance in the image's own CORRECTED frame "
        "(the frame detection and tagging ran in)."),
        cols=_ID + _xy("corr", what="in the corrected frame") + [
            ("resid_tps_px", "float", "px", "distance to the smooth warp of the design (dots: cross-validated)"),
            ("cov_flag", "str", "", "'' | border_estimate")]),
    "features_in_initial_rigid.csv": dict(frame="init", doc=(
        "Every accepted image's features mapped into the INITIAL image's corrected frame by a rigid map "
        "(rotation + translation about a common box centre, scale KEPT): growth plus distortion. The initial "
        "image maps by identity. `feat` covariances are the feature's own error through the map; `align` the "
        "alignment's own (bootstrap); `d` the covariance of the difference to the initial position."),
        cols=_ID + [("x_init", "float", "px", "x in the initial frame"), ("y_init", "float", "px", "y in the initial frame")]
        + [(f"s{a}_feat", "float", "px²", f"feature covariance s{a} through the map") for a in ("xx", "yy", "xy")]
        + [(f"s{a}_align", "float", "px²", f"alignment covariance s{a} at this point") for a in ("xx", "yy", "xy")]
        + [("x0_init", "float", "px", "the initial image's own x of the same tag (blank if absent)"),
           ("y0_init", "float", "px", "the initial image's own y of the same tag"),
           ("dx", "float", "px", "x_init - x0_init"), ("dy", "float", "px", "y_init - y0_init")]
        + [(f"s{a}_d", "float", "px²", f"covariance s{a} of (dx, dy): feat + align + initial") for a in ("xx", "yy", "xy")]),
    "features_in_initial_sim.csv": dict(frame="init", doc=(
        "As features_in_initial_rigid.csv but with a SIMILARITY map (uniform scale removed): (dx, dy) is "
        "distortion only. Print placement error cancels here (the same printed dot is in both images)."),
        cols=None),                    # same columns as the rigid table (filled below)
    "deviation_from_design.csv": dict(frame="expected", doc=(
        "Every feature of every accepted image against the DESIGN: its design position, where uniform expansion "
        "puts it in this image (the image's own similarity fit), and the deviation, in px and in design micrometres "
        "(design axes, y up). Includes the print's own placement error."),
        cols=_ID + [("x_design_um", "float", "µm", "design x"), ("y_design_um", "float", "µm", "design y"),
                    ("x_expected", "float", "px", "x under uniform expansion (corr frame)"),
                    ("y_expected", "float", "px", "y under uniform expansion"),
                    ("dev_x", "float", "px", "x_corr - x_expected"), ("dev_y", "float", "px", "y_corr - y_expected"),
                    ("dev_x_um", "float", "µm", "deviation along design x (design µm at this expansion)"),
                    ("dev_y_um", "float", "µm", "deviation along design y (up)"),
                    ("sxx_dev", "float", "px²", "variance of dev_x"), ("syy_dev", "float", "px²", "variance of dev_y"),
                    ("sxy_dev", "float", "px²", "covariance"),
                    ("mahalanobis2", "float", "", "squared Mahalanobis distance of (dev_x, dev_y)"),
                    ("significant", "bool", "", "mahalanobis2 > 9.21 (outside the 99 % ellipse)"),
                    ("resid_tps_px", "float", "px", "distance to the smooth warp (dots: cross-validated)")]),
    "tags_pose.csv": dict(frame="corr", doc=(
        "One row per decoded ArUco tag of each accepted image (usable or not): centre with covariance, the four "
        "corners (TL, TR, BR, BL), rotation (counter-clockwise on screen) with sigma, printed side length, decode "
        "confidence, and the centre in the raw, initial and design frames."),
        cols=[("image", "str", "", "image file stem"), ("label", "float", "×", "expected expansion"),
              ("lam_derived", "float", "×", "expansion from the tag centres"),
              ("aruco_id", "int", "", "decoded id"), ("tag", "str", "", "design identity (blank: id not in the design)"),
              ("node_i", "int", "", "grid node column"), ("node_j", "int", "", "grid node row")]
        + _xy("corr", what="tag centre, corrected frame")
        + [(f"c{k}{a}", "float", "px", f"corner {k} ({['TL', 'TR', 'BR', 'BL'][k]}) {a}") for k in range(4) for a in "xy"]
        + [("rot_deg", "float", "°", "tag rotation, ccw on screen, corrected frame"),
           ("rot_sigma_deg", "float", "°", "1-sigma of rot_deg"),
           ("rot_rel_frame_deg", "float", "°", "rot_deg minus the frame's median"),
           ("rot_raw_deg", "float", "°", "rotation in the raw frame (= rot_deg - Stage-1 deskew)"),
           ("side_px", "float", "px", "mean printed side length"), ("side_sigma_px", "float", "px", "1-sigma"),
           ("handedness", "float", "", "design->image sign of this frame (-1 expected)"),
           ("n_bits_corrected", "int", "", "bits corrected to read the id"),
           ("margin_bits", "int", "", "Hamming distance to the nearest other id"),
           ("mirror_dist", "int", "", "Hamming distance of the mirrored bits to any id"),
           ("border_errors", "int", "", "border modules read as white"),
           ("contrast", "float", "", "white minus black module mean (8-bit units)"),
           ("decode_class", "str", "", "clean | corrected | ambiguous | duplicate"),
           ("in_edge_band", "bool", "", "corners without a real raw source"),
           ("usable", "bool", "", "used for registration")]
        + _xy("raw_det", what="centre independently detected in the raw frame")
        + [("x_raw_map", "float", "px", "corrected centre mapped to raw"), ("y_raw_map", "float", "px", "")]
        + [("x_init_rigid", "float", "px", "centre in the initial frame (rigid)"), ("y_init_rigid", "float", "px", ""),
           ("x_init_sim", "float", "px", "centre in the initial frame (similarity)"), ("y_init_sim", "float", "px", ""),
           ("x_design_um", "float", "µm", "design centre"), ("y_design_um", "float", "µm", "")]),
    "dropped_features.csv": dict(frame="corr", doc=(
        "Every Stage-2 detection of an accepted image that did NOT become a tagged feature, with the reason."),
        cols=[("image", "str", "", "image file stem"), ("label", "float", "×", "expected expansion"),
              ("category", "str", "", "aruco | dash | dot"), ("index", "int", "", "index in the detection (aruco: id)"),
              ("x_corr", "float", "px", "x"), ("y_corr", "float", "px", "y"),
              ("reason", "str", "", "edge | near_tag | too_close | off_lattice | off_grid | intersection | unmatched | "
                                    "box_mismatch | ambiguous | duplicate | edge_band | not_in_design")]),
    "pairs.csv": dict(frame="corr", doc=(
        "Identity join of each compared image with its reference (by default every expanded image with the "
        "initial): both corrected positions with covariances, the compared position in the reference frame under "
        "both alignments, and the displacement u = aligned compared - reference. One file per pair: "
        "pairs_<ref>x_<cmp>x.csv; this entry describes their columns."),
        cols=[("tag", "str", "", "design identity"), ("category", "str", "", "aruco | dash | dot"),
              ("box", "int", "", "box number (dots)")]
        + _xy("0", what="reference image, corrected frame") + _xy("1", what="compared image, corrected frame")
        + [("x1_rigid", "float", "px", "compared position, rigid map to the reference"), ("y1_rigid", "float", "px", ""),
           ("x1_sim", "float", "px", "compared position, similarity map to the reference"), ("y1_sim", "float", "px", ""),
           ("ux_rigid", "float", "px", "x1_rigid - x0"), ("uy_rigid", "float", "px", "y1_rigid - y0"),
           ("ux_sim", "float", "px", "x1_sim - x0 (distortion only)"), ("uy_sim", "float", "px", "y1_sim - y0"),
           ("sxx_u_sim", "float", "px²", "variance of ux_sim (both features + alignment)"),
           ("syy_u_sim", "float", "px²", "variance of uy_sim"), ("sxy_u_sim", "float", "px²", "covariance")]),
    "local_deformation.csv": dict(frame="init", doc=(
        "Per paired dot of each pair: the affine d1 = F d0 fitted over its nearest paired neighbours (reference "
        "corr px -> compared corr px), its covariance propagated from both images' position errors, and its "
        "decomposition. One file per pair: local_deformation_<ref>x_<cmp>x.csv. Anisotropy >= 0 by construction: "
        "noise biases it upward by about its own sigma."),
        cols=[("tag", "str", "", "dot identity"), ("box", "int", "", "box number"),
              ("x0", "float", "px", "reference x"), ("y0", "float", "px", "reference y")]
        + [(f"F{a}{b}", "float", "", f"deformation gradient F[{a},{b}]") for a in (1, 2) for b in (1, 2)]
        + [(k, "float", u, d) for k, u, d in (
            ("J", "", "det F: areal expansion"), ("J_sigma", "", "1-sigma"),
            ("lin", "×", "sqrt(J): local linear expansion"), ("lin_sigma", "×", "1-sigma"),
            ("lam1", "×", "larger principal stretch"), ("lam1_sigma", "×", "1-sigma"),
            ("lam2", "×", "smaller principal stretch"), ("lam2_sigma", "×", "1-sigma"),
            ("phi_deg", "°", "first principal axis in the reference frame, ccw on screen, mod 180"),
            ("phi_sigma_deg", "°", "1-sigma"),
            ("anisotropy", "", "lam1 / lam2 - 1"), ("anisotropy_sigma", "", "1-sigma"),
            ("rot_deg", "°", "local rotation, ccw on screen"), ("rot_sigma_deg", "°", "1-sigma"),
            ("resid_rms_px", "px", "neighbours' misfit to the affine: local warping"))]
        + [("n_nb", "int", "", "neighbours used")]
        + [(f"Fcov_{i}{j}", "float", "", f"covariance of F entries {i} and {j} (order F11 F12 F21 F22)")
           for i in range(4) for j in range(i, 4)]
        + [("U11", "float", "", "stretch tensor U (F = R U)"), ("U12", "float", "", ""), ("U22", "float", "", "")]),
}
TABLES["features_in_initial_sim.csv"]["cols"] = TABLES["features_in_initial_rigid.csv"]["cols"]


def columns(table):
    """Column names of a table ('pairs_1x_2x.csv' -> the 'pairs.csv' schema)."""
    return [c[0] for c in TABLES[schema_key(table)]["cols"]]


def schema_key(table):
    if table.startswith("pairs_"):
        return "pairs.csv"
    if table.startswith("local_deformation_"):
        return "local_deformation.csv"
    return table


def validate(table, df):
    """List of problems (empty = valid): exact column names and order, dtypes."""
    want = TABLES[schema_key(table)]["cols"]
    names = [c[0] for c in want]
    probs = []
    if list(df.columns) != names:
        missing = [n for n in names if n not in df.columns]
        extra = [n for n in df.columns if n not in names]
        probs.append(f"{table}: columns differ (missing {missing}, extra {extra}, or order)")
        return probs
    import pandas as pd
    for name, dt, _u, _d in want:
        s = df[name]
        if dt == "float" and not (pd.api.types.is_float_dtype(s) or s.isna().all()):
            probs.append(f"{table}: {name} should be float, is {s.dtype}")
        elif dt == "int" and not (pd.api.types.is_integer_dtype(s) or s.isna().all()):
            probs.append(f"{table}: {name} should be integer, is {s.dtype}")
        elif dt == "bool" and not (pd.api.types.is_bool_dtype(s) or s.isna().all()):
            probs.append(f"{table}: {name} should be bool, is {s.dtype}")
    return probs


def readme(manifest=None):
    """The bundle's README.md: frames, files, and every column."""
    out = ["# ArUco Reference Tagger — export bundle", "",
           f"Bundle format {BUNDLE_VERSION}. Generated from `rwtag/export_schema.py`; read it back with "
           "`rwtag.export_reader.read_bundle(folder)`.", ""]
    if manifest:
        out += [f"Project: `{manifest['project']['path']}` · initial image: `{manifest['project']['initial']}` · "
                f"design: `{manifest['design']['name']}` · created {manifest['created']}.", ""]
    out += ["## Frames", "", __doc__.split("Frames (manifest.json repeats these):")[1].split("Covariances")[0].strip(), "",
            "Covariances are given as `sxx`, `syy`, `sxy` (1-sigma = √sxx). Every row carries the image name; the "
            "acquisition metadata and every processing parameter of each image are in `manifest.json` and `images/`.", "",
            "## Files", "",
            "| file | what |", "|---|---|",
            "| `manifest.json` | tool version, design file hashes, frames, error model, every parameter of every image, table hashes |",
            "| `images/<image>.meta.json` | acquisition metadata (objective, laser, gain, date, gel, cells, …) with sources |",
            "| `images/<image>.stage1.json` | Stage-1 optics correction + levels |",
            "| `images/<image>.detect.json` | detector settings, decode report, registration, raw-pass summary, error model |",
            "| `images/<image>.filter.json` | filter settings and counts by reason |",
            "| `images/<image>.tag.json` | warp report, uniform-expansion fit, acceptance |",
            "| `alignment_<ref>x_<cmp>x.json` | rigid, similarity and affine maps compared → reference with uncertainties |",
            "| `rejected.json` | images excluded, and why |", ""]
    for name, t in TABLES.items():
        out += [f"## `{name}`", "", t["doc"], "", "| column | type | unit | meaning |", "|---|---|---|---|"]
        out += [f"| `{n}` | {d} | {u} | {desc} |" for n, d, u, desc in t["cols"]]
        out.append("")
    return "\n".join(out)
