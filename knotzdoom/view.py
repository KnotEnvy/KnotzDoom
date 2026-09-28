"""View geometry: the size of the 3D view surface and the derived ray constants.

The game window is always ``settings.RES``; the 3D view can be rendered at a
lower internal resolution and scaled up, exactly like Doom's low detail mode.
Everything that projects into the view (raycaster, sprites, weapon, hitscan)
reads its numbers from a ``View`` instead of module constants so the detail
level can change at runtime.
"""
import math

import pygame as pg

from .settings import FOV, HALF_FOV, HEIGHT, RES, WIDTH

DETAIL_LEVELS = {'high': 1, 'low': 2}          # divisor of the window size
DETAIL_ORDER = ['auto', 'high', 'low']
COLUMN_WIDTH = 2                               # screen pixels per ray at full detail


class View:
    def __init__(self, screen, divisor=1):
        self.divisor = divisor
        self.width = WIDTH // divisor
        self.height = HEIGHT // divisor
        self.half_width = self.width // 2
        self.half_height = self.height // 2
        self.column = COLUMN_WIDTH
        self.num_rays = self.width // self.column
        self.half_num_rays = self.num_rays // 2
        self.delta_angle = FOV / self.num_rays
        self.screen_dist = self.half_width / math.tan(HALF_FOV)
        self.max_proj_height = self.height * 12
        self.screen = screen
        # at full detail we draw straight onto the window
        self.surface = screen if divisor == 1 else pg.Surface((self.width, self.height))

    @property
    def scaled(self):
        return self.surface is not self.screen

    def present(self):
        """Blit the view onto the window (a no-op at full detail)."""
        if self.scaled:
            pg.transform.scale(self.surface, RES, self.screen)

    def to_screen(self, x, y):
        """Convert view coordinates to window coordinates."""
        return x * self.divisor, y * self.divisor


class DetailController:
    """Picks the detail divisor from the config; in 'auto' mode it drops to
    low detail when frames get slow and climbs back when there is headroom."""

    SLOW_MS = 19.0        # average frame above this -> low detail
    FAST_MS = 7.0         # average frame below this (at low) -> try high again
    WINDOW_MS = 1500.0

    def __init__(self, config):
        self.config = config
        self.auto_divisor = 1
        self.acc_time = 0.0
        self.acc_frames = 0

    @property
    def divisor(self):
        mode = self.config.get('detail', 'auto')
        if mode in DETAIL_LEVELS:
            return DETAIL_LEVELS[mode]
        return self.auto_divisor

    def record_frame(self, frame_ms):
        """Feed the measured frame time (ms); returns True if the divisor changed."""
        if self.config.get('detail', 'auto') != 'auto':
            return False
        self.acc_time += frame_ms
        self.acc_frames += 1
        if self.acc_time < self.WINDOW_MS:
            return False
        average = self.acc_time / max(1, self.acc_frames)
        self.acc_time = 0.0
        self.acc_frames = 0
        before = self.auto_divisor
        if average > self.SLOW_MS and self.auto_divisor == 1:
            self.auto_divisor = 2
        elif average < self.FAST_MS and self.auto_divisor == 2:
            self.auto_divisor = 1
        return before != self.auto_divisor
