"""Timedemo: replay the autoplay bot's route through a level and time real frames.

Records the camera path once (the bot walks to every key and the exit), then
replays it through the real ``PlayState.draw`` (3D view, weapon, overlays and
HUD) and reports mean / median / p95 / max frame times.

    python tools/timedemo.py [level_id] [high|low]
"""
import os
import statistics
import sys
import time

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'tools')]

from autoplay import AutoPlayer  # noqa: E402
from knotzdoom.game import Game  # noqa: E402


def record(game, level_id):
    bot = AutoPlayer(game, game.level_data(game.episode['levels'].index(level_id)))
    poses = []
    tick = bot.tick

    def recording_tick():
        tick()
        poses.append((bot.player.x, bot.player.y, bot.player.angle))

    bot.tick = recording_tick
    bot.run()
    return poses


def replay(game, level_id, poses, detail='high'):
    game.config['detail'] = detail
    game.session = {'difficulty': 1, 'results': [], 'deaths': 0, 'carry': None}
    game.start_level(game.episode['levels'].index(level_id), 1)
    play = game.state
    play.fade = play.title_timer = 0
    for npc in play.world.objects.npcs:       # monsters stay put but are drawn
        npc.alerted = False
    player, ms = play.world.player, []
    for x, y, a in poses:
        player.x, player.y, player.angle = x, y, a
        t0 = time.perf_counter()
        play.draw(game.screen)
        ms.append((time.perf_counter() - t0) * 1000)
    ms.sort()
    return {'frames': len(ms), 'mean': statistics.mean(ms), 'median': ms[len(ms) // 2],
            'p95': ms[int(len(ms) * 0.95)], 'max': ms[-1]}


def main():
    level_id = sys.argv[1] if len(sys.argv) > 1 else 'e1m5'
    detail = sys.argv[2] if len(sys.argv) > 2 else 'high'
    game = Game(headless=True)
    poses = record(game, level_id)[::2]
    r = replay(game, level_id, poses, detail)
    print(f"{level_id} {detail}: {r['frames']} frames  mean {r['mean']:.2f}  median {r['median']:.2f}"
          f"  p95 {r['p95']:.2f}  max {r['max']:.2f} ms")


if __name__ == '__main__':
    main()
