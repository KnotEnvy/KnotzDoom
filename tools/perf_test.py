"""Measure average frame time of the play state headlessly."""
import os
import sys
import time

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame as pg  # noqa: E402
from knotzdoom.game import Game  # noqa: E402
from knotzdoom.states import PlayState  # noqa: E402


def main(level_index=0, frames=240, detail='high'):
    game = Game(headless=True)
    game.config['detail'] = detail
    game.session = {'difficulty': 1, 'results': [], 'deaths': 0, 'carry': None}
    game.start_level(level_index, 1)
    play = game.state
    assert isinstance(play, PlayState)
    world = play.world
    # wake everybody up so AI cost is included
    for npc in world.objects.npcs:
        npc.alert()
    timings = {'raycast': 0.0, 'walls': 0.0, 'sprites': 0.0, 'update': 0.0, 'hud': 0.0, 'total': 0.0}
    renderer = play.renderer
    for i in range(frames):
        world.player.angle += 0.01
        t0 = time.perf_counter()
        game.update(16)
        t1 = time.perf_counter()
        renderer.raycaster.cast(world.player)
        t2 = time.perf_counter()
        renderer.draw_background(world.player)
        renderer.draw_walls(world.player)
        t3 = time.perf_counter()
        renderer.sprite_requests = []
        for sprite in world.drawable_sprites():
            sprite.project(world.player, renderer)
        renderer.draw_sprites()
        t4 = time.perf_counter()
        play.hud.draw_status_bar(game.screen, world)
        t5 = time.perf_counter()
        timings['update'] += t1 - t0
        timings['raycast'] += t2 - t1
        timings['walls'] += t3 - t2
        timings['sprites'] += t4 - t3
        timings['hud'] += t5 - t4
        timings['total'] += t5 - t0
    print(f'level {level_index} detail={detail} ({renderer.view.width}x{renderer.view.height}, {renderer.view.num_rays} rays)')
    for key, value in timings.items():
        print(f'{key:8s} {1000 * value / frames:6.2f} ms/frame')
    print(f'~{frames / timings["total"]:.0f} fps (render+update only)')


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 0, detail=sys.argv[2] if len(sys.argv) > 2 else 'high')
