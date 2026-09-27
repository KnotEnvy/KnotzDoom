"""Items the player can pick up, and decorative / solid props (barrels, pillars, torches)."""
import math
import random

from .sprites import AnimatedSprite
from .weapons import WEAPON_DEFS

PICKUP_DEFS = {
    'stimpack':   {'image': 'pickups/stimpack.png', 'scale': 0.26, 'msg': 'Picked up a stimpack.', 'sound': 'pickup_item'},
    'medikit':    {'image': 'pickups/medikit.png', 'scale': 0.34, 'msg': 'Picked up a medikit.', 'sound': 'pickup_item'},
    'soulsphere': {'frames': 'pickups/soulsphere', 'scale': 0.5, 'z': 0.25, 'frame_time': 140, 'bright': True,
                   'bob': True, 'msg': 'Supercharge!', 'sound': 'powerup'},
    'armor_green': {'image': 'pickups/armor_green.png', 'scale': 0.36, 'msg': 'Picked up the armor.', 'sound': 'pickup_item'},
    'armor_blue': {'image': 'pickups/armor_blue.png', 'scale': 0.36, 'msg': 'Picked up the MegaArmor!', 'sound': 'powerup'},
    'clip':       {'image': 'pickups/bullets.png', 'scale': 0.2, 'msg': 'Picked up a clip.', 'sound': 'pickup_item'},
    'bullet_box': {'image': 'pickups/bullets_box.png', 'scale': 0.3, 'msg': 'Picked up a box of bullets.', 'sound': 'pickup_item'},
    'shells':     {'image': 'pickups/shells.png', 'scale': 0.22, 'msg': 'Picked up 4 shotgun shells.', 'sound': 'pickup_item'},
    'shell_box':  {'image': 'pickups/shells_box.png', 'scale': 0.3, 'msg': 'Picked up a box of shotgun shells.', 'sound': 'pickup_item'},
    'rockets':    {'image': 'pickups/rockets.png', 'scale': 0.3, 'msg': 'Picked up a rocket.', 'sound': 'pickup_item'},
    'rocket_box': {'image': 'pickups/rockets_box.png', 'scale': 0.36, 'msg': 'Picked up a box of rockets.', 'sound': 'pickup_item'},
    'key_red':    {'image': 'pickups/key_red.png', 'scale': 0.3, 'z': 0.08, 'bright': True, 'bob': True,
                   'msg': 'Picked up a red keycard.', 'sound': 'pickup_key'},
    'key_blue':   {'image': 'pickups/key_blue.png', 'scale': 0.3, 'z': 0.08, 'bright': True, 'bob': True,
                   'msg': 'Picked up a blue keycard.', 'sound': 'pickup_key'},
    'key_yellow': {'image': 'pickups/key_yellow.png', 'scale': 0.3, 'z': 0.08, 'bright': True, 'bob': True,
                   'msg': 'Picked up a yellow keycard.', 'sound': 'pickup_key'},
    'shotgun':    {'image': 'pickups/weapon_shotgun.png', 'scale': 0.24, 'msg': 'You got the shotgun!', 'sound': 'pickup_weapon'},
    'chaingun':   {'image': 'pickups/weapon_chaingun.png', 'scale': 0.26, 'msg': 'You got the chaingun!', 'sound': 'pickup_weapon'},
    'rocket_launcher': {'image': 'pickups/weapon_rocketlauncher.png', 'scale': 0.26, 'msg': 'You got the rocket launcher!', 'sound': 'pickup_weapon'},
    'backpack':   {'image': 'pickups/backpack.png', 'scale': 0.32, 'msg': 'Picked up a backpack full of ammo!', 'sound': 'pickup_weapon'},
}

AMMO_PICKUPS = {'clip': ('bullets', 10), 'bullet_box': ('bullets', 50), 'shells': ('shells', 4),
                'shell_box': ('shells', 20), 'rockets': ('rockets', 1), 'rocket_box': ('rockets', 5)}
WEAPON_PICKUPS = {'shotgun', 'chaingun', 'rocket_launcher'}
KEY_PICKUPS = {'key_red': 'red', 'key_blue': 'blue', 'key_yellow': 'yellow'}


def _give_weapon(player, kind):
    """A weapon is picked up when it is new or when it still adds ammo."""
    ammo_type = WEAPON_DEFS[kind]['ammo']
    before = player.ammo[ammo_type]
    return player.give_weapon(kind) or player.ammo[ammo_type] > before


