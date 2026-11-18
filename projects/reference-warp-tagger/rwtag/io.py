"""
rwtag.io
========
Image and session IO. Headless: returns/accepts NumPy arrays and plain dicts.

Ported from the Point-Tracking GUI (`gridtrack/io.py`) and extended for the
Reference-Warp Tagger:
  * sessions now capture BOTH the shared optics (CorrectionParams) and the
    per-image levels (LevelsParams) plus the shared/per-image flags, so the exact
    processed image can be regenerated (Stage 4 tags on that image);
  * sidecar helpers derive/write `<image>.rwsession.json` next to a frame so
    per-image params are auto-discovered on open;
  * `preview_downsample` supports the interactive live-preview (full 7 MP frames
    are too slow to re-correct on every slider tick).
"""
from __future__ import annotations
import json
import os
import numpy as np

try:
    import tifffile
except Exception:                                    # pragma: no cover
    tifffile = None
import cv2

from .types import CorrectionParams, LevelsParams

SESSION_VERSION = 1
SIDECAR_SUFFIX = ".rwsession.json"


# ---------------------------------------------------------------- image load
def load_tiff(path: str, page: int = 0, project: str = "none") -> np.ndarray:
    """Load a TIFF (or any image) as a single-channel float32 array.

    page     : which page of a multipage TIFF to read.
    project  : "none" -> that page; "max" -> max-intensity projection over pages.
    """
    arr = None
    if tifffile is not None and str(path).lower().endswith((".tif", ".tiff")):
        try:                                         # tifffile (best multipage support)
            data = tifffile.imread(path)
            if data.ndim == 2:
                arr = data
            elif data.ndim == 3 and data.shape[-1] in (3, 4):   # RGB(A) single page
                arr = cv2.cvtColor(data[..., :3], cv2.COLOR_RGB2GRAY)
            elif data.ndim == 3:                                # page stack
                arr = data.max(0) if project == "max" else data[min(page, len(data) - 1)]
            else:
                arr = np.asarray(data).reshape(data.shape[-2:])
        except Exception:                            # e.g. LZW without imagecodecs -> cv2
            arr = None
    if arr is None:                                  # fallback for png/jpg / compressed tif
        img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if img is None:
            raise IOError(f"could not read image: {path}")
        arr = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return np.asarray(arr, dtype=np.float32)


def to_uint8(img: np.ndarray, low_pct: float = 0.5, high_pct: float = 99.5) -> np.ndarray:
    """Percentile-stretch a float image to uint8 for display / detection."""
    finite = img[np.isfinite(img)]
    if finite.size == 0:
        return np.zeros(img.shape, np.uint8)
    lo, hi = np.percentile(finite, [low_pct, high_pct])
    if hi <= lo:
        hi = lo + 1.0
    out = np.clip((img - lo) / (hi - lo), 0, 1) * 255.0
    return out.astype(np.uint8)


def display_levels(img: np.ndarray, low_pct: float = 0.5, high_pct: float = 99.5):
    """(lo, hi) percentile display range for a pyqtgraph ImageItem, so a freshly
    opened dim frame shows its features immediately -- independent of the levels
    CORRECTION (which is a separate, exported transform)."""
    finite = img[np.isfinite(img)]
    if finite.size == 0:
        return 0.0, 1.0
    lo, hi = np.percentile(finite, [low_pct, high_pct])
    if hi <= lo:
        hi = lo + 1.0
    return float(lo), float(hi)


def preview_downsample(img: np.ndarray, max_side: int = 1200) -> np.ndarray:
    """Area-downsample so the longest side is <= max_side, for the interactive
    live preview. Returns the input unchanged if already small enough. The
    correction chain is resolution-relative (vignette/lens/levels are per-pixel;
    the FFT cut-off is in x-Nyquist), so the preview matches the full result."""
    h, w = img.shape[:2]
    s = max(h, w)
    if s <= max_side:
        return img.astype(np.float32, copy=False)
    f = max_side / float(s)
    return cv2.resize(img.astype(np.float32), (max(1, int(round(w * f))),
                      max(1, int(round(h * f)))), interpolation=cv2.INTER_AREA)


# ---------------------------------------------------------------- session IO
def sidecar_path(image_path: str) -> str:
    """`<image>.rwsession.json` next to the frame."""
    return os.fspath(image_path) + SIDECAR_SUFFIX


def session_dict(source_path: str, correction: CorrectionParams,
                 levels: LevelsParams, shared_flags: dict | None = None) -> dict:
    return {
        "version": SESSION_VERSION,
        "source_path": source_path,
        "correction": correction.to_dict(),
        "levels": levels.to_dict(),
        "shared_flags": dict(shared_flags or {}),
    }


def save_session(path: str, source_path: str, correction: CorrectionParams,
                 levels: LevelsParams, shared_flags: dict | None = None) -> None:
    """Persist the full Stage-1 tuning (optics + per-image levels + flags) so the
    processed image is reproducible / re-openable."""
    with open(path, "w") as f:
        json.dump(session_dict(source_path, correction, levels, shared_flags), f, indent=2)


def load_session(path: str) -> tuple[str, CorrectionParams, LevelsParams, dict]:
    """Restore (source_path, correction, levels, shared_flags). Tolerant of the
    old two-field format (correction only) and of unknown future keys."""
    with open(path) as f:
        d = json.load(f)
    correction = CorrectionParams.from_dict(d.get("correction", {}))
    levels = LevelsParams.from_dict(d.get("levels", {}))
    return d.get("source_path"), correction, levels, dict(d.get("shared_flags", {}))
