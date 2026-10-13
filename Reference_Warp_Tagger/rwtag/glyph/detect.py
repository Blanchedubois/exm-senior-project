"""
rwtag.glyph.detect
==================
Stage-2 orchestration over the headless glyphtrack modules, adapted from the old
`refwarp.detect` to run on the Stage-1 CORRECTED image (not to re-load/re-correct)
and split into the three steps the GUI drives independently:

    detect_grid(u8)            steps 1-4: dots -> lattice -> dashes -> box grid
    read(u8, clf, grid)        steps 5-7: glyph blobs -> fiducial fit -> slot OCR
    solve(reads, fit, dots)    step 8:    club -> vote -> register -> auto-complete

`detect(...)` runs all three for headless/test use. Everything is numpy/OpenCV.
"""
from __future__ import annotations
import numpy as np

from . import lattice as lt, reader as gr, gridmodel as gm
from .types import DetectResult


def load_classifier(path):
    from .classifier import GlyphClassifier
    return GlyphClassifier.load(path)


def to_u8(img):
    """Accept either an already-8-bit array or a Stage-1 float image and return
    a uint8 view (percentile-stretched), reusing rwtag.io so behaviour matches."""
    from rwtag import io
    a = np.asarray(img)
    if a.dtype == np.uint8:
        return a
    return io.to_uint8(a)


# --------------------------------------------------------------- step 1-4: grid
def detect_grid(u8, dot_area=(30, 220), tophat=15) -> dict:
    """Dots -> refined lattice basis -> boundary dashes -> dash-locked box grid.
    Returns the geometry dict; raises ValueError if too few dots to fit."""
    dots = lt.detect_dots(u8, tophat=tophat, dot_area=dot_area)
    if len(dots) < 30:
        raise ValueError(f"only {len(dots)} dots found — adjust dot size / top-hat")
    basis = lt.refine_basis(dots, lt.estimate_basis(dots))
    dashes = lt.detect_dashes(u8)
    grid = lt.fit_box_grid(basis, dashes)
    on_grid, ndrop = lt.dashes_on_grid(dashes, grid)
    return dict(dots=np.asarray(dots, float), basis=basis,
                dashes_all=np.asarray(dashes, float),
                dashes_on_grid=np.asarray(on_grid, float),
                grid=grid, n_dashes_dropped=int(ndrop))


# --------------------------------------------------------------- step 5-7: read
def read(u8, clf, grid) -> dict:
    """Detect glyph blobs, fit the fiducial lattice, OCR the glyphs sitting at
    slots. Returns glyphs / fit / reads / glyph_h (fit None if too few glyphs)."""
    crops, gpos = gr.detect_glyph_blobs(u8)
    glyph_h = float(np.median([c.shape[0] for c in crops]) / 1.4) if crops else 30.0
    _recs, fit = gr.read_glyphs(u8, clf, grid)
    reads = gr.read_slots(u8, clf, fit) if fit is not None else []
    return dict(glyphs=np.asarray(gpos, float), fit=fit, reads=reads, glyph_h=glyph_h)


# ------------------------------------------------------------- step 8: solve
def solve(reads, fit, dots, manual=None, thresh_frac=0.35) -> dict:
    """Club digits -> vote boxes -> register orientation+offset (numbering rule)
    -> auto-complete every slot. Returns the grid model (registered or not)."""
    return gm.build_grid_model(reads, fit, thresh_frac=thresh_frac, dots=dots,
                               manual=manual or {"numbers": [], "letters": []})


def estimate_deskew(u8, clf) -> float:
    """Rotation (deg) that makes the glyphs upright — wires the Stage-1 Auto-deskew
    button. Dot lattice gives the tilt mod 90°; the correct quadrant is chosen by
    glyph-recognition confidence."""
    return float(gr.estimate_deskew(u8, clf))


# --------------------------------------------------------------- full pipeline
def detect(img, clf, manual=None, dot_area=(30, 220), tophat=15,
           thresh_frac=0.35) -> DetectResult:
    """Run steps 1-8 on a Stage-1 corrected (or 8-bit) image and return a full
    DetectResult. Headless / tests use this; the GUI drives the three steps."""
    u8 = to_u8(img)
    g = detect_grid(u8, dot_area=dot_area, tophat=tophat)
    r = read(u8, clf, g["grid"])
    model = solve(r["reads"], r["fit"], g["dots"], manual=manual,
                  thresh_frac=thresh_frac) if r["fit"] is not None else None
    stage = "solved" if model is not None else ("read" if r["reads"] else "grid")
    return DetectResult(
        u8=u8, dots=g["dots"], basis=g["basis"], dashes_all=g["dashes_all"],
        dashes_on_grid=g["dashes_on_grid"], glyphs=r["glyphs"], grid=g["grid"],
        fit=r["fit"], reads=r["reads"], model=model, glyph_h=r["glyph_h"],
        n_dashes_dropped=g["n_dashes_dropped"], stage=stage)
