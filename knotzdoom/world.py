"""A World is one loaded level plus everything alive inside it."""
import math
import random

from .level import ENEMY_KINDS
from .objects import ObjectHandler
from .pathfinding import PathFinding
from .player import Player
from .settings import DIFFICULTIES, DOOR_OPEN_TIME, DOOR_PASSABLE, DOOR_STAY_OPEN


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
        self.doors = {}
        self.doors_h = {}
        self.doors_v = {}
        for spec in level.doors:
            door = Door(self, spec)
            self.doors[door.pos] = door
            (self.doors_v if door.vertical else self.doors_h)[door.pos] = door
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

    def blocks_projectile(self, tile):
        if tile in self.walls:
            return True
        door = self.doors.get(tile)
        if door is not None and door.open < 0.5:
            return True
        x, y = tile
        return not (0 <= x < self.level.cols and 0 <= y < self.level.rows)

    def tile_occupied(self, tile):
        player = self.player
        if abs(player.x - (tile[0] + 0.5)) < 0.8 and abs(player.y - (tile[1] + 0.5)) < 0.8:
            return True
        return tile in self.objects.npc_tiles

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
        from .assets import TEX_EXIT, TEX_EXIT_ON
        for pos in self.level.exits:
            if self.walls.get(pos) == TEX_EXIT:
                self.walls[pos] = TEX_EXIT_ON
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
        """Fire ``pellets`` hitscan rays from the player around its view direction."""
        player = self.player
        renderer = self.renderer
        if renderer is None:
            return
        view = renderer.view
        depth = renderer.raycaster.depth
        targets = [t for t in self.objects.shootable() if t.on_screen]
        for _ in range(pellets):
            offset = random.uniform(-spread, spread) if spread else 0.0
            col = int(view.half_num_rays + offset / view.delta_angle)
            col = max(0, min(view.num_rays - 1, col))
            px = col * view.column + view.column / 2
            wall_depth = float(depth[col])
            best = None
            for target in targets:
                if abs(target.screen_x - px) <= target.half_width * 0.85 and target.norm_dist < wall_depth:
                    if best is None or target.norm_dist < best.norm_dist:
                        best = target
            if best is not None:
                best.take_damage(random.randint(*damage_range), source=player)
                if hasattr(best, 'hp') and getattr(best, 'kind', '') != 'barrel':
                    # blood slightly towards the shooter so it is not hidden inside the sprite
                    bx = best.x - math.cos(best.theta) * 0.2
                    by = best.y - math.sin(best.theta) * 0.2
                    self.objects.spawn_blood((bx, by), best.scale * 0.55)
            else:
                ray_angle = player.angle + offset
                dist = wall_depth / max(0.2, math.cos(offset)) - 0.12
                px_w = player.x + math.cos(ray_angle) * dist
                py_w = player.y + math.sin(ray_angle) * dist
                if not self.blocks_projectile((int(px_w), int(py_w))):
                    self.objects.spawn_puff((px_w, py_w), random.uniform(0.3, 0.6))

    def splash_damage(self, x, y, radius, damage, source=None):
        for target in self.objects.shootable():
            d = math.hypot(target.x - x, target.y - y)
            if d < radius:
                target.take_damage(int(damage * (1.0 - d / radius)) + 1, source=source)
        player = self.player
        d = math.hypot(player.x - x, player.y - y)
        if d < radius and player.alive:
            player.get_damage(int(damage * 0.7 * (1.0 - d / radius)), source=source)

    def spawn_rocket(self, x, y, angle, owner='player', damage=100, z=0.4):
        return self.objects.spawn_projectile('rocket', x, y, angle, owner, damage, z)

    def spawn_fireball(self, x, y, angle, damage=20, z=0.45):
        return self.objects.spawn_projectile('fireball', x, y, angle, 'npc', damage, z)

    # ------------------------------------------------------------ persistence
    def save_state(self):
        from .assets import TEX_EXIT_ON
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
