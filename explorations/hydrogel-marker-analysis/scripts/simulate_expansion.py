#!/usr/bin/env python3
"""
simulate_expansion.py
=====================
Simulate what an imaged fiducial pattern looks like after the hydrogel it
sits on has EXPANDED, ROTATED, and locally WARPED -- then re-run the ArUco
detector to check the markers still decode.

The deformation is applied to the WHOLE image, so the individual black
squares (modules) INSIDE each ArUco marker expand/rotate/warp too -- i.e.
the "everything swells" (co-swelling) case.

Forward map  (reference coord X  ->  imaged coord x):

        x = c_out + lambda * R(theta) * (X - c) + W(X)

  lambda : linear expansion factor (2-5)
  R(theta): rigid rotation of the whole grid
  W(X)   : optional non-uniform warpage

Key physics the sim demonstrates:
  * Uniform expansion + rotation is a SIMILARITY transform -> ArUco is
    invariant to it: markers always decode, however far apart they move.
  * A GENTLE (long-wavelength) warp is near-affine across a small marker
    -> still decodes.
  * Only a SHARP warp whose wavelength approaches the MARKER SIZE makes the
    marker's internal module grid non-affine enough to corrupt the code.
    Even then, neighbours still ID the box -> graceful degradation.

Outputs
-------
  sim_panels.png        reference | expanded+rotated | +gentle warp (all decode)
  sim_decode_sweep.png  decoded vs expansion / rotation / gentle warp / warp wavelength
  sim_breakpoint.png    short-wavelength warp finally dropping markers

Requires: opencv-contrib-python, numpy, matplotlib, generate_pattern.py
"""

from __future__ import annotations
import numpy as np
import cv2
import cv2.aruco as aruco

from generate_pattern import PatternConfig, generate, get_dictionary, make_detector


# ----------------------------------------------------------------------
# Warp builders: return f(Xx, Xy) -> (wx, wy) displacement in pixels
# ----------------------------------------------------------------------
def gaussian_warp(cx, cy, amp_px, sigma_px):
    """Long-wavelength bump -> near-affine across a small marker."""
    def f(Xx, Xy):
        g = np.exp(-((Xx - cx) ** 2 + (Xy - cy) ** 2) / (2.0 * sigma_px ** 2))
        return amp_px * g, 0.5 * amp_px * g
    return f


def sine_warp(amp_px, period_px):
    """Short-wavelength warp; when period ~ marker size the internal
    module grid becomes strongly non-affine."""
    k = 2.0 * np.pi / period_px
    def f(Xx, Xy):
        return amp_px * np.sin(k * Xy), amp_px * np.sin(k * Xx)
    return f


# ----------------------------------------------------------------------
def render_deformed(ref, lam, theta_deg, warp_fn=None, pad=40):
    H, W = ref.shape
    cx, cy = W / 2.0, H / 2.0
    th = np.deg2rad(theta_deg)
    ct, st = np.cos(th), np.sin(th)

    corners = np.array([[0, 0], [W, 0], [0, H], [W, H]], float)
    fx = lam * (ct * (corners[:, 0] - cx) - st * (corners[:, 1] - cy))
    fy = lam * (st * (corners[:, 0] - cx) + ct * (corners[:, 1] - cy))
    out_w = int(np.ceil(fx.max() - fx.min())) + 2 * pad
    out_h = int(np.ceil(fy.max() - fy.min())) + 2 * pad
    coutx, couty = pad - fx.min(), pad - fy.min()

    py, px = np.meshgrid(np.arange(out_h, dtype=np.float32),
                         np.arange(out_w, dtype=np.float32), indexing="ij")
    Xx = px / lam; Xy = py / lam
    iters = 1 if warp_fn is None else 4
    for _ in range(iters):
        if warp_fn is None:
            wx = wy = 0.0
        else:
            wx, wy = warp_fn(Xx, Xy)
        ex = (px - coutx - wx) / lam
        ey = (py - couty - wy) / lam
        Xx = cx + ct * ex + st * ey
        Xy = cy - st * ex + ct * ey

    return cv2.remap(ref, Xx.astype(np.float32), Xy.astype(np.float32),
                     interpolation=cv2.INTER_LINEAR, borderValue=255)


def count_decoded(img, cfg):
    detect = make_detector(get_dictionary(cfg.aruco_dict))
    corners, ids = detect(img)
    n = 0 if ids is None else len(ids)
    return n, corners, ids


def panel(ax, img, cfg, total, title):
    n, corners, ids = count_decoded(img, cfg)
    vis = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if ids is not None:
        aruco.drawDetectedMarkers(vis, corners, ids, borderColor=(0, 200, 0))
    ax.imshow(cv2.cvtColor(vis, cv2.COLOR_BGR2RGB))
    ax.set_title(f"{title}\n{n}/{total} markers decoded", fontsize=11)
    ax.axis("off")
    return n


