"""Capture curated screenshots for the README into ``screenshots/``.

    python tools/screenshots.py [out_dir]
"""
import os
import sys

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame as pg  # noqa: E402

from knotzdoom.game import Game  # noqa: E402
from knotzdoom.npc import NPC  # noqa: E402
from knotzdoom.pickups import Barrel, Pickup  # noqa: E402
from knotzdoom import states  # noqa: E402


def frames(game, n, dt=16):
    for _ in range(n):
        game.frame(dt)


def save(game, out_dir, name):
    path = os.path.join(out_dir, name + '.png')
    pg.image.save(game.screen, path)
    print(path)


def stage_fight(game, out_dir):
    """Level 1, right hand room, one of every monster in view, shotgun blazing."""
    game.session = {'difficulty': 1, 'results': [], 'deaths': 0, 'carry': None}
    game.start_level(0, 1)
    play = game.state
    world = play.world
    player = world.player
    play.fade = 0
    play.title_timer = 0
    for npc in world.objects.npcs:
        npc.state = 'dead'
        npc.x, npc.y = -10, -10
    world.objects.npcs = []
    player.x, player.y, player.angle = 18.6, 14.5, 0.0
    player.give_weapon('shotgun')
    player.select_weapon('shotgun', instant=True)
    player.ammo['shells'] = 23
    player.armor, player.armor_type = 64, 1
    player.health = 87
    player.keys.add('blue')
    layout = [('trooper', 22.6, 12.4), ('sergeant', 23.4, 13.6), ('cacodemon', 23.2, 15.6),
              ('knight', 21.6, 16.3), ('trooper', 24.2, 14.6)]
    for kind, x, y in layout:
        npc = NPC(world, kind, (x, y))
        npc.alerted = True
        world.objects.npcs.append(npc)
    world.objects.props.append(Barrel(world, (20.5, 12.5)))
    world.objects.pickups.append(Pickup(world, 'medikit', (20.5, 16.5)))
    world.stats['kills_total'] = 10
    world.stats['kills'] = 4
    world.time = 83000
    player.score = 1250
    frames(game, 12)
    # fire the shotgun for the muzzle flash frame
    player.firing = True
    frames(game, 2)
    player.firing = False
    save(game, out_dir, 'play')
    frames(game, 30)
    play.hud.automap = True
    world.seen_tiles.update(world.walls.keys())
    world.seen_tiles.update(world.doors.keys())
    frames(game, 2)
    save(game, out_dir, 'automap')
    play.hud.automap = False


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..', 'screenshots')
    os.makedirs(out_dir, exist_ok=True)
    game = Game(headless=True)
    frames(game, 40)
    save(game, out_dir, 'title')
    game.replace(states.MainMenuState(game))
    frames(game, 5)
    save(game, out_dir, 'menu')
    stage_fight(game, out_dir)
    play = game.state
    results = dict(play.world.stats)
    results.update({'kills': 9, 'kills_total': 10, 'items': 12, 'items_total': 15, 'secrets': 1, 'secrets_total': 2,
                    'time': 83000, 'score': 1250})
    game.replace(states.IntermissionState(game, play, results))
    frames(game, 600)
    save(game, out_dir, 'intermission')


if __name__ == '__main__':
    main()
