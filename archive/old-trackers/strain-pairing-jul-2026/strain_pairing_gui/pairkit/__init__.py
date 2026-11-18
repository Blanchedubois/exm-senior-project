"""
pairkit
=======
Headless core of the multi-image pairing & strain app. Reuses the copied
single-image glyph pipeline (glyphtrack, gridtrack, stageui) by putting the
sibling `point_tracking_gui` on sys.path — no duplication.
"""
from __future__ import annotations
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.normpath(os.path.join(_ROOT, "..", "..", "point_tracking_gui"))
if os.path.isdir(os.path.join(_APP, "glyphtrack")) and _APP not in sys.path:
    sys.path.append(_APP)                    # append: our own packages win from cwd

from . import types, tags, process, project, pair, io_csv, strain, coreg   # noqa: E402,F401

__all__ = ["types", "tags", "process", "project", "pair", "io_csv", "strain", "coreg"]
