"""Level data: loading ``levels/*.json`` and turning the ASCII grid into walls,
doors, specials and "things" (entities to spawn).

Grid legend (one character per tile)::

    #        wall using the level's default texture
    1..9     wall using that texture number
    D        door (unlocked)             R / B / Y   door locked by red / blue / yellow key
    S        secret door (looks like a wall, opens on "use", counts as a secret)
    X        exit switch wall (use it to finish the level)
    .        floor                       ~   secret floor (stepping on it finds a secret)
    P        player start

    enemies:  z trooper   g sergeant   c cacodemon   k hell knight   C cyberdemon
    weapons:  s shotgun   m chaingun   l rocket launcher     p backpack
    ammo:     u bullet clip  U bullet box  e shells  E shell box  q rockets  Q rocket box
    health:   h stimpack  H medikit  o soulsphere   a green armor  A blue armor
    keys:     r red key   b blue key   y yellow key
    props:    % explosive barrel   | pillar   T red torch   t green torch   j candelabra   J skulls
"""
import json
import os
from collections import deque

from .assets import (TEX_DOOR, TEX_DOOR_BLUE, TEX_DOOR_RED, TEX_DOOR_YELLOW, TEX_EXIT)
from .settings import LEVEL_DIR

WALL_CHARS = set('#123456789')
DOOR_CHARS = {'D': None, 'R': 'red', 'B': 'blue', 'Y': 'yellow'}
SECRET_DOOR = 'S'
EXIT_CHAR = 'X'
FLOOR_CHARS = set('.~P')
START_CHAR = 'P'
SECRET_FLOOR = '~'

THING_LEGEND = {
    # enemies
    'z': 'trooper', 'g': 'sergeant', 'c': 'cacodemon', 'k': 'knight', 'C': 'cyberdemon',
    # weapons
    's': 'shotgun', 'm': 'chaingun', 'l': 'rocket_launcher', 'p': 'backpack',
    # ammo
    'u': 'clip', 'U': 'bullet_box', 'e': 'shells', 'E': 'shell_box', 'q': 'rockets', 'Q': 'rocket_box',
    # health / armor
    'h': 'stimpack', 'H': 'medikit', 'o': 'soulsphere', 'a': 'armor_green', 'A': 'armor_blue',
    # keys
    'r': 'key_red', 'b': 'key_blue', 'y': 'key_yellow',
    # props
    '%': 'barrel', '|': 'pillar', 'T': 'torch_red', 't': 'torch_green', 'j': 'candelabra', 'J': 'skulls',
}
ENEMY_KINDS = {'trooper', 'sergeant', 'cacodemon', 'knight', 'cyberdemon'}
KEY_KINDS = {'key_red': 'red', 'key_blue': 'blue', 'key_yellow': 'yellow'}
SOLID_PROPS = {'barrel', 'pillar'}
ITEM_KINDS = set(THING_LEGEND.values()) - ENEMY_KINDS - {'barrel', 'pillar', 'torch_red', 'torch_green', 'candelabra', 'skulls'}

DOOR_TEXTURES = {None: TEX_DOOR, 'red': TEX_DOOR_RED, 'blue': TEX_DOOR_BLUE, 'yellow': TEX_DOOR_YELLOW}


class DoorSpec:
    """Static description of a door tile (the live state lives in world.Door)."""

    def __init__(self, x, y, vertical, locked=None, secret=False, texture=TEX_DOOR):
        self.x, self.y = x, y
        self.vertical = vertical      # True: slab runs north-south (constant x)
        self.locked = locked          # None / 'red' / 'blue' / 'yellow'
        self.secret = secret
        self.texture = texture

    @property
    def pos(self):
        return self.x, self.y


class Thing:
    def __init__(self, kind, x, y):
        self.kind = kind
        self.x, self.y = x, y          # tile coordinates

    @property
    def pos(self):
        return self.x + 0.5, self.y + 0.5


