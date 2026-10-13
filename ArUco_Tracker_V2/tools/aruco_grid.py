#!/usr/bin/env python3
"""
aruco_grid.py — Phase A of the V2 implementation plan.

Parametric CAD generator for the V2 marker field: an ArUco tag at every box
corner, a dense dot lattice filling the interiors, optional sparse boundary
dashes. Emits

    <name>.stl                 binary STL, flat 2 um extrusion (as the V1 print)
    <name>.reference_tags.json the tag map, in the EXISTING rwtag schema so
                               rwtag/refwarp consumes it unchanged
    <name>.ids.json            node (i,j) -> ArUco id, for the record

GEOMETRY (plan section 3)
    750 x 750 um field, 5 x 5 boxes of 150 um, 6 x 6 = 36 corner nodes.
    Tags: DICT_4X4_50, 6 modules incl. border. 43 of its 50 IDs are already
    single-4-connected, so 36 nodes can be filled with SOLID ids and NO STRUTS
    (Phase 0 / scan_connected_ids.py).

POLARITY
    Printed material = the ArUco BLACK modules, border ring included. That ring
    is what makes a solid id one connected rigid island. Under fluorescence the
    print images bright, and the detection path inverts before decoding, so the
    decoder sees a conventional dark-on-light marker.

VARIANTS (plan section 3.1; gated on Phase 0a, which is unresolved)
    conservative   0.510 um/px   tag 20.3 um   dot pitch 5.83 um
    optimistic     0.381 um/px   tag 12.2 um   dot pitch 3.77 um
    Both are generated from the same config; --variant picks one.

Run:  python aruco_grid.py --variant conservative --out ../cad
      python aruco_grid.py --variant optimistic --dashes
      python aruco_grid.py --variant conservative --verify-only
"""
from __future__ import annotations
import argparse
import json
import os
import struct
from dataclasses import dataclass, asdict, field

import numpy as np
import cv2
from cv2 import aruco

HERE = os.path.dirname(os.path.abspath(__file__))


