"""A bot must be able to finish every level with the real collision code."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))

from knotzdoom.level import load_episode  # noqa: E402


@pytest.mark.parametrize('level_id', load_episode()['levels'])
def test_bot_completes_level(game, level_id):
    from autoplay import run_level
    bot = run_level(game, level_id)
    assert bot.world.exit_triggered
    assert bot.sim_time < 10 * 60 * 1000
