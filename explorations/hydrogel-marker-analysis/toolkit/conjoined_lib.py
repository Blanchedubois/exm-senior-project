#!/usr/bin/env python3
"""
conjoined_lib.py
================
Shared library for the conjoined-ArUco hydrogel marker system.

Single source of truth for GEOMETRY (in microns) so the PNG and SVG outputs
match exactly. A tag is drawn as its black modules (rects) plus smooth
elliptical STRUTS that bridge diagonal (corner-only) pinches so the whole tag
is one connected rigid piece.

Primitives (all coordinates in microns, origin top-left, y down):
  ("rect",    x, y, w, h)
  ("ellipse", cx, cy, rx, ry, angle_deg)
  ("circle",  cx, cy, r)
  ("dline",   x0, y0, x1, y1, width, dash, gap)   # dashed line

Renderers:
  render_png(prims, W_um, H_um, px_per_um) -> uint8 image (0=black,255=white)
  render_svg(prims, W_um, H_um)            -> SVG string (viewBox in um, size in mm)
"""
from __future__ import annotations
import numpy as np
import cv2
import cv2.aruco as aruco

N_MODULES = 8            # 6x6 data + 2 border modules
DICT_NAME = "DICT_6X6_1000"


# ---------------------------------------------------------------- ArUco
def get_dictionary():
    return aruco.getPredefinedDictionary(getattr(aruco, DICT_NAME))


def module_map(marker_id):
    """N x N grid, 1 = black module (includes the 1-module border)."""
    img = aruco.generateImageMarker(get_dictionary(), marker_id, N_MODULES, 1)
    return (img < 128).astype(np.uint8)


def n_components(m, conn):
    return cv2.connectedComponents(m, connectivity=conn)[0] - 1


def make_detector():
    return aruco.ArucoDetector(get_dictionary(), aruco.DetectorParameters())


def decodes(img, marker_id):
    _, ids, _ = make_detector().detectMarkers(img)
    return ids is not None and marker_id in [int(x) for x in ids.flatten()]


# ---------------------------------------------------------------- geometry
def marker_primitives(marker_id, cx_um, cy_um, size_um,
                      strut_w_um=0.20, strut_len_frac=0.72, add_struts=True):
    """Rects for black modules + smooth elliptical struts at diagonal pinches.
    `size_um` is the full tag side length; module = size_um / N_MODULES."""
    m = module_map(marker_id)
    mod = size_um / N_MODULES
    x0, y0 = cx_um - size_um / 2.0, cy_um - size_um / 2.0
    prims = []
    for r in range(N_MODULES):
        for c in range(N_MODULES):
            if m[r, c]:
                prims.append(("rect", x0 + c * mod, y0 + r * mod, mod, mod))
    if add_struts and strut_w_um > 0:
        major = strut_len_frac * mod
        for r in range(N_MODULES - 1):
            for c in range(N_MODULES - 1):
                a, b = m[r, c], m[r, c + 1]
                cc, d = m[r + 1, c], m[r + 1, c + 1]
                if a and d and not b and not cc:
                    ang = 45.0
                elif b and cc and not a and not d:
                    ang = 135.0
                else:
                    continue
                vx, vy = x0 + (c + 1) * mod, y0 + (r + 1) * mod
                prims.append(("ellipse", vx, vy, major / 2.0, strut_w_um / 2.0, ang))
    return prims


def circle_primitive(cx_um, cy_um, r_um):
    return ("circle", cx_um, cy_um, r_um)


def dashed_rect(x0, y0, x1, y1, width, dash, gap):
    return [("dline", x0, y0, x1, y0, width, dash, gap),
            ("dline", x1, y0, x1, y1, width, dash, gap),
            ("dline", x1, y1, x0, y1, width, dash, gap),
            ("dline", x0, y1, x0, y0, width, dash, gap)]


