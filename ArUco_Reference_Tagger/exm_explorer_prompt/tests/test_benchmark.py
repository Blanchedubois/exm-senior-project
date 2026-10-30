"""Test 8: timings (set EXM_BENCH=1 to run). Milestone 5 adds the live tier."""

import os
import time

import pytest

from exm_explorer import field, pipeline, scenario

pytestmark = pytest.mark.skipif(os.environ.get("EXM_BENCH") != "1", reason="set EXM_BENCH=1")


def test_report_timings(grid, capsys):
    sc = scenario.legacy_scenario()
    out = {}
    t = time.perf_counter(); field.solve(sc.sites, scenario.Solver()); out["navier solve"] = time.perf_counter() - t
    pipeline.run_fast(sc, grid, registration="truth")
    t = time.perf_counter(); pipeline.run_fast(sc, grid, registration="truth"); out["fast, all windows"] = time.perf_counter() - t
    t = time.perf_counter(); pipeline.run_faithful(sc, grid); out["faithful full"] = time.perf_counter() - t
    with capsys.disabled():
        for k, v in out.items():
            print(f"\n  {k:20s} {v * 1e3:8.0f} ms", end="")
        print()