# ------------------------------------------------------------------ config
@dataclass
class GridConfig:
    # field
    field_um: float = 750.0            # OVERALL printed extent — matches the V1 print
    grid_n: int = 5                    # boxes per side -> (grid_n+1)^2 nodes
    height_um: float = 2.0             # extrusion, matches the V1 print
    fit: str = "inside"                # "inside":  outer extent == field_um EXACTLY.
                                       #            Corner tags sit fully inside the
                                       #            boundary, so the node lattice is
                                       #            inset by half a tag and the box
                                       #            pitch comes out just under 150 um.
                                       # "lattice": box pitch == box_um exactly, and
                                       #            the corner tags overhang by half a
                                       #            tag (extent > field_um).
    box_um: float = 150.0              # only used when fit == "lattice"
    # fiducials
    dict_name: str = "DICT_4X4_50"
    tag_modules: int = 6               # 4x4 payload + 1-module border each side
    tag_um: float = 20.3
    quiet_um: float = 0.0              # 0 = derive it (see quiet_zone_um)
    # --- rounding, so a tag cannot come apart as the gel swells --------------
    round_tags: bool = True
    strut_w_um: float = 0.20           # elliptical neck bridging a diagonal pinch
    strut_len_frac: float = 0.72       # neck length, as a fraction of a module
    fillet_um: float = 0.30            # radius rounding every concave corner
    tag_raster: int = 20               # px per module when rasterising the tag
    # dots
    # ANCHORING FLOOR. A dot only reports a material point if the gel network
    # actually grips it. V1 printed 2.125 um dots and they tracked coherently to
    # 4.2x -- the only size with proven anchoring in this gel. Shrinking to 1 um
    # buys just 24% more dots (the PSF, not the dot, sets the spacing) while
    # halving the gel contact area, so the default stays at the proven size.
    dot_side_um: float = 2.125
    # spacing is DERIVED, so changing the dot size keeps the optics consistent
    psf_fwhm_um: float = 3.18          # system PSF for this variant
    sep_rule: float = 1.75             # measured in Phase 0c
    # Spacing workshop (S1): give the spacing DIRECTLY instead of deriving it from a
    # PSF. 0 = derive (every Rev D print). psf_fwhm_um is then documentation only.
    dot_pitch_override_um: float = 0.0
    # Spectrum print (S1): a different dot size / spacing in each box.
    # [{"col": c, "row": r, "dot_um": d, "pitch_um": p}, ...]; boxes not listed use
    # the global dot_side_um / dot_pitch_um. col, row count from the BOTTOM-LEFT.
    box_specs: list = field(default_factory=list)
    # Tag keep-out used when placing DASHES. 0 = the dots' own keep-out (Rev D).
    # The spacing designs fix it at the optimistic value so that tags AND dashes are
    # identical in every design and only the dot spacing differs.
    dash_keepout_um: float = 0.0
    # boundary dashes (plan section 3.3: default OFF, ArUco addresses globally)
    dashes: bool = True                # tier 2 of 3; matches the V1 print
    dash_len_um: float = 8.125         # measured from the V1 STL
    dash_width_um: float = 2.125       # measured from the V1 STL
    dashes_per_edge: int = 10           # V1 spacing along a 150 um box edge
    # bookkeeping
    variant: str = "conservative"
    ids: list = field(default_factory=list)   # filled by assign_ids
    id_start: int = 0                  # offset into the solid-id pool, so several
                                       # patterns on one coupon carry DISTINCT ids

    @property
    def dot_pitch_um(self):
        """Centre-to-centre dot spacing: given directly, or 1.75 x the imaged spot
        (Phase 0c) when no override is set."""
        import math
        if self.dot_pitch_override_um > 0:
            return float(self.dot_pitch_override_um)
        return self.sep_rule * math.hypot(self.dot_side_um, self.psf_fwhm_um)

    def box_spec(self, col, row):
        """(dot side, pitch) used inside box (col, row)."""
        for b in self.box_specs:
            if int(b["col"]) == col and int(b["row"]) == row:
                return float(b["dot_um"]), float(b["pitch_um"])
        return self.dot_side_um, self.dot_pitch_um

    def psf_max_um(self, dot=None, pitch=None):
        """Largest blur at which `pitch` still satisfies the separation rule."""
        import math
        dot = self.dot_side_um if dot is None else dot
        pitch = self.dot_pitch_um if pitch is None else pitch
        v = (pitch / self.sep_rule) ** 2 - dot ** 2
        return math.sqrt(v) if v > 0 else 0.0

    def box_keepouts(self, dot, pitch):
        """(tag keep-out half-width, dash clearance) for a box with this dot/pitch:
        the same edge-to-edge gap a dot has from its neighbours, pitch - dot."""
        gap = self.quiet_um if self.quiet_um > 0 else pitch - dot
        keep = self.tag_um / 2.0 + gap + dot / 2.0
        dash = (self.dash_width_um / 2.0 + (pitch - dot) + dot / 2.0) if self.dashes else 0.0
        return keep, dash

    @property
    def gel_contact_um2(self):
        """Footprint + sidewall area each dot presents to the gel network."""
        return self.dot_side_um ** 2 + 4 * self.dot_side_um * self.height_um

    @property
    def box_pitch(self):
        """Node-to-node spacing actually used."""
        if self.fit == "inside":
            return (self.field_um - self.tag_um) / self.grid_n
        return self.box_um

    @property
    def origin(self):
        """Design coord of node (0,0): inset by half a tag when fitting inside."""
        return self.tag_um / 2.0 if self.fit == "inside" else 0.0

    @property
    def extent(self):
        """Overall printed extent (outer edge of the corner tags)."""
        return self.box_pitch * self.grid_n + self.tag_um

    @property
    def n_nodes(self):
        return (self.grid_n + 1) ** 2

    @property
    def module_um(self):
        return self.tag_um / self.tag_modules

    @property
    def quiet_zone_um(self):
        """Clear space OUTSIDE the tag before the first dot.

        Workshop W2 showed this is NOT an ArUco constraint: with a plain-inversion
        decoder every clearance from a quarter module up decodes 100% at
        lambda=1 (Phase B's "50% at 3 um" was a CLAHE artefact). What does
        constrain it is the DOT detector -- a dot printed hard against a bright
        tag merges into the tag's blob under top-hat/Otsu, exactly as dots merged
        with dashes at 0.3 um in Phase B. So give a dot the same edge-to-edge gap
        from a tag that it gets from its neighbours: pitch - dot."""
        if self.quiet_um > 0:
            return self.quiet_um
        return self.dot_pitch_um - self.dot_side_um

    @property
    def keepout_um(self):
        """Half-width of the SQUARE keep-out around a tag, measured along x/y.

        The tag is an axis-aligned square, so the exclusion zone must be square
        too. A circle of this radius leaves the tag's own corners uncovered --
        they reach tag_um/2 * sqrt(2) -- and dots then land ON the tag.
        Tested with the Chebyshev (L-infinity) distance, not Euclidean."""
        return self.tag_um / 2.0 + self.quiet_zone_um + self.dot_side_um / 2.0

    @property
    def dash_tag_keepout_um(self):
        return self.dash_keepout_um if self.dash_keepout_um > 0 else self.keepout_um

    @property
    def dash_clear_um(self):
        """Minimum distance from a dot CENTRE to a grid line carrying dashes.

        A dot sitting right beside a dash merges with it -- in the render, and
        far worse on the microscope, whose ~2.7 um blur is wider than the gap.
        So give a dot/dash pair at least the same clear edge-to-edge gap that
        neighbouring dots get from each other."""
        if not self.dashes:
            return 0.0
        dot_gap = self.dot_pitch_um - self.dot_side_um      # gap between two dots
        return self.dash_width_um / 2.0 + dot_gap + self.dot_side_um / 2.0


# Tag size is set by DECODABILITY THROUGH THE BLUR. Workshop W1 (full scene,
# worst-case corner placement, all 36 ids, plain-inversion decoder -- NO CLAHE)
# measured module >= ~1.45 x PSF FWHM for >=95%. Adopted 1.75x = that minimum
# sized for a PSF 20% worse than design. tag = 6 modules.
#   conservative (SAFE):  6 x 1.75 x 3.18 = 33.4 -> 34 um
#   hedge:                6 x 1.75 x 2.50 = 26.3 -> 27 um
#   optimistic (OPT):     6 x 1.75 x 1.91 = 20.1 -> 21; 23 gives 100% at 1.2x PSF
# History: Phase B's 1.8x rule (36/24 um) was inflated by CLAHE in the decoder;
# Rev C's 1.06x had no noise or pixel sampling. Both superseded by W1.
VARIANTS = {
    "conservative": dict(tag_um=34.0, psf_fwhm_um=3.18, variant="conservative"),
    "hedge":        dict(tag_um=27.0, psf_fwhm_um=2.50, variant="hedge"),
    "optimistic":   dict(tag_um=23.0, psf_fwhm_um=1.91, variant="optimistic"),
}


