"""Asset loading and caching.

Wall textures are stored in "shade banks": ``SHADE_LEVELS`` pre-darkened copies
so that distance shading costs nothing per frame (the same trick the original
Doom used with its COLORMAP light levels).  Sprite frames are loaded once per
directory and shared between every entity that uses them.
"""
import os

import numpy as np
import pygame as pg

from .settings import (HALF_HEIGHT, SHADE_LEVELS, SHADE_MAX_DEPTH, SHADE_MIN_BRIGHT,
                       SPRITE_DIR, TEXTURE_SIZE, TEX_DIR, WIDTH)

# Texture ids used inside the level grid / world map.
TEX_DOOR = 10
TEX_DOOR_RED = 11
TEX_DOOR_BLUE = 12
TEX_DOOR_YELLOW = 13
TEX_EXIT = 14
TEX_EXIT_ON = 15

TEXTURE_FILES = {
    1: '1.png', 2: '2.png', 3: '3.png', 4: '4.png', 5: '5.png',
    6: '6.png', 7: '7.png', 8: '8.png', 9: '9.png',
    TEX_DOOR: 'door.png',
    TEX_DOOR_RED: 'door_red.png',
    TEX_DOOR_BLUE: 'door_blue.png',
    TEX_DOOR_YELLOW: 'door_yellow.png',
    TEX_EXIT: 'exit_switch.png',
    TEX_EXIT_ON: 'exit_switch_on.png',
}

_IMAGE_EXT = ('.png', '.bmp', '.jpg')


def shade_brightness(level):
    """Brightness multiplier (0..1) of a shade level (0 = full bright)."""
    level = max(0, min(SHADE_LEVELS - 1, level))
    return 1.0 - (1.0 - SHADE_MIN_BRIGHT) * level / (SHADE_LEVELS - 1)


def shade_level(depth, light_offset=0):
    """Shade level for a given depth, optionally brightened by ``light_offset``."""
    level = int(depth / SHADE_MAX_DEPTH * (SHADE_LEVELS - 1)) - light_offset
    if level < 0:
        return 0
    if level >= SHADE_LEVELS:
        return SHADE_LEVELS - 1
    return level


def darken(surface, brightness):
    """Return a darkened copy of ``surface`` keeping its alpha channel."""
    if brightness >= 0.999:
        return surface.copy()
    out = surface.copy()
    value = max(0, min(255, int(255 * brightness)))
    out.fill((value, value, value), special_flags=pg.BLEND_RGB_MULT)
    return out


