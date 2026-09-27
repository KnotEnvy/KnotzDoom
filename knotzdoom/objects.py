"""Spawns and updates every entity in a level."""
import math
import random

from .level import ENEMY_KINDS
from .npc import NPC
from .pickups import Barrel, Pickup, Prop, PICKUP_DEFS, PROP_DEFS
from .projectiles import Projectile
from .sprites import Particle


class ObjectHandler:
    def __init__(self, world):
        self.world = world
        self.npcs = []
        self.pickups = []
        self.props = []
        self.projectiles = []
        self.particles = []
        self.npc_tiles = set()
        self.spawn_from_level()

    # ------------------------------------------------------------ spawning
    def spawn_from_level(self):
        world = self.world
        skip = world.difficulty['skip']
        enemy_index = 0
        for i, thing in enumerate(world.level.things):
            kind = thing.kind
            if kind in ENEMY_KINDS:
                enemy_index += 1
                if skip and kind != 'cyberdemon' and enemy_index % skip == 0:
                    continue
                self.npcs.append(NPC(world, kind, thing.pos))
            elif kind in PICKUP_DEFS:
                self.pickups.append(Pickup(world, kind, thing.pos, index=i))
            elif kind == 'barrel':
                self.props.append(Barrel(world, thing.pos, index=i))
            elif kind in PROP_DEFS:
                self.props.append(Prop(world, kind, thing.pos))

    # ------------------------------------------------------------ queries
    def drawable(self):
        result = []
        result.extend(self.props)
        result.extend(self.pickups)
        result.extend(self.npcs)
        result.extend(self.projectiles)
        result.extend(self.particles)
        return result

    def alive_npcs(self):
        return [npc for npc in self.npcs if npc.is_alive]

    def barrels(self):
        return [p for p in self.props if isinstance(p, Barrel) and p.alive]

    def shootable(self):
        return self.alive_npcs() + self.barrels()

    # ------------------------------------------------------------ update
    def update(self, dt):
        self.npc_tiles = {npc.map_pos for npc in self.npcs if npc.is_alive}
        for prop in self.props:
            prop.update(dt)
        for pickup in self.pickups:
            pickup.update(dt)
        for npc in self.npcs:
            npc.update(dt)
        for projectile in self.projectiles:
            projectile.update(dt)
        for particle in self.particles:
            particle.update(dt)
        self.props = [p for p in self.props if p.alive]
        self.pickups = [p for p in self.pickups if p.alive]
        self.projectiles = [p for p in self.projectiles if p.alive]
        self.particles = [p for p in self.particles if p.alive]

    # ------------------------------------------------------------ effects
    def spawn_projectile(self, kind, x, y, angle, owner, damage, z=0.4):
        projectile = Projectile(self.world, kind, x, y, angle, owner, damage, z)
        if projectile.alive:
            self.projectiles.append(projectile)
        return projectile

    def spawn_explosion(self, pos, z, scale):
        frames = self.world.game.assets.frames('projectiles/explosion')
        self.particles.append(Particle(self.world, frames, pos, scale=scale, z=z, frame_time=70, bright=True))

    def spawn_blood(self, pos, z, count=3):
        frames = self.world.game.assets.frames('projectiles/blood')
        for _ in range(count):
            vel = (random.uniform(-0.8, 0.8), random.uniform(-0.8, 0.8), random.uniform(0.3, 1.2))
            self.particles.append(Particle(self.world, frames, pos, scale=random.uniform(0.1, 0.18),
                                           z=z + random.uniform(-0.1, 0.15), frame_time=110,
                                           velocity=vel, gravity=3.0))

    def spawn_puff(self, pos, z):
        frames = self.world.game.assets.frames('projectiles/puff')
        self.particles.append(Particle(self.world, frames, pos, scale=0.14, z=z, frame_time=90,
                                       velocity=(0, 0, 0.35), lifetime=400, bright=True))

    def spawn_puff_near(self, player, angle):
        """A miss from an enemy: a puff on the wall behind the player."""
        dist = random.uniform(0.6, 1.4)
        px = player.x + math.cos(angle) * dist + random.uniform(-0.4, 0.4)
        py = player.y + math.sin(angle) * dist + random.uniform(-0.4, 0.4)
        if not self.world.blocks_projectile((int(px), int(py))):
            self.spawn_puff((px, py), random.uniform(0.2, 0.7))

    # ------------------------------------------------------------ persistence
    def save_state(self):
        return {
            'npcs': [npc.save_state() for npc in self.npcs],
            'pickups_left': [p.index for p in self.pickups],
            'barrels_left': [b.index for b in self.barrels()],
        }

    def restore_state(self, state):
        for npc, saved in zip(self.npcs, state.get('npcs', [])):
            npc.restore_state(saved)
        if 'pickups_left' in state:
            left = set(state['pickups_left'])
            self.pickups = [p for p in self.pickups if p.index in left]
        if 'barrels_left' in state:
            left = set(state['barrels_left'])
            for prop in list(self.props):
                if isinstance(prop, Barrel) and prop.index not in left:
                    prop.alive = False
                    self.world.solid_tiles.discard(prop.map_pos)
            self.props = [p for p in self.props if p.alive]
