"""
Headless tests for rwtag.aruco (V2 Stage 2). No Qt.

The synthetic end-to-end tests need the aruco-marker-design generator + simulator
(sibling folder); they are skipped when it is absent.
"""
from __future__ import annotations
import contextlib
import io
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rwtag.aruco import ArucoParams, Design, detect, fit_affine, series as AS
from rwtag.aruco.detect import tag_handedness, refine_gauss
from rwtag.refwarp import warp as W, tagmatch, tagframe as TF

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_V2 = os.path.normpath(os.path.join(_ROOT, "..", "aruco-marker-design", "tools"))
_HAVE_V2 = os.path.exists(os.path.join(_V2, "simulate_v2.py"))


# ------------------------------------------------------------------ helpers
def _toy_design(n=3, box=145.0, tag=23.0, pitch=5.0):
    recs = []
    for j in range(n):
        for i in range(n):
            recs.append(dict(tag=f"aruco|N{i}_{j}|{10 + i + n * j}", category="aruco",
                             x_um=tag / 2 + i * box, y_um=tag / 2 + j * box,
                             meta=dict(aruco_id=10 + i + n * j, size_um=tag, node_i=i, node_j=j)))
    return Design(records=recs, box_um=box, origin_um=tag / 2, dot_pitch_um=pitch,
                  dot_side_um=2.125, tag_um=tag, dict_name="DICT_4X4_50", grid_n=n - 1)


def _rigid_tags(design, lam, theta_deg, scale, t, sign=-1.0):
    """Image tags under expansion lam: CENTRES scale by lam, CORNERS keep the
    printed size (rigid islands); y flipped when sign < 0."""
    th = np.radians(theta_deg)
    R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    F = np.diag([1.0, sign])
    out = {}
    for r in design.tag_records():
        c = np.array([r["x_um"], r["y_um"]])
        ic = (R @ F @ (lam * c)) * scale + t
        dc = design.design_corners(r) - c                     # rigid, printed size
        out[int(r["meta"]["aruco_id"])] = {"centre": ic, "corners": (dc @ (R @ F).T) * scale + ic}
    return out


# ------------------------------------------------------------------ unit
def test_handedness_and_affine_from_centres():
    d = _toy_design()
    for sign in (-1.0, 1.0):
        tags = _rigid_tags(d, lam=2.5, theta_deg=7.0, scale=1.9, t=np.array([300.0, 250.0]), sign=sign)
        s, agree, tot = tag_handedness(d, tags)
        assert s == sign and agree == tot == 9
        A, info = fit_affine(d, tags, ArucoParams())
        assert info["method"] == "affine(centres)" and info["sign"] == sign
        # the affine must map CENTRES exactly (corners are rigid and are not affine images)
        src = np.array([[r["x_um"], r["y_um"]] for r in d.tag_records()])
        pred = src @ A[:, :2].T + A[:, 2]
        assert np.allclose(pred, [tags[int(r["meta"]["aruco_id"])]["centre"] for r in d.tag_records()], atol=1e-6)
        assert abs(info["scale_px_per_um"] - 2.5 * 1.9) < 1e-6


def test_two_and_one_tag_paths():
    d = _toy_design()
    full = _rigid_tags(d, lam=3.0, theta_deg=-4.0, scale=1.96, t=np.array([500.0, 400.0]))
    ids = sorted(full)
    # two tags -> similarity through the centres, rotation from the corners
    A2, i2 = fit_affine(d, {k: full[k] for k in ids[:2]}, ArucoParams())
    assert i2["method"] == "similarity(centres)"
    src = np.array([[r["x_um"], r["y_um"]] for r in d.tag_records()])
    truth = np.array([full[int(r["meta"]["aruco_id"])]["centre"] for r in d.tag_records()])
    assert np.abs(src @ A2[:, :2].T + A2[:, 2] - truth).max() < 1e-6
    # one tag: scale must come from the dot lattice (the tag is rigid)
    p = 5.0 * 3.0 * 1.96                                     # px dot pitch at lambda = 3
    th = np.radians(-4.0); R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    g = np.array([[i, j] for i in range(-10, 11) for j in range(-10, 11)], float) * p
    dots = g @ R.T + np.array([900.0, 700.0])
    A1, i1 = fit_affine(d, {ids[0]: full[ids[0]]}, ArucoParams(), dots=dots)
    assert i1["scale_from_dots"] and i1["sign"] == -1
    assert np.abs(src @ A1[:, :2].T + A1[:, 2] - truth).max() < 2.0     # lattice pitch is a median
    # one tag, no dots -> print scale, flagged
    A0, i0 = fit_affine(d, {ids[0]: full[ids[0]]}, ArucoParams())
    assert "PRINT scale" in i0["method"] and abs(i0["scale_px_per_um"] - 1.96) < 1e-6


