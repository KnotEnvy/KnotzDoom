"""Enemies.

Five monster types are built from the three sprite sets (two are palette
swaps): troopers and sergeants (hitscan), cacodemons (fireballs), hell knights
(fast melee, green cyberdemon) and the cyberdemon boss (rockets).

State machine: idle -> chase <-> attack, with pain interrupts, then dying -> dead.
"""
import math
import random

from .raycasting import line_of_sight
from .settings import DOOR_PASSABLE, LOS_INTERVAL
from .sprites import Animation, AnimatedSprite

NPC_DEFS = {
    'trooper': {
        'sprite': 'npc/soldier', 'variant': None, 'scale': 0.6, 'z': 0.0, 'radius': 0.3,
        'hp': 30, 'speed': 1.5, 'attack': 'hitscan', 'damage': (3, 10), 'pellets': 1,
        'accuracy': 0.55, 'range': 9.0, 'cooldown': 1300, 'pain_chance': 0.75,
        'frame_time': 180, 'attack_frame_time': 200, 'fire_frame': 1, 'score': 100,
        'label': 'TROOPER', 'sight': 15.0,
    },
    'sergeant': {
        'sprite': 'npc/soldier', 'variant': 'dark', 'scale': 0.62, 'z': 0.0, 'radius': 0.3,
        'hp': 50, 'speed': 1.6, 'attack': 'hitscan', 'damage': (3, 8), 'pellets': 3,
        'accuracy': 0.5, 'range': 7.0, 'cooldown': 1500, 'pain_chance': 0.6,
        'frame_time': 180, 'attack_frame_time': 200, 'fire_frame': 1, 'score': 150,
        'label': 'SERGEANT', 'sight': 15.0,
    },
    'cacodemon': {
        'sprite': 'npc/caco_demon', 'variant': None, 'scale': 0.75, 'z': 0.12, 'radius': 0.35,
        'hp': 200, 'speed': 1.3, 'attack': 'fireball', 'damage': (20, 28), 'pellets': 1,
        'accuracy': 1.0, 'range': 11.0, 'cooldown': 1700, 'pain_chance': 0.5,
        'frame_time': 250, 'attack_frame_time': 140, 'fire_frame': 2, 'score': 300,
        'label': 'CACODEMON', 'sight': 16.0,
    },
    'knight': {
        'sprite': 'npc/cyber_demon', 'variant': 'green', 'scale': 0.85, 'z': 0.0, 'radius': 0.35,
        'hp': 320, 'speed': 2.3, 'attack': 'melee', 'damage': (15, 30), 'pellets': 1,
        'accuracy': 1.0, 'range': 1.4, 'cooldown': 900, 'pain_chance': 0.35,
        'frame_time': 190, 'attack_frame_time': 180, 'fire_frame': 1, 'score': 400,
        'label': 'HELL KNIGHT', 'sight': 16.0,
    },
    'cyberdemon': {
        'sprite': 'npc/cyber_demon', 'variant': None, 'scale': 1.0, 'z': 0.0, 'radius': 0.45,
        'hp': 1400, 'speed': 1.7, 'attack': 'rocket', 'damage': (50, 70), 'pellets': 1,
        'accuracy': 1.0, 'range': 15.0, 'cooldown': 1300, 'pain_chance': 0.08,
        'frame_time': 210, 'attack_frame_time': 220, 'fire_frame': 1, 'score': 2500,
        'label': 'CYBERDEMON', 'sight': 20.0, 'boss': True,
    },
}


