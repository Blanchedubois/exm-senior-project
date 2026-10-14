"""
Phase 7 tests (docs/07_PHASE7_DATA_EXPORT.md §6): the bundle's schema, round
trip, frame consistency, deviation from design against the dummy truth, pairs vs
local deformation, rejected frames, and the headless script.
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
import tempfile
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _dummy as DM                                                            # noqa: E402
from rwtag import (correct as C, designs as DS, errors as ER, series as SR, project as PJ, io,   # noqa: E402
                   export as EX, export_reader as RD, export_schema as S)
from rwtag.aruco import ArucoParams                                            # noqa: E402
from rwtag.refwarp import warp as W                                            # noqa: E402
from rwtag.types import PipelineState, LevelsParams                            # noqa: E402

ROT = 6.0
DES = os.path.join(DM.DESIGNS, "1_optimistic")
_CACHE = {}


def _project(run, lams=(1.0, 2.0, 4.0), mirror=None):
    """In-memory Project of a dummy run processed by the series runner (frame
    `mirror` is flipped left-right so the series gates reject it)."""
    key = (run, lams, mirror)
    if key in _CACHE:
        return _CACHE[key]
    d, truth = DM.run("optimistic", run)
    if d is None:
        return None
    p = DM.stage1(truth, ROT)
    design = DS.load(DES)
    frames = []
    for lam in lams:
        raw = DM.load(d, DM.frame(truth, lam))
        if lam == mirror:
            raw = raw[:, ::-1].copy()
        frames.append((lam, DM.corrected(raw, p), raw, p))
    out = SR.process_frames(frames, design, ArucoParams(psf_fwhm_um=1.91),
                            noise_model=ER.NoiseModel(gain_e_per_adu=truth["camera"]["true_gain_e_per_adu"], kappa_dot=0.9))
    proj = PJ.Project(folder=d)
    for f in out:
        path = os.path.join(d, DM.frame(truth, f.label)["files"][0] + ".ome.tif")
        proj.images.append(PJ.ImageEntry(path=path, label=f.label, pipeline=PipelineState(
            correction=p, detection=f.det, features=f.filt, tagging=f.tagging)))
    proj.refresh_roles()
    b = EX.build_bundle(proj, design, EX.ExportOptions(n_boot=100))
    _CACHE[key] = (d, truth, design, proj, b)
    return _CACHE[key]


def _written(r):
    tmp = tempfile.mkdtemp(prefix="rwtag_p7_")
    return tmp, EX.write_bundle(r[4], tmp)


# ------------------------------------------------------------------ schema
def test_schema_validates():
    r = _project("opt_warp")
    if r is None:
        return
    b = r[4]
    assert EX.validate_bundle(b) == []
    want = {"features_raw.csv", "features_corr.csv", "features_in_initial_rigid.csv", "features_in_initial_sim.csv",
            "deviation_from_design.csv", "tags_pose.csv", "dropped_features.csv", "pairs_1x_2x.csv",
            "pairs_1x_4x.csv", "local_deformation_1x_2x.csv", "local_deformation_1x_4x.csv"}
    assert want <= set(b.tables), set(b.tables)
    df = b.tables["features_corr.csv"].rename(columns={"x_corr": "x"})
    assert S.validate("features_corr.csv", df)                       # a renamed column fails
    df2 = b.tables["features_corr.csv"].copy(); df2["box"] = df2["box"].astype(str)
    assert S.validate("features_corr.csv", df2)                      # a wrong dtype fails
    readme = S.readme(b.manifest)
    for t in S.TABLES:
        assert f"`{t}`" in readme
    n = {k: len(v) for k, v in b.tables.items()}
    print(f"  info  rows: " + ", ".join(f"{k} {v}" for k, v in n.items()))
    # every accepted image's every tagged feature, once per feature table
    total = sum(len(im.pipeline.tagging.tags) for im in r[3].images)
    for k in ("features_raw.csv", "features_corr.csv", "deviation_from_design.csv", "features_in_initial_sim.csv"):
        assert n[k] == total, (k, n[k], total)


def test_roundtrip():
    r = _project("opt_warp")
    if r is None:
        return
    tmp, folder = _written(r)
    try:
        rb = RD.read_bundle(folder)
        assert rb.check() == []
        for k, df in r[4].tables.items():
            back = rb.tables[k]
            assert list(back.columns) == list(df.columns), k
            assert len(back) == len(df), k
            for c, dt, _u, _d in S.TABLES[S.schema_key(k)]["cols"]:
                a, b = df[c], back[c]
                if dt == "float":
                    ok = np.allclose(a.to_numpy(float), b.to_numpy(float), rtol=1e-9, atol=1e-9, equal_nan=True)
                else:
                    ok = (a.astype(object).where(a.notna(), None).tolist() == b.astype(object).where(b.notna(), None).tolist())
                assert ok, (k, c)
        assert set(rb.pairs()) == {("1x", "2x"), ("1x", "4x")}
        assert set(rb.images) == {EX.stem(e.path) for e in r[3].images}
        assert set(rb.images[r[4].manifest["project"]["initial"]]) == {"meta", "stage1", "detect", "filter", "tag"}
        al = rb.alignments["alignment_1x_2x.json"]
        assert al["similarity"]["ok"] and al["rigid"]["ok"] and al["affine"]["ok"]
        assert abs(al["similarity"]["expansion"] - 2.0) < 0.01
        # an edited file fails the check
        p = os.path.join(folder, "tags_pose.csv")
        with open(p, "a") as f:
            f.write("\n")
        assert RD.read_bundle(folder).check(raise_=False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------ frames
def test_frames_are_consistent():
    """raw_map through the stored Stage-1 parameters = corr (1e-3 px); the
    initial image in the initial frame = its corr; raw_det next to raw_map."""
    r = _project("opt_warp")
    if r is None:
        return
    b = r[4]
    raw, corr = b.tables["features_raw.csv"], b.tables["features_corr.csv"]
    worst = 0.0
    for st, rec in b.images.items():
        p = C.CorrectionParams.from_dict(rec["stage1"]["correction"]); shape = tuple(rec["stage1"]["image_shape"])
        m = (raw.image == st).to_numpy()
        P = C.forward_geometric(raw.loc[m, ["x_raw_map", "y_raw_map"]].to_numpy(float), p, shape)
        Q = corr.loc[(corr.image == st).to_numpy(), ["x_corr", "y_corr"]].to_numpy(float)
        assert (raw.tag[m].to_numpy() == corr.tag[(corr.image == st).to_numpy()].to_numpy()).all()
        ok = np.isfinite(P).all(1)
        worst = max(worst, float(np.abs(P[ok] - Q[ok]).max()))
        assert ok.mean() > 0.99
    found = raw.raw_found.to_numpy(bool)
    dd = raw.det_minus_map_px.to_numpy(float)[found]
    print(f"  info  raw_map -> corr max error {worst:.2e} px · raw pass re-found {found.mean():.1%} · "
          f"|raw_det - raw_map| median {np.median(dd):.3f} px")
    assert worst < 1e-3 and found.mean() > 0.9 and np.median(dd) < 0.2
    init = b.manifest["project"]["initial"]
    for k in ("features_in_initial_sim.csv", "features_in_initial_rigid.csv"):
        t = b.tables[k]; m = (t.image == init).to_numpy()
        c = corr[(corr.image == init).to_numpy()]
        assert np.allclose(t.loc[m, ["x_init", "y_init"]].to_numpy(float), c[["x_corr", "y_corr"]].to_numpy(float))
        assert np.allclose(t.loc[m, ["dx", "dy"]].to_numpy(float), 0)
    # tags_pose: raw rotation = corrected rotation - deskew; centres agree with features_corr
    tp = b.tables["tags_pose.csv"]
    assert np.allclose(tp.rot_raw_deg, tp.rot_deg - ROT)
    j = tp.merge(corr[corr.category == "aruco"], on=["image", "tag"], suffixes=("", "_f"))
    assert len(j) > 10 and np.allclose(j.x_corr, j.x_corr_f) and np.allclose(j.y_corr, j.y_corr_f)


def test_deviation_matches_truth():
    """opt_warp: the exported deviation from design (design um) against the
    simulator's truth computed the same way; opt_clean: the deviations are noise."""
    r = _project("opt_warp")
    if r is None:
        return
    d, truth, design, proj, b = r
    dev = b.tables["deviation_from_design.csv"]
    pos = {q["tag"]: (q["x_um"], q["y_um"]) for q in design.records}
    for e in proj.images[1:]:
        st = EX.stem(e.path)
        rows = dev[(dev.image == st).to_numpy() & (dev.category == "dot").to_numpy()]
        tags, traw, _ = DM.truth_features(d, DM.frame(truth, e.label), "dot")
        p = C.CorrectionParams.from_dict(b.images[st]["stage1"]["correction"])
        T = dict(zip(tags, C.forward_geometric(traw, p, tuple(b.images[st]["stage1"]["image_shape"]))))
        keep = [t in T and np.isfinite(T[t]).all() for t in rows.tag]
        rows = rows[keep]
        Q = np.array([T[t] for t in rows.tag]); U = np.array([pos[t] for t in rows.tag])
        sim = W.similarity(U, Q)
        tdev = (Q - W.similarity_points(U, sim)) @ np.asarray(sim["R"]) / sim["s"]
        got = rows[["dev_x_um", "dev_y_um"]].to_numpy(float)
        corr = float(np.corrcoef(got.ravel(), tdev.ravel())[0, 1])
        rms = float(np.sqrt(np.mean(((got - tdev) ** 2).sum(1))))
        print(f"  info  warped λ {e.label:g}: deviation-from-design RMS {np.sqrt(np.mean((tdev ** 2).sum(1))):.3f} µm · "
              f"recovered to {rms:.3f} µm · corr {corr:.3f} · significant {rows.significant.mean():.0%}")
        assert corr > 0.9 and rms < 0.1
    rc = _project("opt_clean")
    if rc is None:
        return
    dv = rc[4].tables["deviation_from_design.csv"]
    inside = float((dv.mahalanobis2 < 5.991).mean())
    print(f"  info  clean: deviations inside their 95 % ellipse {inside:.1%} · significant (99 %) {dv.significant.mean():.1%}")
    assert inside > 0.9


