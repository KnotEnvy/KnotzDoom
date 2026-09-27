"""Weapon definitions and the first-person weapon view."""
import random

import pygame as pg

from .settings import HEIGHT, STATUS_BAR_HEIGHT

WEAPON_DEFS = {
    'pistol': {
        'slot': 1, 'ammo': 'bullets', 'ammo_per_shot': 1, 'pickup_ammo': 20,
        'kind': 'hitscan', 'damage': (10, 16), 'pellets': 1, 'spread': 0.015,
        'rate': 380, 'frame_time': 70, 'sound': 'pistol', 'height': 0.46, 'kick': 10,
        'label': 'PISTOL',
    },
    'shotgun': {
        'slot': 2, 'ammo': 'shells', 'ammo_per_shot': 1, 'pickup_ammo': 8,
        'kind': 'hitscan', 'damage': (5, 15), 'pellets': 7, 'spread': 0.075,
        'rate': 560, 'frame_time': 90, 'sound': 'shotgun', 'height': 0.47, 'kick': 22,
        'label': 'SHOTGUN',
    },
    'chaingun': {
        'slot': 3, 'ammo': 'bullets', 'ammo_per_shot': 1, 'pickup_ammo': 40,
        'kind': 'hitscan', 'damage': (8, 14), 'pellets': 1, 'spread': 0.035,
        'rate': 105, 'frame_time': 52, 'sound': 'chaingun', 'height': 0.48, 'kick': 6,
        'label': 'CHAINGUN',
    },
    'rocket_launcher': {
        'slot': 4, 'ammo': 'rockets', 'ammo_per_shot': 1, 'pickup_ammo': 4,
        'kind': 'rocket', 'damage': (90, 130), 'pellets': 1, 'spread': 0.0,
        'rate': 820, 'frame_time': 120, 'sound': 'rocket_launch', 'height': 0.48, 'kick': 26,
        'label': 'ROCKET LAUNCHER',
    },
}
WEAPON_SLOTS = {d['slot']: name for name, d in WEAPON_DEFS.items()}


class Weapon:
    def __init__(self, player, name):
        self.player = player
        self.world = player.world
        self.name = name
        d = WEAPON_DEFS[name]
        self.defn = d
        self.frames = self.load_frames(name, d)
        self.frame_sets = {1: self.frames}       # frames scaled per view divisor
        self.frame = 0
        self.sequence = list(range(1, len(self.frames)))
        self.seq_index = -1
        self.anim_timer = 0.0
        self.cooldown = 0.0
        self.trigger = False
        self.kick = 0.0

    def load_frames(self, name, d):
        return self.world.game.assets.weapon_frames(name, int(HEIGHT * d['height']))

    # ------------------------------------------------------------ logic
    @property
    def ready(self):
        return self.cooldown <= 0 and self.seq_index < 0

    def update(self, dt):
        if self.cooldown > 0:
            self.cooldown -= dt
        if self.seq_index >= 0:
            self.anim_timer += dt
            while self.anim_timer >= self.defn['frame_time'] and self.seq_index >= 0:
                self.anim_timer -= self.defn['frame_time']
                self.seq_index += 1
                if self.seq_index >= len(self.sequence):
                    self.seq_index = -1
                    self.frame = 0
                else:
                    self.frame = self.sequence[self.seq_index]
        if self.kick > 0:
            self.kick = max(0.0, self.kick - dt * 0.09)
        if self.trigger and self.cooldown <= 0 and self.player.alive:
            self.fire()

    def fire(self):
        player = self.player
        d = self.defn
        ammo_type = d['ammo']
        if ammo_type and player.ammo[ammo_type] < d['ammo_per_shot']:
            self.trigger = False
            player.out_of_ammo()
            return
        if ammo_type:
            player.ammo[ammo_type] -= d['ammo_per_shot']
        self.cooldown += d['rate']              # keep the overshoot so the rate is exact at any fps
        self.seq_index = 0
        self.anim_timer = 0.0
        self.frame = self.sequence[0] if self.sequence else 0
        self.kick = d['kick']
        world = self.world
        world.audio.play(d['sound'])
        world.fx.light = max(world.fx.light, 90)
        world.noise(player.pos, 11)
        if d['kind'] == 'hitscan':
            world.hitscan(player.angle, d['pellets'], d['spread'], d['damage'])
        elif d['kind'] == 'rocket':
            world.spawn_rocket(player.x, player.y, player.angle, owner='player',
                               damage=random.randint(*d['damage']))
            world.fx.shake = max(world.fx.shake, 4)

    # ------------------------------------------------------------ drawing
    def frames_for(self, divisor):
        frames = self.frame_sets.get(divisor)
        if frames is None:
            frames = [pg.transform.smoothscale(img, (max(1, img.get_width() // divisor),
                                                     max(1, img.get_height() // divisor)))
                      for img in self.frames]
            self.frame_sets[divisor] = frames
        return frames

    def draw(self, view, bob_x=0.0, bob_y=0.0, lower=0.0):
        """Draw the weapon into the 3D view (offsets are given in window pixels)."""
        d = view.divisor
        image = self.frames_for(d)[self.frame]
        w, h = image.get_size()
        x = view.half_width - w // 2 + int(bob_x / d)
        y = view.height - h + (30 - STATUS_BAR_HEIGHT) // d + int((bob_y + self.kick) / d + lower * (h + 40 // d))
        view.surface.blit(image, (x, y))
