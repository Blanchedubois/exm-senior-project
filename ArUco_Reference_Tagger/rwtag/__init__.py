"""
rwtag — ArUco Reference Tagger, headless core. NO Qt in this package.

Phase 1: image IO and ArUco recognition (rwtag.aruco). Later phases add the
optics correction, the design-driven detector, filtering, tagging, the error
model, pairing and export, following docs/00_PORT_OVERVIEW.md.
"""
from __future__ import annotations

from . import io

__all__ = ["io"]
