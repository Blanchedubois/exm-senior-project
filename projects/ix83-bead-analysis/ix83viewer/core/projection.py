"""Collapse a T-stack into one image (mean / max / min / sum / median / single frame).

Results are cached as .npy under ~/Library/Caches/ix83-bead-analysis (override with
IX83_CACHE_DIR) so re-opening a 400 MB iCloud stack is instant.  The cache
key includes the TIFF's size and mtime, so a changed file is recomputed.
"""

from __future__ import annotations

import hashlib
import os

import numpy as np

from ..io.mm_dataset import MMDataset

METHODS = ("mean", "max", "min", "sum", "median", "frame")

# Median needs every frame in memory at once; cap the frames it samples
# (100 x 1412 x 1412 x uint16 = 400 MB).
MEDIAN_MAX_FRAMES = 100


def cache_dir() -> str:
    d = os.environ.get("IX83_CACHE_DIR") or os.path.expanduser("~/Library/Caches/ix83-bead-analysis")
    os.makedirs(d, exist_ok=True)
    return d


def frame_indices(n_frames: int, start: int = 0, stop: int | None = None, max_frames: int | None = None) -> list[int]:
    stop = n_frames if stop is None else min(stop, n_frames)
    idx = list(range(max(0, start), stop))
    if not idx:
        raise ValueError(f"Empty frame range {start}:{stop} for {n_frames} frames")
    if max_frames and len(idx) > max_frames:
        picks = np.linspace(0, len(idx) - 1, max_frames).round().astype(int)
        idx = [idx[i] for i in picks]
    return idx


def project(
    ds: MMDataset,
    method: str = "mean",
    start: int = 0,
    stop: int | None = None,
    frame: int = 0,
    use_cache: bool = True,
) -> np.ndarray:
    """Project frames [start, stop) of ds.

    Returns float32 for mean/median/sum, the raw dtype for max/min/frame.
    """
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}")
    if method == "frame":
        return ds.frame(frame)

    max_frames = MEDIAN_MAX_FRAMES if method == "median" else None
    indices = frame_indices(ds.n_frames, start, stop, max_frames)

    path = None
    if use_cache:
        key = repr((ds.file_signature, method, indices[0], indices[-1], len(indices)))
        path = os.path.join(cache_dir(), hashlib.sha1(key.encode()).hexdigest() + ".npy")
        if os.path.exists(path):
            return np.load(path)

    result = _compute(ds, method, indices)
    if path:
        tmp = path + ".tmp.npy"
        np.save(tmp, result)
        os.replace(tmp, path)
    return result


def _compute(ds: MMDataset, method: str, indices: list[int]) -> np.ndarray:
    if method == "median":
        stack = np.empty((len(indices), *ds.shape_yx), dtype=ds.dtype)
        for k, img in enumerate(ds.iter_frames(indices)):
            stack[k] = img
        return np.median(stack, axis=0).astype(np.float32)

    acc = None
    for img in ds.iter_frames(indices):
        if acc is None:
            acc = img.astype(np.float64) if method in ("mean", "sum") else img.copy()
        elif method in ("mean", "sum"):
            acc += img
        elif method == "max":
            np.maximum(acc, img, out=acc)
        else:
            np.minimum(acc, img, out=acc)
    if method == "mean":
        acc /= len(indices)
    return acc.astype(np.float32) if method in ("mean", "sum") else acc
