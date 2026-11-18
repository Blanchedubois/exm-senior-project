"""Persistent channel offsets.

Two kinds, both saved to offsets.json in the config folder
(~/Library/Application Support/ix83viewer, override with IX83_CONFIG_DIR):

- pair offsets: for one moving acquisition against one reference
  acquisition (keyed by folder). Set by auto-align or manual nudging.
- calibrations: for an objective + wavelength pair (e.g. 10x, 488 -> 561).
  Chromatic offset is a property of the microscope, so one bead-based
  calibration applies to every field of view taken with that objective.

Lookup order for a pair: pair offset -> reverse pair offset (negated) ->
calibration -> reverse calibration (negated) -> (0, 0).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

from ..io.mm_dataset import MMDataset


@dataclass(frozen=True)
class Offset:
    dy: float = 0.0
    dx: float = 0.0
    source: str = "none"  # none | auto | manual | calibration
    confidence: float | None = None

    @property
    def is_zero(self) -> bool:
        return self.dy == 0 and self.dx == 0


ZERO = Offset()


def _negate(o: Offset) -> Offset:
    """Offset of B relative to A from the offset of A relative to B."""
    return Offset(-o.dy + 0.0, -o.dx + 0.0, o.source, o.confidence)


def config_dir() -> str:
    d = os.environ.get("IX83_CONFIG_DIR") or os.path.expanduser("~/Library/Application Support/ix83viewer")
    os.makedirs(d, exist_ok=True)
    return d


class OffsetStore:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(config_dir(), "offsets.json")
        self.pairs: dict[str, dict] = {}
        self.calibrations: dict[str, dict] = {}
        self._load()

    # ---- pair offsets --------------------------------------------------
    @staticmethod
    def pair_key(moving: MMDataset, reference: MMDataset) -> str:
        return f"{moving.folder}|{reference.folder}"

    def get(self, moving: MMDataset, reference: MMDataset) -> Offset:
        if moving.folder == reference.folder:
            return ZERO
        entry = self.pairs.get(self.pair_key(moving, reference), {})
        if "current" in entry:
            return Offset(**entry["current"])
        reverse = self.pairs.get(self.pair_key(reference, moving), {})
        if "current" in reverse:
            return _negate(Offset(**reverse["current"]))
        cal = self.calibration_for(moving, reference)
        return cal if cal is not None else ZERO

    def auto_result(self, moving: MMDataset, reference: MMDataset) -> Offset | None:
        entry = self.pairs.get(self.pair_key(moving, reference), {})
        return Offset(**entry["auto"]) if "auto" in entry else None

    def set(self, moving: MMDataset, reference: MMDataset, offset: Offset, is_auto_result: bool = False):
        entry = self.pairs.setdefault(self.pair_key(moving, reference), {})
        entry["current"] = asdict(offset)
        if is_auto_result:
            entry["auto"] = asdict(offset)
        self._save()

    def clear(self, moving: MMDataset, reference: MMDataset):
        """Forget the pair offset (falls back to calibration or zero)."""
        entry = self.pairs.get(self.pair_key(moving, reference))
        if entry and "current" in entry:
            del entry["current"]
            if not entry:
                del self.pairs[self.pair_key(moving, reference)]
            self._save()

    # ---- calibrations --------------------------------------------------
    @staticmethod
    def calibration_key(objective: str | None, moving_nm: int | None, reference_nm: int | None) -> str:
        return f"{objective}|{moving_nm}|{reference_nm}"

    def calibration_for(self, moving: MMDataset, reference: MMDataset) -> Offset | None:
        if moving.objective != reference.objective:
            return None
        key = self.calibration_key(moving.objective, moving.wavelength_nm, reference.wavelength_nm)
        if key in self.calibrations:
            return Offset(**{**self.calibrations[key], "source": "calibration"})
        rkey = self.calibration_key(moving.objective, reference.wavelength_nm, moving.wavelength_nm)
        if rkey in self.calibrations:
            return _negate(Offset(**{**self.calibrations[rkey], "source": "calibration"}))
        return None

    def save_calibration(self, moving: MMDataset, reference: MMDataset, offset: Offset):
        key = self.calibration_key(moving.objective, moving.wavelength_nm, reference.wavelength_nm)
        self.calibrations[key] = asdict(offset)
        self._save()

    # ---- persistence ---------------------------------------------------
    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        self.pairs = data.get("pairs", {})
        self.calibrations = data.get("calibrations", {})

    def _save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "pairs": self.pairs, "calibrations": self.calibrations}, f, indent=1)
        os.replace(tmp, self.path)
