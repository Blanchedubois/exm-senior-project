"""
rwtag.meta
==========
The acquisition-metadata record of one image (docs/02_PHASE2_FOUNDATION_AND_METADATA.md §2).

Every value carries a SOURCE so an export can say where it came from:
  "header"   read from the TIFF's OME-XML
  "filename" parsed from the file name (the "1.5X" label)
  "user"     typed into the metadata form (a user edit always wins over a header)
  "pipeline" derived by the analysis (expansion, rotation, handedness); read-only
  ""         unset

`FIELDS` is the single schema: the GUI form, the sidecar and the export's column
dictionary are all generated from it, so adding a field is a one-line change.
Stored beside the image as `<image>.rwmeta.json`. NO Qt here.
"""
from __future__ import annotations
from dataclasses import dataclass, field, fields as dc_fields
import json
import os

META_SUFFIX = ".rwmeta.json"
META_VERSION = 1

GEL_TYPES = ["MAGNIFY", "TExM", "other"]
DESIGNS = ["optimistic", "medium", "conservative", "spectrum", "other"]
CONTROL_KINDS = ["ionic strength (mM)", "iris position", "other"]
IMMERSION = ["Air", "Water", "Oil", "Glycerol", "Silicone", "other"]

# (group, name, kind, label, unit, readonly, choices)
#   kind: str | float | int | bool | choice | date | time
FIELDS = [
    ("Sample", "sample_id", "str", "Sample ID", "", False, None),
    ("Sample", "print_design", "choice", "Print design", "", False, DESIGNS),
    ("Sample", "print_batch", "str", "Print batch", "", False, None),
    ("Sample", "gel_type", "choice", "Gel type", "", False, GEL_TYPES),
    ("Sample", "cells_present", "bool", "Cells present", "", False, None),
    ("Sample", "cells_description", "str", "Which cells", "", False, None),
    ("Sample", "operator", "str", "Operator", "", False, None),

    ("Expansion state", "state_label", "str", "State label", "", False, None),
    ("Expansion state", "expansion_expected", "float", "Expected expansion", "×", False, None),
    ("Expansion state", "expansion_control_kind", "choice", "Expansion set by", "", False, CONTROL_KINDS),
    ("Expansion state", "expansion_control_value", "str", "Control value", "", False, None),
    ("Expansion state", "time_since_expansion_min", "float", "Time since expansion", "min", False, None),

    ("Derived (pipeline)", "expansion_derived", "float", "Derived expansion", "×", True, None),
    ("Derived (pipeline)", "expansion_derived_sigma", "float", "± sigma", "×", True, None),
    ("Derived (pipeline)", "rotation_derived_deg", "float", "Derived rotation", "deg", True, None),
    ("Derived (pipeline)", "handedness", "float", "Handedness", "", True, None),

    ("Optics", "objective_name", "str", "Objective / lens", "", False, None),
    ("Optics", "magnification", "float", "Magnification", "×", False, None),
    ("Optics", "numerical_aperture", "float", "Numerical aperture", "", False, None),
    ("Optics", "immersion", "choice", "Immersion", "", False, IMMERSION),
    ("Optics", "um_per_px", "float", "Pixel size", "µm/px", False, None),
    ("Optics", "binning", "str", "Binning", "", False, None),

    ("Illumination & camera", "laser_wavelength_nm", "float", "Laser wavelength", "nm", False, None),
    ("Illumination & camera", "laser_power_mw", "float", "Laser power", "mW", False, None),
    ("Illumination & camera", "laser_power_pct", "float", "Laser power", "%", False, None),
    ("Illumination & camera", "excitation_filter", "str", "Excitation filter", "", False, None),
    ("Illumination & camera", "emission_filter", "str", "Emission filter", "", False, None),
    ("Illumination & camera", "emission_wavelength_nm", "float", "Emission wavelength", "nm", False, None),
    ("Illumination & camera", "exposure_ms", "float", "Exposure", "ms", False, None),
    ("Illumination & camera", "camera_model", "str", "Camera", "", False, None),
    ("Illumination & camera", "detector_gain_setting", "float", "Detector gain setting", "", False, None),
    ("Illumination & camera", "gain_e_per_adu", "float", "Camera gain", "e⁻/ADU", False, None),
    ("Illumination & camera", "camera_offset_adu", "float", "Camera offset", "ADU", False, None),

    ("Acquisition", "date", "date", "Date", "YYYY-MM-DD", False, None),
    ("Acquisition", "time", "time", "Time", "HH:MM:SS", False, None),
    ("Acquisition", "timezone", "str", "Time zone", "", False, None),
    ("Acquisition", "stitched", "bool", "Stitched", "", False, None),
    ("Acquisition", "n_tiles", "int", "Tiles", "", False, None),
    ("Acquisition", "stitch_software", "str", "Stitching software", "", False, None),
    ("Acquisition", "z_slices", "int", "Z slices", "", False, None),
    ("Acquisition", "z_step_um", "float", "Z step", "µm", False, None),
    ("Acquisition", "file_creator", "str", "File written by", "", False, None),

    ("Notes", "notes", "str", "Notes", "", False, None),
]
FIELD_BY_NAME = {f[1]: f for f in FIELDS}
GROUPS = list(dict.fromkeys(f[0] for f in FIELDS))
# groups copied by "Apply to all images" (instrument settings, not sample/state)
SHARED_GROUPS = ("Optics", "Illumination & camera")
DERIVED = tuple(f[1] for f in FIELDS if f[5])


