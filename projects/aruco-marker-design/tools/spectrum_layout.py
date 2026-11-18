#!/usr/bin/env python3
"""
spectrum_layout.py — the 5 x 5 spacing x size matrix of the spectrum print
(designs/docs/03_SPECTRUM_PRINT.md).

    spacing widens LEFT -> RIGHT, dot size grows TOP -> BOTTOM
    top-left = optimistic, top row = the three designs, bottom-right = safest

Decision D1: "spacing" is the GAP between dot edges (pitch = gap + dot), so every
column tolerates about the same blur in every row. mode="pitch" gives the
alternative (columns are centre-to-centre pitches whatever the dot size).
"""
from __future__ import annotations

DOT_REF = 2.125
GAPS = [2.875, 3.375, 3.875, 4.375, 4.875]        # -> top-row pitch 5.0, 5.5, 6.0, 6.5, 7.0
SIZES = [2.125, 2.5, 3.0, 3.5, 4.0]               # top -> bottom
TAG_UM = 23.0                                     # the same 23 um tag as all three designs
LABELS = {(0, 4): "OPTIMISTIC", (2, 4): "MEDIUM", (4, 4): "CONSERVATIVE", (4, 0): "SAFEST"}


def box_specs(gaps=GAPS, sizes=SIZES, mode="gap"):
    """GridConfig.box_specs for the matrix. Rows count from the BOTTOM in the
    generator, so size index k (from the top) is row n-1-k."""
    n = len(sizes)
    out = []
    for c, g in enumerate(gaps):
        for k, d in enumerate(sizes):
            pitch = g + d if mode == "gap" else g + DOT_REF
            out.append(dict(col=c, row=n - 1 - k, dot_um=float(d), pitch_um=float(pitch)))
    return out
