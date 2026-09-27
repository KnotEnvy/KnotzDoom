"""Save slots stored as JSON files.

Writes are atomic (temp file + rename), every payload is validated before it is
used, and a fingerprint of the level grid is stored so a save made on an
edited level shows up as INCOMPATIBLE instead of scrambling monsters.
"""
import hashlib
import json
import os
import time

from . import settings

SLOTS = 4
SAVE_VERSION = 2
MIGRATIONS = {}        # old version -> callable(payload) -> payload


def slot_path(slot):
    return os.path.join(settings.SAVE_DIR, f'slot{slot}.json')


def level_fingerprint(level):
    """Hash of the grid so saves know which version of a level they belong to."""
    return hashlib.sha1('\n'.join(level.grid).encode('utf-8')).hexdigest()[:16]


def write_save(slot, payload):
    os.makedirs(settings.SAVE_DIR, exist_ok=True)
    payload = dict(payload)
    payload['version'] = SAVE_VERSION
    payload['timestamp'] = time.time()
    payload['date'] = time.strftime('%Y-%m-%d %H:%M')
    path = slot_path(slot)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, indent=1)
    os.replace(tmp, path)
    return payload


def validate(data, level_count):
    """Return (payload, problem). ``problem`` is None when the save is usable."""
    if not isinstance(data, dict):
        return None, 'corrupt'
    version = data.get('version')
    while version in MIGRATIONS:
        data = MIGRATIONS[version](data)
        version = data.get('version')
    if version != SAVE_VERSION:
        return None, 'incompatible'
    try:
        level_index = int(data['level_index'])
        difficulty = int(data['difficulty'])
        world = data['world']
    except (KeyError, TypeError, ValueError):
        return None, 'corrupt'
    if not (0 <= level_index < level_count) or not (0 <= difficulty < len(settings.DIFFICULTIES)):
        return None, 'corrupt'
    if not isinstance(world, dict) or not isinstance(world.get('player'), dict):
        return None, 'corrupt'
    data['level_index'], data['difficulty'] = level_index, difficulty
    data.setdefault('session', {})
    data.setdefault('carry', None)
    return data, None


def read_save(slot, level_count=None):
    """The slot's payload, or ``(None, problem)`` style tuple via ``read_save_status``."""
    payload, _ = read_save_status(slot, level_count)
    return payload


def read_save_status(slot, level_count=None):
    path = slot_path(slot)
    if not os.path.exists(path):
        return None, 'empty'
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None, 'corrupt'
    if level_count is None:
        level_count = 1 << 30
    return validate(data, level_count)


def slot_summaries(level_count=None):
    """Short description of every slot for the save / load menus."""
    summaries = []
    for slot in range(SLOTS):
        data, problem = read_save_status(slot, level_count)
        if data is None:
            summaries.append(None if problem == 'empty' else {'problem': problem})
        else:
            summaries.append({
                'level_name': data.get('level_name', '?'),
                'difficulty': data.get('difficulty_name', '?'),
                'date': data.get('date', ''),
                'time': data.get('world', {}).get('time', 0),
                'level_hash': data.get('level_hash'),
            })
    return summaries
