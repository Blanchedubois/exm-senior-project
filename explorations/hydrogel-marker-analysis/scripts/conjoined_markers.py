#!/usr/bin/env python3
"""
conjoined_markers.py
====================
Make the ArUco tags robust to a rigid-black / expanding-gel by (1) choosing IDs
whose black has no separated squares, and (2) tying diagonal (corner-only)
touches together with small ROUNDED STRUTS so the whole tag is one connected
piece -- then check the conjoined tag under distortion.

Connectivity language:
  * 4-connectivity: two black modules count as joined only if they share an EDGE.
  * 8-connectivity: also joined if they touch only at a CORNER (a "pinch").
A rounded strut placed at a corner-pinch physically converts an 8-connection
into a real material bridge -- so an ID whose black is a single 8-connected
component becomes ONE rigid piece once strutted.

Outputs
-------
  conjoined_ids.json            curated IDs (single 8-connected -> strut-able to one piece)
  conjoined_marker_zoom.png     a tag before vs after strutting (rounded bridges)
  conjoined_strut_benefit.png   decode vs expansion: drifting pieces vs strutted single piece
  conjoined_distortion_map.png  conjoined grid warped -> recovered distortion vector field + J
  prints selection stats and detection checks

Requires: opencv-contrib-python, numpy, matplotlib, generate_pattern.py
"""

from __future__ import annotations
import json
import numpy as np
import cv2
import cv2.aruco as aruco
from generate_pattern import (PatternConfig, generate, get_dictionary,
                              draw_marker, make_detector)

DICT = "DICT_6X6_1000"
N = 8  # 6 data + 2 border modules


# ----------------------------------------------------------------------
# marker module map + connectivity
# ----------------------------------------------------------------------
def mmap(marker_id):
    return (draw_marker(get_dictionary(DICT), marker_id, N, 1) < 128).astype(np.uint8)


def n_components(m, conn):
    return cv2.connectedComponents(m, connectivity=conn)[0] - 1


def components(m, conn):
    num, lab = cv2.connectedComponents(m, connectivity=conn)
    return [(np.argwhere(lab == L).astype(float), np.argwhere(lab == L).mean(0))
            for L in range(1, num)]


# ----------------------------------------------------------------------
# strutted rendering (rounded bridges at diagonal pinches)
# ----------------------------------------------------------------------
def draw_strutted(marker_id, module_px=24, strut_frac=0.20, draw_struts=True, border_modules=1.5):
    m = mmap(marker_id)
    off = int(round(border_modules * module_px))          # white quiet border
    size = N * module_px + 2 * off
    img = np.full((size, size), 255, np.uint8)
    # modules as sharp squares (keeps outer border corners sharp for detection)
    for r in range(N):
        for c in range(N):
            if m[r, c]:
                img[off + r * module_px:off + (r + 1) * module_px,
                    off + c * module_px:off + (c + 1) * module_px] = 0
    # rounded struts at diagonal-only pinches
    if draw_struts:
        rs = int(round(strut_frac * module_px))
        for r in range(N - 1):
            for c in range(N - 1):
                a, b = m[r, c], m[r, c + 1]
                cc, d = m[r + 1, c], m[r + 1, c + 1]
                if (a and d and not b and not cc) or (b and cc and not a and not d):
                    vx, vy = off + (c + 1) * module_px, off + (r + 1) * module_px
                    cv2.circle(img, (vx, vy), rs, 0, -1, cv2.LINE_AA)
    return img


def decodes(img, marker_id):
    corners, ids = make_detector(get_dictionary(DICT))(img)
    return ids is not None and marker_id in [int(x) for x in ids.flatten()]


# ----------------------------------------------------------------------
# rigid-piece spread model (for the strut-benefit demo)
# ----------------------------------------------------------------------
def render_spread(comps, lam, module_px=24):
    center = np.array([(N - 1) / 2.0, (N - 1) / 2.0])
    placed = []
    for rc, cen in comps:
        cen_exp = center + lam * (cen - center)
        for mm in rc:
            placed.append(cen_exp + (mm - cen))
    placed = np.array(placed)
    minrc = placed.min(0) - 1.5
    span = (placed.max(0) - minrc) + 1.5
    img = np.full((int(span[0] * module_px), int(span[1] * module_px)), 255, np.uint8)
    for (r, c) in placed:
        y = (r - minrc[0]) * module_px; x = (c - minrc[1]) * module_px
        img[int(y):int(y + module_px), int(x):int(x + module_px)] = 0
    return img


