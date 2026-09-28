"""Automatic playthrough of a level with the real physics.

A bot walks the level using the tile graph: it collects every key it can
reach, opens doors on the way (waiting for them to slide open), and finally
presses the exit switch.  It proves a level is completable with the actual
collision code, not just on paper.

    python tools/autoplay.py            # all levels
    python tools/autoplay.py e1m3       # one level
"""
import math
import os
import sys
from collections import deque

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knotzdoom.level import KEY_KINDS, load_episode  # noqa: E402
from knotzdoom.settings import DOOR_PASSABLE, PLAYER_SPEED  # noqa: E402
from knotzdoom.world import World  # noqa: E402

STEP_MS = 16
MAX_SIM_MS = 15 * 60 * 1000


class AutoPlayer:
    def __init__(self, game, level, difficulty=1):
        self.game = game
        self.world = World(game, level, difficulty)
        self.player = self.world.player
        self.player.god = True
        for npc in self.world.objects.npcs:       # monsters are not the point here
            npc.state = 'dead'
        self.sim_time = 0
        self.log = []

    # ------------------------------------------------------------ graph
    def walkable(self, tile, keys):
        """Like the monsters' rule, except the bot may use keys it holds and secret doors."""
        world = self.world
        if tile in world.walls or tile in world.solid_tiles or not world.inside(*tile):
            return False
        door = world.doors.get(tile)
        return door is None or not door.locked or door.locked in keys

    def bfs(self, start, keys):
        prev = {start: None}
        queue = deque([start])
        while queue:
            cur = queue.popleft()
            x, y = cur
            for nxt in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if nxt not in prev and self.walkable(nxt, keys):
                    prev[nxt] = cur
                    queue.append(nxt)
        return prev

    @staticmethod
    def path_to(prev, goal):
        if goal not in prev:
            return None
        path = []
        cur = goal
        while cur is not None:
            path.append(cur)
            cur = prev[cur]
        return list(reversed(path))

    # ------------------------------------------------------------ movement
    def tick(self):
        self.world.update(STEP_MS)
        self.sim_time += STEP_MS
        if self.sim_time > MAX_SIM_MS:
            raise RuntimeError('autoplay timed out')

    def walk_path(self, path):
        player = self.player
        for tile in path[1:]:
            tx, ty = tile[0] + 0.5, tile[1] + 0.5
            door = self.world.doors.get(tile)
            stuck = 0
            while math.hypot(tx - player.x, ty - player.y) > 0.12:
                if door is not None and door.open < DOOR_PASSABLE:
                    if door.state in ('closed', 'closing'):
                        player.angle = math.atan2(ty - player.y, tx - player.x)
                        door.use(player)
                    self.tick()
                    continue
                angle = math.atan2(ty - player.y, tx - player.x)
                player.angle = angle
                speed = PLAYER_SPEED * STEP_MS
                before = (player.x, player.y)
                player.try_move(math.cos(angle) * speed, math.sin(angle) * speed)
                self.tick()
                if math.hypot(player.x - before[0], player.y - before[1]) < 1e-4:
                    stuck += 1
                    if stuck > 200:
                        raise RuntimeError(f'stuck at {player.x:.2f},{player.y:.2f} heading to {tile}')
                else:
                    stuck = 0

    # ------------------------------------------------------------ plan
    def run(self):
        world = self.world
        player = self.player
        level = world.level
        while True:
            keys = set(player.keys)
            prev = self.bfs(player.map_pos, keys)
            # exit reachable?
            exit_targets = []
            for (ex, ey) in level.exits:
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    tile = (ex + dx, ey + dy)
                    if tile in prev:
                        exit_targets.append((len(self.path_to(prev, tile)), tile, (ex, ey)))
            if exit_targets:
                _, tile, ex = min(exit_targets)
                self.walk_path(self.path_to(prev, tile))
                player.angle = math.atan2(ex[1] + 0.5 - player.y, ex[0] + 0.5 - player.x)
                player.use()
                for _ in range(5):
                    self.tick()
                if not world.exit_triggered:
                    raise RuntimeError('exit switch did not trigger')
                self.log.append(f'exit reached at {self.sim_time / 1000:.1f}s')
                return True
            # otherwise fetch the nearest reachable key we do not own
            candidates = []
            for pickup in world.objects.pickups:
                color = KEY_KINDS.get(pickup.kind)
                if color and color not in keys and pickup.map_pos in prev:
                    candidates.append((len(self.path_to(prev, pickup.map_pos)), pickup))
            if not candidates:
                raise RuntimeError('no exit and no key reachable')
            _, pickup = min(candidates, key=lambda c: c[0])
            self.walk_path(self.path_to(prev, pickup.map_pos))
            for _ in range(5):
                self.tick()
            if KEY_KINDS[pickup.kind] not in player.keys:
                raise RuntimeError(f'failed to pick up {pickup.kind} at {pickup.map_pos}')
            self.log.append(f'{pickup.kind} at {self.sim_time / 1000:.1f}s')


def run_level(game, level_id):
    from knotzdoom.level import load_level
    level = load_level(level_id)
    bot = AutoPlayer(game, level)
    bot.run()
    return bot


if __name__ == '__main__':
    from knotzdoom.game import Game
    game = Game(headless=True)
    ids = sys.argv[1:] or load_episode()['levels']
    for level_id in ids:
        bot = run_level(game, level_id)
        print(level_id, 'OK', ' | '.join(bot.log))
