"""
rwtag.export
============
The Phase-7 export bundle (docs/07_PHASE7_DATA_EXPORT.md): one folder that holds
every feature's position and uncertainty in every frame of reference, every tag's
pose, the pairs and local deformation, and every parameter each image was taken
and processed with. NO Qt.

  build_bundle(project, design, options) -> Bundle   pure data (DataFrames + dicts)
  write_bundle(bundle, parent_folder)    -> folder   CSV (+ Parquet), JSON, README
  export_project(project, design, parent, options)   both

`project` is an rwtag.project.Project (anything with `.images`, `.initial()`,
`.folder`, `.noise`): each entry must have been run through stages 2-4. Only
ACCEPTED images enter the tables; the others are listed in rejected.json. The
initial image must be accepted (it defines the `init` frame).
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict, is_dataclass
import datetime as _dt
import hashlib
import json
import math
import os
import re
import shutil
import subprocess

import numpy as np
import pandas as pd

from . import correct as C, errors as ER, pairing as PR, export_schema as S
from .refwarp import tagframe as TF, warp as W

TOOL_NAME = "ArUco_Reference_Tagger"
TOOL_VERSION = "0.7.0"
SIG_M2 = 9.21                     # chi-square 2 dof, 99 %


@dataclass
class ExportOptions:
    include_raw: bool = False                       # copy the input TIFFs into images/
    consecutive_pairs: bool = False                 # also pair each accepted image with the next one
    extra_pairs: list = field(default_factory=list)  # [(ref image stem, compared image stem)]
    n_boot: int = 200                               # bootstrap draws for every alignment
    k_neighbours: int = 8                           # local deformation neighbourhood
    parquet: bool = True                            # also write .parquet when pyarrow imports
    float_format: str = "%.10g"


@dataclass
class Bundle:
    name: str
    tables: dict                                    # {file name: DataFrame}
    alignments: dict                                # {file name: dict}
    images: dict                                    # {stem: {meta, stage1, detect, filter, tag}}
    rejected: list
    manifest: dict
    raw_paths: dict = field(default_factory=dict)   # {stem: source TIFF path}
    options: ExportOptions = None


# ================================================================ helpers
def stem(path):
    b = os.path.basename(path)
    for ext in (".ome.tiff", ".ome.tif", ".tiff", ".tif"):
        if b.lower().endswith(ext):
            return b[: -len(ext)]
    return os.path.splitext(b)[0]


def jsonable(o):
    """numpy / dataclass / NaN-safe conversion for json.dump (NaN -> null)."""
    if is_dataclass(o) and not isinstance(o, type):
        return jsonable(asdict(o))
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return jsonable(o.tolist())
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        f = float(o)
        return f if math.isfinite(f) else None
    return o


def parse_tag(tag):
    """Design identity -> the common leading columns."""
    p = tag.split("|")
    out = {"category": p[0], "box": None, "node_i": None, "node_j": None, "di": None, "dj": None,
           "line": None, "m": None}
    if p[0] == "dot":
        out["box"] = int(p[1][1:]); a, b = p[2].split("_"); out["di"], out["dj"] = int(a), int(b)
    elif p[0] == "aruco":
        a, b = p[1][1:].split("_"); out["node_i"], out["node_j"] = int(a), int(b)
    elif p[0] == "dash":
        out["line"], out["m"] = p[1], int(p[2])
    return out


def _cov3(c):
    c = np.asarray(c, float) if c is not None else np.full((2, 2), np.nan)
    return float(c[0, 0]), float(c[1, 1]), float(c[0, 1])


def _covs(C3):
    """(n,2,2) -> three columns."""
    C3 = np.asarray(C3, float).reshape(-1, 2, 2)
    return C3[:, 0, 0], C3[:, 1, 1], C3[:, 0, 1]


def _frame(table, rows):
    """List of dicts -> DataFrame with the schema's columns, order and dtypes
    (pandas nullable Int64 / boolean so blanks survive a round trip)."""
    cols = S.TABLES[S.schema_key(table)]["cols"]
    df = pd.DataFrame(rows, columns=[c[0] for c in cols]) if rows else pd.DataFrame(columns=[c[0] for c in cols])
    return coerce(table, df)


def coerce(table, df):
    for name, dt, _u, _d in S.TABLES[S.schema_key(table)]["cols"]:
        s = df[name]
        if dt == "float":
            df[name] = pd.to_numeric(s, errors="coerce").astype("float64")
        elif dt == "int":
            df[name] = pd.to_numeric(s, errors="coerce").astype("Int64")
        elif dt == "bool":
            df[name] = s.map(lambda v: pd.NA if v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NA
                             else (str(v).lower() in ("true", "1")) if isinstance(v, str) else bool(v)).astype("boolean")
        else:
            df[name] = s.map(lambda v: "" if v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NA
                             else str(v)).astype(object)
    return df


def _git_commit():
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=here, capture_output=True, text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "."], cwd=os.path.dirname(here),
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return sha or None, bool(dirty)
    except Exception:
        return None, None


# ================================================================ per-image context
@dataclass
class _Img:
    entry: object
    stem: str
    short: str                      # name used in pair file names ("2x", or the stem on a clash)
    det: object
    filt: object
    tr: object

    @property
    def label(self):
        return float(self.entry.label)

    @property
    def lam(self):
        return float(self.det.lam_tags)

    @property
    def correction(self):
        return self.entry.pipeline.correction

    @property
    def shape(self):
        return tuple(self.det.u8.shape[:2])


def _images(project):
    """(accepted [_Img] ascending by label with the initial first, rejected [dict])."""
    acc, rej = [], []
    for e in sorted(project.images, key=lambda e: e.label):
        p = e.pipeline
        tr, det = p.tagging, p.detection
        if det is None:
            rej.append({"image": stem(e.path), "label": e.label, "stage": "not run", "reason": "stages 2-4 not run"})
        elif not (det.model and det.model.get("registered")):
            rej.append({"image": stem(e.path), "label": e.label, "stage": "detect",
                        "reason": (det.model or {}).get("reason", "not registered")})
        elif tr is None:
            rej.append({"image": stem(e.path), "label": e.label, "stage": "tag", "reason": "warp fit failed"})
        elif not tr.accepted:
            rej.append({"image": stem(e.path), "label": e.label, "stage": "series", "reason": tr.reason})
        else:
            acc.append(e)
    init = project.initial()
    if init is None or init not in acc:
        raise ValueError("the initial image is not accepted: run stages 2-4 on it (and fix its rejection) first")
    acc.remove(init); acc.insert(0, init)
    labs = [f"{e.label:g}x" for e in acc]
    out = []
    for e, lab in zip(acc, labs):
        st = stem(e.path)
        short = lab if labs.count(lab) == 1 else re.sub(r"[^A-Za-z0-9_.-]+", "_", st)
        out.append(_Img(e, st, short, e.pipeline.detection, e.pipeline.features, e.pipeline.tagging))
    return out, rej


def _alignments(ref: _Img, cmp: _Img, design, n_boot):
    """(pairs, rigid, similarity, affine): compared -> reference."""
    pairs = PR.pair_frames(ref.tr, cmp.tr)
    sim = PR.similarity_align(pairs, n_boot=n_boot)
    boxes = PR.common_boxes(pairs)
    rigid = {"ok": False, "reason": "no common box"}
    if boxes:
        N = boxes[0][0]
        c0 = TF.warped_box_centers(ref.tr.warp, design).get(N)
        c1 = TF.warped_box_centers(cmp.tr.warp, design).get(N)
        if c0 is not None and c1 is not None:
            rigid = PR.rigid_align(pairs, N, c0, c1, n_boot=n_boot)
    aff = PR.affine_align(pairs, n_boot=n_boot)
    return pairs, rigid, sim, aff


def _identity_align(kind):
    return {"ok": True, "kind": kind, "R": np.eye(2), "s": 1.0, "t": np.zeros(2), "fits": [], "identity": True}


def _map(P, Cf, align):
    """Points + their covariances through an alignment; plus the alignment's own
    per-point covariance."""
    P = np.asarray(P, float).reshape(-1, 2)
    A = align.get("s", 1.0) * np.asarray(align["R"])
    Q = PR.apply_align(P, align)
    Cq = np.einsum("ab,nbc,dc->nad", A, np.asarray(Cf, float).reshape(-1, 2, 2), A)
    Ca = PR.align_point_cov(P, align)
    return Q, Cq, Ca


# ================================================================ feature rows
def _features(im: _Img, design):
    """Per tagged feature of one image: everything the feature tables need, as
    arrays aligned with `tags`."""
    det, tr = im.det, im.tr
    rp = det.raw_pass or {}
    tags = sorted(tr.tags)
    n = len(tags)
    corr = np.array([tr.tags[t] for t in tags], float).reshape(-1, 2)
    Ccorr = np.array([PR._cov(tr, t) for t in tags]).reshape(-1, 2, 2)
    raw_det = np.full((n, 2), np.nan); raw_map = np.full((n, 2), np.nan)
    Craw = np.full((n, 2, 2), np.nan)
    flag = [""] * n
    sig = np.full(n, np.nan); bg = np.full(n, np.nan); sp = np.full(n, np.nan)
    dclass = [""] * n
    for k, t in enumerate(tags):
        kind, j = tr.src.get(t, (None, None))
        if kind == "dot":
            if rp.get("dots_det") is not None:
                raw_det[k] = rp["dots_det"][j]; raw_map[k] = rp["dots_map"][j]
            if det.dot_cov_raw is not None:
                Craw[k] = det.dot_cov_raw[j]
            if det.dot_cov_flag is not None:
                flag[k] = str(det.dot_cov_flag[j])
            for arr, dst in ((det.dot_signal, sig), (det.dot_bg, bg), (det.dot_sigma_px, sp)):
                if arr is not None:
                    dst[k] = arr[j]
        elif kind == "dash":
            if rp.get("dashes_det") is not None and j < len(rp["dashes_det"]):
                raw_det[k] = rp["dashes_det"][j]; raw_map[k] = rp["dashes_map"][j]
            if det.dash_cov_raw is not None:
                Craw[k] = det.dash_cov_raw[j]
        elif kind == "aruco":
            if j in rp.get("tags_det", {}):
                raw_det[k] = rp["tags_det"][j]
            if j in rp.get("tags_map", {}):
                raw_map[k] = rp["tags_map"][j]
            tc = det.tag_cov.get(j)
            if tc:
                Craw[k] = tc["centre_raw"]
            if j in det.tags:
                dclass[k] = det.tags[j].decode_class
    miss = ~np.isfinite(raw_map).all(1)
    if miss.any():                      # no raw pass: map the corrected position back exactly
        raw_map[miss] = C.inverse_geometric(corr[miss], im.correction, im.shape)
    pos = {r["tag"]: (r["x_um"], r["y_um"]) for r in design.records}
    um = np.array([pos[t] for t in tags], float).reshape(-1, 2)
    resid = np.array([(tr.residuals or {}).get(t, np.nan) for t in tags], float)
    return dict(tags=tags, corr=corr, Ccorr=Ccorr, raw_det=raw_det, raw_map=raw_map, Craw=Craw, flag=flag,
                signal=sig, bg=bg, sigma=sp, dclass=dclass, um=um, resid=resid)


def _id_cols(im: _Img, tag):
    d = {"image": im.stem, "label": im.label, "lam_derived": im.lam, "tag": tag}
    d.update(parse_tag(tag))
    return d


def _raw_rows(im, F, relative):
    rows = []
    for k, t in enumerate(F["tags"]):
        r = _id_cols(im, t)
        found = bool(np.isfinite(F["raw_det"][k]).all())
        c = _cov3(F["Craw"][k])
        r.update(x_raw_det=F["raw_det"][k, 0], y_raw_det=F["raw_det"][k, 1],
                 sxx_raw_det=c[0] if found else np.nan, syy_raw_det=c[1] if found else np.nan,
                 sxy_raw_det=c[2] if found else np.nan,
                 x_raw_map=F["raw_map"][k, 0], y_raw_map=F["raw_map"][k, 1], sxx_raw_map=c[0], syy_raw_map=c[1],
                 sxy_raw_map=c[2], raw_found=found,
                 det_minus_map_px=float(np.hypot(*(F["raw_det"][k] - F["raw_map"][k]))) if found else np.nan,
                 relative_err=relative, cov_flag=F["flag"][k], signal_adu=F["signal"][k], bg_adu=F["bg"][k],
                 sigma_px=F["sigma"][k], decode_class=F["dclass"][k])
        rows.append(r)
    return rows


def _corr_rows(im, F):
    rows = []
    for k, t in enumerate(F["tags"]):
        r = _id_cols(im, t)
        c = _cov3(F["Ccorr"][k])
        r.update(x_corr=F["corr"][k, 0], y_corr=F["corr"][k, 1], sxx_corr=c[0], syy_corr=c[1], sxy_corr=c[2],
                 resid_tps_px=F["resid"][k], cov_flag=F["flag"][k])
        rows.append(r)
    return rows


def _init_rows(im, F, align, F0, is_initial):
    """features_in_initial_* rows for one image under one alignment."""
    if is_initial:
        Q, Cq, Ca = F["corr"], F["Ccorr"], np.zeros((len(F["tags"]), 2, 2))
    else:
        Q, Cq, Ca = _map(F["corr"], F["Ccorr"], align)
    idx0 = {t: k for k, t in enumerate(F0["tags"])}
    rows = []
    for k, t in enumerate(F["tags"]):
        r = _id_cols(im, t)
        fq, fa = _cov3(Cq[k]), _cov3(Ca[k])
        r.update(x_init=Q[k, 0], y_init=Q[k, 1], sxx_feat=fq[0], syy_feat=fq[1], sxy_feat=fq[2],
                 sxx_align=fa[0], syy_align=fa[1], sxy_align=fa[2])
        k0 = idx0.get(t)
        if k0 is not None:
            p0 = F0["corr"][k0]
            Cd = np.zeros((2, 2)) if is_initial else Cq[k] + Ca[k] + F0["Ccorr"][k0]
            cd = _cov3(Cd)
            r.update(x0_init=p0[0], y0_init=p0[1], dx=Q[k, 0] - p0[0], dy=Q[k, 1] - p0[1],
                     sxx_d=cd[0], syy_d=cd[1], sxy_d=cd[2])
        rows.append(r)
    return rows


def _deviation_rows(im, F):
    sim = im.tr.similarity
    if not sim:
        return []
    exp = W.similarity_points(F["um"], sim)
    dev = F["corr"] - exp
    R = np.asarray(sim["R"]); s = float(sim["s"])
    dev_um = dev @ R / s                            # R^T dev / s, row-wise
    m2 = ER.mahalanobis2(dev, F["Ccorr"])
    rows = []
    for k, t in enumerate(F["tags"]):
        r = _id_cols(im, t)
        c = _cov3(F["Ccorr"][k])
        r.update(x_design_um=F["um"][k, 0], y_design_um=F["um"][k, 1], x_expected=exp[k, 0], y_expected=exp[k, 1],
                 dev_x=dev[k, 0], dev_y=dev[k, 1], dev_x_um=dev_um[k, 0], dev_y_um=dev_um[k, 1],
                 sxx_dev=c[0], syy_dev=c[1], sxy_dev=c[2], mahalanobis2=m2[k],
                 significant=bool(m2[k] > SIG_M2) if np.isfinite(m2[k]) else None, resid_tps_px=F["resid"][k])
        rows.append(r)
    return rows


def _tag_rows(im, design, rigid, sim, is_initial):
    det = im.det
    rp = det.raw_pass or {}
    id2node = design.id_to_node()
    pos = {r["tag"]: (r["x_um"], r["y_um"]) for r in design.records}
    frame_rot = float(det.frame_pose.frame_rot_deg) if det.frame_pose is not None else np.nan
    sign = float(det.model.get("sign", np.nan))
    ids = sorted(det.tags)
    if not ids:
        return []
    centres = np.array([det.tags[i].centre_px for i in ids], float)
    covs = np.array([(det.tag_cov.get(i) or {}).get("centre_corr", np.full((2, 2), np.nan)) for i in ids])
    if is_initial:
        Qr, Qs = centres, centres
    else:
        Qr = PR.apply_align(centres, rigid) if rigid.get("ok") else np.full_like(centres, np.nan)
        Qs = PR.apply_align(centres, sim) if sim.get("ok") else np.full_like(centres, np.nan)
    rows = []
    for k, i in enumerate(ids):
        t = det.tags[i]
        node = id2node.get(i)
        tag = f"aruco|N{node[0]}_{node[1]}|{i}" if node else ""
        tc = det.tag_cov.get(i) or {}
        c = _cov3(covs[k]); craw = _cov3(tc.get("centre_raw"))
        rd = rp.get("tags_det", {}).get(i); rm = rp.get("tags_map", {}).get(i)
        um = pos.get(tag, (np.nan, np.nan))
        r = {"image": im.stem, "label": im.label, "lam_derived": im.lam, "aruco_id": i, "tag": tag,
             "node_i": node[0] if node else None, "node_j": node[1] if node else None,
             "x_corr": t.centre_px[0], "y_corr": t.centre_px[1], "sxx_corr": c[0], "syy_corr": c[1], "sxy_corr": c[2]}
        for q in range(4):
            r[f"c{q}x"] = t.corners_px[q, 0]; r[f"c{q}y"] = t.corners_px[q, 1]
        r.update(rot_deg=t.rot_deg, rot_sigma_deg=tc.get("rot_sigma_deg", np.nan),
                 rot_rel_frame_deg=t.rot_deg - frame_rot, rot_raw_deg=t.rot_deg - float(im.correction.rotate_deg),
                 side_px=t.side_px, side_sigma_px=tc.get("side_sigma_px", np.nan), handedness=sign,
                 n_bits_corrected=t.n_bits_corrected, margin_bits=t.margin_bits, mirror_dist=t.mirror_dist,
                 border_errors=t.border_errors, contrast=t.contrast, decode_class=t.decode_class,
                 in_edge_band=bool(t.in_edge_band), usable=bool(t.usable),
                 x_raw_det=rd[0] if rd else np.nan, y_raw_det=rd[1] if rd else np.nan,
                 sxx_raw_det=craw[0] if rd else np.nan, syy_raw_det=craw[1] if rd else np.nan,
                 sxy_raw_det=craw[2] if rd else np.nan,
                 x_raw_map=rm[0] if rm else np.nan, y_raw_map=rm[1] if rm else np.nan,
                 x_init_rigid=Qr[k, 0], y_init_rigid=Qr[k, 1], x_init_sim=Qs[k, 0], y_init_sim=Qs[k, 1],
                 x_design_um=um[0], y_design_um=um[1])
        rows.append(r)
    return rows


def _dropped_rows(im, design):
    det, filt, tr = im.det, im.filt, im.tr
    base = {"image": im.stem, "label": im.label}
    rows = []
    if filt is not None:
        for cat, recs in (("dot", filt.dot_recs), ("dash", filt.dash_recs)):
            for rec in recs:
                if not rec["keep"]:
                    rows.append(dict(base, category=cat, index=rec["i"], x_corr=rec["x"], y_corr=rec["y"],
                                     reason=rec["reason"]))
    dots = np.asarray(det.dots, float).reshape(-1, 2); dashes = np.asarray(det.dashes_all, float).reshape(-1, 2)
    for key, cat, arr in (("dot", "dot", dots), ("box_mismatch", "dot", dots), ("dash", "dash", dashes)):
        for i in tr.unmatched.get(key, []):
            rows.append(dict(base, category=cat, index=int(i), x_corr=arr[i, 0], y_corr=arr[i, 1],
                             reason="box_mismatch" if key == "box_mismatch" else "unmatched"))
    id2node = design.id_to_node()
    for i, t in sorted(det.tags.items()):
        reason = ("duplicate" if t.duplicate else "ambiguous" if t.margin_bits <= 1 else
                  "edge_band" if t.in_edge_band else "not_in_design" if i not in id2node else "")
        if reason:
            rows.append(dict(base, category="aruco", index=int(i), x_corr=t.centre_px[0], y_corr=t.centre_px[1],
                             reason=reason))
    return rows


def _pair_rows(pairs, rigid, sim):
    n = len(pairs.tags)
    if not n:
        return []
    nan2 = np.full((n, 2), np.nan)
    Pr = PR.apply_align(pairs.P1, rigid) if rigid.get("ok") else nan2
    Ps, Cs1, Csa = _map(pairs.P1, pairs.C1, sim) if sim.get("ok") else (nan2, np.full((n, 2, 2), np.nan), np.full((n, 2, 2), np.nan))
    Cu = pairs.C0 + Cs1 + Csa
    rows = []
    for k, t in enumerate(pairs.tags):
        c0, c1, cu = _cov3(pairs.C0[k]), _cov3(pairs.C1[k]), _cov3(Cu[k])
        rows.append({"tag": t, "category": pairs.cats[k], "box": PR.tag_box(t),
                     "x_0": pairs.P0[k, 0], "y_0": pairs.P0[k, 1], "sxx_0": c0[0], "syy_0": c0[1], "sxy_0": c0[2],
                     "x_1": pairs.P1[k, 0], "y_1": pairs.P1[k, 1], "sxx_1": c1[0], "syy_1": c1[1], "sxy_1": c1[2],
                     "x1_rigid": Pr[k, 0], "y1_rigid": Pr[k, 1], "x1_sim": Ps[k, 0], "y1_sim": Ps[k, 1],
                     "ux_rigid": Pr[k, 0] - pairs.P0[k, 0], "uy_rigid": Pr[k, 1] - pairs.P0[k, 1],
                     "ux_sim": Ps[k, 0] - pairs.P0[k, 0], "uy_sim": Ps[k, 1] - pairs.P0[k, 1],
                     "sxx_u_sim": cu[0], "syy_u_sim": cu[1], "sxy_u_sim": cu[2]})
    return rows


def _deformation_rows(pairs, sim, k):
    if not sim.get("ok"):
        return []
    f = PR.field(pairs, sim, k=k)
    if not f["n"]:
        return []
    rows = []
    iu = [(i, j) for i in range(4) for j in range(i, 4)]
    for n_, t in enumerate(f["tags"]):
        F = f["F"][n_]; Fc = f["F_cov"][n_]; U = f["U_stretch"][n_]
        r = {"tag": t, "box": PR.tag_box(t), "x0": f["P0"][n_, 0], "y0": f["P0"][n_, 1],
             "F11": F[0, 0], "F12": F[0, 1], "F21": F[1, 0], "F22": F[1, 1]}
        for key, col in (("J", "J"), ("lin", "lin"), ("lam1", "lam1"), ("lam2", "lam2"), ("anisotropy", "anisotropy")):
            r[col] = f[key][n_]; r[col + "_sigma"] = f[key + "_sigma"][n_]
        r.update(phi_deg=f["phi_deg"][n_], phi_sigma_deg=f["phi_deg_sigma"][n_], rot_deg=f["rot_deg"][n_],
                 rot_sigma_deg=f["rot_deg_sigma"][n_], resid_rms_px=f["resid_rms"][n_], n_nb=int(f["n_nb"][n_]))
        for i, j in iu:
            r[f"Fcov_{i}{j}"] = Fc[i, j]
        r.update(U11=U[0, 0], U12=U[0, 1], U22=U[1, 1])
        rows.append(r)
    return rows


def _align_record(ref, cmp, rigid, sim, aff, n_boot):
    def clean(a):
        return {k: v for k, v in a.items() if k != "fits"}
    return jsonable({"reference": ref.stem, "compared": cmp.stem, "reference_label": ref.label,
                     "compared_label": cmp.label, "map": "compared corrected px -> reference corrected px",
                     "rigid": clean(rigid), "similarity": clean(sim), "affine": clean(aff), "bootstrap_n": n_boot,
                     "convention": "p_ref = s R p_cmp + t; angle_deg counter-clockwise on screen"})


# ================================================================ per-image records
def _image_record(im: _Img, design):
    e, det, filt, tr = im.entry, im.det, im.filt, im.tr
    p = e.pipeline
    model = {k: v for k, v in (det.model or {}).items() if k not in ("aruco_xy",)}
    rp = {k: v for k, v in (det.raw_pass or {}).items()
          if not isinstance(v, (np.ndarray, dict))}
    warp = {k: v for k, v in (tr.warp or {}).items() if k not in ("H", "tps", "ref_um", "det_px", "pairs")
            and not isinstance(v, (np.ndarray, list, dict))}
    return jsonable({
        "meta": p.meta.to_dict() if hasattr(p.meta, "to_dict") else {},
        "stage1": {"correction": p.correction.to_dict(), "levels": p.levels.to_dict(),
                   "image_shape": list(im.shape), "source": e.path},
        "detect": {"params": det.params, "design_name": det.design_name, "design_sha": det.design_sha,
                   "frame_pose": det.frame_pose, "model": model, "lam_tags": det.lam_tags,
                   "lam_tags_sigma": det.lam_tags_sigma, "lam_dots": det.lam_dots, "rot_raw_deg": det.rot_raw_deg,
                   "n_dots": len(det.dots), "n_dashes": len(det.dashes_all), "n_tags_decoded": len(det.tags),
                   "per_box": det.per_box, "raw_pass": rp, "noise": det.noise},
        "filter": ({"dot_params": filt.dot_params, "dash_params": filt.dash_params, "dot_counts": filt.dot_counts,
                    "dash_counts": filt.dash_counts} if filt is not None else None),
        "tag": {"warp": warp, "similarity": tr.similarity, "per_category": tr.per_category, "per_box": tr.per_box,
                "n_tags": len(tr.tags), "accepted": tr.accepted, "reason": tr.reason, "source": tr.source,
                "confidence": tr.confidence,
                "n_unmatched": {k: len(v) for k, v in (tr.unmatched or {}).items()}},
    })


# ================================================================ build / write
def build_bundle(project, design, options: ExportOptions = None, name=None) -> Bundle:
    o = options or ExportOptions()
    imgs, rejected = _images(project)
    init = imgs[0]
    feats = {im.stem: _features(im, design) for im in imgs}
    F0 = feats[init.stem]
    rows = {k: [] for k in ("features_raw.csv", "features_corr.csv", "features_in_initial_rigid.csv",
                            "features_in_initial_sim.csv", "deviation_from_design.csv", "tags_pose.csv",
                            "dropped_features.csv")}
    tables, aligns = {}, {}
    to_init = {}
    for im in imgs:
        F = feats[im.stem]
        is0 = im is init
        if is0:
            rigid, sim = _identity_align("rigid"), _identity_align("similarity")
        else:
            pairs, rigid, sim, aff = _alignments(init, im, design, o.n_boot)
            to_init[im.stem] = (pairs, rigid, sim, aff)
        relative = bool((im.det.noise or {}).get("relative", True))
        rows["features_raw.csv"] += _raw_rows(im, F, relative)
        rows["features_corr.csv"] += _corr_rows(im, F)
        rows["features_in_initial_rigid.csv"] += (_init_rows(im, F, rigid, F0, is0) if rigid.get("ok") else [])
        rows["features_in_initial_sim.csv"] += (_init_rows(im, F, sim, F0, is0) if sim.get("ok") else [])
        rows["deviation_from_design.csv"] += _deviation_rows(im, F)
        rows["tags_pose.csv"] += _tag_rows(im, design, rigid, sim, is0)
        rows["dropped_features.csv"] += _dropped_rows(im, design)
    for k, v in rows.items():
        tables[k] = _frame(k, v)
    # pairs: every accepted image against the initial, + consecutive, + the user's extra pairs
    by_stem = {im.stem: im for im in imgs}
    plist = [(init, im) for im in imgs[1:]]
    if o.consecutive_pairs:
        plist += [(a, b) for a, b in zip(imgs[1:], imgs[2:])]
    for a, b in o.extra_pairs:
        if a in by_stem and b in by_stem and a != b:
            plist.append((by_stem[a], by_stem[b]))
    seen = set()
    for ref, cmp in plist:
        key = (ref.stem, cmp.stem)
        if key in seen:
            continue
        seen.add(key)
        pairs, rigid, sim, aff = to_init[cmp.stem] if ref is init else _alignments(ref, cmp, design, o.n_boot)
        tag = f"{ref.short}_{cmp.short}"
        tables[f"pairs_{tag}.csv"] = _frame("pairs.csv", _pair_rows(pairs, rigid, sim))
        tables[f"local_deformation_{tag}.csv"] = _frame("local_deformation.csv",
                                                        _deformation_rows(pairs, sim, o.k_neighbours))
        aligns[f"alignment_{tag}.json"] = _align_record(ref, cmp, rigid, sim, aff, o.n_boot)
    images = {im.stem: _image_record(im, design) for im in imgs}
    for r in rejected:
        e = next((x for x in project.images if stem(x.path) == r["image"]), None)
        if e is not None:
            r["meta"] = jsonable(e.meta.to_dict())
    sha, dirty = _git_commit()
    now = _dt.datetime.now().astimezone()
    pname = os.path.basename(os.path.normpath(getattr(project, "folder", "") or "project")) or "project"
    name = name or f"export_{re.sub(r'[^A-Za-z0-9_.-]+', '_', pname)}_{now:%Y%m%d-%H%M%S}"
    noise = dict(getattr(project, "noise", {}) or {})
    manifest = {
        "bundle_version": S.BUNDLE_VERSION,
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION, "git_commit": sha, "git_dirty": dirty},
        "created": now.isoformat(timespec="seconds"),
        "project": {"path": getattr(project, "folder", ""), "initial": init.stem,
                    "images": [{"image": im.stem, "label": im.label, "lam_derived": im.lam, "accepted": True,
                                "short": im.short} for im in imgs]
                    + [{"image": r["image"], "label": r["label"], "accepted": False} for r in rejected]},
        "design": {"name": design.name, "folder": design.folder, "sha256": dict(getattr(design, "file_sha256", {}) or {}),
                   "box_um": design.box_um, "origin_um": design.origin_um, "grid_n": design.grid_n},
        "frames": {"raw": "px, the TIFF as acquired, y down",
                   "corr": "px, after the Stage-1 geometric correction (lens, deskew)",
                   "init_rigid": "px, the initial image's corr frame; rigid map (scale kept)",
                   "init_sim": "px, the initial image's corr frame; similarity map (scale removed)",
                   "expected": "px, this image's corr frame; the image's own similarity fit of the design",
                   "design": "um, the print, y up"},
        "error_model": {"project_calibration": noise,
                        "per_image": {im.stem: im.det.noise for im in imgs},
                        "relative_images": [im.stem for im in imgs if (im.det.noise or {}).get("relative", True)]},
        "options": asdict(o),
        "per_image": images,
        "rejected": rejected,
        "tables": {},
        "alignments": sorted(aligns),
    }
    return Bundle(name=name, tables=tables, alignments=aligns, images=images, rejected=jsonable(rejected),
                  manifest=manifest, raw_paths={im.stem: im.entry.path for im in imgs}, options=o)


def validate_bundle(bundle: Bundle):
    probs = []
    for k, df in bundle.tables.items():
        probs += S.validate(k, df)
    return probs


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_bundle(bundle: Bundle, parent):
    """Write the bundle into parent/<bundle.name>/; returns the folder."""
    probs = validate_bundle(bundle)
    if probs:
        raise ValueError("schema: " + "; ".join(probs))
    o = bundle.options or ExportOptions()
    out = os.path.join(parent, bundle.name)
    os.makedirs(os.path.join(out, "images"), exist_ok=True)
    try:
        import pyarrow  # noqa: F401
        have_pq = bool(o.parquet)
    except Exception:
        have_pq = False
    man = bundle.manifest
    for name, df in bundle.tables.items():
        p = os.path.join(out, name)
        df.to_csv(p, index=False, float_format=o.float_format, lineterminator="\n")
        man["tables"][name] = {"rows": int(len(df)), "sha256": _sha(p), "schema": S.schema_key(name)}
        if have_pq:
            df.to_parquet(os.path.join(out, name[:-4] + ".parquet"), index=False)
    man["parquet"] = have_pq
    man["parquet_note"] = "" if have_pq else "pyarrow not importable (or disabled): CSV only"
    for name, rec in bundle.alignments.items():
        with open(os.path.join(out, name), "w") as f:
            json.dump(rec, f, indent=1)
    for st, rec in bundle.images.items():
        for part in ("meta", "stage1", "detect", "filter", "tag"):
            with open(os.path.join(out, "images", f"{st}.{part}.json"), "w") as f:
                json.dump(rec[part], f, indent=1)
    if o.include_raw:
        man["raw_copies"] = {}
        for st, src in bundle.raw_paths.items():
            if src and os.path.exists(src):
                dst = os.path.join(out, "images", os.path.basename(src))
                shutil.copy2(src, dst)
                man["raw_copies"][st] = {"file": "images/" + os.path.basename(src), "sha256": _sha(dst)}
    with open(os.path.join(out, "rejected.json"), "w") as f:
        json.dump(bundle.rejected, f, indent=1)
    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump(jsonable(man), f, indent=1)
    with open(os.path.join(out, "README.md"), "w") as f:
        f.write(S.readme(man))
    return out


def export_project(project, design, parent, options: ExportOptions = None, name=None):
    b = build_bundle(project, design, options, name)
    return write_bundle(b, parent), b


def row_counts(bundle: Bundle):
    return {k: int(len(v)) for k, v in bundle.tables.items()}
