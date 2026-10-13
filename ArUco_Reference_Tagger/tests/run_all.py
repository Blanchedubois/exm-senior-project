#!/usr/bin/env python3
"""Minimal runner for the headless suites (no pytest in the app's venv):
imports every tests/test_*.py and calls each test_* function.
    python tests/run_all.py [substring ...]"""
import importlib.util, os, sys, traceback, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
only = sys.argv[1:]
n_ok = n_fail = 0
for f in sorted(os.listdir(HERE)):
    if not (f.startswith("test_") and f.endswith(".py")):
        continue
    if only and not any(o in f for o in only):
        continue
    spec = importlib.util.spec_from_file_location(f[:-3], os.path.join(HERE, f))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    for name in dir(mod):
        if name.startswith("test_") and callable(getattr(mod, name)):
            t0 = time.time()
            try:
                getattr(mod, name)(); n_ok += 1
                print(f"  ok    {f}::{name}  ({time.time()-t0:.1f}s)")
            except Exception:
                n_fail += 1
                print(f"  FAIL  {f}::{name}"); traceback.print_exc()
print(f"\n{n_ok} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
