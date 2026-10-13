"""
rwtag.io
========
Image loading and 8-bit conversion. Ported from Reference_Warp_Tagger/rwtag/io.py
(the parts Phase 1 needs); the session sidecars arrive with Phase 2.
"""
from __future__ import annotations
import os
import re
import numpy as np

try:
    import tifffile
except Exception:                                    # pragma: no cover
    tifffile = None
import cv2

IMG_EXTS = (".tif", ".tiff", ".png", ".jpg", ".jpeg")


def load_tiff(path: str, page: int = 0, project: str = "none") -> np.ndarray:
    """Load a TIFF (or any image) as a single-channel float32 array.
    page: which page of a multipage TIFF; project: "none" | "max"."""
    arr = None
    if tifffile is not None and str(path).lower().endswith((".tif", ".tiff")):
        try:
            data = tifffile.imread(path)
            if data.ndim == 2:
                arr = data
            elif data.ndim == 3 and data.shape[-1] in (3, 4):
                arr = cv2.cvtColor(data[..., :3], cv2.COLOR_RGB2GRAY)
            elif data.ndim == 3:
                arr = data.max(0) if project == "max" else data[min(page, len(data) - 1)]
            else:
                arr = np.asarray(data).reshape(data.shape[-2:])
        except Exception:
            arr = None
    if arr is None:
        img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if img is None:
            raise IOError(f"could not read image: {path}")
        arr = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return np.asarray(arr, dtype=np.float32)


def to_uint8(img: np.ndarray, low_pct: float = 0.5, high_pct: float = 99.5) -> np.ndarray:
    """Percentile-stretch a float image to uint8 for display / detection."""
    a = np.asarray(img)
    if a.dtype == np.uint8:
        return a
    finite = a[np.isfinite(a)]
    if finite.size == 0:
        return np.zeros(a.shape, np.uint8)
    lo, hi = np.percentile(finite, [low_pct, high_pct])
    if hi <= lo:
        hi = lo + 1.0
    return (np.clip((a - lo) / (hi - lo), 0, 1) * 255.0).astype(np.uint8)


def to_uint8_robust(img: np.ndarray, bg_pct: float = 50.0) -> np.ndarray:
    """8-bit conversion for DECODING: black point at the background (median), white
    point at the brightest real feature (the max of a 3x3-median-filtered copy,
    so hot pixels do not set it). Unlike the percentile stretch this never
    saturates the tags: at high expansion the printed features are a tiny fraction
    of the frame and the 99.5th percentile falls to the noise floor, which clips
    every tag and erodes its dark modules until the bits misread."""
    a = np.asarray(img)
    if a.dtype == np.uint8:
        return a
    f = a.astype(np.float32)
    finite = f[np.isfinite(f)]
    if finite.size == 0:
        return np.zeros(a.shape, np.uint8)
    lo = float(np.percentile(finite, bg_pct))
    hi = float(cv2.medianBlur(f, 3).max())
    if hi <= lo:
        hi = lo + 1.0
    return (np.clip((f - lo) / (hi - lo), 0, 1) * 255.0).astype(np.uint8)


def display_levels(img: np.ndarray, low_pct: float = 0.5, high_pct: float = 99.5):
    finite = img[np.isfinite(img)]
    if finite.size == 0:
        return 0.0, 1.0
    lo, hi = np.percentile(finite, [low_pct, high_pct])
    return float(lo), float(hi if hi > lo else lo + 1.0)


def preview_downsample(img: np.ndarray, max_side: int = 1200) -> np.ndarray:
    h, w = img.shape[:2]
    s = max(h, w)
    if s <= max_side:
        return img.astype(np.float32, copy=False)
    f = max_side / float(s)
    return cv2.resize(img.astype(np.float32), (max(1, int(round(w * f))),
                      max(1, int(round(h * f)))), interpolation=cv2.INTER_AREA)


def parse_label(filename):
    """'1.5X…' / '1.5x…' -> 1.5; None when the name has no leading <float>X."""
    m = re.match(r"^([0-9]+(?:\.[0-9]+)?)[xX]", os.path.basename(filename))
    return float(m.group(1)) if m else None