@dataclass
class ImageMeta:
    sample_id: str | None = None
    print_design: str | None = None
    print_batch: str | None = None
    gel_type: str | None = None
    cells_present: bool | None = None
    cells_description: str | None = None
    operator: str | None = None
    state_label: str | None = None
    expansion_expected: float | None = None
    expansion_control_kind: str | None = None
    expansion_control_value: str | None = None
    time_since_expansion_min: float | None = None
    expansion_derived: float | None = None
    expansion_derived_sigma: float | None = None
    rotation_derived_deg: float | None = None
    handedness: float | None = None
    objective_name: str | None = None
    magnification: float | None = None
    numerical_aperture: float | None = None
    immersion: str | None = None
    um_per_px: float | None = None
    binning: str | None = None
    laser_wavelength_nm: float | None = None
    laser_power_mw: float | None = None
    laser_power_pct: float | None = None
    excitation_filter: str | None = None
    emission_filter: str | None = None
    emission_wavelength_nm: float | None = None
    exposure_ms: float | None = None
    camera_model: str | None = None
    detector_gain_setting: float | None = None
    gain_e_per_adu: float | None = None
    camera_offset_adu: float | None = None
    date: str | None = None
    time: str | None = None
    timezone: str | None = None
    stitched: bool | None = None
    n_tiles: int | None = None
    stitch_software: str | None = None
    z_slices: int | None = None
    z_step_um: float | None = None
    file_creator: str | None = None
    notes: str | None = None
    sources: dict = field(default_factory=dict)        # name -> header | filename | user | pipeline

    # ---------------------------------------------------------------- values
    def set(self, name, value, source):
        """Set one field with its source. Empty strings become None."""
        if name not in FIELD_BY_NAME:
            raise KeyError(name)
        value = coerce(name, value)
        setattr(self, name, value)
        if value is None:
            self.sources.pop(name, None)
        else:
            self.sources[name] = source

    def source(self, name):
        return self.sources.get(name, "")

    def apply_auto(self, values: dict, source):
        """Fill from the header or filename WITHOUT overwriting a user edit."""
        n = 0
        for k, v in values.items():
            if k in FIELD_BY_NAME and v is not None and self.source(k) != "user":
                self.set(k, v, source); n += 1
        return n

    def set_derived(self, **kv):
        for k, v in kv.items():
            if k not in DERIVED:
                raise KeyError(f"{k} is not a derived field")
            self.set(k, v, "pipeline")

    def copy_groups_from(self, other: "ImageMeta", groups=SHARED_GROUPS):
        """Copy every field of `groups` from another record (values and sources)."""
        for g, name, *_ in FIELDS:
            if g in groups:
                setattr(self, name, getattr(other, name))
                if other.source(name):
                    self.sources[name] = other.source(name)
                else:
                    self.sources.pop(name, None)

    @property
    def gain_known(self):
        return self.gain_e_per_adu is not None and self.gain_e_per_adu > 0

    def optics_short(self):
        """'100×/488 nm' for the sidebar."""
        parts = []
        if self.magnification:
            parts.append(f"{self.magnification:g}×")
        if self.laser_wavelength_nm:
            parts.append(f"{self.laser_wavelength_nm:g} nm")
        return "/".join(parts)

    # ---------------------------------------------------------------- io
    def to_dict(self):
        d = {f.name: getattr(self, f.name) for f in dc_fields(self) if f.name != "sources"}
        d["sources"] = dict(self.sources)
        return d

    @classmethod
    def from_dict(cls, d: dict):
        m = cls()
        for k, v in (d or {}).items():
            if k in FIELD_BY_NAME:
                setattr(m, k, coerce(k, v))
        m.sources = {k: v for k, v in (d or {}).get("sources", {}).items()
                     if k in FIELD_BY_NAME and getattr(m, k) is not None}
        return m


def coerce(name, value):
    """Convert a raw value (from JSON, a header or a text box) to the field's type.
    Empty / unparsable -> None (never a silent guess)."""
    kind = FIELD_BY_NAME[name][2]
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
    try:
        if kind == "float":
            return float(value)
        if kind == "int":
            return int(round(float(value)))
        if kind == "bool":
            if isinstance(value, str):
                return value.lower() in ("1", "true", "yes", "y", "on")
            return bool(value)
    except (TypeError, ValueError):
        return None
    return str(value)


# ---------------------------------------------------------------- sidecar
def meta_path(image_path):
    return os.fspath(image_path) + META_SUFFIX


def save_meta(image_path, meta: ImageMeta):
    with open(meta_path(image_path), "w") as f:
        json.dump({"version": META_VERSION, "image": os.path.basename(image_path),
                   "meta": meta.to_dict()}, f, indent=1)


def load_meta(image_path):
    p = meta_path(image_path)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        d = json.load(f)
    return ImageMeta.from_dict(d.get("meta", d))


def schema_rows():
    """The field dictionary as rows (group, name, kind, label, unit, readonly) —
    for the export README."""
    return [dict(group=g, name=n, kind=k, label=l, unit=u, readonly=ro)
            for g, n, k, l, u, ro, _c in FIELDS]
