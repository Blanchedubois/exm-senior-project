"""
Headless tests for rwtag.pairing (Phase B). No Qt.
"""
from __future__ import annotations
import os
import sys
import csv
import glob
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rwtag import pairing as PR

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODEL = os.path.join(_ROOT, "reference", "glyph_knn.yml")
_STITCHED = os.path.join(_ROOT, "Stitched Images")


def test_pair_tags_join():
    t0 = {"dot|B1|0_0": (10.0, 20.0), "dot|B1|1_0": (30.0, 20.0),
          "dash|V0|3": (5.0, 50.0), "num|B1|center|0": (25.0, 25.0)}
    t1 = {"dot|B1|0_0": (15.0, 28.0), "dash|V0|3": (7.0, 70.0),
          "dot|B9|4_4": (99.0, 99.0)}
    pairs = PR.pair_tags(t0, t1)
    assert set(pairs) == {"dot|B1|0_0", "dash|V0|3"}
    assert pairs["dot|B1|0_0"] == (10.0, 20.0, 15.0, 28.0)      # (init, exp) order
    only_dots = PR.pair_tags(t0, t1, kinds=("dot",))
    assert set(only_dots) == {"dot|B1|0_0"}
    c = PR.pair_counts(t0, t1, pairs)
    assert c["n_pairs"] == 2 and c["n_dot_pairs"] == 1
    assert c["n_dot_init"] == 2 and c["n_dot_exp"] == 2
    assert abs(c["dot_pair_frac"] - 0.5) < 1e-9


def test_pairs_xy_and_csv():
    pairs = {"dot|B1|0_0": (1.0, 2.0, 3.0, 4.0), "dash|V0|1": (9.0, 9.0, 9.0, 9.0)}
    P0, P1, tags = PR.pairs_xy(pairs, kinds=("dot",))
    assert P0.shape == (1, 2) and list(P0[0]) == [1.0, 2.0] and list(P1[0]) == [3.0, 4.0]
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "pairs.csv")
        PR.write_pairs_csv(pairs, p, 1.5, 2.0)
        rows = list(csv.reader(open(p)))
    assert rows[0][0].startswith("#")
    assert rows[1] == ["tag", "category", "x_init_px", "y_init_px", "x_exp_px", "y_exp_px"]
    assert len(rows) == 2 + len(pairs)


def test_kabsch_ignores_uniform_scale():
    import numpy as np
    rng = np.random.default_rng(0)
    P0 = rng.random((200, 2)) * 500 - 250                 # centred target
    th = np.radians(7.0)
    R_true = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    P1 = (P0 @ R_true.T) * 1.8                            # rotated + uniformly scaled
    R = PR.kabsch_rotation(P1, P0)                        # move P1 onto P0
    ang = np.degrees(np.arctan2(R[1, 0], R[0, 0]))
    assert abs(ang + 7.0) < 0.05, ang                      # undoes the rotation
    assert abs(np.linalg.det(R) - 1.0) < 1e-9              # pure rotation, no scale


def test_rigid_align_centers_and_orients():
    import numpy as np
    rng = np.random.default_rng(1)
    c0 = np.array([300.0, 200.0]); c1 = np.array([900.0, 700.0])
    th = np.radians(-5.0)
    Rt = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    base = rng.random((150, 2)) * 400 - 200
    P0 = base + c0
    P1 = (base * 2.0) @ Rt.T + c1                          # scaled 2x, rotated, moved
    pairs = {f"dot|B7|{i}_0": (P0[i, 0], P0[i, 1], P1[i, 0], P1[i, 1])
             for i in range(len(base))}
    a = PR.rigid_align(pairs, 7, c0, c1)
    assert a["ok"] and abs(a["angle_deg"] - 5.0) < 0.1     # undoes the -5 deg
    # the common box centre must map exactly onto the initial centre
    c1_mapped = PR.apply_rigid([c1], a)[0]
    assert np.hypot(*(c1_mapped - c0)) < 1e-9
    # scale untouched: a point 200px from c1 maps ~400px... no — expanded stays 2x:
    p = PR.apply_rigid([c1 + Rt @ np.array([100.0, 0.0]) * 2.0], a)[0]
    assert abs(np.hypot(*(p - c0)) - 200.0) < 1.0          # 2x distance preserved


