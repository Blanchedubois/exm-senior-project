"""Parse IX83 acquisition folder names.

Convention: <wavelength>-<sample>-[<factor>x-]<N>cts-<exposure>ms_<rep>
e.g. "488-Sample1-3.0x-100cts-400ms_2".  Calibration folders such as
"DarkCount_1" and "Bead-Calibration_1" do not follow it and are classified
by keyword instead.

The folder name is the source of truth for the wavelength: the camera
metadata carries no laser information, and file prefixes can be stale
(e.g. 633-Sample1-3.0x-100cts-400ms_2/ holds 561-...-400ms_2_* files).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

KNOWN_WAVELENGTHS = (488, 561, 633)

_SAMPLE_RE = re.compile(
    r"^(?P<wavelength>\d{3})"
    r"-(?P<sample>.+?)"
    r"(?:-(?P<factor>\d+(?:\.\d+)?)x)?"
    r"-(?P<counts>\d+)cts"
    r"-(?P<exposure>\d+(?:\.\d+)?)ms"
    r"(?:_(?P<rep>\d+))?$",
    re.IGNORECASE,
)
_REP_RE = re.compile(r"_(\d+)$")


@dataclass(frozen=True)
class AcquisitionName:
    raw: str
    kind: str  # "sample", "dark", "beads", or "unknown"
    wavelength_nm: int | None = None
    sample: str | None = None
    factor: float | None = None  # the "3.0x" field; probably expansion factor
    counts: int | None = None  # intended number of frames
    exposure_ms: float | None = None
    rep: int | None = None


def parse_name(name: str) -> AcquisitionName:
    m = _SAMPLE_RE.match(name)
    if m:
        g = m.groupdict()
        return AcquisitionName(
            raw=name,
            kind="sample",
            wavelength_nm=int(g["wavelength"]),
            sample=g["sample"],
            factor=float(g["factor"]) if g["factor"] else None,
            counts=int(g["counts"]),
            exposure_ms=float(g["exposure"]),
            rep=int(g["rep"]) if g["rep"] else None,
        )
    lower = name.lower()
    rep_m = _REP_RE.search(name)
    rep = int(rep_m.group(1)) if rep_m else None
    if "dark" in lower:
        return AcquisitionName(raw=name, kind="dark", rep=rep)
    if "bead" in lower:
        return AcquisitionName(raw=name, kind="beads", rep=rep)
    return AcquisitionName(raw=name, kind="unknown", rep=rep)
