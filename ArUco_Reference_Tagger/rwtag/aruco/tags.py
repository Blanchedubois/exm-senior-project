"""
rwtag.aruco.tags
================
Decode every ArUco tag in a frame and return a full per-tag record: id, sub-pixel
corners, centre, rotation, corner-order sign, the printed side length, and a
decode confidence (bits corrected, Hamming margin to the nearest other id,
border errors, contrast). Flags, never silent drops: edge-band tags and
duplicated ids are returned with their flag set and `usable = False`.

Detector settings follow the V2 workshop (R16): decode on the plain-inverted
frame, NO CLAHE, errorCorrectionRate = 1.0, sub-pixel corner refinement.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import math
import numpy as np
import cv2
from cv2 import aruco


@dataclass
class ArucoParams:
    um_per_px: float = 0.510
    psf_fwhm_um: float = 2.5          # the microscope's PSF; sizes the dot top-hat (Phase 3)
    error_correction_rate: float = 1.0
    edge_band_um: float = 0.0         # extra fixed band at the frame edge; Stage 2 tests the exact
                                      # raw source instead (correct.raw_source_valid). find_aruco.py
                                      # on raw frames uses 48 (R16: |k1|·FOV/2·1.4)
    corner_refine: str = "contour"   # "contour" (best on the dummy frames) | "subpix" | "apriltag" | "none"
    corner_win_px: int = 0            # subpix only; 0 -> derived from the module size
    cell_px: int = 12                 # warped-patch resolution per module for the bit read
    invert: bool = True               # bright-on-dark fluorescence -> invert for ArUco
    detector_params: dict = field(default_factory=dict)   # extra cv2 DetectorParameters
    # ---- dots and dashes (port Phase 3) ----
    tophat: int = 0                   # 0 -> derived per dot size: >= 2 x imaged FWHM, odd, >= 11
    noise_k: float = 5.0              # threshold floor: median + k * robust sigma (0 -> plain Otsu)
    refine: str = "gauss"             # "gauss" (Gaussian-mask centroid) | "fit" (LSQ) | "none"
    refine_iters: int = 4
    mask_tags: bool = True            # drop dot detections inside decoded tags (module blobs)
    dash_min_aspect: float = 2.0
    raw_pass: bool = True             # also detect on the raw frame (independent raw positions)
    edge_margin_fwhm: float = 1.0     # a dot is "edge" if its raw source lies within this many FWHM of the raw border

    def imaged_fwhm_px(self, dot_side_um):
        return math.hypot(dot_side_um, self.psf_fwhm_um) / self.um_per_px

    def tophat_px(self, dot_side_um):
        if self.tophat:
            return int(self.tophat) | 1
        return max(11, int(math.ceil(2.0 * self.imaged_fwhm_px(dot_side_um))) | 1)

    def dot_area_px(self, dot_side_um):
        """Accepted blob area band for a dot of this printed size (px^2): from a
        third of the printed footprint to four times the larger of footprint and
        imaged spot (blobs grow with blur; tags and dashes are rejected by the
        roundness gates and the tag mask)."""
        side = dot_side_um / self.um_per_px
        big = max(side, self.imaged_fwhm_px(dot_side_um))
        return (max(6.0, 0.33 * side * side), 4.0 * big * big)

    def to_dict(self):
        from dataclasses import asdict
        return asdict(self)

    @property
    def edge_band_px(self):
        return self.edge_band_um / self.um_per_px


@dataclass
class TagObservation:
    aruco_id: int
    centre_px: np.ndarray            # (2,)
    corners_px: np.ndarray           # (4,2) TL, TR, BR, BL (canonical order)
    rot_deg: float                   # tag rotation, degrees, COUNTER-CLOCKWISE ON SCREEN positive
                                     # (= -atan2(dy, dx) of the TL->TR edge in y-down px; same sign as the
                                     # Stage-1 rotation slider / cv2.getRotationMatrix2D), from all four edges
    corner_sign: float               # sign of cross(TR-TL, BL-TL) in the image frame (+1 normally)
    side_px: float                   # mean edge length (rigid tag -> print scale)
    n_bits_corrected: int = 0        # Hamming distance read bits -> matched id
    margin_bits: int = 0             # Hamming distance read bits -> nearest OTHER id
    mirror_dist: int = 0             # Hamming distance of the MIRRORED read bits -> nearest id (any)
    border_errors: int = 0           # border modules read as white
    contrast: float = 0.0            # mean(white modules) - mean(black modules), image units
    in_edge_band: bool = False
    duplicate: bool = False

    @property
    def decode_class(self):
        if self.duplicate:
            return "duplicate"
        if self.margin_bits <= 1:
            return "ambiguous"
        return "clean" if self.n_bits_corrected == 0 else "corrected"

    @property
    def bits_handedness(self):
        """+1: the bits read directly (proper); -1: the mirrored bits match better
        (a mirrored frame); 0: tie (ids whose mirror is also a dictionary id)."""
        if self.n_bits_corrected < self.mirror_dist:
            return 1.0
        if self.mirror_dist < self.n_bits_corrected:
            return -1.0
        return 0.0

    @property
    def usable(self):
        return (not self.duplicate and not self.in_edge_band and self.margin_bits >= 2)

    def as_row(self):
        c = self.corners_px
        return {"aruco_id": self.aruco_id, "x": float(self.centre_px[0]), "y": float(self.centre_px[1]),
                **{f"c{k}{a}": float(c[k][i]) for k in range(4) for i, a in enumerate("xy")},
                "rot_deg": self.rot_deg, "side_px": self.side_px, "corner_sign": self.corner_sign,
                "n_bits_corrected": self.n_bits_corrected, "margin_bits": self.margin_bits,
                "mirror_dist": self.mirror_dist, "bits_handedness": self.bits_handedness,
                "border_errors": self.border_errors, "contrast": self.contrast,
                "in_edge_band": self.in_edge_band, "duplicate": self.duplicate,
                "decode_class": self.decode_class, "usable": self.usable}


# ------------------------------------------------------------------ detector
def dictionary(dict_name="DICT_4X4_50"):
    return aruco.getPredefinedDictionary(getattr(aruco, dict_name))


def detector(params: ArucoParams, dict_name="DICT_4X4_50", module_px=None):
    p = aruco.DetectorParameters()
    p.errorCorrectionRate = float(params.error_correction_rate)
    method = {"contour": aruco.CORNER_REFINE_CONTOUR, "subpix": aruco.CORNER_REFINE_SUBPIX,
              "apriltag": aruco.CORNER_REFINE_APRILTAG, "none": aruco.CORNER_REFINE_NONE}[params.corner_refine]
    p.cornerRefinementMethod = method
    if method == aruco.CORNER_REFINE_SUBPIX:
        win = params.corner_win_px or (max(3, int(round(0.6 * module_px))) if module_px else 5)
        p.cornerRefinementWinSize = int(win)
        p.cornerRefinementMaxIterations = 50
        p.cornerRefinementMinAccuracy = 0.01
    for k, v in params.detector_params.items():
        setattr(p, k, v)
    return aruco.ArucoDetector(dictionary(dict_name), p)


# ------------------------------------------------------------------ bits
def _read_bits(inv_u8, corners, marker_size, cell_px):
    """Warp the tag quad to a square of (marker_size + 2) cells and read one bit
    per module (1 = white on the INVERTED frame = a '1' bit in OpenCV's
    dictionary). Returns (payload bits (n,n) uint8, border_errors, contrast)."""
    n = marker_size + 2
    S = n * cell_px
    dst = np.array([[0, 0], [S - 1, 0], [S - 1, S - 1], [0, S - 1]], np.float32)
    H = cv2.getPerspectiveTransform(np.asarray(corners, np.float32), dst)
    patch = cv2.warpPerspective(inv_u8, H, (S, S), flags=cv2.INTER_LINEAR)
    cells = patch.reshape(n, cell_px, n, cell_px)
    inner = cells[:, cell_px // 4: -max(1, cell_px // 4), :, cell_px // 4: -max(1, cell_px // 4)]
    means = inner.mean(axis=(1, 3))                       # (n, n) per-module mean
    thr = 0.5 * (means.max() + means.min())
    bits_all = (means > thr).astype(np.uint8)
    border = np.ones((n, n), bool); border[1:-1, 1:-1] = False
    border_errors = int(bits_all[border].sum())
    payload = bits_all[1:-1, 1:-1]
    white = means[bits_all == 1]; black = means[bits_all == 0]
    contrast = float(white.mean() - black.mean()) if len(white) and len(black) else 0.0
    return payload, border_errors, contrast


def _confidence(dic, bits, aruco_id):
    """(n_bits_corrected, margin_bits, mirror_dist): Hamming distance of the read
    bits to the matched id, to the nearest OTHER id, and of the MIRRORED bits to
    the nearest id of all -- each over all four rotations. OpenCV returns the
    corners clockwise whatever the image, so a mirrored frame can only be seen in
    the bits: its mirrored pattern matches an id better than the direct read."""
    n_ids = dic.bytesList.shape[0]
    n_corr = int(dic.getDistanceToId(bits, int(aruco_id), True))
    margin = min(int(dic.getDistanceToId(bits, int(o), True)) for o in range(n_ids) if o != aruco_id)
    mb = np.ascontiguousarray(bits[:, ::-1])
    mirror = min(int(dic.getDistanceToId(mb, int(o), True)) for o in range(n_ids))
    return n_corr, margin, mirror


def _rotation_deg(c):
    """Rotation of a (near-)square from all four edges, counter-clockwise on screen
    positive: each edge direction is turned back to the TL->TR orientation, the
    four are averaged, and the y-down pixel angle is negated."""
    e = [c[1] - c[0], c[2] - c[1], c[3] - c[2], c[0] - c[3]]
    ang = [np.arctan2(v[1], v[0]) - k * np.pi / 2 for k, v in enumerate(e)]
    return -float(np.degrees(np.arctan2(np.mean(np.sin(ang)), np.mean(np.cos(ang)))))


# ------------------------------------------------------------------ decode
def decode_tags(u8, params: ArucoParams, dict_name="DICT_4X4_50", tag_um=None,
                tag_modules=6):
    """Decode every tag in an 8-bit bright-on-dark frame.
    Returns ({id: TagObservation}, info). All detections are returned; look at
    `.usable` / `.decode_class` before trusting one."""
    u8 = np.asarray(u8, np.uint8)
    inv = (255 - u8) if params.invert else u8
    module_px = (tag_um / tag_modules / params.um_per_px) if tag_um else None
    det = detector(params, dict_name, module_px)
    dic = det.getDictionary()
    corners, ids, _rej = det.detectMarkers(inv)
    H, W = inv.shape[:2]
    b = params.edge_band_px
    found = []                                           # [(id, TagObservation)] in detection order
    n_raw = 0 if ids is None else int(len(ids))
    if ids is not None:
        for c, i in zip(corners, ids.flatten()):
            c = np.asarray(c, float).reshape(4, 2)
            i = int(i)
            bits, border_err, contrast = _read_bits(inv, c, dic.markerSize, params.cell_px)
            n_corr, margin, mirror = _confidence(dic, bits, i)
            e1, e2 = c[1] - c[0], c[3] - c[0]
            sides = [np.linalg.norm(c[(k + 1) % 4] - c[k]) for k in range(4)]
            obs = TagObservation(
                aruco_id=i, centre_px=c.mean(0), corners_px=c,
                rot_deg=_rotation_deg(c),
                corner_sign=float(np.sign(e1[0] * e2[1] - e1[1] * e2[0]) or 1.0),
                side_px=float(np.mean(sides)),
                n_bits_corrected=n_corr, margin_bits=margin, mirror_dist=mirror, border_errors=border_err,
                contrast=contrast,
                in_edge_band=bool(c[:, 0].min() < b or c[:, 1].min() < b
                                  or c[:, 0].max() > W - 1 - b or c[:, 1].max() > H - 1 - b))
            found.append((i, obs))
    counts = {}
    for i, _o in found:
        counts[i] = counts.get(i, 0) + 1
    out, dupes = {}, sorted(i for i, n in counts.items() if n > 1)
    for i, obs in found:                                 # keep the first of a duplicated id, flagged
        obs.duplicate = counts[i] > 1
        out.setdefault(i, obs)
    info = {"n_raw": n_raw, "n_usable": sum(o.usable for o in out.values()),
            "n_edge_band": sum(o.in_edge_band for o in out.values()),
            "dupes": sorted(dupes), "n_ambiguous": sum(o.decode_class == "ambiguous" for o in out.values()),
            "dict": dict_name}
    return out, info
