"""
pairkit.types
============
Data contracts for the multi-image pairing/strain app. No Qt, no heavy imports.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class PointRecord:
    """One filtered fiducial in one processed image, box-tagged for pairing."""
    type: str               # "dot" | "digit" | "letter" | "dash"
    box_number: int         # absolute box 1..25 (from the registered grid)
    sub_id: str             # within-box identity: dot "di_dj" / glyph slot / dash "edge_k"
    char: str               # digit/letter char ("" for dot/dash)
    x: float                # image pixels
    y: float
    fx: float               # box-local position, fraction of the box [0,1] (design frame)
    fy: float
    tag: str = None         # canonical tag (assigned by pairkit.tags); None = untagged
    node: tuple = None      # dots: fit grid node (bi,bj) — used to seed manual anchors

    @property
    def key(self):
        """Exact identity used to pair glyphs (box + slot + char)."""
        return (self.type, self.box_number, self.sub_id)


@dataclass
class PointTable:
    """All filtered points from one processed image."""
    path: str
    points: list = field(default_factory=list)   # [PointRecord]
    box_pitch: float = 0.0     # px — box period (scale proxy)
    dot_pitch: float = 0.0     # px
    deskew_deg: float = 0.0
    registered: bool = False
    label: float = 0.0         # expansion factor (set by the project)
    role: str = "expansion"    # "initial" | "expansion"

    def by_type(self, *types):
        return [p for p in self.points if p.type in types]

    def counts(self):
        out = {}
        for p in self.points:
            out[p.type] = out.get(p.type, 0) + 1
        return out
