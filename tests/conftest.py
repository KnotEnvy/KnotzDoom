"""Shared fixtures: a headless pygame Game instance."""
import os
import sys

import tempfile

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
# never touch the player's real config / saves / records
os.environ['KNOTZDOOM_DATA_DIR'] = tempfile.mkdtemp(prefix='knotzdoom-tests-')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest  # noqa: E402


@pytest.fixture(scope='session')
def game():
    from knotzdoom.game import Game
    return Game(headless=True)


@pytest.fixture
def world(game):
    """A fresh World for the first level."""
    from knotzdoom.world import World
    return World(game, game.level_data(0), difficulty_index=1)
