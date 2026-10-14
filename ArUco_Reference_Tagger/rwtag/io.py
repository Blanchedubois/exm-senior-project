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


# ================================================================ sessions (Stage 1)
# Ported from Reference_Warp_Tagger/rwtag/io.py: the Stage-1 tuning (shared optics
# + per-image levels + shared/per-image flags) is saved as `<image>.rwsession.json`
# so the exact corrected image is reproducible.
import json as _json

SESSION_VERSION = 1
SIDECAR_SUFFIX = ".rwsession.json"


def sidecar_path(image_path: str) -> str:
    return os.fspath(image_path) + SIDECAR_SUFFIX


def session_dict(source_path, correction, levels, shared_flags=None):
    return {"version": SESSION_VERSION, "source_path": source_path,
            "correction": correction.to_dict(), "levels": levels.to_dict(),
            "shared_flags": dict(shared_flags or {})}


def save_session(path, source_path, correction, levels, shared_flags=None):
    with open(path, "w") as f:
        _json.dump(session_dict(source_path, correction, levels, shared_flags), f, indent=2)


def load_session(path):
    """(source_path, CorrectionParams, LevelsParams, shared_flags). Tolerant of the
    old two-field format and of unknown future keys."""
    from .types import CorrectionParams, LevelsParams
    with open(path) as f:
        d = _json.load(f)
    return (d.get("source_path"), CorrectionParams.from_dict(d.get("correction", {})),
            LevelsParams.from_dict(d.get("levels", {})), dict(d.get("shared_flags", {})))


# ================================================================ OME metadata
_LEN_TO_UM = {"µm": 1.0, "um": 1.0, "micron": 1.0, "nm": 1e-3, "mm": 1e3, "m": 1e6, "Å": 1e-4}
_TIME_TO_MS = {"ms": 1.0, "s": 1e3, "µs": 1e-3, "us": 1e-3, "ns": 1e-6, "min": 6e4}
_POWER_TO_MW = {"mW": 1.0, "W": 1e3, "µW": 1e-3, "uW": 1e-3}
_WL_TO_NM = {"nm": 1.0, "µm": 1e3, "um": 1e3}


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _num(el, attr, units=None, unit_attr=None, default_unit=None):
    if el is None or el.get(attr) in (None, ""):
        return None
    try:
        v = float(el.get(attr))
    except ValueError:
        return None
    if units:
        u = el.get(unit_attr or (attr + "Unit"), default_unit)
        v *= units.get(u, 1.0)
    return v


def read_ome_metadata(path) -> dict:
    """Acquisition fields found in a TIFF's OME-XML, keyed by rwtag.meta field
    names. Missing elements are simply absent -- nothing is guessed. Works on any
    OME schema version (namespace-agnostic). Non-OME files return {}."""
    out = {}
    if tifffile is None or not str(path).lower().endswith((".tif", ".tiff")):
        return out
    try:
        with tifffile.TiffFile(path) as tf:
            xml = tf.ome_metadata
    except Exception:
        return out
    if not xml:
        return out
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return out
    els = {}
    for el in root.iter():
        els.setdefault(_local(el.tag), []).append(el)

    def first(*names):
        for n in names:
            if els.get(n):
                return els[n][0]
        return None

    if root.get("Creator"):
        out["file_creator"] = root.get("Creator")
    pix = first("Pixels")
    if pix is not None:
        out["um_per_px"] = _num(pix, "PhysicalSizeX", _LEN_TO_UM, default_unit="µm")
        nz = pix.get("SizeZ")
        if nz and int(nz) > 1:
            out["z_slices"] = int(nz)
            out["z_step_um"] = _num(pix, "PhysicalSizeZ", _LEN_TO_UM, default_unit="µm")
    img = first("Image")
    if img is not None and img.get("AcquisitionDate"):
        stamp = img.get("AcquisitionDate")
        date, _, time = stamp.partition("T")
        out["date"] = date
        if time:
            out["time"] = time[:8]
            tz = time[8:].strip()
            if tz:
                out["timezone"] = tz
    obj = first("Objective")
    if obj is not None:
        out["magnification"] = _num(obj, "NominalMagnification")
        out["numerical_aperture"] = _num(obj, "LensNA")
        if obj.get("Immersion"):
            out["immersion"] = obj.get("Immersion")
        name = " ".join(x for x in (obj.get("Manufacturer"), obj.get("Model")) if x)
        if not name and (obj.get("NominalMagnification") or obj.get("LensNA")):
            mag, na = obj.get("NominalMagnification"), obj.get("LensNA")
            name = f"{float(mag):g}x" + (f"/{float(na):g}" if na else "") if mag else f"NA {na}"
        if name:
            out["objective_name"] = name
    src = first("Laser", "LightEmittingDiode", "GenericExcitationSource", "Arc", "Filament")
    if src is not None:
        out["laser_wavelength_nm"] = _num(src, "Wavelength", _WL_TO_NM, default_unit="nm")
        out["laser_power_mw"] = _num(src, "Power", _POWER_TO_MW, default_unit="mW")
    ch = first("Channel")
    if ch is not None:
        if out.get("laser_wavelength_nm") is None:
            out["laser_wavelength_nm"] = _num(ch, "ExcitationWavelength", _WL_TO_NM, default_unit="nm")
        out["emission_wavelength_nm"] = _num(ch, "EmissionWavelength", _WL_TO_NM, default_unit="nm")
    ds = first("DetectorSettings")
    det = first("Detector")
    g = _num(ds, "Gain") if ds is not None else None
    if g is None and det is not None:
        g = _num(det, "Gain")
    out["detector_gain_setting"] = g
    if ds is not None and ds.get("Binning"):
        out["binning"] = ds.get("Binning")
    if det is not None:
        name = " ".join(x for x in (det.get("Manufacturer"), det.get("Model")) if x)
        if name:
            out["camera_model"] = name
    plane = first("Plane")
    if plane is not None:
        out["exposure_ms"] = _num(plane, "ExposureTime", _TIME_TO_MS, default_unit="s")
    return {k: v for k, v in out.items() if v is not None}


def auto_meta(path):
    """Header values + the filename label, as {field: (value, source)}."""
    vals = {k: (v, "header") for k, v in read_ome_metadata(path).items()}
    lab = parse_label(path)
    if lab is not None:
        vals.setdefault("expansion_expected", (lab, "filename"))
        vals.setdefault("state_label", (f"{lab:g}X", "filename"))
    return vals