# SPACING WORKSHOP (designs/docs/01_DESIGN_PARAMETERS.md): the reference dot, three
# spacings, and NOTHING ELSE different (user, 2026-09-29: "I don't want the ArUco
# markers to be bigger, I just want the spacing between the dots to change").
# Tags are 23 um in all three, on the same nodes with the same ids, and the dashes
# are the same 480 in the same places (dash_keepout_um pinned to the optimistic
# value). "optimistic" IS the Rev D print, built exactly as before -- derived pitch
# 1.75 x hypot(2.125, 1.91) = 5.00014 um, nominal 5.0 -- so the file stays
# byte-identical. Medium and conservative give the spacing directly; their
# psf_fwhm_um is the largest blur that DOT spacing tolerates. The 23 um tag itself
# decodes reliably only to a blur of ~2.6 um (module >= 1.45 x PSF, W1) -- see
# designs/docs/01 section 3.
TAG_UM_ALL = 23.0
OPT_DASH_KEEPOUT = GridConfig(tag_um=TAG_UM_ALL, psf_fwhm_um=1.91).keepout_um
SPACING_DESIGNS = {
    "optimistic":   dict(tag_um=TAG_UM_ALL, psf_fwhm_um=1.91, variant="optimistic"),
    "medium":       dict(tag_um=TAG_UM_ALL, psf_fwhm_um=2.69, dot_pitch_override_um=6.0,
                         dash_keepout_um=OPT_DASH_KEEPOUT, variant="medium"),
    "conservative": dict(tag_um=TAG_UM_ALL, psf_fwhm_um=3.39, dot_pitch_override_um=7.0,
                         dash_keepout_um=OPT_DASH_KEEPOUT, variant="conservative-7um"),
}


# ------------------------------------------------------------------ ArUco
def module_map(dict_name, marker_id, n_modules):
    """n x n uint8, 1 = BLACK module (the printed material), border included."""
    d = aruco.getPredefinedDictionary(getattr(aruco, dict_name))
    img = aruco.generateImageMarker(d, marker_id, n_modules, 1)
    return (img < 128).astype(np.uint8)


def solid_ids(dict_name, n_modules, n_ids):
    """IDs whose black pattern is a single 4-connected piece -> one rigid island,
    no struts needed."""
    out = []
    for i in range(n_ids):
        m = module_map(dict_name, i, n_modules)
        if cv2.connectedComponents(m, connectivity=4)[0] - 1 == 1:
            out.append(i)
    return out


def n_leaves(mask):
    """Black modules attached to the rest by exactly one edge -- the only modules
    a 4-connected id can physically shed. W3: a shed leaf carried off by the gel
    is tolerated to lambda ~2 and loses the id 20% of the time by lambda 3, so
    ids with no leaves are strictly safer."""
    M = mask.shape[0]; n = 0
    for r in range(M):
        for c in range(M):
            if mask[r, c] and sum(1 for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1))
                                  if 0 <= r + dr < M and 0 <= c + dc < M
                                  and mask[r + dr, c + dc]) == 1:
                n += 1
    return n


def assign_ids(cfg: GridConfig):
    """Node (i,j) -> ArUco id, row-major over the solid pool, LEAF-FREE ids first
    (then fewest leaves), so the 36 nodes use the most robust ids available."""
    n_ids = int(cfg.dict_name.rsplit("_", 1)[1])
    pool = solid_ids(cfg.dict_name, cfg.tag_modules, n_ids)
    pool = sorted(pool, key=lambda i: (n_leaves(module_map(cfg.dict_name, i, cfg.tag_modules)), i))
    need = cfg.n_nodes
    if len(pool) < need + cfg.id_start:
        raise SystemExit(f"{cfg.dict_name} has only {len(pool)} solid ids, need "
                         f"{need} from offset {cfg.id_start} — use a larger dictionary")
    k, out = cfg.id_start, {}
    for j in range(cfg.grid_n + 1):
        for i in range(cfg.grid_n + 1):
            out[(i, j)] = pool[k]; k += 1
    return out, pool


def decompose(mask):
    """Greedy maximal-rectangle decomposition of a binary mask.
    Non-overlapping rectangles keep the STL free of self-intersections."""
    m = mask.astype(bool).copy()
    rects = []
    while m.any():
        ys, xs = np.nonzero(m)
        y0, x0 = int(ys[0]), int(xs[0])
        x1 = x0
        while x1 + 1 < m.shape[1] and m[y0, x1 + 1]:
            x1 += 1
        y1 = y0
        while y1 + 1 < m.shape[0] and m[y1 + 1, x0:x1 + 1].all():
            y1 += 1
        rects.append((x0, y0, x1 + 1, y1 + 1))
        m[y0:y1 + 1, x0:x1 + 1] = False
    return rects