class LevelData:
    """Everything parsed from one level file."""

    def __init__(self, data, level_id=None):
        self.id = data.get('id', level_id or 'level')
        self.name = data.get('name', self.id)
        self.par_time = int(data.get('par_time', 120))
        self.sky = data.get('sky', 'sky')
        self.floor_color = tuple(data.get('floor_color', (30, 30, 30)))
        self.default_wall = int(data.get('default_wall', 1))
        self.music = data.get('music', 'theme')
        self.story = data.get('story', '')
        self.player_angle = float(data.get('player_angle', 0))   # degrees
        self.grid = list(data['grid'])
        self.rows = len(self.grid)
        self.cols = max(len(row) for row in self.grid)
        self.grid = [row.ljust(self.cols, '#') for row in self.grid]

        self.walls = {}          # (x, y) -> texture id
        self.doors = []          # DoorSpec
        self.exits = set()       # (x, y) of exit switch walls
        self.things = []         # Thing
        self.secret_tiles = set()
        self.player_start = None
        self.parse()

    # ------------------------------------------------------------ parsing
    def char(self, x, y):
        if 0 <= y < self.rows and 0 <= x < self.cols:
            return self.grid[y][x]
        return '#'

    def is_solid_char(self, ch):
        return ch in WALL_CHARS or ch in DOOR_CHARS or ch in (SECRET_DOOR, EXIT_CHAR)

    def door_orientation(self, x, y):
        """A door slab sits across the corridor: if the tiles left/right are
        solid the corridor runs north-south and the slab runs east-west."""
        left_right = self.is_solid_char(self.char(x - 1, y)) and self.is_solid_char(self.char(x + 1, y))
        up_down = self.is_solid_char(self.char(x, y - 1)) and self.is_solid_char(self.char(x, y + 1))
        if left_right and not up_down:
            return False       # slab runs east-west (constant y)
        if up_down and not left_right:
            return True        # slab runs north-south (constant x)
        # ambiguous: prefer the orientation with open floor on the other axis
        open_lr = (not self.is_solid_char(self.char(x - 1, y))) + (not self.is_solid_char(self.char(x + 1, y)))
        open_ud = (not self.is_solid_char(self.char(x, y - 1))) + (not self.is_solid_char(self.char(x, y + 1)))
        return open_lr >= open_ud

    def parse(self):
        for y, row in enumerate(self.grid):
            for x, ch in enumerate(row):
                if ch == '#':
                    self.walls[(x, y)] = self.default_wall
                elif ch in WALL_CHARS:
                    self.walls[(x, y)] = int(ch)
                elif ch == EXIT_CHAR:
                    self.walls[(x, y)] = TEX_EXIT
                    self.exits.add((x, y))
                elif ch in DOOR_CHARS:
                    locked = DOOR_CHARS[ch]
                    self.doors.append(DoorSpec(x, y, self.door_orientation(x, y), locked,
                                               texture=DOOR_TEXTURES[locked]))
                elif ch == SECRET_DOOR:
                    self.doors.append(DoorSpec(x, y, self.door_orientation(x, y), None, secret=True,
                                               texture=self.neighbor_wall_texture(x, y)))
                elif ch == START_CHAR:
                    self.player_start = (x + 0.5, y + 0.5)
                elif ch == SECRET_FLOOR:
                    self.secret_tiles.add((x, y))
                elif ch in THING_LEGEND:
                    self.things.append(Thing(THING_LEGEND[ch], x, y))
                elif ch in FLOOR_CHARS or ch == ' ':
                    pass
                else:
                    raise ValueError(f'{self.id}: unknown grid character {ch!r} at {x},{y}')
        if self.player_start is None:
            self.player_start = (1.5, 1.5)

    def neighbor_wall_texture(self, x, y):
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            ch = self.char(nx, ny)
            if ch == '#':
                return self.default_wall
            if ch in WALL_CHARS:
                return int(ch)
        return self.default_wall

    # ------------------------------------------------------------ queries
    def is_floor(self, x, y):
        """True when the tile is walkable ground (doors count as floor here)."""
        ch = self.char(x, y)
        return not self.is_solid_char(ch) or ch in DOOR_CHARS or ch == SECRET_DOOR

    def door_at(self, x, y):
        for door in self.doors:
            if door.x == x and door.y == y:
                return door
        return None

    def secret_areas(self):
        """Group contiguous secret floor tiles into areas (each counts once)."""
        areas = []
        seen = set()
        for tile in sorted(self.secret_tiles):
            if tile in seen:
                continue
            area = set()
            queue = deque([tile])
            seen.add(tile)
            while queue:
                cx, cy = queue.popleft()
                area.add((cx, cy))
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if (nx, ny) in self.secret_tiles and (nx, ny) not in seen:
                        seen.add((nx, ny))
                        queue.append((nx, ny))
            areas.append(frozenset(area))
        return areas

    def count(self, kind):
        return sum(1 for t in self.things if t.kind == kind)

    @property
    def enemy_count(self):
        return sum(1 for t in self.things if t.kind in ENEMY_KINDS)


