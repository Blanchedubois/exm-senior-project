#!/usr/bin/env python3
"""
mesh_merge.py — one closed, MANIFOLD solid per printed island (spacing workshop, S4).

The box-style STL writes every footprint rectangle as its own closed box. Inside a
tag the rectangles abut, so that file carries coincident internal faces. The first
merged variant (w11_print_budget.merged_triangles) removed those faces but left
T-JUNCTIONS: a wall or a top face whose edge runs past a neighbour's corner without
a vertex there. The surface is closed as a set, but 1-3 % of its edges do not
match edge-to-edge, and a strict mesh checker calls that non-manifold.

Here every rectangle is first given ALL the vertices that fall on its boundary
(its own corners plus the corners of every rectangle of the same island that touch
it). Top and bottom are fanned from the rectangle's centre over that ordered
boundary; a wall is emitted for each boundary segment that no neighbour covers.
Every edge is then shared by exactly two faces.

    manifold_triangles(islands, h) -> list of (normal, v0, v1, v2), n_internal_segments
"""
from __future__ import annotations
import numpy as np

TOL = 1e-7


def _on_boundary(p, r):
    x, y = p
    x0, y0, x1, y1 = r
    inside = x0 - TOL <= x <= x1 + TOL and y0 - TOL <= y <= y1 + TOL
    return inside and (abs(x - x0) < TOL or abs(x - x1) < TOL or abs(y - y0) < TOL or abs(y - y1) < TOL)


def _covers(p, r):
    """p lies in the CLOSED rectangle r."""
    return r[0] - TOL <= p[0] <= r[2] + TOL and r[1] - TOL <= p[1] <= r[3] + TOL


def island_triangles(rects, h):
    R = [tuple(map(float, r)) for r in rects]
    corners = [[(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])] for r in R]
    tris, internal = [], 0
    for k, r in enumerate(R):
        pts = list(corners[k])
        touch = [m for m in range(len(R)) if m != k
                 and R[m][0] <= r[2] + TOL and R[m][2] >= r[0] - TOL
                 and R[m][1] <= r[3] + TOL and R[m][3] >= r[1] - TOL]
        for m in touch:
            for p in corners[m]:
                if _on_boundary(p, r) and all(abs(p[0] - q[0]) > TOL or abs(p[1] - q[1]) > TOL for q in pts):
                    pts.append(p)
        cx, cy = (r[0] + r[2]) / 2.0, (r[1] + r[3]) / 2.0
        pts.sort(key=lambda p: np.arctan2(p[1] - cy, p[0] - cx))          # counter-clockwise
        n = len(pts)
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            tris.append(((0, 0, 1), (cx, cy, h), (a[0], a[1], h), (b[0], b[1], h)))
            tris.append(((0, 0, -1), (cx, cy, 0.0), (b[0], b[1], 0.0), (a[0], a[1], 0.0)))
            mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
            if any(_covers(mid, R[m]) for m in touch):
                internal += 1
                continue                                                   # shared with a neighbour: no wall
            nx, ny = b[1] - a[1], -(b[0] - a[0])                           # outward for a CCW boundary
            L = (nx * nx + ny * ny) ** 0.5
            nrm = (nx / L, ny / L, 0.0)
            A0, B0, A1, B1 = (a[0], a[1], 0.0), (b[0], b[1], 0.0), (a[0], a[1], h), (b[0], b[1], h)
            tris.append((nrm, A0, B0, B1))
            tris.append((nrm, A0, B1, A1))
    return tris, internal


def manifold_triangles(islands, h):
    """`islands` = build()'s info["islands"] (kind, cx, cy, rel rects)."""
    out, internal = [], 0
    for isl in islands:
        rects = [(isl["cx"] + a, isl["cy"] + b, isl["cx"] + c, isl["cy"] + d) for a, b, c, d in isl["rel"]]
        t, n = island_triangles(rects, h)
        out += t; internal += n
    return out, internal


def islands_from_rects(rects, group):
    """Helper for a translated subset: rects + an island index per rect."""
    by = {}
    for r, g in zip(rects, group):
        by.setdefault(int(g), []).append(tuple(r))
    return [dict(kind="", cx=0.0, cy=0.0, rel=v) for v in by.values()]