def tag_rects(cfg: GridConfig, aruco_id: int, cx: float, cy: float):
    """Footprint rectangles for ONE tag, in um, with every diagonal pinch bridged
    by a smooth elliptical neck and every concave corner filleted.

    WHY. The 36 ids are all single-4-connected, so no tag can come apart by
    topology. But 34 corner-only (diagonal) touches remain across the set, and a
    sharp notch in a rigid island held in a swelling matrix is a fracture
    initiator. The neck geometry is the one proven in
    hydrogel_marker_analysis (strut_prominence.py): it lives inside ArUco's
    ignored corner-sampling margin, so the decoded id is unchanged -- which the
    Phase-A gate re-checks by decoding every generated tag.

    Done on a raster at `tag_raster` px per module. The resulting staircase step
    is ~module/tag_raster (~0.17 um), at or below the 2PP voxel, so it is smooth
    as far as the printer is concerned.
    """
    N, M = cfg.tag_raster, cfg.tag_modules
    m = module_map(cfg.dict_name, aruco_id, M)
    mask = np.kron(m, np.ones((N, N), np.uint8))
    n_pinch = 0
    if cfg.round_tags:
        major = max(2, int(round(cfg.strut_len_frac * N)))
        minor = max(1, int(round(cfg.strut_w_um / cfg.module_um * N)))
        for r in range(M - 1):
            for c in range(M - 1):
                a, b, cc, d = m[r, c], m[r, c + 1], m[r + 1, c], m[r + 1, c + 1]
                if a and d and not b and not cc:
                    ang = 45.0            # black runs top-left -> bottom-right
                elif b and cc and not a and not d:
                    ang = 135.0
                else:
                    continue
                cv2.ellipse(mask, ((c + 1) * N, (r + 1) * N),
                            (major // 2, max(1, minor // 2)), ang, 0, 360, 1, -1)
                n_pinch += 1
        rpx = max(1, int(round(cfg.fillet_um / cfg.module_um * N)))
        # closing fills concave notches with radius rpx; 2*rpx stays far below the
        # one-module (N px) white gaps, so no white module is ever bridged.
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * rpx + 1, 2 * rpx + 1))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)

    px = cfg.module_um / N
    x0, y0 = cx - cfg.tag_um / 2.0, cy - cfg.tag_um / 2.0
    H = mask.shape[0]
    out = []
    for (a, b, c, d) in decompose(mask):
        out.append((x0 + a * px, y0 + (H - d) * px, x0 + c * px, y0 + (H - b) * px))
    return out, n_pinch