# -------------------------------------------------------------------- loading
class LevelError(ValueError):
    pass


def load_level(level_id, validate=True):
    path = os.path.join(LEVEL_DIR, f'{level_id}.json')
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except OSError as exc:
        raise LevelError(f'cannot read level {level_id!r}: {exc}') from exc
    except ValueError as exc:
        raise LevelError(f'level {level_id!r} is not valid JSON: {exc}') from exc
    if not isinstance(data, dict) or 'grid' not in data:
        raise LevelError(f'level {level_id!r} needs a "grid"')
    level = LevelData(data, level_id)
    if validate:
        problems = validate_level(level)
        if problems:
            raise LevelError(f'level {level_id!r} is not playable: ' + '; '.join(problems[:5]))
    return level


def load_episode():
    """``levels/episode.json``: level order, story and credits text."""
    path = os.path.join(LEVEL_DIR, 'episode.json')
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh)


# -------------------------------------------------------------------- validation
def reachable_tiles(level, start_tile, keys=()):
    """Flood fill over walkable tiles from ``start_tile`` given owned keys."""
    keys = set(keys)
    doors = {d.pos: d for d in level.doors}
    seen = {start_tile}
    queue = deque([start_tile])
    while queue:
        cx, cy = queue.popleft()
        for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
            if (nx, ny) in seen or not level.is_floor(nx, ny):
                continue
            door = doors.get((nx, ny))
            if door is not None and door.locked and door.locked not in keys:
                continue
            seen.add((nx, ny))
            queue.append((nx, ny))
    return seen


def validate_level(level):
    """Return a list of human readable problems (empty when the level is sound)."""
    problems = []
    if level.player_start is None:
        problems.append('no player start (P)')
    if not level.exits:
        problems.append('no exit switch (X)')
    for row in level.grid:
        if len(row) != level.cols:
            problems.append('ragged grid rows')
            break
    # border must be solid so rays and pathfinding never leave the grid
    for x in range(level.cols):
        for y in (0, level.rows - 1):
            if level.is_floor(x, y):
                problems.append(f'open border tile at {x},{y}')
    for y in range(level.rows):
        for x in (0, level.cols - 1):
            if level.is_floor(x, y):
                problems.append(f'open border tile at {x},{y}')
    for thing in level.things:
        if not level.is_floor(thing.x, thing.y):
            problems.append(f'{thing.kind} placed inside a wall at {thing.x},{thing.y}')
    for door in level.doors:
        if level.is_floor(door.x - 1, door.y) and level.is_floor(door.x + 1, door.y) \
                and level.is_floor(door.x, door.y - 1) and level.is_floor(door.x, door.y + 1):
            problems.append(f'door at {door.x},{door.y} is not embedded in a wall')
    # progression: collect keys iteratively and check the exit is reachable
    start = (int(level.player_start[0]), int(level.player_start[1]))
    keys = set()
    while True:
        reach = reachable_tiles(level, start, keys)
        found = {KEY_KINDS[t.kind] for t in level.things if t.kind in KEY_KINDS and (t.x, t.y) in reach}
        if found <= keys:
            break
        keys |= found
    exit_reachable = any(
        (ex + dx, ey + dy) in reach
        for (ex, ey) in level.exits for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)))
    if level.exits and not exit_reachable:
        problems.append('exit switch is not reachable from the player start')
    for thing in level.things:
        if (thing.x, thing.y) not in reach:
            problems.append(f'{thing.kind} at {thing.x},{thing.y} is unreachable')
    for door in level.doors:
        if door.locked and door.locked not in keys:
            problems.append(f'{door.locked} door at {door.x},{door.y} but its key is unreachable')
    return problems
