"""Test 8: timings (set EXM_BENCH=1 to run). Targets on an M1: fast tier
< 150 ms, full tier < 5 s."""

import os
import time

import pytest

from exm_explorer import field, live, pipeline, scenario

pytestmark = pytest.mark.skipif(os.environ.get("EXM_BENCH") != "1", reason="set EXM_BENCH=1")


def test_report_timings(grid, capsys):
    sc = scenario.legacy_scenario()
    out = {}
    t = time.perf_counter(); field.solve(sc.sites, scenario.Solver()); out["navier solve"] = time.perf_counter() - t
    pipeline.run_fast(sc, grid, registration="truth")
    t = time.perf_counter(); pipeline.run_fast(sc, grid, registration="truth"); out["fast, all windows"] = time.perf_counter() - t
    t = time.perf_counter(); pipeline.run_faithful(sc, grid); out["faithful full"] = time.perf_counter() - t
    live.analysis_job(sc, "fast", focus_site=sc.sites[0], extrema={})
    ts = []
    for k in range(5):                                   # as while dragging
        sc.sites[0].cx += 2.0
        t = time.perf_counter()
        live.analysis_job(sc, "fast", focus_site=sc.sites[0], extrema={})
        ts.append(time.perf_counter() - t)
    out["live fast tier (median)"] = sorted(ts)[2]
    t = time.perf_counter(); live.analysis_job(sc, "full", focus_site=sc.sites[0], extrema={})
    out["live full tier"] = time.perf_counter() - t
    with capsys.disabled():
        for k, v in out.items():
            print(f"\n  {k:20s} {v * 1e3:8.0f} ms", end="")
        print()
