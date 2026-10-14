"""Shared helpers for tests that read the dummy series (not a test module)."""
from __future__ import annotations
import csv
import json
import os
import sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from rwtag import io, correct as C                                    # noqa: E402
from rwtag.types import CorrectionParams, LevelsParams                # noqa: E402

DUMMY = os.path.normpath(os.path.join(ROOT, "..", "ArUco_Tracker_V2", "dummy"))
DESIGNS = os.path.join(ROOT, "designs")
DESIGN_DIR = {"optimistic": "1_optimistic", "medium": "2_medium", "conservative": "3_conservative",
              "spectrum": "4_spectrum"}


def run(design, name):
    """(folder, truth) or (None, None) with a skip note."""
    d = os.path.join(DUMMY, design, name)
    if not os.path.exists(os.path.join(d, "truth.json")):
        print(f"  skip: dummy run {design}/{name} not generated"); return None, None
    with open(os.path.join(d, "truth.json")) as f:
        return d, json.load(f)


def frame(truth, lam):
    return [f for f in truth["frames"] if abs(f["label"] - lam) < 1e-9][0]


def stage1(truth, rotate=0.0):
    """Stage-1 params that exactly undo the dummy camera's lens and vignette."""
    cam = truth["camera"]
    return CorrectionParams(k1=cam["lens_k1"], k2=cam["lens_k2"], vig_strength=cam["vignette_strength"],
                            vig_power=cam["vignette_power"], rotate_deg=rotate)


def load(d, fr, seed=0):
    return io.load_tiff(os.path.join(d, fr["files"][seed] + ".ome.tif"))


def corrected(raw, p):
    return C.process(raw, p, LevelsParams())


def truth_features(d, fr, category="dot"):
    """(tags list, raw px (N,2), box (N,)) for one category."""
    with open(os.path.join(d, fr["truth_csv"])) as f:
        rows = [r for r in csv.DictReader(f) if r["category"] == category]
    raw = np.array([[float(r["x_raw"]), float(r["y_raw"])] for r in rows])
    box = np.array([int(r["box"]) if r["box"] else 0 for r in rows])
    return [r["tag"] for r in rows], raw, box


def detectable(raw_xy, shape, margin):
    """Truth points whose raw position lies at least `margin` px inside the frame."""
    H, W = shape[:2]
    return ((raw_xy[:, 0] >= margin) & (raw_xy[:, 0] <= W - 1 - margin) &
            (raw_xy[:, 1] >= margin) & (raw_xy[:, 1] <= H - 1 - margin))
