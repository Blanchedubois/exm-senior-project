"""
Phase 2 tests for rwtag.project (no Qt): roles (ported from V1), persistence with
the embedded metadata, sidecar priority, apply-to-all, and the dummy frames
corrected by Stage 1 matching their ground truth.
"""
from __future__ import annotations
import json
import os
import shutil
import sys
import tempfile
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from rwtag import project as P, correct as C, io, meta as M          # noqa: E402
from rwtag.types import CorrectionParams, LevelsParams               # noqa: E402
from rwtag.aruco import ArucoParams, Design, decode_tags, fit_affine  # noqa: E402

DUMMY = os.path.normpath(os.path.join(ROOT, "..", "aruco-marker-design", "dummy"))


def _dummy(design, run):
    d = os.path.join(DUMMY, design, run)
    if not os.path.exists(os.path.join(d, "truth.json")):
        print(f"  skip: dummy run {design}/{run} not generated"); return None, None
    return d, json.load(open(os.path.join(d, "truth.json")))


def _link(src, d):
    dst = os.path.join(d, os.path.basename(src))
    try:
        os.symlink(src, dst)
    except OSError:
        shutil.copy(src, dst)
    return dst


# ------------------------------------------------------------ ported V1
def test_initial_auto_lowest_and_override():
    proj = P.Project(folder="/tmp")
    a = proj.add("/tmp/2.0Xb.tif", 2.0)
    b = proj.add("/tmp/1.5Xa.tif", 1.5)
    c = proj.add("/tmp/3.0Xc.tif", 3.0)
    assert proj.initial() is b and b.role == "initial"
    assert [e.label for e in proj.expanded()] == [2.0, 3.0]
    proj.set_initial(c)
    assert proj.initial() is c and b.role == "expanded"
    proj.remove(c)
    assert proj.initial() is b


def test_stage_status_progression():
    e = P.ImageEntry(path="/nonexistent/2.0X.tif", label=2.0)
    assert e.stage_status() == (False, False, False, False)


# ------------------------------------------------------------ metadata in the project
def test_project_embeds_meta_and_roundtrips():
    d0, truth = _dummy("optimistic", "opt_clean")
    if d0 is None:
        return
    with tempfile.TemporaryDirectory() as d:
        paths = [_link(os.path.join(d0, f["files"][0] + ".ome.tif"), d) for f in truth["frames"][:3]]
        proj = P.Project(folder=d)
        for p in paths:
            proj.add(p, io.parse_label(p))
        e = proj.images[1]
        assert e.meta.magnification == 20.0 and e.meta.source("magnification") == "header"
        assert e.meta.expansion_expected == 1.5 and e.meta.source("expansion_expected") == "filename"
        e.meta.set("cells_present", True, "user"); e.meta.set("cells_description", "U2OS", "user")
        e.meta.set("gain_e_per_adu", 0.235, "user")
        path = proj.save()
        saved = json.load(open(path))
        assert saved["images"][1]["meta"]["cells_description"] == "U2OS"
        # sidecar wins over the embedded copy
        e.meta.set("notes", "edited later", "user"); e.save_meta()
        p2 = P.Project.load(path)
        e2 = p2.images[1]
        assert e2.meta.cells_present is True and e2.meta.notes == "edited later"
        assert e2.meta.gain_known and e2.meta.source("um_per_px") == "header"
        # with the sidecar gone, the embedded copy is used and a sidecar re-written
        os.remove(M.meta_path(e2.path))
        p3 = P.Project.load(path)
        assert p3.images[1].meta.cells_description == "U2OS" and os.path.exists(M.meta_path(e2.path))


def test_apply_meta_groups_to_all():
    proj = P.Project(folder="/tmp")
    a = proj.add("/tmp/1.5Xa.tif", 1.5); b = proj.add("/tmp/2Xb.tif", 2.0)
    a.meta.set("magnification", 100, "user"); a.meta.set("laser_wavelength_nm", 561, "user")
    a.meta.set("gain_e_per_adu", 0.5, "user"); a.meta.set("sample_id", "gel-7", "user")
    n = proj.apply_meta_groups_to_all(a)
    assert n == 1 and b.meta.magnification == 100 and b.meta.gain_e_per_adu == 0.5
    assert b.meta.sample_id is None                          # sample group stays per image
    assert b.meta.optics_short() == "100×/561 nm"


