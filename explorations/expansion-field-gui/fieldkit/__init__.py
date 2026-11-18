"""
fieldkit -- headless multi-image orchestration on top of the `gridtrack` core.

The five per-image tracking stages are NOT reimplemented here: this package
imports `gridtrack` (from the sibling point-tracking-gui) and adds only
(a) multi-image project management + per-stage CSV output, and
(b) the pairing stage (initial <-> each expansion) [Phase 3, later].

No GUI toolkit is imported anywhere in this package.
"""
from __future__ import annotations
import os
import sys

# --- make the shared gridtrack + stageui core importable (reuse, don't duplicate)
# APPEND (not insert-0): point-tracking-gui also has a top-level `app` package, and
# putting it ahead of this app's dir would let it shadow *our* `app`. Appending lets
# our own packages (app, fieldkit) win from the cwd while still resolving the shared
# `gridtrack` / `stageui` (which exist only in point-tracking-gui) from there.
_ROOT = os.path.dirname(os.path.abspath(__file__))
_PTG = os.path.normpath(os.path.join(_ROOT, "..", "..", "point-tracking-gui"))
if os.path.isdir(os.path.join(_PTG, "gridtrack")) and _PTG not in sys.path:
    sys.path.append(_PTG)

from . import io_csv, markers, pipeline, pairing, strain, analysis, project    # noqa: E402,F401

__all__ = ["io_csv", "markers", "pipeline", "pairing", "strain", "analysis", "project"]