def placeholder_surface(size, color=(255, 0, 255)):
    """A loud checkerboard used when an asset file is missing."""
    surf = pg.Surface(size, pg.SRCALPHA)
    surf.fill(color)
    step = max(4, size[0] // 8)
    for y in range(0, size[1], step):
        for x in range(0, size[0], step):
            if (x // step + y // step) % 2:
                pg.draw.rect(surf, (0, 0, 0), (x, y, step, step))
    return surf


def tint_surface(surface, mode):
    """Create a palette-swapped variant of a sprite frame.

    ``mode`` is one of: 'green' (swap red/green), 'blue' (swap red/blue),
    'dark' (darker, desaturated), 'gold' (warm yellow), 'gray'.
    """
    out = surface.copy()
    rgb = pg.surfarray.pixels3d(out)
    if mode == 'green':
        rgb[:, :, [0, 1]] = rgb[:, :, [1, 0]]
    elif mode == 'blue':
        rgb[:, :, [0, 2]] = rgb[:, :, [2, 0]]
    elif mode == 'dark':
        gray = rgb.mean(axis=2, keepdims=True)
        mixed = (rgb * 0.45 + gray * 0.35).astype(np.uint8)
        rgb[:, :, :] = mixed
    elif mode == 'gold':
        r = np.clip(rgb[:, :, 0].astype(np.int16) + 40, 0, 255)
        g = np.clip(rgb[:, :, 1].astype(np.int16) * 0.9 + 30, 0, 255)
        b = (rgb[:, :, 2] * 0.5).astype(np.uint8)
        rgb[:, :, 0] = r
        rgb[:, :, 1] = g
        rgb[:, :, 2] = b
    elif mode == 'gray':
        gray = rgb.mean(axis=2).astype(np.uint8)
        rgb[:, :, 0] = gray
        rgb[:, :, 1] = gray
        rgb[:, :, 2] = gray
    del rgb
    return out


class Assets:
    """Central cache of every image used by the engine."""

    def __init__(self):
        self.wall_banks = {}       # tex id -> [surface per shade level]
        self.frames_cache = {}     # (dir, variant) -> [surfaces]
        self.image_cache = {}      # path -> surface
        self.sky_cache = {}
        self.missing = []          # asset paths that could not be found
        self.load_wall_textures()
        self.digits = self.load_digits()

    # ------------------------------------------------------------ helpers
    def load_image(self, path, alpha=True):
        if path in self.image_cache:
            return self.image_cache[path]
        try:
            img = pg.image.load(path)
            img = img.convert_alpha() if alpha else img.convert()
        except (pg.error, FileNotFoundError):
            self.missing.append(path)
            img = placeholder_surface((64, 64))
        self.image_cache[path] = img
        return img

    def get_texture(self, path, res=(TEXTURE_SIZE, TEXTURE_SIZE)):
        img = self.load_image(path)
        if img.get_size() != tuple(res):
            img = pg.transform.smoothscale(img, res)
        return img

    # ------------------------------------------------------------ walls
    def load_wall_textures(self):
        for tex_id, filename in TEXTURE_FILES.items():
            path = os.path.join(TEX_DIR, filename)
            base = self.get_texture(path).convert_alpha()
            self.wall_banks[tex_id] = [darken(base, shade_brightness(lvl)) for lvl in range(SHADE_LEVELS)]

    def wall_texture(self, tex_id, level=0):
        bank = self.wall_banks.get(tex_id) or self.wall_banks[1]
        return bank[level]

    # ------------------------------------------------------------ sky
    def sky(self, name='sky'):
        if name in self.sky_cache:
            return self.sky_cache[name]
        path = os.path.join(TEX_DIR, name if name.endswith('.png') else name + '.png')
        img = self.load_image(path, alpha=False)
        img = pg.transform.smoothscale(img, (WIDTH, HALF_HEIGHT))
        self.sky_cache[name] = img
        return img

    # ------------------------------------------------------------ digits
    def load_digits(self, size=64):
        digits = {}
        for i in range(11):
            path = os.path.join(TEX_DIR, 'digits', f'{i}.png')
            digits[str(i)] = self.get_texture(path, (size, size))
        return digits

    # ------------------------------------------------------------ sprites
    def frames(self, rel_dir, variant=None):
        """All frames in ``resources/sprites/<rel_dir>`` sorted by file name."""
        key = (rel_dir, variant)
        if key in self.frames_cache:
            return self.frames_cache[key]
        if variant is not None:
            base = self.frames(rel_dir)
            result = [tint_surface(img, variant) for img in base]
            self.frames_cache[key] = result
            return result
        path = os.path.join(SPRITE_DIR, rel_dir)
        result = []
        if os.path.isdir(path):
            names = sorted(n for n in os.listdir(path) if n.lower().endswith(_IMAGE_EXT))
            for name in names:
                result.append(self.load_image(os.path.join(path, name)))
        if not result:
            self.missing.append(path)
            result = [placeholder_surface((64, 64))]
        self.frames_cache[key] = result
        return result

    def frame(self, rel_path, variant=None):
        """A single sprite image ``resources/sprites/<rel_path>``."""
        key = ('file:' + rel_path, variant)
        if key in self.frames_cache:
            return self.frames_cache[key][0]
        img = self.load_image(os.path.join(SPRITE_DIR, rel_path))
        if variant is not None:
            img = tint_surface(img, variant)
        self.frames_cache[key] = [img]
        return img
