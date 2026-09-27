"""User options persisted to ``config.json`` in the repository root."""
import json
import os

from .settings import CONFIG_PATH

DEFAULTS = {
    'music_volume': 0.5,
    'sfx_volume': 0.8,
    'mouse_sensitivity': 1.0,     # multiplier on MOUSE_SENSITIVITY
    'crosshair': True,
    'screen_shake': True,
    'show_fps': False,
    'always_run': False,
    'fullscreen': False,
    'head_bob': True,
    'fps_cap': 60,
}


class Config:
    """A small dict-backed options object with load/save."""

    def __init__(self, path=CONFIG_PATH):
        self.path = path
        self.values = dict(DEFAULTS)
        self.load()

    def load(self):
        try:
            with open(self.path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            for key in DEFAULTS:
                if key in data and type(data[key]) is type(DEFAULTS[key]):
                    self.values[key] = data[key]
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            with open(self.path, 'w', encoding='utf-8') as fh:
                json.dump(self.values, fh, indent=2, sort_keys=True)
        except OSError:
            pass

    def __getitem__(self, key):
        return self.values[key]

    def __setitem__(self, key, value):
        self.values[key] = value

    def get(self, key, default=None):
        return self.values.get(key, default)
