#!/usr/bin/env python3
"""
s5_gate.py — gate of spacing-workshop phase S5: does analyse_spectrum.py return the
KNOWN answer?

Synthetic images of the spectrum print through the Phase-B camera model (lens,
vignette, rotation, drift, 2 um warp, L2 noise, Stage-1 corrected) at three blurs
from an unexpanded reference, plus one expanded frame in which only part of the
print is in view. The script under test sees the image and the spec sheet only;
this gate holds the simulator's truth.

  per box     |recognised (script) - recognised (truth)| <= 0.05, every box in view
              (truth = dots given their CORRECT identity within 3 px / dots in view)
  one line    the design the script recommends == the design the truth recommends
  blur        measured blur within 15 % of the injected one
  expansion   within 1 % of the injected one; handedness -1

Run:  python s5_gate.py   -> designs/docs/S5_gate.json, designs/4_spectrum/example/
"""
from __future__ import annotations
import contextlib, io, json, os, sys, time
import numpy as np
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
V2 = os.path.normpath(os.path.join(HERE, ".."))
SPEC_DIR = os.path.join(V2, "designs", "4_spectrum")
sys.path.insert(0, HERE); sys.path.insert(0, SPEC_DIR)
sys.path.insert(0, os.path.normpath(os.path.join(V2, "..", "reference-warp-tagger")))
from aruco_grid import build                                                    # noqa: E402
from build_spectrum import spectrum_cfg                                         # noqa: E402
import simulate_v2 as V                                                         # noqa: E402
from phase_c_verify import stage1, truth, NOISE                                 # noqa: E402
import analyse_spectrum as AN                                                   # noqa: E402
from rwtag.aruco import Design                                                  # noqa: E402

CASES = [(1.9, 1.0), (2.7, 1.0), (3.4, 1.0), (3.1, 2.0)]


def main():
    t0 = time.time()
    cfg = spectrum_cfg()
    with contextlib.redirect_stdout(io.StringIO()):
        _r, recs, info = build(cfg)
    islands = info["islands"]
    dot_recs = [r for r in recs if r["category"] == "dot"]
    spec = json.load(open(os.path.join(SPEC_DIR, "spec_sheet.json")))
    design = Design.load(os.path.join(SPEC_DIR, "reference_tags.json"))
    sim = V.SimConfig(); sim.signal_exp = 0.0
    lobes = V.make_lobes(cfg.field_um, sim)
    band_um = abs(sim.lens_k1) * sim.fov_um / 2.0 * 1.4
    ex = os.path.join(SPEC_DIR, "example"); os.makedirs(ex, exist_ok=True)
    rng = np.random.default_rng(11)
    out, all_ok = [], True
    for k, (psf, lam) in enumerate(CASES):
        theta = 2.0 + 3.0 * k; drift = rng.uniform(-8, 8, 2)
        rects, _a, _b = V.place(islands, lam, sim, lobes, cfg.field_um, drift)
        lv = V.Level("S5", psf, NOISE["read_noise"], NOISE["full_well"], NOISE["background"])
        img = V.degrade(V.render_scene(rects, sim, theta), sim, lv, np.random.default_rng(50 + k), lam=None)
        u8 = stage1(img, sim)
        Td, okd, _ = truth(islands, "dot", lam, sim, cfg, lobes, theta, drift)
        tpx = {r["tag"]: Td[i] for i, r in enumerate(dot_recs)}
        res = AN.analyse(u8, spec, design, um_per_px=sim.um_per_px, edge_band_um=band_um)
        # truth, per box
        tb = {}
        for i, r in enumerate(dot_recs):
            b = tb.setdefault(r["meta"]["box"], [0, 0])
            if okd[i]:
                b[0] += 1
                xy = res["matched"].get(r["tag"])
                if xy is not None and np.hypot(xy[0] - Td[i][0], xy[1] - Td[i][1]) < 3.0:
                    b[1] += 1
        rows, worst = [], 0.0
        truth_boxes = []
        for b in res["boxes"]:
            n, c = tb[b["box"]]
            rt = c / n if n >= AN.MIN_IN_VIEW else float("nan")
            rs = b["recognised"]
            if rt == rt and rs == rs:
                worst = max(worst, abs(rs - rt))
            rows.append(dict(box=b["box"], dot=b["dot_um"], pitch=b["pitch_um"], in_view_script=b["in_view"],
                             in_view_truth=n, recognised_script=rs, recognised_truth=rt, merged=b["merged"],
                             blur=b["blur_um"], contrast=b["contrast"], scatter_px=b["scatter_px"]))
            truth_boxes.append(dict(b, recognised=rt))
        rec_t = AN.recommend(truth_boxes)
        # a false "correct" is impossible above; a false MATCH (script counts it, truth does not) shows as script > truth
        checks = {
            "per box |script - truth| <= 0.05": worst <= 0.05,
            "recommended design == truth's": res["recommended"] == rec_t["recommended"]
                                             and res["tightest_pitch_um"] == rec_t["tightest_pitch_um"],
            "blur within 15 %": abs(res["blur_um"] / psf - 1) <= 0.15,
            "expansion within 1 %": abs(res["expansion"] / lam - 1) <= 0.01,
            "handedness -1": res["handedness"] == -1,
        }
        ok = all(checks.values()); all_ok &= ok
        print(f"\n=== injected blur {psf} um, expansion {lam:g}x ===")
        print(AN.table(res))
        print(f"  truth says: {rec_t['verdict']}")
        print(f"  worst |script - truth| = {worst:.3f} · blur measured {res['blur_um']:.2f} (injected {psf}) · "
              f"expansion {res['expansion']:.4f}")
        for kk, v in checks.items():
            print(f"    [{'PASS' if v else 'FAIL'}] {kk}")
        stem = os.path.join(ex, f"synthetic_blur{psf:g}um_{lam:g}x")
        cv2.imwrite(stem + ".png", u8)
        AN.save(res, stem, f"synthetic, injected blur {psf} µm, {lam:g}×")
        out.append(dict(psf=psf, lam=lam, checks=checks, passed=ok, worst_diff=worst, blur_measured=res["blur_um"],
                        expansion=res["expansion"], recommended=res["recommended"], tightest=res["tightest_pitch_um"],
                        truth_recommended=rec_t["recommended"], verdict=res["verdict"], boxes=rows,
                        tags_decoded=res["tags_decoded"]))
    with open(os.path.join(V2, "designs", "docs", "S5_gate.json"), "w") as f:
        json.dump(out, f, indent=1, default=float)
    print(f"\n  S5 ANALYSIS GATE: {'PASS' if all_ok else 'FAIL'}   ({time.time()-t0:.0f} s)")
    raise SystemExit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