# ------------------------------------------------------------------ geometry
def build(cfg: GridConfig):
    """Return (rects, records) — rects are (x0,y0,x1,y1) um footprints in the
    design frame (y-UP, origin at the field corner); records are tag-map rows."""
    rects, recs, dot_rects, islands = [], [], [], []
    idmap, _pool = assign_ids(cfg)
    cfg.ids = [[int(i), int(j), int(v)] for (i, j), v in sorted(idmap.items())]

    # ---- TIER 1: ArUco fiducials at every node -----------------------------
    n_pinch_total = 0
    for (i, j), aid in sorted(idmap.items()):
        cx = cfg.origin + i * cfg.box_pitch
        cy = cfg.origin + j * cfg.box_pitch
        tr, npin = tag_rects(cfg, aid, cx, cy)
        rects.extend(tr)
        islands.append(dict(kind="aruco", cx=float(cx), cy=float(cy), aruco_id=int(aid),
                            rel=[(a - cx, b - cy, c - cx, d - cy) for a, b, c, d in tr]))
        n_pinch_total += npin
        recs.append(dict(tag=f"aruco|N{i}_{j}|{aid}", category="aruco",
                         x_um=float(cx), y_um=float(cy),
                         meta={"node_i": i, "node_j": j, "aruco_id": int(aid),
                               "dict": cfg.dict_name, "size_um": cfg.tag_um}))
    cfg_pinch = n_pinch_total

    # ---- TIER 3: dot lattice, per box, with tag keep-out -------------------
    nodes = np.array([[cfg.origin + i * cfg.box_pitch, cfg.origin + j * cfg.box_pitch]
                      for j in range(cfg.grid_n + 1) for i in range(cfg.grid_n + 1)], float)
    # CENTRE the lattice in the box. A fixed phase of p/2 leaves unequal margins
    # whenever the box is not an exact multiple of the pitch -- 2.24 um of
    # asymmetry in the conservative variant, which is visible by eye. Fit the
    # rows first, then split the leftover evenly.
    # Dot size, pitch and both keep-outs are PER BOX (spectrum print); with no
    # box_specs every box gets the global values and the build is unchanged.
    boxes = []
    for col in range(cfg.grid_n):
        for row in range(cfg.grid_n):
            N = col * cfg.grid_n + row + 1        # V1 numbering rule, column-major
            dot, p = cfg.box_spec(col, row)
            half = dot / 2.0
            if cfg.box_specs:
                keepout, dash_clear = cfg.box_keepouts(dot, p)
            else:
                keepout, dash_clear = cfg.keepout_um, cfg.dash_clear_um
            n_per = int(np.floor((cfg.box_pitch - p) / p)) + 1
            phase = (cfg.box_pitch - (n_per - 1) * p) / 2.0
            bx = cfg.origin + col * cfg.box_pitch
            by = cfg.origin + row * cfg.box_pitch
            n_box = 0
            for dj in range(n_per):
                for di in range(n_per):
                    x = bx + phase + di * p
                    y = by + phase + dj * p
                    if np.min(np.maximum(np.abs(nodes[:, 0] - x),
                                         np.abs(nodes[:, 1] - y))) < keepout:
                        continue                   # inside a tag's square keep-out
                    if cfg.dashes:                 # clear of the grid-marker lines
                        du = min(abs(x - (cfg.origin + k * cfg.box_pitch))
                                 for k in range(cfg.grid_n + 1))
                        dv = min(abs(y - (cfg.origin + k * cfg.box_pitch))
                                 for k in range(cfg.grid_n + 1))
                        if min(du, dv) < dash_clear:
                            continue
                    r4 = (x - half, y - half, x + half, y + half)
                    rects.append(r4); dot_rects.append(r4)
                    islands.append(dict(kind="dot", cx=float(x), cy=float(y),
                                        rel=[(-half, -half, half, half)]))
                    meta = {"box": N, "di": di, "dj": dj}
                    if cfg.box_specs:
                        meta.update(dot_um=dot, pitch_um=p)
                    recs.append(dict(tag=f"dot|B{N}|{di}_{dj}", category="dot",
                                     x_um=float(x), y_um=float(y), meta=meta))
                    n_box += 1
            boxes.append(dict(box=N, col=col, row=row, dot_um=dot, pitch_um=p, gap_um=p - dot,
                              per_row=int(n_per), phase_um=float(phase), count=n_box,
                              x0_um=float(bx), y0_um=float(by), tag_keepout_um=float(keepout),
                              dash_clear_um=float(dash_clear),
                              psf_max_um=cfg.psf_max_um(dot, p)))
    p = cfg.dot_pitch_um
    n_per = int(np.floor((cfg.box_pitch - p) / p)) + 1
    phase = (cfg.box_pitch - (n_per - 1) * p) / 2.0

    # ---- TIER 2: grid markers (boundary dashes) ----------------------------
    if cfg.dashes:
        L, W = cfg.dash_len_um, cfg.dash_width_um
        for j in range(cfg.grid_n + 1):            # horizontal lines
            y = cfg.origin + j * cfg.box_pitch
            for span in range(cfg.grid_n):
                for k in range(cfg.dashes_per_edge):
                    x = cfg.origin + (span + (k + 0.5) / cfg.dashes_per_edge) * cfg.box_pitch
                    if np.min(np.maximum(np.abs(nodes[:, 0] - x),
                                         np.abs(nodes[:, 1] - y))) < cfg.dash_tag_keepout_um + L / 2:
                        continue
                    rects.append((x - L / 2, y - W / 2, x + L / 2, y + W / 2))
                    islands.append(dict(kind="dash", cx=float(x), cy=float(y),
                                        rel=[(-L / 2, -W / 2, L / 2, W / 2)]))
                    recs.append(dict(tag=f"dash|H{j}|{span*cfg.dashes_per_edge+k}",
                                     category="dash", x_um=float(x), y_um=float(y),
                                     meta={"line": f"H{j}"}))
        for i in range(cfg.grid_n + 1):            # vertical lines
            x = cfg.origin + i * cfg.box_pitch
            for span in range(cfg.grid_n):
                for k in range(cfg.dashes_per_edge):
                    y = cfg.origin + (span + (k + 0.5) / cfg.dashes_per_edge) * cfg.box_pitch
                    if np.min(np.maximum(np.abs(nodes[:, 0] - x),
                                         np.abs(nodes[:, 1] - y))) < cfg.dash_tag_keepout_um + L / 2:
                        continue
                    rects.append((x - W / 2, y - L / 2, x + W / 2, y + L / 2))
                    islands.append(dict(kind="dash", cx=float(x), cy=float(y),
                                        rel=[(-W / 2, -L / 2, W / 2, L / 2)]))
                    recs.append(dict(tag=f"dash|V{i}|{span*cfg.dashes_per_edge+k}",
                                     category="dash", x_um=float(x), y_um=float(y),
                                     meta={"line": f"V{i}"}))
    return rects, recs, dict(n_pinch=cfg_pinch, dot_rects=dot_rects,
                             islands=islands, dot_phase=float(phase),
                             dots_per_row=int(n_per), boxes=boxes)


# ------------------------------------------------------------------ STL
def stl_triangles(rects, h):
    """Each footprint rectangle -> a closed box: 2 top, 2 bottom, 8 side."""
    tris = []
    for (x0, y0, x1, y1) in rects:
        v = {
            "a0": (x0, y0, 0.0), "b0": (x1, y0, 0.0), "c0": (x1, y1, 0.0), "d0": (x0, y1, 0.0),
            "a1": (x0, y0, h),   "b1": (x1, y0, h),   "c1": (x1, y1, h),   "d1": (x0, y1, h),
        }
        tris += [
            (( 0, 0, 1), v["a1"], v["b1"], v["c1"]), (( 0, 0, 1), v["a1"], v["c1"], v["d1"]),
            (( 0, 0,-1), v["a0"], v["c0"], v["b0"]), (( 0, 0,-1), v["a0"], v["d0"], v["c0"]),
            (( 0,-1, 0), v["a0"], v["b0"], v["b1"]), (( 0,-1, 0), v["a0"], v["b1"], v["a1"]),
            (( 1, 0, 0), v["b0"], v["c0"], v["c1"]), (( 1, 0, 0), v["b0"], v["c1"], v["b1"]),
            (( 0, 1, 0), v["c0"], v["d0"], v["d1"]), (( 0, 1, 0), v["c0"], v["d1"], v["c1"]),
            ((-1, 0, 0), v["d0"], v["a0"], v["a1"]), ((-1, 0, 0), v["d0"], v["a1"], v["d1"]),
        ]
    return tris


def write_stl(path, tris, header=b"ArUco_Tracker_V2"):
    with open(path, "wb") as f:
        f.write(header.ljust(80, b"\0"))
        f.write(struct.pack("<I", len(tris)))
        for n, a, b, c in tris:
            f.write(struct.pack("<12fH", *n, *a, *b, *c, 0))
    return path