# ---------------------------------------------------------------- PNG
def render_png(prims, W_um, H_um, px_per_um):
    ppu = px_per_um
    W, H = int(round(W_um * ppu)), int(round(H_um * ppu))
    img = np.full((H, W), 255, np.uint8)
    for p in prims:
        k = p[0]
        if k == "rect":
            _, x, y, w, h = p
            x0, y0 = int(round(x * ppu)), int(round(y * ppu))
            x1, y1 = int(round((x + w) * ppu)), int(round((y + h) * ppu))
            img[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = 0
        elif k == "ellipse":
            _, cx, cy, rx, ry, ang = p
            cv2.ellipse(img, (int(round(cx * ppu)), int(round(cy * ppu))),
                        (max(1, int(round(rx * ppu))), max(1, int(round(ry * ppu)))),
                        ang, 0, 360, 0, -1, cv2.LINE_AA)
        elif k == "circle":
            _, cx, cy, r = p
            cv2.circle(img, (int(round(cx * ppu)), int(round(cy * ppu))),
                       max(1, int(round(r * ppu))), 0, -1, cv2.LINE_AA)
        elif k == "dline":
            _, x0, y0, x1, y1, width, dash, gap = p
            _png_dashed(img, x0, y0, x1, y1, width, dash, gap, ppu)
    return img


def _png_dashed(img, x0, y0, x1, y1, width, dash, gap, ppu):
    length = np.hypot(x1 - x0, y1 - y0)
    if length <= 0:
        return
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    t = max(1, int(round(width * ppu)))
    d = 0.0
    while d < length:
        e = min(d + dash, length)
        cv2.line(img, (int(round((x0 + ux * d) * ppu)), int(round((y0 + uy * d) * ppu))),
                 (int(round((x0 + ux * e) * ppu)), int(round((y0 + uy * e) * ppu))),
                 0, t, cv2.LINE_AA)
        d += dash + gap


# ---------------------------------------------------------------- SVG
def render_svg(prims, W_um, H_um, background=True):
    mm = lambda v: v / 1000.0
    out = [f'<?xml version="1.0" encoding="UTF-8"?>',
           f'<!-- units: 1 viewBox unit = 1 micron; physical size = '
           f'{W_um:.3f} x {H_um:.3f} um. black = write region. -->',
           f'<svg xmlns="http://www.w3.org/2000/svg" '
           f'width="{mm(W_um):.5f}mm" height="{mm(H_um):.5f}mm" '
           f'viewBox="0 0 {W_um:.4f} {H_um:.4f}">']
    if background:
        out.append(f'<rect x="0" y="0" width="{W_um:.4f}" height="{H_um:.4f}" fill="white"/>')
    body = ['<g fill="black" stroke="none">']
    lines = []
    for p in prims:
        k = p[0]
        if k == "rect":
            _, x, y, w, h = p
            body.append(f'<rect x="{x:.4f}" y="{y:.4f}" width="{w:.4f}" height="{h:.4f}"/>')
        elif k == "ellipse":
            _, cx, cy, rx, ry, ang = p
            body.append(f'<ellipse cx="{cx:.4f}" cy="{cy:.4f}" rx="{rx:.4f}" ry="{ry:.4f}" '
                        f'transform="rotate({ang:.1f} {cx:.4f} {cy:.4f})"/>')
        elif k == "circle":
            _, cx, cy, r = p
            body.append(f'<circle cx="{cx:.4f}" cy="{cy:.4f}" r="{r:.4f}"/>')
        elif k == "dline":
            _, x0, y0, x1, y1, width, dash, gap = p
            lines.append(f'<line x1="{x0:.4f}" y1="{y0:.4f}" x2="{x1:.4f}" y2="{y1:.4f}" '
                         f'stroke="black" stroke-width="{width:.4f}" '
                         f'stroke-dasharray="{dash:.3f} {gap:.3f}"/>')
    body.append('</g>')
    out += body + lines + ['</svg>']
    return "\n".join(out)


# ---------------------------------------------------------------- ID curation
def scan_conjoinable(n_ids=1000):
    """Return dict of ID lists by connectivity of the black pattern."""
    solid, conjoinable, needs_struts = [], [], []
    for i in range(n_ids):
        m = module_map(i)
        n4, n8 = n_components(m, 4), n_components(m, 8)
        if n8 == 1:
            conjoinable.append(i)
            if n4 == 1:
                solid.append(i)
            else:
                needs_struts.append(i)
    return {"dict": DICT_NAME, "n_scanned": n_ids,
            "conjoinable_ids": conjoinable,          # single 8-connected -> one piece w/ struts
            "solid_no_struts": solid,                # single 4-connected -> already solid
            "needs_struts": needs_struts}            # multi 4- but single 8-connected
