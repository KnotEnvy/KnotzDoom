"""Save slots stored as JSON files in ``saves/``."""
import json
import os
import time

from .settings import SAVE_DIR

SLOTS = 4
SAVE_VERSION = 1


def slot_path(slot):
    return os.path.join(SAVE_DIR, f'slot{slot}.json')


def write_save(slot, payload):
    os.makedirs(SAVE_DIR, exist_ok=True)
    payload = dict(payload)
    payload['version'] = SAVE_VERSION
    payload['timestamp'] = time.time()
    payload['date'] = time.strftime('%Y-%m-%d %H:%M')
    with open(slot_path(slot), 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, indent=1)
    return payload


def read_save(slot):
    path = slot_path(slot)
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if data.get('version') != SAVE_VERSION:
        return None
    return data


def slot_summaries():
    """Short description of every slot for the save / load menus."""
    summaries = []
    for slot in range(SLOTS):
        data = read_save(slot)
        if data is None:
            summaries.append(None)
        else:
            summaries.append({
                'level_name': data.get('level_name', '?'),
                'difficulty': data.get('difficulty_name', '?'),
                'date': data.get('date', ''),
                'time': data.get('world', {}).get('time', 0),
            })
    return summaries


def delete_save(slot):
    try:
        os.remove(slot_path(slot))
    except OSError:
        pass
