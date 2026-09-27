"""A World is one loaded level plus everything alive inside it."""
import math
import random

from .assets import TEX_EXIT, TEX_EXIT_ON
from .objects import ObjectHandler
from .pathfinding import PathFinding
from .player import Player
from .raycasting import line_of_sight, trace
from .settings import (DIFFICULTIES, DOOR_OPEN_TIME, DOOR_PASSABLE, DOOR_STAY_OPEN, DOOR_SLAB_THICKNESS,
                       MAX_DEPTH, PLAYER_RADIUS)


class Effects:
    """Screen effects requested by gameplay code, consumed by the play state."""

    def __init__(self):
        self.damage_flash = 0      # alpha of the red overlay
        self.bonus_flash = 0       # alpha of the yellow overlay
        self.shake = 0             # pixels
        self.light = 0             # ms of extra brightness (muzzle flash / explosion)

    def update(self, dt):
        self.damage_flash = max(0, self.damage_flash - dt * 0.45)
        self.bonus_flash = max(0, self.bonus_flash - dt * 0.4)
        self.shake = max(0, self.shake - dt * 0.03)
        self.light = max(0, self.light - dt)


class Door:
    def __init__(self, world, spec):
        self.world = world
        self.x, self.y = spec.x, spec.y
        self.vertical = spec.vertical
        self.locked = spec.locked
        self.secret = spec.secret
        self.texture = spec.texture
        self.open = 0.0
        self.state = 'closed'      # closed / opening / open / closing
        self.timer = 0.0
        self.found = False

    @property
    def pos(self):
        return self.x, self.y

    @property
    def passable(self):
        return self.open >= DOOR_PASSABLE

    def use(self, player):
        world = self.world
        if self.locked and self.locked not in player.keys:
            world.audio.play('door_locked')
            world.message(f'You need a {self.locked} key to open this door.')
            return False
        if self.state in ('closed', 'closing'):
            self.start_opening()
            if self.secret and not self.found:
                self.found = True
                world.found_secret()
        return True

    def open_for_npc(self):
        if self.locked:
            return False
        if self.state in ('closed', 'closing'):
            self.start_opening()
        return True

    def start_opening(self):
        self.state = 'opening'
        self.world.audio.play('door_open', pos=self.pos)

    def update(self, dt):
        if self.state == 'opening':
            self.open = min(1.0, self.open + dt / DOOR_OPEN_TIME)
            if self.open >= 1.0:
                self.state = 'open'
                self.timer = DOOR_STAY_OPEN
        elif self.state == 'open':
            self.timer -= dt
            if self.timer <= 0:
                if self.world.tile_occupied(self.pos):
                    self.timer = 800
                else:
                    self.state = 'closing'
                    self.world.audio.play('door_close', pos=self.pos)
        elif self.state == 'closing':
            if self.world.tile_occupied(self.pos):
                self.start_opening()
                return
            self.open = max(0.0, self.open - dt / DOOR_OPEN_TIME)
            if self.open <= 0.0:
                self.state = 'closed'

    def save_state(self):
        return {'open': self.open, 'state': self.state, 'timer': self.timer, 'found': self.found}

    def restore_state(self, state):
        self.open = float(state.get('open', 0.0))
        self.state = state.get('state', 'closed')
        self.timer = float(state.get('timer', 0.0))
        self.found = bool(state.get('found', False))


