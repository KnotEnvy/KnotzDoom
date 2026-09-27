"""Text rendering in the style of the existing red glowing HUD digits.

``BigFont`` renders bevelled, glowing red letters (title, menus, headings).
``PixelFont`` renders small chunky text (messages, HUD labels, options).
Both cache rendered surfaces because text is re-drawn every frame.
"""
import pygame as pg

RED_TOP = (255, 120, 80)
RED_MID = (235, 45, 30)
RED_BOTTOM = (120, 8, 8)
GRAY_TOP = (215, 215, 215)
GRAY_MID = (150, 150, 150)
GRAY_BOTTOM = (70, 70, 70)
GOLD_TOP = (255, 240, 170)
GOLD_MID = (240, 180, 40)
GOLD_BOTTOM = (130, 70, 10)
PALETTES = {
    'red': (RED_TOP, RED_MID, RED_BOTTOM, (255, 60, 30)),
    'gray': (GRAY_TOP, GRAY_MID, GRAY_BOTTOM, (180, 180, 180)),
    'gold': (GOLD_TOP, GOLD_MID, GOLD_BOTTOM, (255, 200, 60)),
}


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


class BigFont:
    def __init__(self, size=56):
        self.size = size
        self.font = pg.font.Font(None, size)
        self.font.set_bold(True)
        self.cache = {}

    def render(self, text, palette='red', glow=True):
        key = (text, palette, glow)
        if key in self.cache:
            return self.cache[key]
        top, mid, bottom, glow_color = PALETTES[palette]
        outline = max(1, self.size // 24)
        pad = outline * 2 + (self.size // 6 if glow else 0)
        base = self.font.render(text, True, (255, 255, 255)).convert_alpha()
        w, h = base.get_size()
        # vertical gradient masked by the glyphs
        gradient = pg.Surface((w, h), pg.SRCALPHA)
        for y in range(h):
            t = y / max(1, h - 1)
            color = _lerp(top, mid, t * 2) if t < 0.5 else _lerp(mid, bottom, (t - 0.5) * 2)
            pg.draw.line(gradient, color + (255,), (0, y), (w, y))
        gradient.blit(base, (0, 0), special_flags=pg.BLEND_RGBA_MULT)
        dark = self.font.render(text, True, (30, 0, 0)).convert_alpha()
        surf = pg.Surface((w + pad * 2, h + pad * 2), pg.SRCALPHA)
        if glow:
            glow_surf = self.font.render(text, True, glow_color).convert_alpha()
            padded = pg.Surface((w + pad * 2, h + pad * 2), pg.SRCALPHA)
            padded.blit(glow_surf, (pad, pad))
            small = pg.transform.smoothscale(padded, (max(1, padded.get_width() // 8), max(1, padded.get_height() // 8)))
            blurred = pg.transform.smoothscale(small, padded.get_size())
            blurred.set_alpha(150)
            surf.blit(blurred, (0, 0))
        for dx in range(-outline, outline + 1):
            for dy in range(-outline, outline + 1):
                if dx or dy:
                    surf.blit(dark, (pad + dx, pad + dy))
        surf.blit(gradient, (pad, pad))
        self.cache[key] = surf
        return surf

    def draw(self, screen, text, x, y, palette='red', align='center', glow=True):
        surf = self.render(text, palette, glow)
        rect = surf.get_rect()
        if align == 'center':
            rect.center = (x, y)
        elif align == 'left':
            rect.midleft = (x, y)
        else:
            rect.midright = (x, y)
        screen.blit(surf, rect)
        return rect


class PixelFont:
    """Small text rendered at half size and scaled up 2x for a chunky look."""

    def __init__(self, size=18, scale=2):
        self.font = pg.font.Font(None, size)
        self.scale = scale
        self.cache = {}

    def render(self, text, color=(220, 220, 220), shadow=True):
        key = (text, color, shadow)
        if key in self.cache:
            return self.cache[key]
        base = self.font.render(text, False, color).convert_alpha()
        w, h = base.get_size()
        if shadow:
            dark = self.font.render(text, False, (0, 0, 0)).convert_alpha()
            surf = pg.Surface((w + 1, h + 1), pg.SRCALPHA)
            surf.blit(dark, (1, 1))
            surf.blit(base, (0, 0))
        else:
            surf = base
        surf = pg.transform.scale(surf, (surf.get_width() * self.scale, surf.get_height() * self.scale))
        self.cache[key] = surf
        return surf

    def draw(self, screen, text, x, y, color=(220, 220, 220), align='left', shadow=True):
        surf = self.render(text, color, shadow)
        rect = surf.get_rect()
        if align == 'left':
            rect.topleft = (x, y)
        elif align == 'center':
            rect.midtop = (x, y)
        else:
            rect.topright = (x, y)
        screen.blit(surf, rect)
        return rect

    def height(self):
        return self.font.get_height() * self.scale


class Fonts:
    def __init__(self):
        self.title = BigFont(150)
        self.heading = BigFont(72)
        self.menu = BigFont(54)
        self.small_big = BigFont(38)
        self.pixel = PixelFont(18, 2)
        self.pixel_large = PixelFont(24, 2)
