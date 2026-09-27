"""Sound effects and music with volume control and distance attenuation."""
import math
import os

import pygame as pg

from .settings import MUSIC_DIR, SOUND_DIR

SFX_FILES = {
    'shotgun': 'shotgun.wav', 'npc_pain': 'npc_pain.wav', 'npc_death': 'npc_death.wav',
    'npc_attack': 'npc_attack.wav', 'player_pain': 'player_pain.wav',
    'pistol': 'pistol.wav', 'chaingun': 'chaingun.wav', 'rocket_launch': 'rocket_launch.wav',
    'explosion': 'explosion.wav', 'barrel_explode': 'barrel_explode.wav',
    'door_open': 'door_open.wav', 'door_close': 'door_close.wav', 'door_locked': 'door_locked.wav',
    'pickup_item': 'pickup_item.wav', 'pickup_weapon': 'pickup_weapon.wav', 'pickup_key': 'pickup_key.wav',
    'powerup': 'powerup.wav', 'switch': 'switch.wav', 'secret_found': 'secret_found.wav',
    'menu_move': 'menu_move.wav', 'menu_select': 'menu_select.wav', 'menu_back': 'menu_back.wav',
    'player_death': 'player_death.wav', 'fireball': 'fireball.wav', 'level_complete': 'level_complete.wav',
    'tally_tick': 'tally_tick.wav', 'tally_done': 'tally_done.wav',
}
BASE_VOLUMES = {'npc_attack': 0.35, 'chaingun': 0.6, 'pistol': 0.7, 'tally_tick': 0.5, 'menu_move': 0.5}

MUSIC_FILES = {
    'theme': os.path.join(SOUND_DIR, 'theme.mp3'),
    'menu': os.path.join(MUSIC_DIR, 'menu.wav'),
    'intermission': os.path.join(MUSIC_DIR, 'intermission.wav'),
    'boss': os.path.join(MUSIC_DIR, 'boss.wav'),
    'hell': os.path.join(MUSIC_DIR, 'hell.wav'),
    'victory': os.path.join(MUSIC_DIR, 'victory.wav'),
}


class Audio:
    def __init__(self, config):
        self.config = config
        self.enabled = True
        self.sounds = {}
        self.current_music = None
        self.listener = None            # object with x, y used for attenuation
        try:
            if not pg.mixer.get_init():
                pg.mixer.init()
            pg.mixer.set_num_channels(32)
        except pg.error:
            self.enabled = False
        if self.enabled:
            for name, filename in SFX_FILES.items():
                path = os.path.join(SOUND_DIR, filename)
                try:
                    self.sounds[name] = pg.mixer.Sound(path)
                except (pg.error, FileNotFoundError):
                    pass
        self.apply_volumes()

    # ------------------------------------------------------------ volumes
    @property
    def sfx_volume(self):
        return float(self.config['sfx_volume'])

    @property
    def music_volume(self):
        return float(self.config['music_volume'])

    def apply_volumes(self):
        if not self.enabled:
            return
        try:
            pg.mixer.music.set_volume(self.music_volume)
        except pg.error:
            pass

    # ------------------------------------------------------------ playback
    def play(self, name, volume=1.0, pos=None, max_dist=18.0):
        """Play a sound; if ``pos`` is given it is attenuated by distance to the listener."""
        if not self.enabled:
            return
        sound = self.sounds.get(name)
        if sound is None:
            return
        gain = volume * self.sfx_volume * BASE_VOLUMES.get(name, 1.0)
        if pos is not None and self.listener is not None:
            dist = math.hypot(pos[0] - self.listener.x, pos[1] - self.listener.y)
            if dist >= max_dist:
                return
            gain *= max(0.0, 1.0 - dist / max_dist) ** 1.3
        if gain <= 0.01:
            return
        channel = sound.play()
        if channel is not None:
            channel.set_volume(min(1.0, gain))

    def play_music(self, name, loops=-1, fade_ms=600):
        if not self.enabled:
            return
        if name == self.current_music and pg.mixer.music.get_busy():
            return
        path = MUSIC_FILES.get(name)
        if path is None or not os.path.exists(path):
            self.stop_music()
            return
        try:
            pg.mixer.music.load(path)
            pg.mixer.music.set_volume(self.music_volume)
            pg.mixer.music.play(loops, fade_ms=fade_ms)
            self.current_music = name
        except pg.error:
            self.current_music = None

    def stop_music(self, fade_ms=400):
        if not self.enabled:
            return
        try:
            pg.mixer.music.fadeout(fade_ms)
        except pg.error:
            pass
        self.current_music = None

    def pause_music(self):
        if self.enabled:
            pg.mixer.music.pause()

    def resume_music(self):
        if self.enabled:
            pg.mixer.music.unpause()