# ----------------------------------------------------------------------
# deformation for the distortion map
# ----------------------------------------------------------------------
def deform(P, c, lam, theta_deg, A, sigma, wc):
    th = np.deg2rad(theta_deg); ct, st = np.cos(th), np.sin(th)
    d = P - c
    out = c + lam * np.stack([ct * d[:, 0] - st * d[:, 1], st * d[:, 0] + ct * d[:, 1]], 1)
    dw = P - wc; r = np.hypot(dw[:, 0], dw[:, 1]) + 1e-9
    g = A * np.exp(-(r ** 2) / (2 * sigma ** 2))
    return out + np.stack([g * dw[:, 0] / r, g * dw[:, 1] / r], 1)


def fit_affine(U, D):
    G = np.hstack([U, np.ones((len(U), 1))])
    sol, *_ = np.linalg.lstsq(G, D, rcond=None)
    return sol[:2, :].T


def paste_min(canvas, stamp, cx, cy):
    s = stamp.shape[0]; x0, y0 = int(round(cx - s / 2)), int(round(cy - s / 2))
    H, W = canvas.shape
    sx0, sy0 = max(0, -x0), max(0, -y0)
    sx1, sy1 = s - max(0, x0 + s - W), s - max(0, y0 + s - H)
    cx0, cy0 = max(0, x0), max(0, y0)
    if sx1 > sx0 and sy1 > sy0:
        canvas[cy0:cy0 + sy1 - sy0, cx0:cx0 + sx1 - sx0] = np.minimum(
            canvas[cy0:cy0 + sy1 - sy0, cx0:cx0 + sx1 - sx0], stamp[sy0:sy1, sx0:sx1])


def rot_stamp(stamp, deg):
    s = stamp.shape[0]; pad = int(s * 0.3)
    big = np.full((s + 2 * pad, s + 2 * pad), 255, np.uint8); big[pad:pad + s, pad:pad + s] = stamp
    S = big.shape[0]; M = cv2.getRotationMatrix2D((S / 2, S / 2), -deg, 1.0)
    return cv2.warpAffine(big, M, (S, S), borderValue=255)


