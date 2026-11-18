"""
refwarp.detect
==============
Thin wrapper over the existing glyphtrack pipeline: run optics + deskew, detect
dots / dashes / glyphs, fit the box grid, read slots, and register (box numbers).
Returns everything the warp stage needs. No tagging here — that's the warp's job.
"""
from __future__ import annotations
from dataclasses import replace
import numpy as np


def load_classifier(path):
    from glyphtrack.classifier import GlyphClassifier
    return GlyphClassifier.load(path)


def detect(path, clf, correction=None, auto_deskew=True, manual=None):
    from gridtrack import io, correct
    from gridtrack.types import CorrectionParams
    from glyphtrack import lattice as lt, reader as gr, gridmodel as gm

    img = io.load_tiff(path)
    c = correction or CorrectionParams()
    if auto_deskew and not c.rotate_deg:
        base = correct.apply(img, replace(c, rotate_deg=0.0))
        c = replace(c, rotate_deg=gr.estimate_deskew(io.to_uint8(base), clf))
    u8 = io.to_uint8(correct.apply(img, c))

    dots = lt.detect_dots(u8)
    basis = lt.refine_basis(dots, lt.estimate_basis(dots))
    dashes = lt.detect_dashes(u8)
    grid = lt.fit_box_grid(basis, dashes)
    _crops, gpos = gr.detect_glyph_blobs(u8)              # every glyph-sized blob (digit/letter)
    _c, fit = gr.read_glyphs(u8, clf, grid)
    reads = gr.read_slots(u8, clf, fit)
    model = gm.build_grid_model(reads, fit, dots=dots,
                                manual=manual or {"numbers": [], "letters": []})
    return dict(u8=u8, dots=np.asarray(dots, float), basis=basis,
                dashes=np.asarray(dashes, float), glyphs=np.asarray(gpos, float),
                grid=grid, fit=fit, reads=reads, model=model, deskew=float(c.rotate_deg))