def test_coarse_map_reproduces_affine():
    """fit = {O, U, V, box_um} built as detect() builds it must make
    warp.coarse_map equal the affine under the identity registration."""
    A = np.array([[1.7, 0.2, 310.0], [0.1, -1.8, 900.0]])
    box = 145.4
    fit = {"O": A[:, 2], "U": A[:, :2] @ [box, 0], "V": A[:, :2] @ [0, box], "box_um": box}
    um = np.array([[0.0, 0.0], [750.0, 0.0], [12.3, 456.7], [700.0, 700.0]])
    got = W.coarse_map(um, fit, {"orient": (0, 1, 1, 1), "offset": (0, 0)})
    assert np.allclose(got, um @ A[:, :2].T + A[:, 2])


def test_tagmatch_aruco_by_id():
    d = _toy_design()
    recs = d.records + [dict(tag="dot|B1|0_0", category="dot", x_um=30.0, y_um=30.0, meta={})]
    H = np.array([[2.0, 0, 5.0], [0, -2.0, 400.0], [0, 0, 1.0]])
    view = {"basis": {"pitch": 10.0}, "dots": np.array([[65.0, 340.0]]), "dashes": None,
            "glyphs": None, "aruco": {10: (11.0, 22.0), 99: (1.0, 1.0)}}
    res = tagmatch.tag_image(view, H, recs)
    assert res["tag_xy"]["aruco|N0_0|10"] == (11.0, 22.0)
    assert not any(t.endswith("|99") for t in res["tag_xy"])
    assert "dot|B1|0_0" in res["tag_xy"]


def test_refine_gauss_recovers_subpixel_centre():
    rng = np.random.default_rng(1)
    img = np.full((41, 41), 10.0)
    yy, xx = np.mgrid[0:41, 0:41]
    cx, cy, s = 20.37, 19.71, 2.6
    img += 180 * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * s * s))
    img = np.clip(img + rng.normal(0, 3, img.shape), 0, 255).astype(np.uint8)
    out = refine_gauss(img, np.array([[20.0, 20.0]]), s)
    assert np.hypot(out[0, 0] - cx, out[0, 1] - cy) < 0.15


# ------------------------------------------------------------------ end to end
def _synthetic_series(lams=(1.0, 2.0, 4.0)):
    sys.path.insert(0, _V2)
    from dataclasses import asdict
    from aruco_grid import GridConfig, VARIANTS, build
    import simulate_v2 as V
    v = VARIANTS["optimistic"]
    gcfg = GridConfig(dict_name="DICT_4X4_50", tag_modules=6, tag_um=v["tag_um"],
                      psf_fwhm_um=v["psf_fwhm_um"], dot_side_um=2.125, dashes=True,
                      round_tags=True, fit="inside", field_um=750.0)
    with contextlib.redirect_stdout(io.StringIO()):
        _r, recs, info = build(gcfg)
    design = Design.from_dict({"box_um": gcfg.box_pitch, "grid_n": gcfg.grid_n,
                               "dot_pitch": gcfg.dot_pitch_um, "dot_side_um": 2.125,
                               "config": asdict(gcfg), "records": recs})
    sim = V.SimConfig(); sim.signal_exp = 0.0
    lobes = V.make_lobes(gcfg.field_um, sim)
    lv = V.Level("t", gcfg.psf_fwhm_um, 6.0, 240.0, 14.0)
    band = abs(sim.lens_k1) * sim.fov_um / 2.0 * 1.4
    params = ArucoParams(um_per_px=sim.um_per_px, psf_fwhm_um=gcfg.psf_fwhm_um, edge_band_um=band)
    frames, truths = [], {}
    rng = np.random.default_rng(3)
    for k, lam in enumerate(lams):
        drift = rng.uniform(-8, 8, 2); theta = 2.0 + 3.0 * k
        rects, _tc, _tid = V.place(info["islands"], lam, sim, lobes, gcfg.field_um, drift)
        img = V.degrade(V.render_scene(rects, sim, theta), sim, lv, np.random.default_rng(k), lam=None)
        und = V._radial(img, sim.lens_k1, sim.lens_k2, sim.fov_px / 2.0, inverse=True)
        u8 = np.clip(und.astype(np.float32) / np.clip(V._vignette(und.shape, sim), 0.1, 1), 0, 255).astype(np.uint8)
        frames.append((lam, u8))
        # truth dots in the un-distorted frame
        rfov = sim.fov_um * sim.render_margin
        C = np.array([[i["cx"], i["cy"]] for i in info["islands"] if i["kind"] == "dot"])
        P0 = np.array([375.0, 375.0]); centre = np.array([rfov / 2, rfov / 2]) + drift
        Cd = centre + lam * (C - P0) + V.warp_disp(C, lobes, sim.warp_sigma_um) * lam
        import cv2
        M = cv2.getRotationMatrix2D((rfov / 2, rfov / 2), theta, 1.0)
        R = np.column_stack([Cd[:, 0], rfov - Cd[:, 1]]) @ M[:, :2].T + M[:, 2]
        lo = (rfov - sim.fov_um) / 2
        px = (R - lo) / sim.um_per_px - 0.5
        truths[lam] = {r["tag"]: px[i] for i, r in enumerate(r for r in recs if r["category"] == "dot")}
    return design, params, frames, truths


