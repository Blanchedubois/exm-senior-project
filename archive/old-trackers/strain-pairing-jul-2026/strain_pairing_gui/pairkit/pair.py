"""
pairkit.pair
===========
Pair every point of each expansion image to the INITIAL image by CANONICAL TAG.

Each processed image independently assigns every filtered point an absolute tag
(pairkit.tags) from its position in the design frame, so the same physical dot /
dash / digit gets the same tag in every image regardless of expansion. Pairing is
therefore an exact dict join on the tag: initial point i pairs to the expansion
point that carries the identical tag, or to nothing. This is one-to-one by
construction (tags are unique within an image — no double counting), independent
per image, and keeps edge points that a proximity matcher would drop.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class PairingResult:
    initial: object                 # PointTable
    expansions: list                # [PointTable]
    matches: list = field(default_factory=list)   # matches[e][i] = PointRecord | None
    box_stats: list = field(default_factory=list)  # matches[e]: {box: (paired, initial_dots)}

    def rate(self, e):
        m = self.matches[e]
        return sum(1 for x in m if x is not None) / max(len(m), 1)


def pair(initial, expansions, tol_frac=0.4, glyph_tol=0.10, align_dots=True):
    """Tag join: initial[i] pairs to the expansion point with the same canonical
    tag. `tol_frac`/`glyph_tol`/`align_dots` are accepted for call-site
    compatibility but unused — identity comes from the tag, not proximity."""
    matches, box_stats = [], []
    for t in expansions:
        exp_by_tag = {p.tag: p for p in t.points if p.tag}   # unique tag -> point
        m = [None] * len(initial.points)
        bstat = defaultdict(lambda: [0, 0])                  # box -> [paired, initial dots]
        for i, ip in enumerate(initial.points):
            if ip.type == "dot":
                bstat[ip.box_number][1] += 1
            if not ip.tag:
                continue
            mp = exp_by_tag.get(ip.tag)
            if mp is None:
                continue
            m[i] = mp
            if ip.type == "dot":
                bstat[ip.box_number][0] += 1
        matches.append(m)
        box_stats.append({b: tuple(v) for b, v in bstat.items()})
    return PairingResult(initial, expansions, matches, box_stats)