class World:
    def __init__(self, game, level, difficulty_index=1, carry_state=None):
        self.game = game
        self.audio = game.audio
        self.level = level
        self.difficulty_index = difficulty_index
        self.difficulty = DIFFICULTIES[difficulty_index]
        self.walls = dict(level.walls)
        self.cols, self.rows = level.cols, level.rows
        self.doors = {}
        self.door_list = []
        for spec in level.doors:
            door = Door(self, spec)
            self.doors[door.pos] = door
            self.door_list.append(door)
        self.cells = self.build_cells()
        self.seen_tiles = set()
        self.solid_tiles = set()
        self.fx = Effects()
        self.messages = []
        self.time = 0.0
        self.renderer = None
        self.exit_triggered = False
        self.exit_timer = 0.0
        self.player_dead = False
        self.secret_areas = level.secret_areas()
        self.found_areas = set()
        self.stats = {
            'kills': 0, 'items': 0, 'secrets': 0,
            'kills_total': 0, 'items_total': 0,
            'secrets_total': len(self.secret_areas) + sum(1 for d in self.doors.values() if d.secret),
        }
        self.player = Player(self, level.player_start, math.radians(level.player_angle))
        if carry_state:
            self.player.restore_carry(carry_state)
        self.objects = ObjectHandler(self)
        self.stats['kills_total'] = len(self.objects.npcs)
        self.stats['items_total'] = len(self.objects.pickups)
        self.pathfinding = PathFinding(self)
        self.audio.listener = self.player

    # ------------------------------------------------------------ grid
    def build_cells(self):
        """Flat cell list for the raycaster: >0 wall texture, <0 -(door index + 1), 0 floor.
        The border is forced solid so a ray can never leave the grid."""
        cols, rows = self.cols, self.rows
        cells = [0] * (cols * rows)
        for (x, y), tex in self.walls.items():
            cells[y * cols + x] = tex
        for i, door in enumerate(self.door_list):
            cells[door.y * cols + door.x] = -(i + 1)
        for x in range(cols):
            for y in (0, rows - 1):
                if cells[y * cols + x] == 0:
                    cells[y * cols + x] = 1
        for y in range(rows):
            for x in (0, cols - 1):
                if cells[y * cols + x] == 0:
                    cells[y * cols + x] = 1
        return cells

    def set_wall(self, tile, texture):
        self.walls[tile] = texture
        self.cells[tile[1] * self.cols + tile[0]] = texture

    def inside(self, x, y):
        return 0 <= x < self.cols and 0 <= y < self.rows

    # ------------------------------------------------------------ queries
    def blocks_movement(self, tile):
        if tile in self.walls:
            return True
        door = self.doors.get(tile)
        if door is not None and door.open < DOOR_PASSABLE:
            return True
        if tile in self.solid_tiles:
            return True
        x, y = tile
        return not (0 <= x < self.level.cols and 0 <= y < self.level.rows)

    def blocking_tiles(self, x, y, radius):
        """The blocking tiles overlapped by a circle of ``radius`` at (x, y)."""
        blocks = self.blocks_movement
        x0, x1 = int(x - radius), int(x + radius)
        y0, y1 = int(y - radius), int(y + radius)
        return {t for t in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)) if blocks(t)}

    def circle_blocked(self, x, y, radius):
        """True when a circle of ``radius`` at (x, y) overlaps a blocking tile."""
        blocks = self.blocks_movement
        x0, x1 = int(x - radius), int(x + radius)
        y0, y1 = int(y - radius), int(y + radius)
        return (blocks((x0, y0)) or blocks((x1, y0)) or blocks((x0, y1)) or blocks((x1, y1)))

    def step_blocked(self, x, y, nx, ny, radius):
        """Whether a mover may step from (x, y) to (nx, ny).  A mover that already
        overlaps something solid (a door closed on it, say) may still make moves
        that do not enter any new solid tile, so it can never be frozen in place."""
        if not self.circle_blocked(nx, ny, radius):
            return False
        return not self.blocking_tiles(nx, ny, radius) <= self.blocking_tiles(x, y, radius)

    def blocks_point(self, x, y):
        """True when a point (projectile, puff) is inside a wall or on the closed
        part of a door slab, so shots agree with what is drawn."""
        tile = (int(x), int(y))
        if tile in self.walls or not self.inside(x, y):
            return True
        door = self.doors.get(tile)
        if door is None:
            return False
        if door.vertical:
            centre_dist, frac = abs(x - tile[0] - 0.5), y - tile[1]
        else:
            centre_dist, frac = abs(y - tile[1] - 0.5), x - tile[0]
        return centre_dist < DOOR_SLAB_THICKNESS and frac < 1.0 - door.open

    def tile_occupied(self, tile):
        """Does any body (not just a centre point) overlap the tile?  Used by doors."""
        cx, cy = tile[0] + 0.5, tile[1] + 0.5
        player = self.player
        if abs(player.x - cx) < 0.5 + PLAYER_RADIUS and abs(player.y - cy) < 0.5 + PLAYER_RADIUS:
            return True
        for npc in self.objects.npcs:
            if npc.is_alive and abs(npc.x - cx) < 0.5 + npc.radius and abs(npc.y - cy) < 0.5 + npc.radius:
                return True
        return False

    def drawable_sprites(self):
        return self.objects.drawable()

    @property
    def enemies_left(self):
        return sum(1 for npc in self.objects.npcs if npc.is_alive)

    # ------------------------------------------------------------ update
    def update(self, dt):
        self.fx.update(dt)
        if self.player.alive and not self.exit_triggered:
            self.time += dt
        self.player.update(dt)
        for door in self.doors.values():
            door.update(dt)
        self.pathfinding.update(dt)
        self.objects.update(dt)
        self.check_secret_floor()
        if self.exit_triggered:
            self.exit_timer += dt

    def check_secret_floor(self):
        tile = self.player.map_pos
        if tile not in self.level.secret_tiles:
            return
        for area in self.secret_areas:
            if tile in area and area not in self.found_areas:
                self.found_areas.add(area)
                self.found_secret()
                return

    def found_secret(self):
        self.stats['secrets'] += 1
        self.player.score += 250
        self.audio.play('secret_found')
        self.message('A secret is revealed!')

    def message(self, text):
        self.messages.append(text)

    # ------------------------------------------------------------ events
    def on_kill(self, npc):
        self.stats['kills'] += 1
        self.player.score += npc.score
        self.objects.spawn_blood(npc.pos, npc.scale * 0.5, count=5)

    def on_player_death(self):
        self.player_dead = True

    def trigger_exit(self, tile=None):
        if self.exit_triggered:
            return
        self.exit_triggered = True
        self.exit_timer = 0.0
        for pos in self.level.exits:
            if self.walls.get(pos) == TEX_EXIT:
                self.set_wall(pos, TEX_EXIT_ON)
        self.audio.play('switch')
        self.audio.play('level_complete')
        self.player.firing = False

    def noise(self, pos, radius):
        """Wake up enemies that can 'hear' a shot fired at ``pos``."""
        for npc in self.objects.npcs:
            if not npc.is_alive or npc.alerted:
                continue
            d = self.pathfinding.distance(npc.map_pos)
            if d is not None and d <= radius:
                npc.alert()

    # ------------------------------------------------------------ combat
    def hitscan(self, angle, pellets, spread, damage_range):
        """Fire ``pellets`` rays from the player around ``angle``, traced in
        world space: the nearest thing whose collision circle the ray crosses
        before the first wall takes the damage."""
        player = self.player
        targets = self.objects.shootable()
        for _ in range(pellets):
            ray_angle = angle + (random.uniform(-spread, spread) if spread else 0.0)
            cos_a, sin_a = math.cos(ray_angle), math.sin(ray_angle)
            wall_dist = trace(self, player.x, player.y, ray_angle, MAX_DEPTH)
            best, best_dist = None, wall_dist
            for target in targets:
                dx, dy = target.x - player.x, target.y - player.y
                along = dx * cos_a + dy * sin_a
                if along <= 0.0 or along >= best_dist:
                    continue
                across = abs(dy * cos_a - dx * sin_a)
                if across <= target.radius:
                    best, best_dist = target, along
            if best is not None:
                best.take_damage(random.randint(*damage_range), source=player)
                if best.bleeds:
                    # blood slightly towards the shooter so it is not hidden inside the sprite
                    self.objects.spawn_blood((best.x - cos_a * 0.2, best.y - sin_a * 0.2), best.scale * 0.55)
            elif wall_dist < MAX_DEPTH:
                dist = wall_dist - 0.12
                self.objects.spawn_puff((player.x + cos_a * dist, player.y + sin_a * dist), random.uniform(0.3, 0.6))

    def splash_damage(self, x, y, radius, damage, source=None):
        """Radius damage with falloff; walls shield things behind them."""
        for target in self.objects.shootable():
            d = math.hypot(target.x - x, target.y - y)
            if d < radius and line_of_sight(self, x, y, target.x, target.y):
                target.take_damage(int(damage * (1.0 - d / radius)) + 1, source=source)
        player = self.player
        d = math.hypot(player.x - x, player.y - y)
        if d < radius and player.alive and line_of_sight(self, x, y, player.x, player.y):
            player.get_damage(int(damage * 0.7 * (1.0 - d / radius)), source=source)

    def spawn_rocket(self, x, y, angle, owner='player', damage=100, z=0.4):
        return self.objects.spawn_projectile('rocket', x, y, angle, owner, damage, z)

    def spawn_fireball(self, x, y, angle, damage=20, z=0.45):
        return self.objects.spawn_projectile('fireball', x, y, angle, 'npc', damage, z)

    # ------------------------------------------------------------ persistence
    def save_state(self):
        return {
            'level': self.level.id,
            'difficulty': self.difficulty_index,
            'time': self.time,
            'stats': dict(self.stats),
            'player': self.player.full_state(),
            'doors': {f'{x},{y}': d.save_state() for (x, y), d in self.doors.items()},
            'objects': self.objects.save_state(),
            'found_areas': [sorted(area) for area in self.found_areas],
            'seen': sorted(self.seen_tiles),
        }

    def restore_state(self, state):
        self.time = float(state.get('time', 0.0))
        self.stats.update(state.get('stats', {}))
        self.player.restore_full(state.get('player', {}))
        for key, door_state in state.get('doors', {}).items():
            x, y = (int(v) for v in key.split(','))
            door = self.doors.get((x, y))
            if door is not None:
                door.restore_state(door_state)
        self.objects.restore_state(state.get('objects', {}))
        for area in state.get('found_areas', []):
            tiles = frozenset(tuple(t) for t in area)
            for known in self.secret_areas:
                if known == tiles:
                    self.found_areas.add(known)
        self.seen_tiles = {tuple(t) for t in state.get('seen', [])}
        self.pathfinding.flood(self.player.map_pos)