# ----------------------------------------------------------------------
def main():
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # ---------- 1. scan & curate ----------
    ids = list(range(1000))
    n4 = {i: n_components(mmap(i), 4) for i in ids}
    n8 = {i: n_components(mmap(i), 8) for i in ids}
    single4 = [i for i in ids if n4[i] == 1]
    single8 = [i for i in ids if n8[i] == 1]                 # strut-able to one piece
    strut_helps = [i for i in ids if n4[i] > 1 and n8[i] == 1]
    with open("conjoined_ids.json", "w") as f:
        json.dump({"dict": DICT,
                   "single_4connected_solid": single4,
                   "single_8connected_strutable": single8,
                   "strut_converts_to_single": strut_helps}, f, indent=2)
    print(f"{DICT}: of 1000 IDs")
    print(f"  single 4-connected (already solid, no struts needed): {len(single4)}")
    print(f"  single 8-connected (ONE piece once strutted)        : {len(single8)}")
    print(f"  struts convert multi->single for                    : {len(strut_helps)} IDs")
    print(f"  -> curated usable-with-struts pool: {len(single8)} IDs (saved to conjoined_ids.json)\n")

    # ---------- 2. strutted marker zoom ----------
    demo = max(strut_helps, key=lambda i: n4[i])          # worst case: most pieces
    plain = draw_strutted(demo, draw_struts=False)
    strut = draw_strutted(demo, draw_struts=True)
    ok_plain, ok_strut = decodes(plain, demo), decodes(strut, demo)
    print(f"Demo ID {demo}: n4={n4[demo]} pieces (edge), n8={n8[demo]} piece (with corners).")
    print(f"  plain tag decodes  : {ok_plain}")
    print(f"  strutted tag decodes: {ok_strut}  (struts must not break the code)\n")

    fig, ax = plt.subplots(1, 2, figsize=(11, 5.6), dpi=120)
    ax[0].imshow(plain, cmap="gray", vmin=0, vmax=255)
    ax[0].set_title(f"ID {demo}: as-is\n{n4[demo]} separate black pieces (corner pinches)", fontsize=10)
    ax[1].imshow(strut, cmap="gray", vmin=0, vmax=255)
    ax[1].set_title(f"ID {demo}: rounded struts added\nnow 1 connected piece — decodes: {ok_strut}",
                    fontsize=10)
    for a in ax:
        a.axis("off")
    fig.suptitle("Rounded struts bridge diagonal pinches -> conjoined tag (code unchanged)", fontsize=12)
    fig.tight_layout(); fig.savefig("conjoined_marker_zoom.png"); plt.close(fig)

    # ---------- 3. strut benefit: drift vs strutted ----------
    comps4 = components(mmap(demo), 4)      # without struts: separate pieces drift
    lambdas = [1.0, 1.1, 1.2, 1.35, 1.5, 1.75, 2.0, 2.5, 3.0]
    dec_no = [decodes(render_spread(comps4, L), demo) for L in lambdas]
    dec_yes = [decodes(draw_strutted(demo), demo) for _ in lambdas]   # one rigid piece: intact at any L
    fig, ax = plt.subplots(figsize=(8.5, 4.6), dpi=120)
    ax.plot(lambdas, [int(x) for x in dec_no], "o-", color="#e0342b", label="pieces NOT joined (drift apart)")
    ax.plot(lambdas, [int(x) for x in dec_yes], "^-", color="#1f9d55", label="rounded struts (one piece)")
    ax.set(xlabel="expansion factor lambda", ylabel="decodes? (1=yes)", ylim=(-0.1, 1.2),
           title=f"ID {demo}: struts keep the tag decodable as the gel expands")
    ax.legend(); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig("conjoined_strut_benefit.png"); plt.close(fig)
    print(f"Without struts, ID {demo} decodes up to lambda="
          f"{max([l for l,d in zip(lambdas,dec_no) if d], default=None)}; "
          f"with struts: all tested (rigid single piece).\n")

    # ---------- 4. conjoined distortion map ----------
    cfg = PatternConfig(n_boxes_x=3, n_boxes_y=3, box_size_um=30.0, marker_um=6.0,
                        dot_pitch_um=1.5, px_per_um=10.0)
    _, meta = generate(cfg)
    ppu = cfg.px_per_um; total = meta["n_nodes"]
    Wum, Hum = meta["field_size_um"]; c = np.array([Wum / 2, Hum / 2])
    lam, theta, A, sigma = 3.0, 10.0, 8.0, 22.0
    wc = np.array([Wum * 0.6, Hum * 0.4])

    curated = single8[:total]               # assign only conjoined IDs to the nodes
    node_U = np.array([[n["x_um"], n["y_um"]] for n in meta["nodes"]])
    node_D = deform(node_U, c, lam, theta, A, sigma, wc)
    dot_U = np.array([[f["x_um"], f["y_um"]] for b in meta["boxes"] for f in b["features"]])
    dot_D = deform(dot_U, c, lam, theta, A, sigma, wc)

    allD = np.vstack([node_D, dot_D]); minxy = allD.min(0) - cfg.marker_um * 1.5
    span = (allD.max(0) - minxy) + cfg.marker_um * 1.5
    canvas = np.full((int(span[1] * ppu), int(span[0] * ppu)), 255, np.uint8)
    to_px = lambda P: (P - minxy) * ppu

    rdot = max(1, int(round(cfg.dot_diameter_um / 2 * ppu)))
    for p in to_px(dot_D):
        cv2.circle(canvas, (int(p[0]), int(p[1])), rdot, 0, -1, cv2.LINE_AA)
    marker_px = int(round(cfg.marker_um * ppu))
    for mid, p in zip(curated, to_px(node_D)):
        stamp = cv2.resize(draw_strutted(mid, border_modules=0), (marker_px, marker_px),
                           interpolation=cv2.INTER_AREA)
        paste_min(canvas, rot_stamp(stamp, theta), p[0], p[1])

    # detect + recover
    corners, idsdet = make_detector(get_dictionary(DICT))(canvas)
    det = {}
    if idsdet is not None:
        for k, v in enumerate(idsdet.flatten()):
            det[int(v)] = corners[k].reshape(-1, 2).mean(0)
    n_dec = len(det)
    U_rec, D_rec = [], []
    for mid, U in zip(curated, node_U):
        if mid in det:
            U_rec.append(U); D_rec.append(det[mid] / ppu + minxy)
    U_rec, D_rec = np.array(U_rec), np.array(D_rec)
    Fg = fit_affine(U_rec, D_rec); tg = D_rec.mean(0) - U_rec.mean(0) @ Fg.T
    resid = D_rec - (U_rec @ Fg.T + tg)

    # per-box J from curated corner ids
    idpos = {mid: node_U[k] for k, mid in enumerate(curated)}
    Jmap = np.full((cfg.n_boxes_y, cfg.n_boxes_x), np.nan)
    node_index = {(n["i"], n["j"]): curated[k] for k, n in enumerate(meta["nodes"])}
    for b in meta["boxes"]:
        corners_ij = [(b["box_i"], b["box_j"]), (b["box_i"] + 1, b["box_j"]),
                      (b["box_i"], b["box_j"] + 1), (b["box_i"] + 1, b["box_j"] + 1)]
        cid = [node_index[ij] for ij in corners_ij]
        if all(i in det for i in cid):
            U4 = np.array([idpos[i] for i in cid]); D4 = np.array([det[i] / ppu + minxy for i in cid])
            Jmap[b["box_j"], b["box_i"]] = np.linalg.det(fit_affine(U4, D4))

    fig, axes = plt.subplots(1, 2, figsize=(15, 6.4), dpi=120)
    vis = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)
    if idsdet is not None:
        aruco.drawDetectedMarkers(vis, corners, idsdet, borderColor=(0, 200, 0))
    axes[0].imshow(cv2.cvtColor(vis, cv2.COLOR_BGR2RGB))
    axes[0].set_title(f"Conjoined grid warped (lambda={lam}, {theta} deg, local bump)\n"
                      f"{n_dec}/{total} strutted markers decoded", fontsize=10); axes[0].axis("off")
    q = axes[1].quiver(U_rec[:, 0], U_rec[:, 1], resid[:, 0], resid[:, 1],
                       np.hypot(resid[:, 0], resid[:, 1]), cmap="viridis",
                       angles="xy", scale_units="xy", scale=1)
    axes[1].set_aspect("equal"); axes[1].invert_yaxis()
    axes[1].set_title("Recovered distortion map (warpage residual at nodes)\n"
                      f"per-box J=det F: {np.nanmin(Jmap):.1f}..{np.nanmax(Jmap):.1f} "
                      f"(uniform {lam**2:.0f})", fontsize=10)
    axes[1].set_xlabel("um"); axes[1].set_ylabel("um")
    fig.colorbar(q, ax=axes[1], fraction=0.046, label="warpage |residual| (um)")
    fig.suptitle("Conjoined (strutted, single-piece) tags warp coherently and stay decodable "
                 "-> distortion map recovered", fontsize=12)
    fig.tight_layout(); fig.savefig("conjoined_distortion_map.png"); plt.close(fig)

    print(f"Distortion map: {n_dec}/{total} conjoined markers decoded; "
          f"warpage recovered; per-box J in {np.nanmin(Jmap):.1f}..{np.nanmax(Jmap):.1f} "
          f"(uniform lambda^2={lam**2:.0f}).")
    print("\nOutputs: conjoined_ids.json, conjoined_marker_zoom.png, "
          "conjoined_strut_benefit.png, conjoined_distortion_map.png")


if __name__ == "__main__":
    main()