def test_synthetic_end_to_end():
    if not _HAVE_V2:
        print("  skip: aruco-marker-design not found"); return
    design, params, frames, truths = _synthetic_series()
    out = AS.process_frames(frames, design, params)
    for f in out:
        assert f.ok, (f.label, f.reason)
        assert f.det.model["sign"] == -1.0, "design y-up -> image y-down must be a reflection"
        tr = truths[f.label]
        dots = [(t, xy) for t, xy in f.tags.items() if t.startswith("dot|")]
        err = np.array([np.hypot(*(np.array(xy) - tr[t])) for t, xy in dots])
        assert (err < 3.0).mean() >= 0.99, (f.label, (err < 3.0).mean())
        assert np.sqrt(np.mean(err[err < 3.0] ** 2)) < 0.5
        assert any(t.startswith("aruco|") for t in f.tags)
    assert out[0].source == "baseline" and all(f.source == "direct" for f in out[1:])
    print(f"  info  {[(f.label, f.n_tags) for f in out]}")


def test_mirrored_frame_is_rejected_by_series():
    """A mirrored frame must never enter pairing. ArUco dictionaries are not
    mirror-symmetric, so a flipped frame normally decodes NO tag and is rejected
    as unregistered; if some id did decode, the corner-order handedness check
    rejects it instead. Either reason is acceptable, acceptance is not."""
    if not _HAVE_V2:
        print("  skip: aruco-marker-design not found"); return
    design, params, frames, _ = _synthetic_series(lams=(1.0, 2.0))
    lam2, u8 = frames[1]
    out = AS.process_frames([frames[0], (lam2, u8[:, ::-1].copy())], design, params)
    assert out[0].ok and not out[1].ok, out[1].reason
    assert "handedness" in out[1].reason or "no ArUco tag" in out[1].reason, out[1].reason


def test_series_sign_gate():
    """The handedness gate itself: a frame whose fit sign differs from the
    baseline's is rejected with a handedness reason (exercised by faking the
    second frame's design as y-mirrored)."""
    if not _HAVE_V2:
        print("  skip: aruco-marker-design not found"); return
    design, params, frames, _ = _synthetic_series(lams=(1.0, 2.0))
    real = AS.detect                                      # the name series.py calls
    calls = {"n": 0}

    def flipped_detect(img, d, p=None, dict_name=None):
        det = real(img, d, p, dict_name)
        calls["n"] += 1
        if calls["n"] == 2 and det.model.get("registered"):
            det.model["sign"] = -det.model["sign"]           # pretend the fit came out proper
        return det
    AS.detect = flipped_detect
    try:
        out = AS.process_frames(frames, design, params)
    finally:
        AS.detect = real
    assert out[0].ok and not out[1].ok and "handedness" in out[1].reason, out[1].reason
