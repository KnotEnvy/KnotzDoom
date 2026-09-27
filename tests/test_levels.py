"""Every level in the episode must load, validate and follow the design rules."""
import json
import os

import pytest

from knotzdoom.level import ENEMY_KINDS, LevelData, load_episode, load_level, validate_level
from knotzdoom.settings import LEVEL_DIR

EPISODE = load_episode()


@pytest.mark.parametrize('level_id', EPISODE['levels'])
def test_level_is_valid(level_id):
    level = load_level(level_id)
    assert validate_level(level) == []
    assert level.player_start is not None
    assert level.exits, 'a level needs an exit switch'
    assert level.enemy_count > 0
    assert 20 <= level.cols <= 40 and 20 <= level.rows <= 40


def test_episode_files_exist():
    for level_id in EPISODE['levels']:
        assert os.path.exists(os.path.join(LEVEL_DIR, f'{level_id}.json'))
    assert EPISODE['intro'] and EPISODE['outro'] and EPISODE['credits']


def test_only_last_level_has_boss():
    for i, level_id in enumerate(EPISODE['levels']):
        level = load_level(level_id)
        bosses = level.count('cyberdemon')
        if i == len(EPISODE['levels']) - 1:
            assert bosses == 1
        else:
            assert bosses == 0


def test_door_orientation_rules():
    level = load_level('e1m1')
    doors = {d.pos: d for d in level.doors}
    assert doors[(10, 3)].vertical is True        # walls above and below -> slab runs north-south
    assert doors[(5, 5)].vertical is False        # walls left and right -> slab runs east-west
    assert doors[(17, 17)].locked == 'blue'
    assert doors[(10, 17)].secret is True
    assert len(level.secret_areas()) == 1


def test_validator_catches_problems():
    grid = [
        '#######',
        '#P....#',
        '#.....#',
        '#..r..#',
        '#B#####',      # locked door in the border -> open border tile + key unreachable? no: key is reachable
        '#######',
    ]
    level = LevelData({'grid': grid}, 'broken')
    problems = validate_level(level)
    assert any('exit' in p for p in problems)
    # a thing inside a wall
    level = LevelData({'grid': ['#####', '#P..#', '#####', '##z##', '#####']}, 'wall_thing')
    assert any('inside a wall' in p or 'unreachable' in p for p in validate_level(level))


def test_unknown_character_rejected():
    with pytest.raises(ValueError):
        LevelData({'grid': ['####', '#P?#', '####']}, 'bad')


def test_grid_rows_padded():
    level = LevelData({'grid': ['#####', '#P.', '#####']}, 'ragged')
    assert level.cols == 5
    assert all(len(row) == 5 for row in level.grid)