# ----------------------------------------------------------------------
def main():
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cfg = PatternConfig(n_boxes_x=3, n_boxes_y=3, box_size_um=30.0,
                        marker_um=6.0, dot_pitch_um=1.5, px_per_um=8.0,
                        draw_box_boundary=True)
    ref, meta = generate(cfg)
    total = meta["n_nodes"]
    ppu = cfg.px_per_um
    cx = cy = ref.shape[0] / 2.0

    print(f"Reference: {count_decoded(ref, cfg)[0]}/{total} markers decoded\n")

    # ---- illustrative panels ----
    fig, axes = plt.subplots(1, 3, figsize=(16, 6), dpi=120)
    panel(axes[0], render_deformed(ref, 1.0, 0.0), cfg, total, "reference\n(lambda=1, 0 deg)")
    panel(axes[1], render_deformed(ref, 3.0, 25.0), cfg, total,
          "expanded + rotated\n(lambda=3, 25 deg)")
    panel(axes[2], render_deformed(ref, 3.0, 25.0, gaussian_warp(cx, cy, 10 * ppu, 18 * ppu)),
          cfg, total, "+ gentle warpage\n(lambda=3, 25 deg, 18 um scale)")
    fig.suptitle("Rigid grid under expansion + rotation + gentle warpage — all markers survive",
                 fontsize=13)
    fig.tight_layout(); fig.savefig("sim_panels.png"); plt.close(fig)

    # ---- sweeps ----
    lambdas = [1.0, 2.0, 3.0, 4.0, 5.0]
    d_lam = [count_decoded(render_deformed(ref, L, 25.0), cfg)[0] for L in lambdas]

    thetas = [0, 30, 60, 90]
    d_th = [count_decoded(render_deformed(ref, 3.0, float(t)), cfg)[0] for t in thetas]

    gentle_amp = [0, 8, 16]
    d_gentle = [count_decoded(render_deformed(ref, 3.0, 25.0,
                gaussian_warp(cx, cy, a * ppu, 18 * ppu)), cfg)[0] for a in gentle_amp]

    periods = [30, 16, 10, 7, 5, 4]      # warp wavelength (um); marker = 6 um
    d_period = [count_decoded(render_deformed(ref, 3.0, 25.0,
                sine_warp(1.2 * ppu, p * ppu)), cfg)[0] for p in periods]

    fig, axes = plt.subplots(1, 4, figsize=(19, 4.3), dpi=120)
    axes[0].plot(lambdas, d_lam, "o-", color="#1f9d55")
    axes[0].set(title="vs expansion (25 deg)", xlabel="lambda",
                ylabel=f"decoded / {total}", ylim=(0, total + 1))
    axes[1].plot(thetas, d_th, "o-", color="#1166cc")
    axes[1].set(title="vs rotation (lambda=3)", xlabel="deg", ylim=(0, total + 1))
    axes[2].plot(gentle_amp, d_gentle, "o-", color="#e08a00")
    axes[2].set(title="vs gentle warp amp (18 um scale)", xlabel="amp (um)", ylim=(0, total + 1))
    axes[3].plot(periods, d_period, "o-", color="#e0342b")
    axes[3].axvline(cfg.marker_um, ls="--", color="gray")
    axes[3].set(title="vs warp WAVELENGTH (amp 1.2 um)", xlabel="period (um)  [dashed = marker size]",
                ylim=(0, total + 1))
    for ax in axes:
        ax.grid(alpha=0.3)
    fig.suptitle("Decode survival: expansion, rotation and gentle warp are free; "
                 "markers break only when warp wavelength approaches marker size", fontsize=12)
    fig.tight_layout(); fig.savefig("sim_decode_sweep.png"); plt.close(fig)

    # ---- breaking-point panels: short-wavelength warp ----
    fig, axes = plt.subplots(1, 3, figsize=(16, 6), dpi=120)
    for ax, p in zip(axes, [16, 7, 4]):
        panel(ax, render_deformed(ref, 3.0, 25.0, sine_warp(1.2 * ppu, p * ppu)),
              cfg, total, f"warp wavelength {p} um (marker 6 um)")
    fig.suptitle("Breaking point: as warp wavelength approaches the marker size, "
                 "internal modules go non-affine and codes drop (box still IDed by neighbours)",
                 fontsize=12)
    fig.tight_layout(); fig.savefig("sim_breakpoint.png"); plt.close(fig)

    # ---- report ----
    print("Expansion (25 deg):        " + "  ".join(f"L={L}:{n}" for L, n in zip(lambdas, d_lam)))
    print("Rotation (lambda=3):       " + "  ".join(f"{t}deg:{n}" for t, n in zip(thetas, d_th)))
    print("Gentle warp (18um scale):  " + "  ".join(f"{a}um:{n}" for a, n in zip(gentle_amp, d_gentle)))
    print("Warp wavelength (amp1.2):  " + "  ".join(f"{p}um:{n}" for p, n in zip(periods, d_period)))
    print(f"(all counts out of {total})")
    print("\nOutputs: sim_panels.png, sim_decode_sweep.png, sim_breakpoint.png")


if __name__ == "__main__":
    main()
