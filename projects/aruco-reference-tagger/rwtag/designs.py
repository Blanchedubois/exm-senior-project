"""
rwtag.designs
=============
The design registry: the four spacing-workshop prints shipped in `designs/`,
plus any folder holding a `reference_tags.json`. Loaded designs are cached.
"""
from __future__ import annotations
import os

from .aruco.design import Design

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY_DIR = os.path.join(_ROOT, "designs")
REGISTRY = [("Optimistic (5.0 µm)", "1_optimistic"), ("Medium (6.0 µm)", "2_medium"),
            ("Conservative (7.0 µm)", "3_conservative"), ("Spectrum test print", "4_spectrum")]
META_NAME = {"1_optimistic": "optimistic", "2_medium": "medium",
             "3_conservative": "conservative", "4_spectrum": "spectrum"}
_CACHE = {}


def registry():
    """[(label, absolute folder)] for the shipped designs that are present."""
    return [(lab, os.path.join(REGISTRY_DIR, sub)) for lab, sub in REGISTRY
            if os.path.exists(os.path.join(REGISTRY_DIR, sub, "reference_tags.json"))]


def load(folder) -> Design:
    folder = os.path.abspath(folder)
    if folder not in _CACHE:
        _CACHE[folder] = Design.load_folder(folder, name=os.path.basename(folder))
    return _CACHE[folder]


def meta_name(folder):
    """The value for ImageMeta.print_design ('optimistic', … or 'other')."""
    return META_NAME.get(os.path.basename(os.path.abspath(folder)), "other")


def default_folder():
    reg = registry()
    return reg[0][1] if reg else ""