def test_pairs_match_local_deformation():
    r = _project("opt_warp")
    if r is None:
        return
    b = r[4]
    for ref_cmp in ("1x_2x", "1x_4x"):
        pr, dfm = b.tables[f"pairs_{ref_cmp}.csv"], b.tables[f"local_deformation_{ref_cmp}.csv"]
        j = dfm.merge(pr, on="tag", how="left")
        assert j.x_0.notna().all() and np.allclose(j.x0, j.x_0) and np.allclose(j.y0, j.y_0)
        # similarity displacement has zero mean and its covariance roughly covers it
        d = pr[pr.category == "dot"]
        m2 = ER.mahalanobis2(d[["ux_sim", "uy_sim"]].to_numpy(float),
                             np.stack([np.stack([d.sxx_u_sim, d.sxy_u_sim], 1), np.stack([d.sxy_u_sim, d.syy_u_sim], 1)], 1))
        print(f"  info  {ref_cmp}: {len(pr)} pairs · {len(dfm)} deformation rows · lin median {dfm.lin.median():.4f}")
        assert abs(dfm.lin.median() / float(ref_cmp.split("_")[1][:-1]) - 1) < 0.01
    # features_in_initial_sim of the expanded image == pairs' x1_sim for the same tag
    fs = b.tables["features_in_initial_sim.csv"]; pr = b.tables["pairs_1x_2x.csv"]
    st2 = [im["image"] for im in b.manifest["project"]["images"] if im.get("short") == "2x"][0]
    j = fs[fs.image == st2].merge(pr, on="tag")
    assert len(j) == len(pr) and np.allclose(j.x_init, j.x1_sim) and np.allclose(j.dx, j.ux_sim)