class NPC(AnimatedSprite):
    bleeds = True

    def __init__(self, world, kind, pos):
        d = NPC_DEFS[kind]
        self.kind = kind
        self.defn = d
        assets = world.game.assets
        self.anims = {name: assets.frames(f"{d['sprite']}/{name}", d['variant'])
                      for name in ('idle', 'walk', 'attack', 'pain', 'death')}
        super().__init__(world, self.anims['idle'], pos, d['scale'], d['z'], d['frame_time'])
        self.anim_name = 'idle'
        self.radius = d['radius']
        self.max_hp = int(d['hp'] * world.difficulty['hp'])
        self.hp = self.max_hp
        self.speed = d['speed'] * world.difficulty['speed']
        self.state = 'idle'
        self.alerted = False
        self.cooldown = random.uniform(400, 1000)
        self.sees_player = False
        self.los_timer = random.uniform(0, 100)
        self.attack_fired = False
        self.score = d['score']

    # ------------------------------------------------------------ helpers
    @property
    def is_alive(self):
        return self.state not in ('dying', 'dead')

    def set_anim(self, name, loop=True, frame_time=None, restart=False):
        if self.anim_name == name and not restart:
            return
        self.anim_name = name
        self.anim = Animation(self.anims[name], frame_time or self.defn['frame_time'], loop)
        self.image = self.anim.image

    def check_sight(self):
        player = self.world.player
        if not player.alive:
            self.sees_player = False
            return
        if self.dist > self.defn['sight']:
            self.sees_player = False
            return
        self.sees_player = line_of_sight(self.world, self.x, self.y, player.x, player.y)

    def alert(self):
        if not self.alerted and self.is_alive:
            self.alerted = True
            self.cooldown = max(self.cooldown, random.uniform(250, 700))

    # ------------------------------------------------------------ update
    def update(self, dt):
        if self.state == 'dead':
            return
        self.anim.update(dt)
        self.image = self.anim.image
        if self.state == 'dying':
            if self.anim.done:
                self.state = 'dead'
            return
        self.cooldown -= dt
        player = self.world.player
        self.dist = math.hypot(player.x - self.x, player.y - self.y)
        self.los_timer += dt
        if self.los_timer >= LOS_INTERVAL:
            self.los_timer = 0
            self.check_sight()

        if self.state == 'pain':
            if self.anim.done:
                self.state = 'chase'
                self.set_anim('walk')
            return
        if self.state == 'attack':
            if not self.attack_fired and self.anim.index >= self.defn['fire_frame']:
                self.attack_fired = True
                self.perform_attack()
            if self.anim.done:
                self.state = 'chase'
                self.cooldown = self.defn['cooldown'] * random.uniform(0.75, 1.25)
                self.set_anim('walk')
            return
        if not self.alerted:
            if self.sees_player and player.alive:
                self.alert()
            self.set_anim('idle')
            return
        if not player.alive:
            self.set_anim('idle')
            return
        if self.can_attack():
            self.start_attack()
            return
        self.state = 'chase'
        self.set_anim('walk')
        self.chase(dt)

    def can_attack(self):
        return self.cooldown <= 0 and self.sees_player and self.dist <= self.defn['range']

    def start_attack(self):
        self.state = 'attack'
        self.attack_fired = False
        self.set_anim('attack', loop=False, frame_time=self.defn['attack_frame_time'], restart=True)

    def perform_attack(self):
        world = self.world
        player = world.player
        if not player.alive:
            return
        d = self.defn
        mult = world.difficulty['dmg']
        kind = d['attack']
        angle = math.atan2(player.y - self.y, player.x - self.x)
        if kind == 'hitscan':
            world.audio.play('npc_attack', pos=self.pos)
            if not line_of_sight(world, self.x, self.y, player.x, player.y):
                return
            for _ in range(d['pellets']):
                chance = d['accuracy'] * max(0.25, 1.0 - self.dist / (d['range'] * 1.6))
                if random.random() < chance:
                    player.take_damage(random.randint(*d['damage']) * mult)
                else:
                    world.objects.spawn_puff_near(player, angle)
        elif kind == 'fireball':
            world.audio.play('fireball', pos=self.pos)
            error = random.uniform(-0.05, 0.05)
            world.spawn_fireball(self.x, self.y, angle + error, damage=random.randint(*d['damage']) * mult,
                                 z=0.45)
        elif kind == 'rocket':
            world.audio.play('rocket_launch', pos=self.pos)
            error = random.uniform(-0.03, 0.03)
            world.spawn_rocket(self.x, self.y, angle + error, owner='npc',
                               damage=random.randint(*d['damage']) * mult, z=0.55)
        elif kind == 'melee':
            world.audio.play('npc_attack', pos=self.pos)
            if self.dist <= d['range'] + 0.3 and line_of_sight(world, self.x, self.y, player.x, player.y):
                player.take_damage(random.randint(*d['damage']) * mult)

    # ------------------------------------------------------------ movement
    def chase(self, dt):
        world = self.world
        player = world.player
        step = self.speed * dt / 1000.0
        if self.sees_player and self.dist < 2.5 and self.defn['attack'] != 'melee' and self.dist > 1.2:
            # keep a little distance when already close and in sight
            return
        if self.sees_player and self.dist < 3.0:
            target = (player.x, player.y)
        else:
            nxt = world.pathfinding.next_step(self.map_pos, world.objects.npc_tiles)
            if nxt is None:
                return
            door = world.doors.get(nxt)
            if door is not None:
                if door.open < DOOR_PASSABLE:
                    door.open_for_npc()
                    if door.open < DOOR_PASSABLE:
                        return
            target = (nxt[0] + 0.5, nxt[1] + 0.5)
        angle = math.atan2(target[1] - self.y, target[0] - self.x)
        dx = math.cos(angle) * step
        dy = math.sin(angle) * step
        if self.defn['attack'] == 'melee' and self.dist < 0.9:
            return
        step_blocked = world.step_blocked
        if not step_blocked(self.x, self.y, self.x + dx, self.y, self.radius):
            self.x += dx
        if not step_blocked(self.x, self.y, self.x, self.y + dy, self.radius):
            self.y += dy

    # ------------------------------------------------------------ damage
    def take_damage(self, amount):
        if not self.is_alive:
            return
        self.hp -= int(amount)
        self.alert()
        if self.hp <= 0:
            self.die()
            return
        self.world.audio.play('npc_pain', pos=self.pos)
        if random.random() < self.defn['pain_chance']:
            self.state = 'pain'
            self.set_anim('pain', loop=False, frame_time=110, restart=True)

    def die(self):
        self.state = 'dying'
        self.set_anim('death', loop=False, frame_time=100, restart=True)
        self.world.audio.play('npc_death', pos=self.pos)
        self.world.on_kill(self)

    # ------------------------------------------------------------ persistence
    def save_state(self):
        return {'kind': self.kind, 'x': self.x, 'y': self.y, 'hp': self.hp,
                'alive': self.is_alive, 'alerted': self.alerted}

    def restore_state(self, state):
        self.x = float(state['x'])
        self.y = float(state['y'])
        self.hp = int(state['hp'])
        self.alerted = bool(state.get('alerted', False))
        if not state.get('alive', True):
            self.state = 'dead'
            self.set_anim('death', loop=False, frame_time=100, restart=True)
            self.anim.index = len(self.anim.frames) - 1
            self.anim.done = True
            self.image = self.anim.image
