"""User options persisted to ``config.json``.

Every option has a schema entry: its type, default and either a range or the
allowed values.  Values from disk are coerced and clamped, so a hand-edited
``"music_volume": 5`` becomes 1.0 instead of blowing out the mixer.
"""
import json

from .settings import CONFIG_PATH

# key: (default, kind, constraint)   kind: 'float' (min, max) | 'int' allowed set | 'bool' | 'choice' allowed
SCHEMA = {
    'music_volume': (0.5, 'float', (0.0, 1.0)),
    'sfx_volume': (0.8, 'float', (0.0, 1.0)),
    'mouse_sensitivity': (1.0, 'float', (0.2, 3.0)),
    'crosshair': (True, 'bool', None),
    'screen_shake': (True, 'bool', None),
    'show_fps': (False, 'bool', None),
    'always_run': (False, 'bool', None),
    'fullscreen': (False, 'bool', None),
    'head_bob': (True, 'bool', None),
    'fps_cap': (60, 'int', (0, 30, 60, 90, 120, 144)),
    'detail': ('auto', 'choice', ('auto', 'high', 'low')),
}
DEFAULTS = {key: spec[0] for key, spec in SCHEMA.items()}


def coerce(key, value):
    """Return a valid value for ``key`` or None when ``value`` cannot be used."""
    default, kind, constraint = SCHEMA[key]
    try:
        if kind == 'float':
            value = float(value)
            return min(constraint[1], max(constraint[0], value))
        if kind == 'int':
            value = int(value)
            return value if value in constraint else None
        if kind == 'bool':
            if isinstance(value, str):
                return value.lower() in ('1', 'true', 'yes', 'on')
            return bool(value)
        if kind == 'choice':
            return value if value in constraint else None
    except (TypeError, ValueError):
        return None
    return None


class Config:
    """A small dict-backed options object with load/save and validation."""

    def __init__(self, path=CONFIG_PATH):
        self.path = path
        self.values = dict(DEFAULTS)
        self.rejected = []
        self.load()

    def load(self):
        try:
            with open(self.path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        for key, value in data.items():
            if key not in SCHEMA:
                self.rejected.append(key)
                continue
            fixed = coerce(key, value)
            if fixed is None:
                self.rejected.append(key)
            else:
                self.values[key] = fixed

    def save(self):
        try:
            with open(self.path, 'w', encoding='utf-8') as fh:
                json.dump(self.values, fh, indent=2, sort_keys=True)
        except OSError:
            pass

    def __getitem__(self, key):
        return self.values[key]

    def __setitem__(self, key, value):
        fixed = coerce(key, value)
        if fixed is None:
            raise ValueError(f'invalid value for {key}: {value!r}')
        self.values[key] = fixed

    def get(self, key, default=None):
        return self.values.get(key, default)
