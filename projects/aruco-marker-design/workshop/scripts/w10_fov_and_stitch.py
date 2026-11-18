#!/usr/bin/env python3
"""
w10_fov_and_stitch.py — Workshop W10 (Rev D, Phase 4).

QUESTION
    How wide should the stitched field be at high expansion? The scaling law
    (plan section 2) says dots in view ~ (stitch / (pitch * lambda))^2, and W9
    measured the constant of proportionality end to end at lambda = 6 for the
    current 1365 um stitch. Sweep the stitch width and read off what each
    candidate needs to keep >= 1,000 usable dots at lambda_max.

WHY THE V1 DERATE NO LONGER APPLIES
    On the real V1 series only ~33% of the geometrically-visible dots paired,
    because the "initial" 1.5x frame already overflowed the field and the
    pairing was by lattice registration. In V2 the reference frame holds the
    ENTIRE pattern (750 um in a 1365 um field) and pairing is by tag identity,
    so a dot detected in an expanded frame is always pairable. W9's usable-dot
    counts are therefore the paired counts.

METHOD
    usable(lambda, S) = D * eff * ((S - 2 b) / (750 lambda))^2, capped at D*eff
    with D = dots in the print, eff = W9 worst-frame efficiency, b = the 25 um
    un-distortion band. The model is checked against W9's measured lambda = 6
    counts for the 1365 um stitch (it should agree to within the rotation and
    drift W9 included), then swept over S. Acquisition cost ~ (S / 1365)^2
    (tile count, hence time and bleaching exposure), independent of tile size.
    Tags in view at lambda_max are reported too (registration redundancy).

PASS (WORKSHOP_PLAN.md section 4)
    The stitch width at which >= 1,000 paired dots survive at lambda_max, per
    candidate, with its cost.

Run:  python w10_fov_and_stitch.py
"""
from __future__ import annotations
import json
import math
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FIG_DIR = os.path.normpath(os.path.join(HERE, "..", "figures"))
OUT_JSON = os.path.join(FIG_DIR, "w10_fov_and_stitch.json")

FIELD, BAND, S_NOW = 750.0, 25.0, 1365.0
NODE_PITCH = {"OPT": 145.4, "HEDGE": 144.6, "SAFE": 143.2}      # (750 - tag) / 5
DOTS = {"OPT": 17825, "HEDGE": 12825, "SAFE": 8625}
WIDTHS = [1365, 1700, 2048, 2730, 3400, 4096, 5460]
LAM_MAX = [4, 5, 6]


def usable(cand, lam, S, eff):
    frac = min(1.0, ((S - 2 * BAND) / (FIELD * lam)) ** 2)
    return DOTS[cand] * eff * frac


def tags_in_view(cand, lam, S):
    return min(36.0, ((S - 2 * BAND) / (NODE_PITCH[cand] * lam)) ** 2)


def main():
    os.makedirs(FIG_DIR, exist_ok=True)
    w9 = json.load(open(os.path.join(FIG_DIR, "w9_candidate_montage.json")))
    diag = {"OPT": "1.91", "HEDGE": "2.5", "SAFE": "3.18"}         # each print at its design PSF
    eff = {c: w9["table"][c][p]["dot_eff_min"] for c, p in diag.items()}
    meas6 = {c: w9["table"][c][p]["dots_l6"] for c, p in diag.items()}

    print("model check against W9 (lambda = 6, current 1365 um stitch):")
    print(f"{'print':<7}{'eff':>6}{'model':>8}{'W9 measured':>13}{'ratio':>7}")
    ratio = {}
    for c in DOTS:
        m = usable(c, 6, S_NOW, eff[c]); ratio[c] = meas6[c] / m
        print(f"{c:<7}{eff[c]:>6.0%}{m:>8.0f}{meas6[c]:>13,}{ratio[c]:>7.2f}")
    k = float(np.mean(list(ratio.values())))
    print(f"  -> calibration factor {k:.2f} (rotation + drift crop that the pure-area model omits); applied below\n")

    results = {}
    print(f"{'print':<7}{'λmax':>5}" + "".join(f"{w:>8}" for w in WIDTHS) + "    need for >=1,000")
    for c in DOTS:
        results[c] = {}
        for lam in LAM_MAX:
            row = [k * usable(c, lam, S, eff[c]) for S in WIDTHS]
            need = next((S for S, u in zip(WIDTHS, row) if u >= 1000), None)
            # exact width for 1,000 from the model (before the cap)
            S_exact = FIELD * lam * math.sqrt(1000.0 / (k * DOTS[c] * eff[c])) + 2 * BAND
            results[c][str(lam)] = dict(usable=dict(zip(map(str, WIDTHS), row)), need_width=need,
                                        need_width_exact=S_exact, cost=(S_exact / S_NOW) ** 2,
                                        tags_at_need=tags_in_view(c, lam, S_exact))
            print(f"{c:<7}{lam:>5}" + "".join(f"{u:>8,.0f}" for u in row)
                  + f"    {S_exact:>6.0f} um  (x{(S_exact/S_NOW)**2:.1f} area, {tags_in_view(c, lam, S_exact):.0f} tags)")
    print("\n(columns = stitch width in um; current = 1365; cost = area relative to current = tile count)")

    print("\nW10 — stitch width for >= 1,000 paired dots at λmax:")
    for c in DOTS:
        print("  " + c + ": " + " · ".join(f"λ{l}: {results[c][str(l)]['need_width_exact']:.0f} um "
                                              f"(x{results[c][str(l)]['cost']:.1f})" for l in LAM_MAX))

    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.4), dpi=110)
    Ss = np.linspace(1000, 6000, 200)
    for c in DOTS:
        ax1.plot(Ss, [k * usable(c, 6, S, eff[c]) for S in Ss], label=f"{c} (λ = 6)")
        ax1.plot(Ss, [k * usable(c, 4, S, eff[c]) for S in Ss], ":", c=ax1.lines[-1].get_color(), label=f"{c} (λ = 4)")
    ax1.axhline(1000, c="k", ls="--", lw=0.8, label="1,000 dots"); ax1.axvline(S_NOW, c="grey", ls=":", lw=0.8)
    ax1.set_xlabel("stitch width (um)"); ax1.set_ylabel("paired dots in the stitch"); ax1.set_yscale("log")
    ax1.grid(alpha=.3, which="both"); ax1.legend(fontsize=7); ax1.set_title("paired dots vs stitch width", fontsize=10)
    for c in DOTS:
        ax2.plot(LAM_MAX, [results[c][str(l)]["need_width_exact"] for l in LAM_MAX], "o-", label=c)
    ax2.axhline(S_NOW, c="grey", ls=":", lw=0.8, label="current 1365 um")
    ax2.set_xlabel("λmax"); ax2.set_ylabel("stitch width for >= 1,000 paired dots (um)")
    ax2.grid(alpha=.3); ax2.legend(fontsize=8); ax2.set_title("required stitch vs λmax", fontsize=10)
    fig.suptitle("W10 — field of view / stitch width (model calibrated to W9 at λ = 6)", fontsize=10)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(os.path.join(FIG_DIR, "stitch_width.png")); plt.close(fig)
    with open(OUT_JSON, "w") as f:
        json.dump(dict(calibration=k, eff=eff, widths=WIDTHS, results=results), f, indent=1, default=float)
    print("\nwrote figures/stitch_width.png + w10_fov_and_stitch.json")


if __name__ == "__main__":
    main()
