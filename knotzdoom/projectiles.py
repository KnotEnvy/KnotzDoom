"""Fireballs and rockets."""
import math

from .sprites import AnimatedSprite

PROJECTILE_DEFS = {
    'fireball': {'frames': 'projectiles/fireball', 'scale': 0.32, 'speed': 7.0, 'frame_time': 90,
                 'splash_radius': 0.0, 'splash_damage': 0, 'explosion_scale': 0.45,
                 'sound': 'fireball', 'shake': 0},
    'rocket': {'frames': 'projectiles/rocket', 'scale': 0.28, 'speed': 11.0, 'frame_time': 60,
               'splash_radius': 2.2, 'splash_damage': 90, 'explosion_scale': 1.0,
               'sound': 'explosion', 'shake': 12},
}


class Projectile(AnimatedSprite):
    bright = True

    def __init__(self, world, kind, x, y, angle, owner='player', damage=20, z=0.4):
        d = PROJECTILE_DEFS[kind]
        self.kind = kind
        self.defn = d
        frames = world.game.assets.frames(d['frames'])
        # start a little in front of the shooter so it never hits them
        super().__init__(world, frames, (x + math.cos(angle) * 0.45, y + math.sin(angle) * 0.45),
                         d['scale'], z, d['frame_time'])
        self.angle = angle
        self.owner = owner
        self.damage = damage
        self.vx = math.cos(angle) * d['speed']
        self.vy = math.sin(angle) * d['speed']
        self.age = 0.0
        if world.blocks_point(self.x, self.y):
            self.explode()

    def update(self, dt):
        if not self.alive:
            return
        super().update(dt)
        self.age += dt
        if self.age > 8000:
            self.alive = False
            return
        world = self.world
        seconds = dt / 1000.0
        # sub-step so fast rockets never tunnel through a wall
        steps = max(1, int(math.hypot(self.vx, self.vy) * seconds / 0.25) + 1)
        for _ in range(steps):
            nx = self.x + self.vx * seconds / steps
            ny = self.y + self.vy * seconds / steps
            if world.blocks_point(nx, ny):
                self.explode()
                return
            self.x, self.y = nx, ny
            if self.check_targets():
                return

    def check_targets(self):
        world = self.world
        if self.owner == 'player':
            for target in world.objects.shootable():
                if math.hypot(target.x - self.x, target.y - self.y) < target.radius + 0.15:
                    target.take_damage(self.damage)
                    self.explode()
                    return True
        else:
            player = world.player
            if player.alive and math.hypot(player.x - self.x, player.y - self.y) < 0.5:
                player.take_damage(self.damage)
                self.explode()
                return True
            for target in world.objects.barrels():
                if math.hypot(target.x - self.x, target.y - self.y) < target.radius + 0.1:
                    target.take_damage(self.damage)
                    self.explode()
                    return True
        return False

    def explode(self):
        if not self.alive:
            return
        self.alive = False
        world = self.world
        d = self.defn
        world.objects.spawn_explosion(self.pos, self.z, d['explosion_scale'])
        world.audio.play(d['sound'], pos=self.pos, volume=0.9 if self.kind == 'rocket' else 0.5)
        if d['splash_radius'] > 0:
            splash = d['splash_damage']
            if self.owner != 'player':
                splash *= 0.6 * world.difficulty['dmg']
            world.splash_damage(self.x, self.y, d['splash_radius'], splash)
        if d['shake']:
            dist = math.hypot(world.player.x - self.x, world.player.y - self.y)
            if dist < 6:
                world.fx.shake = max(world.fx.shake, int(d['shake'] * (1 - dist / 6)))
        world.fx.flash_ms = max(world.fx.flash_ms, 120)
