#!/usr/bin/env python3
"""
simulate_rigid_spread.py
========================
Simulate the RIGID-ISLAND case: the ArUco markers (and the interior dots)
keep their exact size and internal pattern, but their POSITIONS spread apart
as the hydrogel expands, rotates and warps non-uniformly. Then detect the
markers and RECOVER the distortion field -- i.e. run the actual measurement.

Contrast with simulate_expansion.py (the "everything swells" case, where the
image itself is warped so the markers' internal modules distort and can
eventually break). Here each feature is a rigid stamp that only TRANSLATES /
rotates rigidly, so:

    * markers NEVER distort internally -> they always decode, at any
      expansion factor and under any warp (the only limits are staying in
      frame and remaining resolvable);
    * the measurement comes entirely from how far the features spread.

Applied deformation (microns):
    x = c + lambda0 * R(theta) * (X - c) + bump(X)
    bump(X) = A * exp(-|X - wc|^2 / 2 sigma^2) * outward_unit(X - wc)
    -> a localized region of EXTRA local expansion, so det(F) varies in space.

Pipeline demonstrated:
    detect ArUco -> node positions by ID -> displacement u(X)
    -> per-box deformation gradient F -> areal expansion J = det F
    -> residual (warpage) after removing the global similarity.

Outputs
-------
  rigid_spread_scene.png   imaged expanded scene with ArUco detections
  rigid_spread_field.png   recovered warpage quiver + local-expansion J heatmap
  prints markers-decoded and displacement-recovery RMS error

Requires: opencv-contrib-python, numpy, matplotlib, generate_pattern.py
"""

from __future__ import annotations
import numpy as np
import cv2
import cv2.aruco as aruco

from generate_pattern import (PatternConfig, generate, get_dictionary,
                              make_detector, draw_marker)


# ----------------------------------------------------------------------
def deform(P_um, c, lam, theta_deg, A, sigma, wc):
    """Apply expansion+rotation+localized bump to points P (N,2) in microns."""
    th = np.deg2rad(theta_deg)
    ct, st = np.cos(th), np.sin(th)
    d = P_um - c
    xr = np.stack([ct * d[:, 0] - st * d[:, 1], st * d[:, 0] + ct * d[:, 1]], 1)
    out = c + lam * xr
    # localized outward bump -> spatially varying expansion
    dw = P_um - wc
    r = np.hypot(dw[:, 0], dw[:, 1]) + 1e-9
    g = A * np.exp(-(r ** 2) / (2 * sigma ** 2))
    out += np.stack([g * dw[:, 0] / r, g * dw[:, 1] / r], 1)
    return out


def paste_min(canvas, stamp, cx, cy):
    s = stamp.shape[0]
    x0, y0 = int(round(cx - s / 2)), int(round(cy - s / 2))
    x1, y1 = x0 + s, y0 + s
    H, W = canvas.shape
    if x0 < 0 or y0 < 0 or x1 > W or y1 > H:
        sx0, sy0 = max(0, -x0), max(0, -y0)
        sx1, sy1 = s - max(0, x1 - W), s - max(0, y1 - H)
        cx0, cy0 = max(0, x0), max(0, y0)
        if sx1 <= sx0 or sy1 <= sy0:
            return
        canvas[cy0:cy0 + (sy1 - sy0), cx0:cx0 + (sx1 - sx0)] = np.minimum(
            canvas[cy0:cy0 + (sy1 - sy0), cx0:cx0 + (sx1 - sx0)], stamp[sy0:sy1, sx0:sx1])
    else:
        canvas[y0:y1, x0:x1] = np.minimum(canvas[y0:y1, x0:x1], stamp)


def rot_stamp(stamp, theta_deg):
    s = stamp.shape[0]
    pad = int(s * 0.25)
    big = np.full((s + 2 * pad, s + 2 * pad), 255, np.uint8)
    big[pad:pad + s, pad:pad + s] = stamp
    S = big.shape[0]
    M = cv2.getRotationMatrix2D((S / 2, S / 2), -theta_deg, 1.0)
    return cv2.warpAffine(big, M, (S, S), borderValue=255)


