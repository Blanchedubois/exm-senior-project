"""
glyphtrack
==========
Headless detection + recognition for the older number/letter marker system
(5x5 boxes, box number at corners+centre, A/B/C/D orientation letters, dot fill,
dashed boundaries). Trained from the reference Nanoscribe STL.
"""
from . import types, stl_glyphs, classifier   # noqa: F401

__all__ = ["types", "stl_glyphs", "classifier"]
