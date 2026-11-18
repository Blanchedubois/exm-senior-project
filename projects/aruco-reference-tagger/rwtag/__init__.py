"""
rwtag — ArUco Reference Tagger, headless core. NO Qt in this package.

Phase 1: ArUco recognition (rwtag.aruco).
Phase 2: image IO + Stage-1 sessions (io), optics correction and exact raw <->
corrected point mapping (correct), the acquisition-metadata record (meta), the
multi-image project (project).
Later phases add the design-driven detector, filtering, tagging, the error model,
pairing and export, following docs/00_PORT_OVERVIEW.md.
"""
from __future__ import annotations

from .meta import ImageMeta
from .types import CorrectionParams, LevelsParams, PipelineState
from . import correct, io, meta, project

__all__ = ["ImageMeta", "CorrectionParams", "LevelsParams", "PipelineState",
           "correct", "io", "meta", "project"]
