#!/usr/bin/env python3
"""
s1_gate.py — gate of spacing-workshop phase S1 (generator extensions + spec sheet).

  A  REGRESSION   the three Rev D prints rebuild BYTE-IDENTICAL (STL md5, records, ids)
  B  OPTIMISTIC   --design optimistic is the existing optimistic STL, byte for byte
  C  SPACING      --design medium / conservative: pitch exactly 6.0 / 7.0 um, same 23 um
                  tags and same dashes as optimistic, Phase-A gate PASS
  D  PER BOX      the 5 x 5 spectrum matrix builds: every box has its own size, pitch,
                  count and clearances (exact), no two features overlap, STL round-trips
  E  SPEC SHEET   sheets written for C and D re-read and agree with a render of the STL

Run:  python s1_gate.py        (work files in designs/_s1/, removed on success)
"""
from __future__ import annotations
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
V2 = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(V2, "workshop", "scripts"))
from aruco_grid import (GridConfig, SPACING_DESIGNS, OPT_DASH_KEEPOUT, build, stl_triangles, write_stl,     # noqa: E402
                        verify, verify_geometry, verify_boxes)
from w11_print_budget import overlaps                                                     # noqa: E402
import spec_sheet as SS                                                                   # noqa: E402
import spectrum_layout as SL                                                              # noqa: E402

WORK = os.path.join(V2, "designs", "_s1")
CAD = os.path.join(V2, "cad")
RES = []


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"    [{'PASS' if ok else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))


def run_cli(*args):
    r = subprocess.run([sys.executable, os.path.join(HERE, "aruco_grid.py"), *args, "--out", WORK],
                       capture_output=True, text=True)
    return r.returncode, r.stdout


def quiet_build(cfg):
    with contextlib.redirect_stdout(io.StringIO()):
        return build(cfg)


def main():
    os.makedirs(WORK, exist_ok=True)
    print("A  regression — Rev D prints")
    for v in ("optimistic", "hedge", "conservative"):
        rc, _ = run_cli("--variant", v)
        a, b = os.path.join(WORK, f"aruco_grid_{v}.stl"), os.path.join(CAD, f"aruco_grid_{v}.stl")
        same_rec = (json.load(open(a.replace(".stl", ".reference_tags.json")))["records"]
                    == json.load(open(b.replace(".stl", ".reference_tags.json")))["records"])
        same_ids = (json.load(open(a.replace(".stl", ".ids.json")))
                    == json.load(open(b.replace(".stl", ".ids.json"))))
        check(f"{v}: gate PASS, STL byte-identical, records and ids identical",
              rc == 0 and md5(a) == md5(b) and same_rec and same_ids, md5(a)[:12])

    print("B  --design optimistic == the existing optimistic print")
    rc, _ = run_cli("--design", "optimistic", "--name", "d_optimistic")
    check("byte-identical STL", rc == 0 and md5(os.path.join(WORK, "d_optimistic.stl"))
          == md5(os.path.join(CAD, "aruco_grid_optimistic.stl")))

    print("C  spacing given directly")
    for d, pitch, count in (("medium", 6.0, 11700), ("conservative", 7.0, 8000)):
        rc, out = run_cli("--design", d, "--name", f"d_{d}")
        vj = json.load(open(os.path.join(WORK, f"d_{d}.verify.json")))
        check(f"{d}: Phase-A gate PASS, pitch exactly {pitch}, {count:,} dots",
              rc == 0 and abs(vj["exact_pitch_um"] - pitch) < 1e-9 and vj["n_dots"] == count,
              f"pitch {vj['exact_pitch_um']:.9f}, dots {vj['n_dots']:,}")

    print("D  per-box dot size and spacing (the spectrum matrix)")
    cfg = GridConfig(tag_um=SL.TAG_UM, psf_fwhm_um=3.39, dot_pitch_override_um=7.0,
                     dash_keepout_um=OPT_DASH_KEEPOUT, box_specs=SL.box_specs(), variant="spectrum")
    rects, recs, info = quiet_build(cfg)
    okb, rows = verify_boxes(cfg, recs, info)
    sizes = sorted({round(r[2] - r[0], 6) for r in info["dot_rects"]})
    check("25 boxes, each with its own size / pitch / count / clearances (exact)", okb and len(rows) == 25,
          f"{sum(r['n'] for r in rows):,} dots")
    check("dot sizes are the five specified", sizes == sorted(SL.SIZES), str(sizes))
    top = {b["col"]: b for b in info["boxes"] if b["row"] == cfg.grid_n - 1}
    check("top row = the three designs (pitch 5.0 / 6.0 / 7.0, dot 2.125)",
          [top[c]["pitch_um"] for c in (0, 2, 4)] == [5.0, 6.0, 7.0]
          and all(top[c]["dot_um"] == 2.125 for c in top))
    check("no two features overlap", overlaps(rects) == 0)
    stl = os.path.join(WORK, "spectrum_test.stl")
    write_stl(stl, stl_triangles(rects, cfg.height_um))
    with contextlib.redirect_stdout(io.StringIO()):
        okv, stats = verify(stl, cfg, recs)
        gerr, _gs, _gp = verify_geometry(info["dot_rects"], recs)
    check("STL round-trip: every dot recovered, all 36 tags decode, extent 750", okv and gerr < 1e-9,
          f"{stats['n_dots']:,} dots, {stats['tags_decoded']}/36 tags")
    for b in sorted(info["boxes"], key=lambda b: (-b["row"], b["col"])):
        if b["col"] == 0:
            print("       ", end="")
        print(f"{b['dot_um']:.3f}/{b['pitch_um']:.3f}:{b['count']:>4}  ", end="\n" if b["col"] == 4 else "")

    print("E  spec sheets agree with their prints")
    mcfg = GridConfig(**SPACING_DESIGNS["medium"])
    _r, mrecs, minfo = quiet_build(mcfg)
    for nm, c, r, i, s in (("medium", mcfg, mrecs, minfo, os.path.join(WORK, "d_medium.stl")),
                           ("spectrum", cfg, recs, info, stl)):
        out = SS.write(os.path.join(WORK, f"sheet_{nm}"), nm, c, r, i,
                       labels=SL.LABELS if nm == "spectrum" else None)
        ok, checks = SS.verify_against_stl(out["spec"], out["features"], s)
        check(f"{nm}: sheet re-read and checked against the rendered STL", ok,
              "; ".join(k for k, v in checks.items() if not v))
    sp = json.load(open(os.path.join(WORK, "sheet_spectrum", "spec_sheet.json")))
    tl = next(b for b in sp["boxes"] if b["label"] == "OPTIMISTIC")
    br = next(b for b in sp["boxes"] if b["label"] == "SAFEST")
    check("spectrum sheet: OPTIMISTIC is top-left, SAFEST is bottom-right",
          tl["position"] == "top-left" and br["position"] == "bottom-right",
          f"box {tl['box']} / box {br['box']}")

    ok = all(v for _, v in RES)
    print(f"\n  S1 GATE: {'PASS' if ok else 'FAIL'}  ({sum(v for _, v in RES)}/{len(RES)})")
    if ok:
        keep = os.path.join(V2, "designs", "docs", "S1_gate.json")
        json.dump({"checks": RES, "spectrum_boxes": info["boxes"]}, open(keep, "w"), indent=1, default=float)
        shutil.rmtree(WORK)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