def test_overlay_composite_geometry():
    import numpy as np
    img0 = np.full((100, 120), 200, np.uint8)
    img1 = np.full((150, 160), 100, np.uint8)
    a = {"ok": True, "R": np.eye(2), "t": np.array([-20.0, -30.0]),
         "c_init": np.array([0.0, 0.0]), "c_exp": np.array([0.0, 0.0]), "box": 1}
    rgb, origin = PR.overlay_composite(img0, img1, a)
    assert origin[0] == -20 and origin[1] == -30           # canvas grows to hold both
    assert rgb.shape[0] >= 130 and rgb.shape[1] >= 140
    ox, oy = int(-origin[0]), int(-origin[1])
    assert rgb[oy + 50, ox + 60, 1] == 200 and rgb[oy + 50, ox + 60, 2] == 200  # cyan init
    assert rgb[10, 10, 0] == 100                            # red expanded at its offset


def test_displacement_field_uniform_expansion():
    """Pure λ=1.5 expansion about a centre: |u| must grow as (λ-1)·r and the
    local linear expansion must recover λ everywhere."""
    import numpy as np
    rng = np.random.default_rng(2)
    c = np.array([500.0, 500.0])
    P0 = rng.random((300, 2)) * 900 + 50
    P1 = c + 1.5 * (P0 - c)                              # uniform expansion about c
    pairs = {f"dot|B13|{i}_0": (P0[i, 0], P0[i, 1], P1[i, 0], P1[i, 1])
             for i in range(len(P0))}
    a = PR.rigid_align(pairs, 13, c, c)
    f = PR.displacement_field(pairs, a)
    st = PR.field_stats(f)
    assert abs(st["lin_median"] - 1.5) < 0.01, st
    r = np.hypot(*(f["P0"] - c).T)
    expect = 0.5 * r
    err = np.abs(f["umag"] - expect)
    assert np.median(err) < 1.0, np.median(err)          # |u| = (λ-1)·r


def test_field_csv_and_heat_grid():
    import numpy as np
    rng = np.random.default_rng(3)
    P0 = rng.random((60, 2)) * 400
    P1 = P0 * 1.2
    pairs = {f"dot|B1|{i}_0": (P0[i, 0], P0[i, 1], P1[i, 0], P1[i, 1])
             for i in range(len(P0))}
    a = PR.rigid_align(pairs, 1, [0, 0], [0, 0])
    f = PR.displacement_field(pairs, a)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "field.csv")
        PR.write_field_csv(f, p, 1.5, 2.0, a)
        rows = list(csv.reader(open(p)))
    assert rows[1][0] == "tag" and len(rows[1]) == 11
    assert len(rows) == 2 + len(f["tags"])
    grid, (gw, gh) = PR.heat_grid(f["P0"], f["lin"], (400, 400))
    assert (gw, gh) == (400, 400)
    assert np.isfinite(grid).any(), "heat grid empty"
    inside = grid[np.isfinite(grid)]
    assert abs(np.median(inside) - 1.2) < 0.05           # interpolates the true value


def test_expansion_rows_and_summary_csv():
    import numpy as np
    rng = np.random.default_rng(4)
    P0 = rng.random((200, 2)) * 800
    t0 = {f"dot|B5|{i}_0": tuple(P0[i]) for i in range(len(P0))}
    t2 = {f"dot|B5|{i}_0": tuple(P0[i] * (2.0 / 1.5)) for i in range(len(P0))}
    expanded = [("2x_frame", 2.0, t2), ("3x_frame", 3.0, None)]     # one rejected
    rows = PR.expansion_rows(t0, 1.5, expanded)
    assert len(rows) == 2
    ok = rows[0]
    assert abs(ok["expected"] - 2.0 / 1.5) < 1e-9
    assert abs(ok["measured"] - 2.0 / 1.5) < 0.01, ok["measured"]
    assert ok["pair_frac"] > 0.99
    bad = rows[1]
    assert bad["status"] == "untagged/rejected" and not np.isfinite(bad["measured"])
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "s.csv")
        PR.write_summary_csv(rows, p, 1.5, "init.tif")
        r = list(csv.reader(open(p)))
    assert r[1][:4] == ["image", "expected_x_absolute", "expected_vs_initial",
                        "measured_vs_initial"]
    assert len(r) == 2 + len(rows)
    assert r[3][3] == "" and r[3][9] == "untagged/rejected"          # rejected row honest


