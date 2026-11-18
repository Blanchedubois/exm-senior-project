"""Saved display state: per-acquisition channel settings, contrast levels, presets.

Files in the config folder (see core/offsets.config_dir):
  display.json        {"channels": {folder: ChannelSettings}, "levels": {key: [lo, hi]}}
  presets/<name>.json {wavelength: {"settings": ChannelSettings, "levels": {mode: [lo, hi]}}}
"""

from __future__ import annotations

import json
import os
import re

from ..io.mm_dataset import MMDataset
from .adjust import ChannelSettings
from .offsets import config_dir
from .processing import Processing


class LevelStore(dict):
    """Contrast levels keyed by acquisition + display mode + processing, since
    a Sum projection or a background-subtracted image needs different levels."""

    @staticmethod
    def key(ds: MMDataset, mode: str, processing: Processing | None = None) -> str:
        return f"{ds.folder}|{mode}|{(processing or Processing()).key()}"


class SettingsStore:
    def __init__(self, folder: str | None = None):
        self.folder = folder or config_dir()
        self.path = os.path.join(self.folder, "display.json")
        self.preset_dir = os.path.join(self.folder, "presets")
        self.channels: dict[str, ChannelSettings] = {}
        self.levels = LevelStore()
        self._load()

    # ---- per-acquisition settings --------------------------------------
    def get(self, ds: MMDataset) -> ChannelSettings:
        return self.channels.get(ds.folder, ChannelSettings())

    def set(self, ds: MMDataset, settings: ChannelSettings):
        if settings == ChannelSettings():
            self.channels.pop(ds.folder, None)
        else:
            self.channels[ds.folder] = settings

    # ---- presets -------------------------------------------------------
    def list_presets(self) -> list[str]:
        if not os.path.isdir(self.preset_dir):
            return []
        return sorted(n[:-5] for n in os.listdir(self.preset_dir) if n.endswith(".json"))

    def save_preset(self, name: str, channels: dict[str, dict]):
        """channels: {wavelength or label: {"settings": ChannelSettings, "levels": {mode: (lo, hi)}}}"""
        os.makedirs(self.preset_dir, exist_ok=True)
        data = {k: {"settings": v["settings"].to_dict(), "levels": {m: list(l) for m, l in v["levels"].items()}}
                for k, v in channels.items()}
        with open(self._preset_path(name), "w", encoding="utf-8") as f:
            json.dump({"version": 1, "channels": data}, f, indent=1)

    def load_preset(self, name: str) -> dict[str, dict]:
        with open(self._preset_path(name), encoding="utf-8") as f:
            data = json.load(f)["channels"]
        return {k: {"settings": ChannelSettings.from_dict(v["settings"]),
                    "levels": {m: tuple(l) for m, l in v.get("levels", {}).items()}}
                for k, v in data.items()}

    def delete_preset(self, name: str):
        try:
            os.remove(self._preset_path(name))
        except FileNotFoundError:
            pass

    def _preset_path(self, name: str) -> str:
        safe = re.sub(r"[^\w\- .]", "_", name).strip() or "preset"
        return os.path.join(self.preset_dir, safe + ".json")

    # ---- persistence ---------------------------------------------------
    def save(self):
        os.makedirs(self.folder, exist_ok=True)
        data = {"version": 1,
                "channels": {k: v.to_dict() for k, v in self.channels.items()},
                "levels": {k: list(v) for k, v in self.levels.items()}}
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, self.path)

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        self.channels = {k: ChannelSettings.from_dict(v) for k, v in data.get("channels", {}).items()}
        self.levels.update({k: tuple(v) for k, v in data.get("levels", {}).items()})