def test_rejected_listed():
    r = _project("opt_clean", mirror=2.0)
    if r is None:
        return
    b = r[4]
    st = EX.stem(r[3].images[1].path)
    assert [x["image"] for x in b.rejected] == [st], b.rejected
    print(f"  info  rejected: {b.rejected[0]['reason']}")
    for k, df in b.tables.items():
        if "image" in df.columns:
            assert st not in set(df.image), k
    assert set(k for k in b.tables if k.startswith("pairs_")) == {"pairs_1x_4x.csv"}
    # the initial image not accepted -> refuse
    proj = PJ.Project(folder=r[3].folder, images=[PJ.ImageEntry(path=e.path, label=e.label, pipeline=e.pipeline)
                                                  for e in r[3].images[1:]])
    proj.refresh_roles()
    try:
        EX.build_bundle(proj, r[2])
        assert False, "export of a project whose initial image is rejected must fail"
    except ValueError as ex:
        assert "initial" in str(ex)


# ------------------------------------------------------------------ headless
def make_dummy_project(tmp, run="opt_warp", lams=(1.0, 2.0, 4.0), rotate=ROT):
    """A saved project folder: symlinked dummy TIFFs + Stage-1 sidecars + settings."""
    d, truth = DM.run("optimistic", run)
    if d is None:
        return None, None
    proj = PJ.Project(folder=tmp, design_folder=DES)
    p = DM.stage1(truth, rotate)
    for lam in lams:
        src = os.path.join(d, DM.frame(truth, lam)["files"][0] + ".ome.tif")
        dst = os.path.join(tmp, os.path.basename(src))
        try:
            os.symlink(src, dst)
        except OSError:
            shutil.copy(src, dst)
        io.save_session(io.sidecar_path(dst), dst, p, LevelsParams(), {})
        proj.add(dst, lam)
    proj.store_settings(ArucoParams(psf_fwhm_um=truth["camera"]["psf_fwhm_um"]))
    return proj, truth