# kind -> callable(player, kind) returning True when the item was consumed
PICKUP_EFFECTS = {
    'stimpack': lambda p, k: p.give_health(10),
    'medikit': lambda p, k: p.give_health(25),
    'soulsphere': lambda p, k: p.give_health(100, limit=200),
    'armor_green': lambda p, k: p.give_armor(100, 1),
    'armor_blue': lambda p, k: p.give_armor(200, 2),
    'backpack': lambda p, k: p.give_backpack(),
}
PICKUP_EFFECTS.update({k: (lambda p, kind: p.give_ammo(*AMMO_PICKUPS[kind])) for k in AMMO_PICKUPS})
PICKUP_EFFECTS.update({k: _give_weapon for k in WEAPON_PICKUPS})
PICKUP_EFFECTS.update({k: (lambda p, kind: p.give_key(KEY_PICKUPS[kind])) for k in KEY_PICKUPS})

PROP_DEFS = {
    'barrel':      {'frames': 'decorations/barrel', 'scale': 0.55, 'frame_time': 260, 'solid': True, 'radius': 0.35},
    'pillar':      {'image': 'decorations/pillar.png', 'scale': 1.0, 'solid': True, 'radius': 0.35},
    'torch_red':   {'frames': 'animated_sprites/red_light', 'scale': 0.8, 'frame_time': 120, 'bright': True},
    'torch_green': {'frames': 'animated_sprites/green_light', 'scale': 0.8, 'frame_time': 120, 'bright': True},
    'candelabra':  {'image': 'static_sprites/candlebra.png', 'scale': 0.7, 'bright': True},
    'skulls':      {'image': 'decorations/skulls.png', 'scale': 0.28},
}


class Pickup(AnimatedSprite):
    def __init__(self, world, kind, pos, index=0):
        d = PICKUP_DEFS[kind]
        assets = world.game.assets
        frames = assets.frames(d['frames']) if 'frames' in d else [assets.frame(d['image'])]
        super().__init__(world, frames, pos, d['scale'], d.get('z', 0.0), d.get('frame_time', 150))
        self.kind = kind
        self.index = index
        self.defn = d
        self.bright = d.get('bright', False)
        self.base_z = self.z
        self.bob = d.get('bob', False)
        self.phase = random.uniform(0, math.tau)

    def update(self, dt):
        super().update(dt)
        if self.bob:
            self.phase += dt * 0.004
            self.z = self.base_z + 0.04 * math.sin(self.phase)
        player = self.world.player
        if player.alive and abs(player.x - self.x) < 0.6 and abs(player.y - self.y) < 0.6:
            if math.hypot(player.x - self.x, player.y - self.y) < 0.6:
                self.try_pickup(player)

    def try_pickup(self, player):
        if not self.apply(player):
            return
        self.alive = False
        world = self.world
        world.audio.play(self.defn['sound'])
        world.message(self.defn['msg'])
        world.fx.bonus_flash = max(world.fx.bonus_flash, 90)
        world.stats['items'] += 1
        player.score += 10

    def apply(self, player):
        effect = PICKUP_EFFECTS.get(self.kind)
        return bool(effect and effect(player, self.kind))


class Prop(AnimatedSprite):
    def __init__(self, world, kind, pos):
        d = PROP_DEFS[kind]
        assets = world.game.assets
        frames = assets.frames(d['frames']) if 'frames' in d else [assets.frame(d['image'])]
        super().__init__(world, frames, pos, d['scale'], d.get('z', 0.0), d.get('frame_time', 150))
        self.kind = kind
        self.defn = d
        self.bright = d.get('bright', False)
        self.solid = d.get('solid', False)
        self.radius = d.get('radius', 0.3)
        # desynchronise animations of identical props
        self.anim.index = random.randrange(len(frames))
        self.image = self.anim.image
        if self.solid:
            world.solid_tiles.add(self.map_pos)


class Barrel(Prop):
    """Explosive barrel: 20 hp, blows up with splash damage and chains to neighbours."""

    def __init__(self, world, pos, index=0):
        super().__init__(world, 'barrel', pos)
        self.index = index
        self.hp = 20
        self.fused = False
        self.fuse = 0.0

    def take_damage(self, amount, source=None):
        if self.fused or not self.alive:
            return
        self.hp -= int(amount)
        if self.hp <= 0:
            self.fused = True
            self.fuse = random.uniform(60, 220)

    def update(self, dt):
        super().update(dt)
        if self.fused:
            self.fuse -= dt
            if self.fuse <= 0:
                self.explode()

    def explode(self):
        if not self.alive:
            return
        self.alive = False
        world = self.world
        world.solid_tiles.discard(self.map_pos)
        world.objects.spawn_explosion(self.pos, 0.25, 0.95)
        world.audio.play('barrel_explode', pos=self.pos)
        world.splash_damage(self.x, self.y, 1.9, 90, source=self)
        world.fx.light = max(world.fx.light, 120)
        dist = math.hypot(world.player.x - self.x, world.player.y - self.y)
        if dist < 6:
            world.fx.shake = max(world.fx.shake, int(12 * (1 - dist / 6)))