# ------------------------------------------------------------ Stage 1 on the dummy frames
def _stage1_params(truth, rotate=0.0):
    cam = truth["camera"]
    c = cam.get("lens_centre_frac", 0.5)          # the render's true lens centre
    return CorrectionParams(k1=cam["lens_k1"], k2=cam["lens_k2"], vig_strength=cam["vignette_strength"],
                            vig_power=cam["vignette_power"], rotate_deg=rotate, dist_cx=c, dist_cy=c)


def _truth_tags(frame):
    return {int(k): v for k, v in frame["tags"].items() if v["in_frame"]}


def test_dummy_truth_after_correction():
    """The dummy camera's lens model and correct.py's are the same model: the
    truth's raw positions pushed through forward_geometric land on its
    un-distorted positions."""
    d0, truth = _dummy("optimistic", "opt_warp")
    if d0 is None:
        return
    p = _stage1_params(truth)
    W = truth["camera"]["fov_px"]
    for frame in truth["frames"]:
        tt = _truth_tags(frame)
        raw = np.array([[t["x_raw"], t["y_raw"]] for t in tt.values()])
        und = np.array([[t["x_und"], t["y_und"]] for t in tt.values()])
        err = np.hypot(*(C.forward_geometric(raw, p, (W, W)) - und).T)
        assert err.max() < 0.05, (frame["label"], err.max())
        back = np.hypot(*(C.inverse_geometric(und, p, (W, W)) - raw).T)
        assert back.max() < 0.05, (frame["label"], back.max())


def test_tags_on_corrected_frame_match_truth():
    """Decode on the Stage-1 corrected frame (lens + vignette + a 10 deg deskew):
    every tag lands on forward_geometric(truth raw) and the expansion factor from
    the tag centres is recovered to 0.5 % at every lambda, which the raw frame
    could not give (Phase 1: up to 5.7 % lens bias)."""
    d0, truth = _dummy("optimistic", "opt_clean")
    if d0 is None:
        return
    cam = truth["camera"]
    p = _stage1_params(truth, rotate=10.0)
    design = Design.load(os.path.join(d0, "reference_tags.json"))
    params = ArucoParams(um_per_px=cam["um_per_px"], psf_fwhm_um=cam["psf_fwhm_um"], edge_band_um=48.0)
    for frame in truth["frames"]:
        raw = io.load_tiff(os.path.join(d0, frame["files"][0] + ".ome.tif"))
        corr = C.process(raw, p, LevelsParams())
        tags, _ = decode_tags(io.to_uint8_robust(corr), params, design.dict_name, tag_um=design.tag_um)
        tt = _truth_tags(frame)
        errs = []
        for i, t in tags.items():
            if t.usable and i in tt:
                exp = C.forward_geometric([[tt[i]["x_raw"], tt[i]["y_raw"]]], p, raw.shape)[0]
                errs.append(np.hypot(*(t.centre_px - exp)))
        A, info = fit_affine(design, tags)
        lam = info["scale_px_per_um"] * cam["um_per_px"]
        print(f"  info  lambda {frame['label']:g}: {len(errs)} tags on corrected frame, centre err "
              f"median {np.median(errs):.2f} max {max(errs):.2f} px · lambda {lam:.4f} · rot {info['rot_deg']:+.2f}")
        assert len(errs) >= min(4, len(tt)) and max(errs) < 0.8, frame["label"]
        assert abs(lam / frame["label"] - 1) < 0.005, (frame["label"], lam)
        assert info["sign"] == -1.0


def test_stale_corrected_frame_is_recomputed():
    """Changing Stage-1 parameters after the corrected frame was made must not let
    a later stage run on the stale frame (found in Phase 6: a lens left
    uncorrected biased every expansion ratio by 1.8 %)."""
    d0, truth = _dummy("optimistic", "opt_clean")
    if d0 is None:
        return
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d0, truth["frames"][0]["files"][0] + ".ome.tif")
        e = P.ImageEntry(path=_link(src, d), label=1.0)
        e.ensure_loaded()
        before = e.pipeline.corrected_image.copy()
        e.pipeline.correction.k1 = truth["camera"]["lens_k1"]
        assert not e.pipeline.corrected_is_current()
        e.ensure_loaded()
        assert e.pipeline.corrected_is_current() and not np.allclose(before, e.pipeline.corrected_image)
