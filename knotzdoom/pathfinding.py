"""Flow-field pathfinding.

Instead of running a breadth-first search for every enemy every frame, one BFS
is flooded outwards from the player's tile a few times per second.  Each
enemy then simply steps to the neighbouring tile with the smallest distance.
Diagonal steps are only allowed when both orthogonal neighbours are free so
nobody clips through wall corners.
"""
from collections import deque

STEPS = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, -1), (1, 1), (-1, 1))


class PathFinding:
    def __init__(self, world, interval=120):
        self.world = world
        self.interval = interval
        self.timer = interval          # compute immediately on first update
        self.graph = {}
        self.dist = {}
        self.build_graph()

    def passable(self, tile):
        """Tiles monsters may walk over: floor, and doors they can open
        (not locked ones, and not secret doors, which they would give away)."""
        world = self.world
        if tile in world.walls or tile in world.solid_tiles:
            return False
        door = world.doors.get(tile)
        if door is not None and (door.locked or door.secret):
            return False
        return world.inside(tile[0], tile[1])

    def neighbours(self, tile):
        x, y = tile
        result = []
        for dx, dy in STEPS:
            nxt = (x + dx, y + dy)
            if not self.passable(nxt):
                continue
            if dx and dy and not (self.passable((x + dx, y)) and self.passable((x, y + dy))):
                continue
            result.append(nxt)
        return result

    def build_graph(self):
        level = self.world.level
        self.graph = {}
        for y in range(level.rows):
            for x in range(level.cols):
                if self.passable((x, y)):
                    self.graph[(x, y)] = self.neighbours((x, y))

    def refresh_tile(self, tile):
        """Re-link a tile and its neighbours after it changed (a barrel blew up)."""
        x, y = tile
        for dx, dy in STEPS + ((0, 0),):
            t = (x + dx, y + dy)
            if self.passable(t):
                self.graph[t] = self.neighbours(t)
            else:
                self.graph.pop(t, None)

    def update(self, dt):
        self.timer += dt
        if self.timer >= self.interval:
            self.timer = 0
            self.flood(self.world.player.map_pos)

    def flood(self, goal):
        dist = {goal: 0}
        queue = deque([goal])
        graph = self.graph
        while queue:
            cur = queue.popleft()
            d = dist[cur] + 1
            for nxt in graph.get(cur, ()):
                if nxt not in dist:
                    dist[nxt] = d
                    queue.append(nxt)
        self.dist = dist

    def next_step(self, tile, occupied=()):
        """The neighbour of ``tile`` closest to the player, avoiding ``occupied`` tiles."""
        best = None
        best_d = self.dist.get(tile, 1 << 30)
        for nxt in self.graph.get(tile, ()):
            d = self.dist.get(nxt)
            if d is None or nxt in occupied:
                continue
            if d < best_d:
                best_d = d
                best = nxt
        return best

    def distance(self, tile):
        return self.dist.get(tile)
