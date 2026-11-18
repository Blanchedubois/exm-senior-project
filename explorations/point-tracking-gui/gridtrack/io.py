"""
gridtrack.io
============
Image and session IO. Headless: returns/accepts NumPy arrays and plain dicts.
"""
from __future__ import annotations
import json
import numpy as np

try:
    import tifffile
except Exception:                                    # pragma: no cover
    tifffile = None
import cv2

from .types import CorrectionParams


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


def save_session(path: str, source_path: str, params: CorrectionParams) -> None:
    """Persist the Stage-1 tuning so it is reproducible / re-openable."""
    with open(path, "w") as f:
        json.dump({"source_path": source_path, "correction": params.to_dict()}, f, indent=2)


def load_session(path: str) -> tuple[str, CorrectionParams]:
    with open(path) as f:
        d = json.load(f)
    return d.get("source_path"), CorrectionParams.from_dict(d.get("correction", {}))