# ------------------------------------------------------------------ verify
def verify_geometry(dotrects, recs):
    """EXACT check, in floating point, before any rasterisation: every dot record
    must sit at the centre of its own footprint rectangle, and every dot must be
    the configured size. This is the real correctness gate -- the render below is
    a lossy measurement and cannot test better than its own pixel size."""
    dotrecs = [r for r in recs if r["category"] == "dot"]
    assert len(dotrects) == len(dotrecs), "dot rect/record mismatch"
    err = max(max(abs((r[0] + r[2]) / 2 - c["x_um"]),
                  abs((r[1] + r[3]) / 2 - c["y_um"]))
              for r, c in zip(dotrects, dotrecs))
    sides = {round(r[2] - r[0], 9) for r in dotrects} | {round(r[3] - r[1], 9)
                                                         for r in dotrects}
    # exact nearest-neighbour pitch, straight from the records (no rasterisation)
    from scipy.spatial import cKDTree
    Pd = np.array([[c["x_um"], c["y_um"]] for c in dotrecs], float)
    pitch = float(np.median(cKDTree(Pd).query(Pd, k=2)[0][:, 1]))
    print(f"\n  EXACT geometry: max |rect centre - record| = {err:.2e} um "
          f"over {len(dotrecs):,} dots; dot side(s) {sorted(sides)} um; "
          f"NN pitch {pitch:.6f} um")
    return err, sides, pitch


def verify_boxes(cfg: GridConfig, recs, info):
    """EXACT, per box: every dot of box N is the size and sits on the pitch the box
    was specified with, the count matches, and no dot is closer to a tag or a dash
    line than the box's own gap. Returns (ok, rows)."""
    from scipy.spatial import cKDTree
    tags = np.array([[r["x_um"], r["y_um"]] for r in recs if r["category"] == "aruco"], float)
    lines = [cfg.origin + k * cfg.box_pitch for k in range(cfg.grid_n + 1)]
    by_box = {}
    for r in recs:
        if r["category"] == "dot":
            by_box.setdefault(r["meta"]["box"], []).append((r["x_um"], r["y_um"]))
    ok, rows = True, []
    for b in info["boxes"]:
        P = np.array(by_box.get(b["box"], []), float).reshape(-1, 2)
        row = dict(box=b["box"], n=len(P), pitch=float("nan"), tag_clear=float("nan"),
                   dash_clear=float("nan"))
        good = len(P) == b["count"] and len(P) > 4
        if len(P) > 4:
            nn = cKDTree(P).query(P, k=2)[0][:, 1]
            row["pitch"] = float(np.median(nn))
            good &= abs(nn.min() - b["pitch_um"]) < 1e-9
            # edge-to-edge clearances (Chebyshev to the square tag; perpendicular to a line)
            cheb = np.min(np.maximum(np.abs(P[:, None, 0] - tags[None, :, 0]),
                                     np.abs(P[:, None, 1] - tags[None, :, 1])), axis=1)
            row["tag_clear"] = float(cheb.min() - cfg.tag_um / 2 - b["dot_um"] / 2)
            good &= row["tag_clear"] >= b["gap_um"] - 1e-9
            if cfg.dashes:
                d = np.min([np.minimum(np.abs(P[:, 0] - L), np.abs(P[:, 1] - L)) for L in lines], axis=0)
                row["dash_clear"] = float(d.min() - cfg.dash_width_um / 2 - b["dot_um"] / 2)
                good &= row["dash_clear"] >= b["gap_um"] - 1e-9
        row["ok"] = bool(good); ok &= bool(good); rows.append(row)
    return ok, rows