def test_heat_grid_masks_unpaired_voids():
    """Two dense clusters far apart: the convex hull bridges the gap, but the
    mask must NaN the bridge — heat only near actual paired dots."""
    import numpy as np
    rng = np.random.default_rng(7)
    left = rng.random((80, 2)) * 150 + 25            # cluster around x~25..175
    right = rng.random((80, 2)) * 150 + [625, 25]    # cluster around x~625..775
    P0 = np.vstack([left, right])
    vals = np.full(len(P0), 1.5)
    grid, (gw, gh) = PR.heat_grid(P0, vals, (200, 800), step=10)
    xs = np.arange(5, 800, 10)
    mid = np.argmin(np.abs(xs - 400))                # dead centre of the void
    inl = np.argmin(np.abs(xs - 100))                # inside the left cluster
    col_mid = grid[:, mid]; col_in = grid[:, inl]
    assert not np.isfinite(col_mid).any(), "void between clusters must be masked"
    assert np.isfinite(col_in).any(), "cluster interior must be filled"


def test_similarity_residuals_pure_and_warped():
    import numpy as np
    rng = np.random.default_rng(5)
    P0 = rng.random((400, 2)) * 1000
    th = np.radians(9.0)
    R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    P1 = 1.6 * (P0 @ R.T) + [50.0, -30.0]                # pure similarity
    pairs = {f"dot|B1|{i}_0": (*P0[i], *P1[i]) for i in range(len(P0))}
    sim = PR.similarity_residuals(pairs)
    assert abs(sim["scale"] - 1.6) < 1e-6
    assert abs(sim["angle_deg"] - 9.0) < 1e-6
    assert sim["rms"] < 1e-9, "pure similarity must leave zero residual"
    # inject a known warp on top -> residual distribution reflects it
    warp = 6.0 * np.column_stack([np.sin(P0[:, 0] / 90.0), np.cos(P0[:, 1] / 110.0)])
    pairs2 = {f"dot|B1|{i}_0": (*P0[i], *(P1[i] + warp[i])) for i in range(len(P0))}
    sim2 = PR.similarity_residuals(pairs2)
    assert 3.0 < np.median(sim2["resid"]) < 9.0, np.median(sim2["resid"])


def test_expansion_distributions_and_csv():
    import numpy as np
    rng = np.random.default_rng(6)
    P0 = rng.random((150, 2)) * 700
    t0 = {f"dot|B2|{i}_0": tuple(P0[i]) for i in range(len(P0))}
    t2 = {f"dot|B2|{i}_0": tuple(P0[i] * (2.0 / 1.5)) for i in range(len(P0))}
    dists = PR.expansion_distributions(t0, 1.5, [("2x", 2.0, t2), ("3x", 3.0, None)])
    assert len(dists) == 1                                # untagged image skipped
    d = dists[0]
    assert abs(np.median(d["lin"]) - 2.0 / 1.5) < 0.01
    assert abs(d["sim_scale"] - 2.0 / 1.5) < 1e-6
    assert d["rms"] < 1e-9
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "d.csv")
        PR.write_distributions_csv(dists, p, 1.5)
        rows = list(csv.reader(open(p)))
    assert rows[1] == ["image_label", "expected_vs_initial",
                       "local_linear_expansion", "warp_residual_px"]
    assert len(rows) >= 2 + len(d["resid"])


def test_real_two_frame_pairing():
    f15 = sorted(glob.glob(os.path.join(_STITCHED, "1.5X*.tif")))
    f20 = sorted(glob.glob(os.path.join(_STITCHED, "2.0X*.tif")))
    if not (f15 and f20) or not os.path.exists(_MODEL):
        print("  SKIP  test_real_two_frame_pairing (no data/model)"); return
    from rwtag import project as P
    from rwtag.glyph import detect as D
    clf = D.load_classifier(_MODEL)
    e0 = P.ImageEntry(path=f15[0], label=1.5)
    e1 = P.ImageEntry(path=f20[0], label=2.0)
    ok0, _ = P.run_stages(e0, clf)
    ok1, _ = P.run_stages(e1, clf)
    assert ok0 and ok1
    pairs = PR.pair_tags(e0.pipeline.tagging.tags, e1.pipeline.tagging.tags)
    c = PR.pair_counts(e0.pipeline.tagging.tags, e1.pipeline.tagging.tags, pairs)
    assert c["n_dot_pairs"] > 800, c
    assert c["dot_pair_frac"] > 0.5, c
    print(f"  info  1.5x↔2.0x: {c['n_pairs']} pairs, {c['n_dot_pairs']} dots "
          f"({c['dot_pair_frac']:.0%})")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fails = 0
    for fn in fns:
        try:
            fn(); print(f"  PASS  {fn.__name__}")
        except AssertionError as e:
            fails += 1; print(f"  FAIL  {fn.__name__}: {e}")
        except Exception as e:
            fails += 1; print(f"  ERR   {fn.__name__}: {e!r}")
    print(f"\n{len(fns) - fails}/{len(fns)} passed")
    sys.exit(1 if fails else 0)
