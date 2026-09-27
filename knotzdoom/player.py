"""The player: movement, mouse look, inventory, damage and the "use" action."""
import math

import pygame as pg

from .settings import (HEIGHT, MOUSE_BORDER, MOUSE_MAX_PIXELS_PER_SEC, MOUSE_RAD_PER_PIXEL, WIDTH,
                       HALF_WIDTH, HALF_HEIGHT, PLAYER_MAX_ARMOR, PLAYER_MAX_HEALTH, PLAYER_RADIUS,
                       PLAYER_ROT_SPEED, PLAYER_SPEED, PLAYER_SPRINT_MULT, USE_DISTANCE)
from .weapons import WEAPON_DEFS, WEAPON_SLOTS, Weapon

AMMO_MAX = {'bullets': 200, 'shells': 50, 'rockets': 50}
AMMO_NAMES = {'bullets': 'BULL', 'shells': 'SHEL', 'rockets': 'RCKT'}
DEATH_ANIM_TIME = 1100      # ms for the camera to sink to the floor


class Player:
    def __init__(self, world, pos, angle=0.0):
        self.world = world
        self.x, self.y = pos
        self.angle = angle % math.tau
        self.cam_h = 0.5
        self.health = PLAYER_MAX_HEALTH
        self.armor = 0
        self.armor_type = 0                 # 0 none, 1 green (1/3 absorb), 2 blue (1/2 absorb)
        self.ammo = {'bullets': 50, 'shells': 0, 'rockets': 0}
        self.max_ammo = dict(AMMO_MAX)
        self.weapons = {}
        self.weapon = None
        self.pending_weapon = None
        self.switch_progress = 0.0           # 0 = fully raised, 1 = fully lowered
        self.switch_dir = 0                  # -1 raising, +1 lowering, 0 idle
        self.keys = set()
        self.alive = True
        self.death_timer = 0.0
        self.god = False
        self.noclip = False
        self.score = 0
        self.bob_phase = 0.0
        self.bob_amount = 0.0
        self.moving = False
        self.sprinting = False
        self.firing = False
        self.last_hurt = -10000
        self.give_weapon('pistol', announce=False)
        self.ammo['bullets'] = 50

    # ------------------------------------------------------------ properties
    @property
    def pos(self):
        return self.x, self.y

    @property
    def map_pos(self):
        return int(self.x), int(self.y)

    @property
    def game(self):
        return self.world.game

    @property
    def config(self):
        return self.world.game.config

    # ------------------------------------------------------------ inventory
    def give_weapon(self, name, announce=True):
        """Returns True if the weapon was new."""
        is_new = name not in self.weapons
        if is_new:
            self.weapons[name] = Weapon(self, name)
        ammo_type = WEAPON_DEFS[name]['ammo']
        if ammo_type:
            self.give_ammo(ammo_type, WEAPON_DEFS[name]['pickup_ammo'], scale=True)
        if is_new and (self.weapon is None or WEAPON_DEFS[name]['slot'] > WEAPON_DEFS[self.weapon.name]['slot']):
            self.select_weapon(name, instant=self.weapon is None)
        return is_new

    def give_ammo(self, ammo_type, amount, scale=True):
        """Returns True if any ammo was added."""
        if scale:
            amount = int(round(amount * self.world.difficulty['ammo']))
        before = self.ammo[ammo_type]
        self.ammo[ammo_type] = min(self.max_ammo[ammo_type], before + amount)
        return self.ammo[ammo_type] > before

    def give_health(self, amount, limit=PLAYER_MAX_HEALTH):
        if self.health >= limit:
            return False
        self.health = min(limit, self.health + amount)
        return True

    def give_armor(self, amount, armor_type):
        if self.armor >= amount:
            return False
        self.armor = min(PLAYER_MAX_ARMOR, amount)
        self.armor_type = armor_type
        return True

    def give_key(self, color):
        if color in self.keys:
            return False
        self.keys.add(color)
        return True

    def give_backpack(self):
        self.max_ammo = {k: v * 2 for k, v in AMMO_MAX.items()}
        for ammo_type in self.ammo:
            self.give_ammo(ammo_type, {'bullets': 10, 'shells': 4, 'rockets': 1}[ammo_type])
        return True

    def has_ammo_for(self, name):
        ammo_type = WEAPON_DEFS[name]['ammo']
        return ammo_type is None or self.ammo[ammo_type] >= WEAPON_DEFS[name]['ammo_per_shot']

    def select_weapon(self, name, instant=False):
        if name not in self.weapons:
            return False
        if self.weapon is not None and self.weapon.name == name and self.pending_weapon is None:
            return True
        if instant or self.weapon is None:
            self.weapon = self.weapons[name]
            self.pending_weapon = None
            self.switch_progress = 0.0
            self.switch_dir = 0
        else:
            self.pending_weapon = name
            self.switch_dir = 1
        return True

    def select_slot(self, slot):
        name = WEAPON_SLOTS.get(slot)
        if name:
            return self.select_weapon(name)
        return False

    def cycle_weapon(self, direction):
        names = [n for n in WEAPON_SLOTS.values() if n in self.weapons]
        if not names or self.weapon is None:
            return
        idx = names.index(self.weapon.name if self.pending_weapon is None else self.pending_weapon)
        self.select_weapon(names[(idx + direction) % len(names)])

    def best_weapon_with_ammo(self):
        for slot in sorted(WEAPON_SLOTS, reverse=True):
            name = WEAPON_SLOTS[slot]
            if name in self.weapons and self.has_ammo_for(name):
                return name
        return 'pistol'

    # ------------------------------------------------------------ damage
    def get_damage(self, amount, source=None, scaled=True):
        if not self.alive:
            return
        amount = int(round(amount))
        world = self.world
        if amount <= 0 or world.exit_triggered:      # nothing can hurt you once the exit is hit
            return
        if self.god:
            world.fx.damage_flash = max(world.fx.damage_flash, 40)
            return
        if self.armor > 0:
            absorbed = int(amount * (0.5 if self.armor_type == 2 else 0.34))
            absorbed = min(absorbed, self.armor)
            self.armor -= absorbed
            amount -= absorbed
            if self.armor == 0:
                self.armor_type = 0
        self.health -= amount
        self.last_hurt = world.time
        world.fx.damage_flash = min(220, max(world.fx.damage_flash, 50 + amount * 5))
        world.fx.shake = max(world.fx.shake, min(14, 2 + amount // 3))
        world.audio.play('player_pain')
        if self.health <= 0:
            self.health = 0
            self.die()

    def die(self):
        self.alive = False
        self.firing = False
        self.death_timer = 0.0
        if self.weapon:
            self.weapon.trigger = False
        self.world.audio.play('player_death')
        self.world.on_player_death()

    # ------------------------------------------------------------ input
    def handle_event(self, event):
        if not self.alive:
            return
        if event.type == pg.MOUSEBUTTONDOWN:
            if event.button == 1:
                self.firing = True
        elif event.type == pg.MOUSEBUTTONUP and event.button == 1:
            self.firing = False
        elif event.type == pg.MOUSEWHEEL:
            if event.y:
                self.cycle_weapon(1 if event.y > 0 else -1)
        elif event.type == pg.KEYDOWN:
            if pg.K_1 <= event.key <= pg.K_9:
                self.select_slot(event.key - pg.K_0)
            elif event.key in (pg.K_e, pg.K_SPACE):
                self.use()

    def movement(self, dt):
        keys = pg.key.get_pressed()
        forward = (keys[pg.K_w] or keys[pg.K_UP]) - (keys[pg.K_s] or keys[pg.K_DOWN])
        strafe = keys[pg.K_d] - keys[pg.K_a]
        if keys[pg.K_LEFT]:
            self.angle -= PLAYER_ROT_SPEED * dt
        if keys[pg.K_RIGHT]:
            self.angle += PLAYER_ROT_SPEED * dt
        self.angle %= math.tau
        self.moving = bool(forward or strafe)
        if not self.moving:
            return
        self.sprinting = bool(keys[pg.K_LSHIFT] or keys[pg.K_RSHIFT]) != bool(self.config['always_run'])
        speed = PLAYER_SPEED * dt * (PLAYER_SPRINT_MULT if self.sprinting else 1.0)
        # direction in player space, normalised so diagonals are not faster
        length = math.hypot(forward, strafe)
        forward, strafe = forward / length * speed, strafe / length * speed
        sin_a, cos_a = math.sin(self.angle), math.cos(self.angle)
        self.try_move(forward * cos_a - strafe * sin_a, forward * sin_a + strafe * cos_a)

    def try_move(self, dx, dy):
        """Move with wall sliding: each axis is tried separately."""
        if self.noclip:
            self.x += dx
            self.y += dy
            return
        step_blocked = self.world.step_blocked
        if not step_blocked(self.x, self.y, self.x + dx, self.y, PLAYER_RADIUS):
            self.x += dx
        if not step_blocked(self.x, self.y, self.x, self.y + dy, PLAYER_RADIUS):
            self.y += dy

    def mouse_control(self, dt):
        if not self.game.mouse_grabbed:
            return
        mx, my = pg.mouse.get_pos()
        rel = pg.mouse.get_rel()[0]
        if mx < MOUSE_BORDER or mx > WIDTH - MOUSE_BORDER or my < MOUSE_BORDER or my > HEIGHT - MOUSE_BORDER:
            # re-centre the cursor and swallow the warp so the view never jumps
            pg.mouse.set_pos([HALF_WIDTH, HALF_HEIGHT])
            pg.mouse.get_rel()
        self.turn_by_pixels(rel, dt)

    def turn_by_pixels(self, rel, dt):
        """Turn by a mouse delta; the turn per pixel does not depend on the frame rate."""
        limit = MOUSE_MAX_PIXELS_PER_SEC * dt / 1000.0
        rel = max(-limit, min(limit, rel))
        self.angle = (self.angle + rel * MOUSE_RAD_PER_PIXEL * self.config['mouse_sensitivity']) % math.tau

    # ------------------------------------------------------------ use
    def use(self):
        world = self.world
        cos_a, sin_a = math.cos(self.angle), math.sin(self.angle)
        for step in (0.35, 0.7, 1.0, USE_DISTANCE):
            tile = int(self.x + cos_a * step), int(self.y + sin_a * step)
            if tile == self.map_pos:
                continue
            door = world.doors.get(tile)
            if door is not None:
                door.use(self)
                return
            if tile in world.walls:
                if tile in world.level.exits:
                    world.trigger_exit(tile)
                return

    # ------------------------------------------------------------ update
    def update(self, dt):
        if not self.alive:
            self.death_timer += dt
            t = min(1.0, self.death_timer / DEATH_ANIM_TIME)
            self.cam_h = 0.5 - 0.42 * (t * t)
            if self.weapon:
                self.weapon.update(dt)
            return
        self.movement(dt)
        self.mouse_control(dt)
        self.update_bob(dt)
        self.update_weapon_switch(dt)
        if self.weapon:
            self.weapon.trigger = self.firing and self.switch_dir == 0
            self.weapon.update(dt)

    def update_bob(self, dt):
        if self.moving and self.config['head_bob']:
            self.bob_phase += dt * (0.011 if self.sprinting else 0.008)
            self.bob_amount = min(1.0, self.bob_amount + dt / 200.0)
        else:
            self.bob_amount = max(0.0, self.bob_amount - dt / 200.0)
        self.cam_h = 0.5 + 0.012 * math.sin(self.bob_phase) * self.bob_amount

    def update_weapon_switch(self, dt):
        if self.switch_dir == 0:
            return
        self.switch_progress += self.switch_dir * dt / 160.0
        if self.switch_dir > 0 and self.switch_progress >= 1.0:
            self.switch_progress = 1.0
            if self.pending_weapon and self.pending_weapon in self.weapons:
                self.weapon = self.weapons[self.pending_weapon]
            self.pending_weapon = None
            self.switch_dir = -1
        elif self.switch_dir < 0 and self.switch_progress <= 0.0:
            self.switch_progress = 0.0
            self.switch_dir = 0

    def out_of_ammo(self):
        """Called by a weapon that could not fire: switch to something usable."""
        best = self.best_weapon_with_ammo()
        if self.weapon is None or best != self.weapon.name:
            self.select_weapon(best)

    # ------------------------------------------------------------ persistence
    def carry_state(self):
        """What follows the player into the next level."""
        return {
            'health': self.health, 'armor': self.armor, 'armor_type': self.armor_type,
            'ammo': dict(self.ammo), 'max_ammo': dict(self.max_ammo),
            'weapons': sorted(self.weapons), 'weapon': self.weapon.name if self.weapon else 'pistol',
            'score': self.score,
        }

    def restore_carry(self, state):
        self.health = int(state.get('health', self.health))
        self.armor = int(state.get('armor', 0))
        self.armor_type = int(state.get('armor_type', 0))
        self.max_ammo = dict(state.get('max_ammo', AMMO_MAX))
        self.ammo.update({k: int(v) for k, v in state.get('ammo', {}).items()})
        for name in state.get('weapons', []):
            if name in WEAPON_DEFS and name not in self.weapons:
                self.weapons[name] = Weapon(self, name)
        self.score = int(state.get('score', 0))
        self.select_weapon(state.get('weapon', 'pistol'), instant=True)

    def full_state(self):
        state = self.carry_state()
        state.update({'x': self.x, 'y': self.y, 'angle': self.angle, 'keys': sorted(self.keys),
                      'god': self.god, 'noclip': self.noclip})
        return state

    def restore_full(self, state):
        self.restore_carry(state)
        self.x = float(state.get('x', self.x))
        self.y = float(state.get('y', self.y))
        self.angle = float(state.get('angle', self.angle))
        self.keys = set(state.get('keys', []))
        self.god = bool(state.get('god', False))
        self.noclip = bool(state.get('noclip', False))