def verify(stl_path, cfg: GridConfig, recs, ppu=6.0):
    """Round-trip: render the written STL top-down, recover dots and decode every
    tag.

    NOTE ON TOLERANCE. `render_topdown` rasterises to an integer pixel grid, so a
    recovered centroid cannot be better than ~1 px = 1/ppu um. The position
    tolerance here is therefore expressed in PIXELS, not in a fixed um figure;
    the sub-micron correctness of the geometry is established by
    verify_geometry() above, in floating point."""
    import sys
    sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..",
                                                     "Reference_Warp_Tagger")))
    from rwtag.glyph import stl_glyphs as sg

    v, _n = sg.load_stl_triangles(stl_path)
    Pv = v.reshape(-1, 3)
    ext = (float(Pv[:, 0].max() - Pv[:, 0].min()), float(Pv[:, 1].max() - Pv[:, 1].min()))
    print(f"\n  STL outer extent {ext[0]:.2f} x {ext[1]:.2f} um "
          f"(target {cfg.extent:.2f}; V1 print 750.00)")

    img, to_px, to_um, _ = sg.render_topdown(stl_path, px_per_um=ppu)
    print(f"  rendered {img.shape[1]}x{img.shape[0]} px at {ppu} px/um")

    # --- dots: the small square components ---------------------------------
    n, lab, st, cen = cv2.connectedComponentsWithStats((img > 0).astype(np.uint8), 8)
    w = st[1:, cv2.CC_STAT_WIDTH] / ppu
    h = st[1:, cv2.CC_STAT_HEIGHT] / ppu
    sides = sorted({cfg.dot_side_um} | {float(b["dot_um"]) for b in cfg.box_specs})
    # One size: the original 0.4 um window. Several sizes (spectrum): the raster
    # can grow a feature by up to 1.5 px (0.25 um at 6 px/um) and the sizes are
    # >= 0.375 um apart, so 0.3 um accepts every dot; a dot matching two sizes is
    # still counted once (the masks are OR-ed).
    tol = 0.4 if len(sides) == 1 else 0.3
    isdot = np.zeros(len(w), bool)
    for side in sides:
        isdot |= (np.abs(w - side) < tol) & (np.abs(h - side) < tol)
    exp_dots = sum(1 for r in recs if r["category"] == "dot")
    print(f"  dot components {int(isdot.sum()):,}  (expected {exp_dots:,})")

    # --- dot positions vs the tag map --------------------------------------
    # OpenCV centroids are means of pixel INDICES; a region spanning pixels i..j
    # has centroid (i+j)/2, whose geometric centre is half a pixel further on.
    det = np.array([to_um(cen[1:][k][0] + 0.5, cen[1:][k][1] + 0.5)
                    for k in np.nonzero(isdot)[0]], float)
    ref = np.array([[r["x_um"], r["y_um"]] for r in recs if r["category"] == "dot"], float)
    err = float("nan")
    if len(det) and len(ref):
        from scipy.spatial import cKDTree
        d, _ = cKDTree(ref).query(det)
        err = float(np.max(d))
        print(f"  dot position error vs tag map: max {err:.4f} um, "
              f"median {np.median(d):.4f} um")

    # --- recovered pitch ----------------------------------------------------
    pitch = float("nan")
    if len(det) > 100:
        from scipy.spatial import cKDTree
        nn = cKDTree(det).query(det, k=2)[0][:, 1]
        pitch = float(np.median(nn))
        print(f"  recovered dot pitch {pitch:.4f} um  (config {cfg.dot_pitch_um})")

    # --- every tag must decode ---------------------------------------------
    d = aruco.getPredefinedDictionary(getattr(aruco, cfg.dict_name))
    det_a = aruco.ArucoDetector(d, aruco.DetectorParameters())
    inv = 255 - img                      # render is bright-on-dark; ArUco wants dark-on-light
    _c, ids, _r = det_a.detectMarkers(inv)
    found = {int(x) for x in ids.flatten()} if ids is not None else set()
    want = {int(v) for _i, _j, v in cfg.ids}
    print(f"  ArUco decoded {len(found & want)}/{len(want)} tags at {ppu} px/um "
          f"({cfg.module_um*ppu:.1f} px per module)")

    # One rasterised pixel bounds BOTH the centroid and the recovered pitch: at
    # 6 px/um a 3.77 um pitch snaps to exactly 22 px = 3.667 um. The exact pitch
    # is checked in floating point by verify_geometry().
    raster_tol = 1.0 / ppu                      # one pixel, in um
    checks = {
        "dot count exact": int(isdot.sum()) == exp_dots,
        f"dot position < 1 px ({raster_tol:.3f} um)": err < raster_tol,
        # a spectrum print has 25 pitches; they are checked box by box, exactly, by
        # verify_boxes() -- the single median pitch means nothing there
        f"pitch within 1 px ({raster_tol:.3f} um)": bool(cfg.box_specs)
                                                    or abs(pitch - cfg.dot_pitch_um) < raster_tol,
        "all tags decode": found >= want,
        f"outer extent == {cfg.field_um:.0f} um":
            cfg.fit != "inside" or (abs(ext[0] - cfg.field_um) < 1e-6
                                    and abs(ext[1] - cfg.field_um) < 1e-6),
    }
    print()
    for k, v in checks.items():
        print(f"    [{'PASS' if v else 'FAIL'}] {k}")
    ok = all(checks.values())
    return ok, dict(extent_um=ext, n_dots=int(isdot.sum()), expected_dots=exp_dots,
                    max_pos_err_um=err, raster_tol_um=raster_tol, pitch_um=pitch,
                    tags_decoded=len(found & want), tags_total=len(want),
                    checks={k: bool(v) for k, v in checks.items()}, pass_=bool(ok))


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=list(VARIANTS), default="conservative")
    ap.add_argument("--design", choices=list(SPACING_DESIGNS), default=None,
                    help="spacing-workshop design (5 / 6 / 7 um); overrides --variant")
    ap.add_argument("--name", default=None, help="output base name (default aruco_grid_<variant>)")
    ap.add_argument("--no-dashes", action="store_true",
                    help="omit the grid-marker tier (dashes are ON by default)")
    ap.add_argument("--dot-um", type=float, default=2.125,
                    help="dot side length (default 2.125 = the V1-proven size; "
                         "smaller packs tighter but anchors to the gel less well)")
    ap.add_argument("--no-round", action="store_true",
                    help="omit tag struts/fillets (sharp module corners)")
    ap.add_argument("--fit", choices=("inside", "lattice"), default="inside",
                    help="inside: outer extent == --field-um exactly (default); "
                         "lattice: node pitch == 150 um, corner tags overhang")
    ap.add_argument("--field-um", type=float, default=750.0,
                    help="overall printed extent (default 750, matching the V1 print)")
    ap.add_argument("--out", default=os.path.join(HERE, "..", "cad"))
    ap.add_argument("--ppu", type=float, default=6.0, help="verification render px/um")
    ap.add_argument("--verify-only", action="store_true")
    a = ap.parse_args()

    base = SPACING_DESIGNS[a.design] if a.design else VARIANTS[a.variant]
    cfg = GridConfig(**base, dashes=not a.no_dashes,
                     round_tags=not a.no_round, fit=a.fit, field_um=a.field_um,
                     dot_side_um=a.dot_um)
    out_dir = os.path.normpath(a.out)
    os.makedirs(out_dir, exist_ok=True)
    name = ((a.name or f"aruco_grid_{a.design or a.variant}")
            + ("" if abs(a.dot_um - 2.125) < 1e-9 else f"_dot{a.dot_um:g}")
            + ("" if cfg.dashes else "_nodash")
            + ("" if cfg.round_tags else "_sharp")
            + ("" if a.fit == "inside" else "_lattice"))
    stl_path = os.path.join(out_dir, name + ".stl")

    print(f"=== {name} ===")
    print(f"  OUTER EXTENT {cfg.extent:.2f} x {cfg.extent:.2f} um   "
          f"(V1 print: 750.00 x 750.00)   fit='{cfg.fit}'")
    print(f"  {cfg.grid_n}x{cfg.grid_n} boxes, node pitch {cfg.box_pitch:.2f} um · "
          f"{cfg.n_nodes} nodes")
    print(f"  tag {cfg.tag_um} um ({cfg.dict_name}, {cfg.tag_modules} modules of "
          f"{cfg.module_um:.2f} um) · keep-out r={cfg.keepout_um:.1f} um")
    print(f"  TIER 1 ArUco  {cfg.tag_um} um, {cfg.dict_name}, rounded="
          f"{cfg.round_tags} (neck {cfg.strut_w_um} um, fillet {cfg.fillet_um} um, "
          f"raster {cfg.tag_raster} px/module)")
    print(f"  TIER 2 grid   {'on' if cfg.dashes else 'OFF'}: dashes "
          f"{cfg.dash_len_um} x {cfg.dash_width_um} um, {cfg.dashes_per_edge}/edge, "
          f"dot keep-out {cfg.dash_clear_um:.2f} um")
    print(f"  TIER 3 dots   {cfg.dot_side_um} um square at {cfg.dot_pitch_um:.2f} um pitch "
          + (f"(GIVEN; tolerates a PSF up to {cfg.psf_max_um():.2f} um)"
             if cfg.dot_pitch_override_um > 0 else
             f"(derived: {cfg.sep_rule} x imaged spot, PSF {cfg.psf_fwhm_um} um)"))
    print(f"                gel contact {cfg.gel_contact_um2:.1f} um^2/dot"
          + ("   [V1-proven anchoring]" if abs(cfg.dot_side_um - 2.125) < 1e-9
             else f"   [!] BELOW the V1-proven 2.125 um "
                  f"({100*cfg.gel_contact_um2/21.5:.0f}% of its gel contact) "
                  f"— validate on the Phase-E coupon"))

    rects, recs, info = build(cfg)
    n_pinch = info["n_pinch"]
    cat = {}
    for r in recs:
        cat[r["category"]] = cat.get(r["category"], 0) + 1
    area = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in rects)
    print(f"\n  records: " + " · ".join(f"{k} {v:,}" for k, v in sorted(cat.items()))
          + f"   ({n_pinch} diagonal pinches bridged)")
    print(f"  footprint {area:,.0f} um^2 = {100*area/cfg.field_um**2:.1f}% areal fill"
          f"   (V1: 74,140 um^2 = 13.2%)")
    print(f"  volume {area*cfg.height_um:,.0f} um^3   (V1: 148,122 um^3)")

    if not a.verify_only:
        tris = stl_triangles(rects, cfg.height_um)
        write_stl(stl_path, tris)
        print(f"\n  wrote {os.path.basename(stl_path)}  "
              f"({len(tris):,} triangles, {os.path.getsize(stl_path)/1e6:.1f} MB)")

        tagmap = {"box_um": cfg.box_pitch, "grid_n": cfg.grid_n,
                  "dot_pitch": cfg.dot_pitch_um, "dot_phase": info["dot_phase"],
                  "dot_side_um": cfg.dot_side_um,
                  "generator": "aruco_grid.py", "config": asdict(cfg), "records": recs}
        with open(os.path.join(out_dir, name + ".reference_tags.json"), "w") as f:
            json.dump(tagmap, f)
        with open(os.path.join(out_dir, name + ".ids.json"), "w") as f:
            json.dump({"dict": cfg.dict_name, "modules": cfg.tag_modules,
                       "nodes": cfg.ids}, f, indent=1)
        print(f"  wrote {name}.reference_tags.json ({len(recs):,} records) + .ids.json")

    gerr, gsides, gpitch = verify_geometry(info["dot_rects"], recs)
    ok, stats = verify(stl_path, cfg, recs, ppu=a.ppu)
    exact_ok = (gerr < 1e-9 and gsides == {cfg.dot_side_um}
                and abs(gpitch - cfg.dot_pitch_um) < 1e-9)
    print(f"    [{'PASS' if exact_ok else 'FAIL'}] exact geometry "
          f"(centres, dot size, pitch = {gpitch:.6f} um)")
    stats.update(exact_geometry_err_um=gerr, exact_pitch_um=gpitch,
                 exact_ok=bool(exact_ok))
    ok = ok and exact_ok
    print(f"\n  PHASE-A GATE: {'PASS' if ok else 'FAIL'}")
    with open(os.path.join(out_dir, name + ".verify.json"), "w") as f:
        json.dump(stats, f, indent=1)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