def test_headless_script():
    """scripts/export_project.py on a saved project = the in-process run + export
    (same table hashes)."""
    tmp = tempfile.mkdtemp(prefix="rwtag_p7h_")
    try:
        proj, truth = make_dummy_project(tmp)
        if proj is None:
            return
        path = proj.save()
        # in process
        design = DS.load(DES)
        PJ.run_all(proj, design)
        f1, b1 = EX.export_project(proj, design, tmp, EX.ExportOptions(n_boot=50), name="inproc")
        # the script, in a fresh interpreter
        script = os.path.join(DM.ROOT, "scripts", "export_project.py")
        res = subprocess.run([sys.executable, script, path, "--name", "script", "--boot", "50"],
                             capture_output=True, text=True, timeout=600)
        assert res.returncode == 0, res.stdout + res.stderr
        m1 = json.load(open(os.path.join(f1, "manifest.json")))
        m2 = json.load(open(os.path.join(tmp, "script", "manifest.json")))
        assert set(m1["tables"]) == set(m2["tables"])
        diff = [k for k in m1["tables"] if m1["tables"][k]["sha256"] != m2["tables"][k]["sha256"]]
        print(f"  info  script: {len(m2['tables'])} tables, identical hashes: {not diff}")
        assert not diff, diff
        assert m2["per_image"][EX.stem(proj.images[0].path)]["detect"]["params"]["psf_fwhm_um"] == truth["camera"]["psf_fwhm_um"]
        RD.read_bundle(os.path.join(tmp, "script")).check()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
