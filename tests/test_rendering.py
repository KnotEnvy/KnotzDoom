"""Golden-image and frame budget tests for the renderer."""
import hashlib
import os
import time

import pygame as pg
import pytest

from knotzdoom.renderer import Renderer
from knotzdoom.world import World

GOLDEN_DIR = os.path.join(os.path.dirname(__file__), 'golden')
POSES = [(1.5, 3.5, 0.0), (12.5, 5.5, 2.2), (20.0, 14.5, -0.6)]


def deterministic_world(game, level=0):
    """A world whose props all show frame 0 and whose monsters are gone."""
    world = World(game, game.level_data(level), 1)
    for npc in world.objects.npcs:
        npc.state = 'dead'
    for sprite in world.objects.props + world.objects.pickups:
        sprite.anim.index = 0
        sprite.image = sprite.anim.image
    return world


def render_pose(game, world, renderer, pose):
    player = world.player
    player.x, player.y, player.angle = pose
    player.cam_h = 0.5
    renderer.light = 0
    renderer.render(player)
    renderer.present()
    small = pg.transform.smoothscale(game.screen, (160, 90))
    return pg.image.tostring(small, 'RGB')


@pytest.mark.parametrize('detail', [1, 2])
def test_golden_frames(game, detail):
    """Rendering must not change silently: compare downscaled frames with stored hashes.
    Regenerate with KNOTZDOOM_UPDATE_GOLDEN=1 after an intentional visual change."""
    world = deterministic_world(game)
    renderer = Renderer(game, world, divisor=detail)
    os.makedirs(GOLDEN_DIR, exist_ok=True)
    path = os.path.join(GOLDEN_DIR, f'e1m1_detail{detail}.txt')
    digests = [hashlib.sha1(render_pose(game, world, renderer, pose)).hexdigest() for pose in POSES]
    if os.environ.get('KNOTZDOOM_UPDATE_GOLDEN') or not os.path.exists(path):
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(digests) + '\n')
    with open(path, 'r', encoding='utf-8') as fh:
        expected = fh.read().split()
    assert digests == expected


def test_low_detail_matches_high_detail_closely(game):
    """The half-resolution view must show the same picture, only chunkier."""
    world = deterministic_world(game)
    high = Renderer(game, world, divisor=1)
    low = Renderer(game, world, divisor=2)
    a = render_pose(game, world, high, POSES[1])
    b = render_pose(game, world, low, POSES[1])
    diff = sum(abs(x - y) for x, y in zip(a, b)) / len(a)
    assert diff < 6.0            # mean channel difference on a 160x90 downscale


@pytest.mark.perf
def test_frame_budget(game):
    """A frame on the largest level stays within budget (run with -m perf)."""
    game.config['detail'] = 'high'
    game.session = {'difficulty': 1, 'results': [], 'deaths': 0, 'carry': None}
    game.start_level(4, 1)
    play = game.state
    play.fade = play.title_timer = 0
    times = []
    for i in range(120):
        play.world.player.angle += 0.02
        t0 = time.perf_counter()
        play.draw(game.screen)
        times.append(time.perf_counter() - t0)
    times.sort()
    assert times[len(times) // 2] * 1000 < 12.0      # median under 12 ms (reference machine: ~6 ms)