def fit_affine(U, D):
    """Least-squares linear map D = A U + t; return 2x2 A."""
    n = U.shape[0]
    G = np.hstack([U, np.ones((n, 1))])          # (n,3)
    sol, *_ = np.linalg.lstsq(G, D, rcond=None)  # (3,2)
    return sol[:2, :].T                          # 2x2


# ----------------------------------------------------------------------
def main():
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cfg = PatternConfig(n_boxes_x=3, n_boxes_y=3, box_size_um=30.0,
                        marker_um=6.0, dot_pitch_um=1.5, px_per_um=10.0,
                        marker_border_bits=1)
    ref, meta = generate(cfg)
    ppu = cfg.px_per_um
    total = meta["n_nodes"]

    Wum, Hum = meta["field_size_um"]
    c = np.array([Wum / 2, Hum / 2])

    # applied deformation params
    lam, theta = 3.0, 15.0
    A, sigma = 7.0, 22.0
    wc = np.array([Wum * 0.62, Hum * 0.42])       # bump centre (off-centre)

    # ---- ground-truth deformed positions ----
    node_U = np.array([[n["x_um"], n["y_um"]] for n in meta["nodes"]])
    node_ids = [n["id"] for n in meta["nodes"]]
    node_D = deform(node_U, c, lam, theta, A, sigma, wc)

    dot_U = np.array([[f["x_um"], f["y_um"]] for b in meta["boxes"] for f in b["features"]])
    dot_D = deform(dot_U, c, lam, theta, A, sigma, wc)

    # ---- render the "imaged" expanded scene (rigid stamps) ----
    allD = np.vstack([node_D, dot_D])
    pad_um = cfg.marker_um * 1.5
    minxy = allD.min(0) - pad_um
    span = (allD.max(0) - minxy) + pad_um
    Wpx, Hpx = int(span[0] * ppu), int(span[1] * ppu)
    canvas = np.full((Hpx, Wpx), 255, np.uint8)

    def to_px(P):
        q = (P - minxy) * ppu
        return q

    # dots (rigid, fixed size)
    rdot = max(1, int(round(cfg.dot_diameter_um / 2 * ppu)))
    for p in to_px(dot_D):
        cv2.circle(canvas, (int(round(p[0])), int(round(p[1]))), rdot, 0, -1, cv2.LINE_AA)

    # markers (rigid, fixed size, rigidly rotated by theta)
    dictionary = get_dictionary(cfg.aruco_dict)
    marker_px = int(round(cfg.marker_um * ppu))
    for nid, p in zip(node_ids, to_px(node_D)):
        stamp = draw_marker(dictionary, nid, marker_px, cfg.marker_border_bits)
        stamp = rot_stamp(stamp, theta)
        paste_min(canvas, stamp, p[0], p[1])

    # ---- detect ----
    detect = make_detector(dictionary)
    corners, ids = detect(canvas)
    n_dec = 0 if ids is None else len(ids)
    det_center = {}
    if ids is not None:
        for k, idv in enumerate(ids.flatten()):
            det_center[int(idv)] = corners[k].reshape(-1, 2).mean(0)  # px

    # ---- recover node displacements (by ID) ----
    U_rec, D_rec_um = [], []
    for nid, U in zip(node_ids, node_U):
        if nid in det_center:
            d_um = det_center[nid] / ppu + minxy
            U_rec.append(U); D_rec_um.append(d_um)
    U_rec = np.array(U_rec); D_rec_um = np.array(D_rec_um)

    # recovery error vs ground truth
    gt = {nid: d for nid, d in zip(node_ids, node_D)}
    err = np.array([np.hypot(*(D_rec_um[i] - gt[node_ids[node_ids.index(node_ids[i])]]))
                    for i in range(len(U_rec))]) if False else None
    # simpler: align recovered to the same ids used
    rec_ids = [nid for nid in node_ids if nid in det_center]
    D_true = np.array([gt[i] for i in rec_ids])
    rms_um = float(np.sqrt(np.mean(np.sum((D_rec_um - D_true) ** 2, 1))))

    # ---- per-box areal expansion J = det F ----
    inv = {nid: k for k, nid in enumerate(node_ids)}
    nx = cfg.n_boxes_x
    Jmap = np.full((cfg.n_boxes_y, cfg.n_boxes_x), np.nan)
    for b in meta["boxes"]:
        ids4 = list(b["corner_node_ids"].values())
        if all(i in det_center for i in ids4):
            U4 = np.array([node_U[inv[i]] for i in ids4])
            D4 = np.array([det_center[i] / ppu + minxy for i in ids4])
            F = fit_affine(U4, D4)
            Jmap[b["box_j"], b["box_i"]] = np.linalg.det(F)

    # residual (warpage) after removing the global similarity fit
    Fg = fit_affine(U_rec, D_rec_um)
    tg = D_rec_um.mean(0) - (U_rec.mean(0) @ Fg.T)
    resid = D_rec_um - (U_rec @ Fg.T + tg)

    # ---- figure 1: imaged scene ----
    vis = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)
    if ids is not None:
        aruco.drawDetectedMarkers(vis, corners, ids, borderColor=(0, 200, 0))
    fig, ax = plt.subplots(figsize=(8, 8), dpi=120)
    ax.imshow(cv2.cvtColor(vis, cv2.COLOR_BGR2RGB))
    ax.set_title(f"Rigid islands spread by expansion (lambda={lam}) + rotation "
                 f"({theta} deg) + local bump\n{n_dec}/{total} markers decoded — "
                 f"rigid markers never distort internally", fontsize=10)
    ax.axis("off"); fig.tight_layout(); fig.savefig("rigid_spread_scene.png"); plt.close(fig)

    # ---- figure 2: recovered field ----
    fig, axes = plt.subplots(1, 2, figsize=(15, 6.2), dpi=120)
    # (a) warpage residual quiver on undeformed frame
    axes[0].quiver(U_rec[:, 0], U_rec[:, 1], resid[:, 0], resid[:, 1],
                   np.hypot(resid[:, 0], resid[:, 1]), cmap="viridis",
                   angles="xy", scale_units="xy", scale=1)
    axes[0].set_title("Recovered warpage (residual after removing mean expansion+rotation)\n"
                      "vectors at marker nodes", fontsize=10)
    axes[0].set_aspect("equal"); axes[0].invert_yaxis()
    axes[0].set_xlabel("um"); axes[0].set_ylabel("um")
    # (b) per-box areal expansion J heatmap
    im = axes[1].imshow(Jmap, cmap="magma", origin="upper")
    axes[1].set_title(f"Local areal expansion  J = det F  per box\n"
                      f"(uniform would be lambda^2 = {lam**2:.0f}; bump raises it locally)",
                      fontsize=10)
    for (jj, ii), val in np.ndenumerate(Jmap):
        if not np.isnan(val):
            axes[1].text(ii, jj, f"{val:.0f}", ha="center", va="center",
                         color="w", fontsize=11, fontweight="bold")
    axes[1].set_xticks(range(cfg.n_boxes_x)); axes[1].set_yticks(range(cfg.n_boxes_y))
    axes[1].set_xlabel("box i"); axes[1].set_ylabel("box j")
    fig.colorbar(im, ax=axes[1], fraction=0.046, label="J = det F")
    fig.suptitle("Measurement recovered from rigid markers spreading apart", fontsize=12)
    fig.tight_layout(); fig.savefig("rigid_spread_field.png"); plt.close(fig)

    # ---- report ----
    print(f"Markers decoded         : {n_dec}/{total}")
    print(f"Displacement recovery RMS: {rms_um*1000:.1f} nm  "
          f"({rms_um/cfg.px_per_um*ppu:.4f} um)  [~ marker-center localization precision]")
    print(f"Global expansion (fit)   : det = {np.linalg.det(Fg):.2f}  (applied lambda^2 = {lam**2:.0f})")
    print(f"J range across boxes     : {np.nanmin(Jmap):.1f} .. {np.nanmax(Jmap):.1f} "
          f"(uniform = {lam**2:.0f}; higher near the imposed bump)")
    print("\nOutputs: rigid_spread_scene.png, rigid_spread_field.png")


if __name__ == "__main__":
    main()
