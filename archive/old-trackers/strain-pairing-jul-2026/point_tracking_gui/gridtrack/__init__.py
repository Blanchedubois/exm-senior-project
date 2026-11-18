"""
gridtrack -- headless image-processing core for the point-tracking GUI.

No GUI toolkit is imported anywhere in this package: every function takes NumPy
arrays + parameter dataclasses and returns arrays + dataclasses, so the same
processing is reusable in other GUIs, batch scripts, and tests.

Stage 1-5 (implemented): io, correct, address, reference, measure, correspond, filters, types.
"""
from . import types, io, correct, address, reference, correspond, measure, filters  # noqa: F401

__all__ = ["types", "io", "correct", "address", "reference", "correspond",
           "measure", "filters"]
