#!/usr/bin/env python3
"""
gen_assets.py - procedural art / sound / music generator for KnotzDoom.

Deterministically generates every extra asset the game needs, matching the
style of the existing 1993-Doom-flavoured art already in ``resources/``:

  * wall textures (256x256 RGB PNG) and two 1200x400 sky panoramas
  * pixel-art sprites (pickups, decorations, projectiles) as RGBA PNGs
  * first-person weapon frames (drawn at 194x210, upscaled 5x nearest -> 970x1050)
  * retro 8-bit flavoured sound effects (16-bit mono 22050 Hz WAV)
  * looping music (16-bit stereo 22050 Hz WAV)

Usage::

    python3 tools/gen_assets.py                          # everything
    python3 tools/gen_assets.py --only sprites           # one family
    python3 tools/gen_assets.py --contact-sheet out.png  # + overview sheet

Only pygame and numpy are required and the script runs headless (dummy SDL
drivers).  All output paths are resolved relative to the repository root (the
parent directory of ``tools/``), never the current working directory.

Layout of this file:
    1. generic helpers (seeding, noise, dithering, palette ramps, Canvas)
    2. wall textures + skies
    3. sprites: pickups, decorations, projectiles, first-person weapons
    4. sound synthesis helpers + sound effects
    5. music sequencing helpers + music loops
    6. contact sheet, verification table, CLI
"""
import os

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

import argparse          # noqa: E402
import math              # noqa: E402
import random            # noqa: E402
import sys               # noqa: E402
import time              # noqa: E402
import wave              # noqa: E402
import zlib              # noqa: E402

import numpy as np       # noqa: E402
import pygame as pg      # noqa: E402

pg.init()
pg.display.set_mode((1, 1))          # convert_alpha() needs a display surface

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES_DIR = os.path.join(ROOT, 'resources')

SR = 22050                            # audio sample rate for everything we write

GENERATED_IMAGES = []                 # (label, absolute path) -> contact sheet
GENERATED_AUDIO = []                  # absolute paths of written WAVs


# ---------------------------------------------------------------------------
# 1. generic helpers
# ---------------------------------------------------------------------------
def seed_for(name):
    """Seed ``random`` and ``numpy.random`` from an asset name.

    Every asset seeds itself, so regenerating a single family (``--only``)
    yields byte-identical files.  Returns a private RandomState as well.
    """
    h = zlib.crc32(name.encode('utf-8')) & 0xffffffff
    random.seed(h)
    np.random.seed(h)
    return np.random.RandomState(h)


def rpath(*parts):
    """Absolute path under resources/, creating the directory."""
    path = os.path.join(RES_DIR, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


# -- noise ------------------------------------------------------------------
BAYER4 = (np.array([[0, 8, 2, 10],
                    [12, 4, 14, 6],
                    [3, 11, 1, 9],
                    [15, 7, 13, 5]], np.float32) + 0.5) / 16.0


def bayer(h, w):
    """4x4 ordered-dither threshold matrix tiled over an (h, w) area."""
    return np.tile(BAYER4, (h // 4 + 1, w // 4 + 1))[:h, :w]


def value_noise(h, w, cell, rng, tile_x=True, tile_y=True):
    """Smooth value noise in [0, 1] with ~``cell`` px features.

    The lattice always has an integer number of cells across the image, so the
    result tiles seamlessly on the requested axes.
    """
    gh = max(1, int(round(h / cell)))
    gw = max(1, int(round(w / cell)))
    grid = rng.random_sample((gh + 1, gw + 1))
    if tile_y:
        grid[-1, :] = grid[0, :]
    if tile_x:
        grid[:, -1] = grid[:, 0]
    ys = np.arange(h) * gh / h
    xs = np.arange(w) * gw / w
    y0 = np.floor(ys).astype(int)
    x0 = np.floor(xs).astype(int)
    fy = ys - y0
    fx = xs - x0
    fy = fy * fy * (3 - 2 * fy)            # smoothstep
    fx = fx * fx * (3 - 2 * fx)
    y1 = np.minimum(y0 + 1, gh)
    x1 = np.minimum(x0 + 1, gw)
    a = grid[np.ix_(y0, x0)]
    b = grid[np.ix_(y0, x1)]
    c = grid[np.ix_(y1, x0)]
    d = grid[np.ix_(y1, x1)]
    fx = fx[None, :]
    fy = fy[:, None]
    top = a * (1 - fx) + b * fx
    bot = c * (1 - fx) + d * fx
    return (top * (1 - fy) + bot * fy).astype(np.float32)


def fbm(h, w, cell, octaves=4, persistence=0.5, rng=None, tile_x=True, tile_y=True):
    """Fractal (multi-octave) value noise, normalised to roughly [0, 1]."""
    rng = rng if rng is not None else np.random
    total = np.zeros((h, w), np.float32)
    amp, norm = 1.0, 0.0
    for o in range(octaves):
        c = max(1.0, cell / (2 ** o))
        total += amp * value_noise(h, w, c, rng, tile_x, tile_y)
        norm += amp
        amp *= persistence
    return total / norm


def ridged(h, w, cell, octaves, rng, tile_x=True, tile_y=True):
    """Billowy 'ridged' noise (1 - |2n - 1|): good for clouds and flesh."""
    return 1.0 - np.abs(fbm(h, w, cell, octaves, 0.5, rng, tile_x, tile_y) * 2 - 1)


def blur(a, radius, wrap=False):
    """Cheap separable box blur repeated 3x (approximates a gaussian)."""
    a = a.astype(np.float32)
    for _ in range(3):
        for axis in (0, 1):
            acc = a.copy()
            for k in range(1, radius + 1):
                if wrap:
                    acc += np.roll(a, k, axis=axis) + np.roll(a, -k, axis=axis)
                else:
                    pad = [(0, 0), (0, 0)]
                    pad[axis] = (k, k)
                    p = np.pad(a, pad, mode='edge')
                    sl_a = [slice(None), slice(None)]
                    sl_b = [slice(None), slice(None)]
                    sl_a[axis] = slice(2 * k, None)
                    sl_b[axis] = slice(0, -2 * k)
                    acc += p[tuple(sl_a)] + p[tuple(sl_b)]
            a = acc / (2 * radius + 1)
    return a


def dilate(mask, r=1):
    """Binary dilation with a diamond (4-neighbour) structuring element."""
    m = mask.copy()
    for _ in range(r):
        p = np.pad(m, 1)
        m = (p[1:-1, 1:-1] | p[2:, 1:-1] | p[:-2, 1:-1] | p[1:-1, 2:] | p[1:-1, :-2])
    return m


def erode(mask, r=1):
    return ~dilate(~mask, r)


# -- palette ramps (dark -> light), Doom-ish muted colours --------------------
RAMPS = {
    'steel':    [(22, 22, 26), (46, 48, 54), (72, 76, 84), (104, 108, 118), (140, 146, 158), (184, 190, 200)],
    'gunmetal': [(12, 12, 14), (28, 28, 32), (48, 50, 56), (74, 78, 86), (108, 114, 124), (150, 156, 166)],
    'stone':    [(24, 22, 20), (48, 46, 42), (76, 74, 68), (106, 104, 96), (136, 134, 124), (166, 164, 152)],
    'cobble':   [(12, 12, 14), (28, 28, 30), (46, 46, 48), (66, 64, 62), (88, 86, 82), (108, 106, 100)],
    'hellbrick': [(10, 8, 8), (22, 18, 18), (36, 30, 30), (52, 44, 42), (70, 60, 56)],
    'flesh':    [(26, 4, 4), (62, 10, 8), (104, 22, 16), (144, 42, 28), (178, 72, 50), (206, 112, 88)],
    'bone':     [(84, 74, 56), (140, 128, 100), (190, 180, 150), (226, 220, 194), (248, 246, 232)],
    'lava':     [(110, 18, 4), (196, 58, 8), (240, 128, 20), (255, 200, 70), (255, 246, 190)],
    'fire':     [(110, 8, 0), (210, 44, 0), (250, 124, 10), (255, 208, 60), (255, 255, 214)],
    'smoke':    [(26, 24, 24), (50, 48, 48), (80, 76, 76), (112, 108, 108), (148, 144, 144), (186, 182, 182)],
    'brass':    [(78, 50, 10), (136, 94, 20), (192, 144, 40), (230, 194, 80), (250, 236, 150)],
    'copper':   [(80, 36, 14), (140, 66, 28), (196, 104, 50), (232, 150, 90)],
    'wood':     [(42, 24, 10), (76, 46, 18), (116, 74, 30), (156, 106, 50), (190, 140, 82)],
    'leather':  [(34, 20, 10), (62, 38, 18), (96, 60, 28), (132, 88, 44), (166, 118, 66)],
    'glove':    [(52, 28, 12), (92, 54, 22), (136, 84, 36), (178, 122, 62), (214, 164, 104)],
    'sleeve':   [(20, 36, 18), (36, 62, 30), (56, 90, 44), (80, 118, 62)],
    'green':    [(16, 46, 16), (30, 86, 28), (52, 132, 42), (92, 182, 68), (156, 228, 118)],
    'toxic':    [(24, 84, 12), (64, 160, 20), (124, 230, 40), (190, 255, 100), (240, 255, 200)],
    'barrel':   [(16, 34, 16), (28, 62, 26), (44, 96, 38), (70, 132, 54), (112, 172, 80)],
    'blue':     [(14, 22, 78), (26, 50, 140), (46, 90, 204), (90, 142, 240), (162, 202, 255)],
    'soul':     [(18, 28, 110), (34, 66, 190), (80, 130, 236), (150, 196, 255), (222, 240, 255)],
    'red':      [(66, 6, 6), (126, 14, 10), (190, 28, 18), (232, 70, 48), (252, 140, 110)],
    'blood':    [(40, 2, 2), (86, 6, 6), (140, 12, 10), (196, 30, 22), (236, 80, 60)],
    'yellow':   [(108, 78, 0), (168, 128, 8), (222, 182, 28), (250, 222, 80), (255, 246, 172)],
    'olive':    [(28, 32, 14), (50, 56, 24), (78, 86, 38), (108, 116, 58), (140, 148, 84)],
    'white':    [(86, 86, 96), (136, 136, 146), (186, 186, 196), (224, 224, 232), (250, 250, 255)],
    'dark':     [(6, 6, 8), (16, 16, 20), (30, 30, 36), (48, 48, 56), (68, 68, 80)],
    'purple':   [(26, 14, 42), (42, 24, 64), (62, 38, 90), (84, 54, 116), (110, 76, 146)],
    'navy':     [(3, 5, 18), (8, 10, 30), (14, 16, 44), (24, 24, 62), (36, 34, 82)],
    'hellsky':  [(6, 2, 2), (34, 6, 4), (78, 14, 8), (134, 34, 12), (196, 82, 26), (244, 160, 62)],
    'explode':  [(28, 18, 18), (76, 28, 18), (154, 48, 10), (228, 118, 18), (255, 200, 60), (255, 255, 222)],
}
OUTLINE = (10, 8, 8)
WHITE = (255, 255, 255)


class Canvas:
    """A small RGBA pixel-art canvas (numpy backed) with mask/ramp helpers.

    Drawing works in two steps: build a boolean *mask* with the geometric
    helpers (rect/ellipse/poly...), then ``fill`` it with a palette ramp
    indexed by a *shade field* (0 = darkest, 1 = lightest) which is quantised
    with ordered (Bayer) dithering - no smooth gradients, like the 1993 art.
    """

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.rgb = np.zeros((h, w, 3), np.float32)
        self.alpha = np.zeros((h, w), np.float32)
        self._bayer = bayer(h, w)
        yy, xx = np.mgrid[0:h, 0:w]
        self.yy = yy.astype(np.float32)
        self.xx = xx.astype(np.float32)

    # -- geometry -> boolean masks -------------------------------------------
    def shape(self, draw):
        s = pg.Surface((self.w, self.h))
        s.fill((0, 0, 0))
        draw(s)
        return pg.surfarray.array_red(s).T > 127

    def rect(self, x, y, w, h):
        if w <= 0 or h <= 0:
            return np.zeros((self.h, self.w), bool)
        return self.shape(lambda s: pg.draw.rect(s, WHITE, (int(x), int(y), int(w), int(h))))

    def ellipse(self, x, y, w, h):
        if w <= 0 or h <= 0:
            return np.zeros((self.h, self.w), bool)
        return self.shape(lambda s: pg.draw.ellipse(s, WHITE, (int(x), int(y), int(w), int(h))))

    def circle(self, cx, cy, r):
        return self.shape(lambda s: pg.draw.circle(s, WHITE, (int(round(cx)), int(round(cy))), max(1, int(round(r)))))

    def poly(self, pts):
        pts = [(int(round(x)), int(round(y))) for x, y in pts]
        return self.shape(lambda s: pg.draw.polygon(s, WHITE, pts))

    def line(self, p0, p1, width=1):
        p0 = (int(round(p0[0])), int(round(p0[1])))
        p1 = (int(round(p1[0])), int(round(p1[1])))
        return self.shape(lambda s: pg.draw.line(s, WHITE, p0, p1, int(width)))

    def rrect(self, x, y, w, h, r):
        """Rounded rectangle (corner radius r)."""
        m = self.rect(x + r, y, w - 2 * r, h) | self.rect(x, y + r, w, h - 2 * r)
        for cx, cy in ((x + r, y + r), (x + w - r - 1, y + r), (x + r, y + h - r - 1), (x + w - r - 1, y + h - r - 1)):
            m |= self.circle(cx, cy, r)
        return m

    def all(self):
        return np.ones((self.h, self.w), bool)

    def none(self):
        return np.zeros((self.h, self.w), bool)

    # -- shade fields: float arrays (h, w), 0 = dark ... 1 = light -------------
    def grad_v(self, y0, y1):
        return np.clip((self.yy - y0) / max(1e-6, (y1 - y0)), 0, 1)

    def grad_h(self, x0, x1):
        return np.clip((self.xx - x0) / max(1e-6, (x1 - x0)), 0, 1)

    def cyl(self, x0, x1, hl=0.35):
        """Vertical cylinder lit from the upper left: highlight at fraction hl."""
        u = (self.xx - x0) / max(1e-6, (x1 - x0))
        d = np.abs(u - hl) / max(hl, 1 - hl)
        return np.clip(1 - d, 0, 1) ** 0.8

    def cyl_v(self, y0, y1, hl=0.3):
        """Horizontal cylinder (highlight at fraction hl from the top)."""
        u = (self.yy - y0) / max(1e-6, (y1 - y0))
        d = np.abs(u - hl) / max(hl, 1 - hl)
        return np.clip(1 - d, 0, 1) ** 0.8

    def sphere(self, cx, cy, r, light=(-0.45, -0.45)):
        dx = (self.xx - cx) / r
        dy = (self.yy - cy) / r
        z = np.sqrt(np.clip(1 - dx * dx - dy * dy, 0, 1))
        lx, ly = light
        lz = math.sqrt(max(0.0, 1 - lx * lx - ly * ly))
        return np.clip(dx * lx + dy * ly + z * lz, 0, 1)

    def radial(self, cx, cy, r):
        return np.clip(1 - np.hypot(self.xx - cx, self.yy - cy) / r, 0, 1)

    def dist(self, cx, cy):
        return np.hypot(self.xx - cx, self.yy - cy)

    def noise(self, cell, rng, octaves=3):
        return fbm(self.h, self.w, cell, octaves, 0.5, rng, tile_x=False, tile_y=False)

    # -- painting ------------------------------------------------------------
    def fill(self, mask, ramp, t=0.5, grit=0.0, rng=None, alpha=1.0):
        """Paint mask with ramp colours chosen by shade field t (Bayer dithered).

        grit adds fine noise to t before quantisation (the speckled Doom look).
        """
        n = len(ramp)
        if np.isscalar(t):
            t = np.full((self.h, self.w), float(t), np.float32)
        if grit and rng is not None:
            t = t + (fbm(self.h, self.w, 3, 2, 0.5, rng, False, False) - 0.5) * grit
        q = np.clip(t, 0, 0.9999) * (n - 1)
        base = np.floor(q)
        frac = q - base
        idx = np.clip((base + (frac > self._bayer)).astype(int), 0, n - 1)
        cols = np.asarray(ramp, np.float32)[idx]
        self.rgb[mask] = cols[mask]
        self.alpha[mask] = alpha

    def paint(self, mask, color, alpha=1.0):
        self.rgb[mask] = np.asarray(color, np.float32)
        self.alpha[mask] = alpha

    def tint(self, mask, color, amount):
        """Blend a colour into existing pixels; amount is a scalar or field."""
        c = np.asarray(color, np.float32)
        if np.isscalar(amount):
            amt = np.full((self.h, self.w), float(amount), np.float32)
        else:
            amt = amount.astype(np.float32)
        a = amt[mask][:, None]
        self.rgb[mask] = self.rgb[mask] * (1 - a) + c * a

    def glow(self, cx, cy, r, color, strength=0.6, power=2.0, add_alpha=True):
        """Soft additive halo (used for lights, magic and fire)."""
        f = self.radial(cx, cy, r) ** power * strength
        f = np.floor(f * 8 + self._bayer) / 8          # keep it stepped/dithered
        m = f > 0
        c = np.asarray(color, np.float32)
        fm = f[m][:, None]
        self.rgb[m] = self.rgb[m] * (1 - fm) + c * fm
        if add_alpha:
            self.alpha[m] = np.maximum(self.alpha[m], f[m])

    def outline(self, color=OUTLINE, inner=False, thresh=0.5):
        """1px dark outline: outside the opaque silhouette (or just inside)."""
        solid = self.alpha > thresh
        if inner:
            edge = solid & ~erode(solid)
        else:
            edge = dilate(solid) & ~solid
        self.rgb[edge] = np.asarray(color, np.float32)
        self.alpha[edge] = 1.0

    def grunge(self, rng, amount=0.12, cell=3):
        """Dithered brightness speckle over everything opaque."""
        m = self.alpha > 0
        n = fbm(self.h, self.w, cell, 2, 0.5, rng, False, False)
        f = 1 + (np.floor(n * 4 + self._bayer) / 4 - 0.5) * 2 * amount
        self.rgb[m] = np.clip(self.rgb[m] * f[m][:, None], 0, 255)

    def blit(self, other, x, y):
        """Alpha-composite another canvas onto this one at (x, y)."""
        x, y = int(x), int(y)
        sx0, sy0 = max(0, -x), max(0, -y)
        dx0, dy0 = max(0, x), max(0, y)
        w = min(other.w - sx0, self.w - dx0)
        h = min(other.h - sy0, self.h - dy0)
        if w <= 0 or h <= 0:
            return
        src = other.rgb[sy0:sy0 + h, sx0:sx0 + w]
        sa = other.alpha[sy0:sy0 + h, sx0:sx0 + w][..., None]
        dst = self.rgb[dy0:dy0 + h, dx0:dx0 + w]
        da = self.alpha[dy0:dy0 + h, dx0:dx0 + w][..., None]
        out_a = sa + da * (1 - sa)
        safe = np.where(out_a > 0, out_a, 1)
        self.rgb[dy0:dy0 + h, dx0:dx0 + w] = (src * sa + dst * da * (1 - sa)) / safe
        self.alpha[dy0:dy0 + h, dx0:dx0 + w] = out_a[..., 0]

    def flipped(self):
        c = Canvas(self.w, self.h)
        c.rgb = self.rgb[:, ::-1].copy()
        c.alpha = self.alpha[:, ::-1].copy()
        return c

    # -- output ---------------------------------------------------------------
    def surface(self):
        rgb = np.clip(self.rgb, 0, 255).astype(np.uint8)
        a = (np.clip(self.alpha, 0, 1) * 255 + 0.5).astype(np.uint8)[..., None]
        rgba = np.ascontiguousarray(np.concatenate([rgb, a], axis=2))
        return pg.image.frombuffer(rgba.tobytes(), (self.w, self.h), 'RGBA').copy()

    def surface_rgb(self):
        rgb = np.ascontiguousarray(np.clip(self.rgb, 0, 255).astype(np.uint8))
        return pg.image.frombuffer(rgb.tobytes(), (self.w, self.h), 'RGB').copy()


def save_surface(surf, *rel):
    path = rpath(*rel)
    pg.image.save(surf, path)
    label = '/'.join(rel[-2:]).replace('.png', '')
    GENERATED_IMAGES.append((label, path))
    return path


def save_sprite(canvas, *rel):
    return save_surface(canvas.surface(), *rel)


def save_texture(canvas, *rel):
    return save_surface(canvas.surface_rgb(), *rel)


# ---------------------------------------------------------------------------
# 2. wall textures + skies
# ---------------------------------------------------------------------------
TEX = 256


def tex_canvas():
    return Canvas(TEX, TEX)


def rivet(c, x, y, r=3):
    """Small domed rivet with a dark ring."""
    ring = c.circle(x, y, r + 1) & ~c.circle(x, y, r)
    c.tint(ring, (12, 12, 14), 0.75)
    c.fill(c.circle(x, y, r), RAMPS['steel'], c.sphere(x, y, r + 0.5))


def bevel(c, x, y, w, h, depth=2, raised=True, light=(150, 156, 166), dark=(14, 14, 16), amt=0.85):
    """Light top/left + dark bottom/right edges (inverted when recessed)."""
    top = c.rect(x, y, w, depth) | c.rect(x, y, depth, h)
    bot = c.rect(x, y + h - depth, w, depth) | c.rect(x + w - depth, y, depth, h)
    if raised:
        c.tint(top & ~bot, light, amt)
        c.tint(bot, dark, amt)
    else:
        c.tint(top & ~bot, dark, amt)
        c.tint(bot, light, amt * 0.7)


def scratches(c, rng, n=8, color=(170, 174, 184), amt=0.5, length=(10, 40)):
    for _ in range(n):
        x0, y0 = rng.randint(0, c.w), rng.randint(0, c.h)
        ln = rng.randint(length[0], length[1])
        ang = rng.uniform(-0.5, 0.5) + (0 if rng.random_sample() < 0.5 else math.pi / 2)
        x1, y1 = x0 + math.cos(ang) * ln, y0 + math.sin(ang) * ln
        c.tint(c.line((x0, y0), (x1, y1), 1), color, amt)


def rust(c, rng, amount=0.5, color=(96, 48, 18), cell=24, thresh=0.62):
    n = fbm(c.h, c.w, cell, 3, 0.55, rng)
    m = n > thresh
    c.tint(m, color, np.clip((n - thresh) * 6, 0, 1) * amount)


def metal_base(c, rng, ramp='gunmetal', level=0.45, spread=0.3, brushed=True):
    """Grungy sheet-metal base fill with horizontal brushing."""
    n = fbm(c.h, c.w, 32, 3, 0.5, rng)
    t = level + (n - 0.5) * spread
    if brushed:
        streak = value_noise(c.h, c.w, 3, rng)
        stretched = fbm(c.h, c.w, 2, 1, 0.5, rng)
        # stretch horizontally by averaging along x
        stretched = np.mean([np.roll(stretched, k, axis=1) for k in range(-12, 13, 3)], axis=0)
        t = t + (stretched - 0.5) * 0.35 + (streak - 0.5) * 0.06
    c.fill(c.all(), RAMPS[ramp], t)


def hazard_stripes(c, mask, rng, period=14):
    diag = ((c.xx + c.yy) // (period // 2)).astype(int) % 2 == 0
    c.fill(mask & diag, RAMPS['yellow'], 0.55 + (fbm(c.h, c.w, 12, 2, 0.5, rng) - 0.5) * 0.5)
    c.fill(mask & ~diag, RAMPS['dark'], 0.35 + (fbm(c.h, c.w, 12, 2, 0.5, rng) - 0.5) * 0.4)


def gen_door(name, key=None):
    """Gunmetal sliding door slab; ``key`` adds coloured light bars + card emblem."""
    rng = seed_for(name)
    c = tex_canvas()
    metal_base(c, rng, 'gunmetal', 0.42, 0.28)
    # raised riveted frame
    inner = c.rect(18, 18, TEX - 36, TEX - 36)
    frame = ~inner
    c.fill(frame, RAMPS['steel'], 0.38 + (fbm(TEX, TEX, 24, 3, 0.5, rng) - 0.5) * 0.25)
    bevel(c, 0, 0, TEX, TEX, 2, True)
    bevel(c, 18, 18, TEX - 36, TEX - 36, 2, False)
    for i in range(8):
        p = 16 + i * 32
        for x, y in ((p, 9), (p, TEX - 9), (9, p), (TEX - 9, p)):
            rivet(c, x, y, 3)
    # two recessed panels with a lighter inner plate
    for py in (28, 148):
        bevel(c, 28, py, 200, 80, 2, False)
        plate = c.rect(34, py + 6, 188, 68)
        c.tint(plate, (120, 126, 138), 0.10)
        for gx in range(56, 220, 48):          # faint vertical ribs
            c.tint(c.rect(gx, py + 12, 2, 56), (10, 10, 12), 0.35)
            c.tint(c.rect(gx + 2, py + 12, 1, 56), (150, 156, 166), 0.25)
    # centre seam band with hazard stripes
    band = c.rect(18, 108, 220, 40)
    c.fill(band, RAMPS['dark'], 0.45 + (fbm(TEX, TEX, 16, 3, 0.5, rng) - 0.5) * 0.3)
    bevel(c, 18, 108, 220, 40, 2, False)
    hazard_stripes(c, c.rect(30, 116, 196, 24), rng)
    c.tint(c.rect(30, 116, 196, 24), (0, 0, 0), np.clip(fbm(TEX, TEX, 20, 3, 0.5, rng) - 0.45, 0, 1) * 1.2)
    c.paint(c.rect(18, 127, 220, 2), (8, 8, 10))
    c.tint(c.rect(18, 129, 220, 1), (140, 146, 158), 0.5)
    # round port light (upper panel)
    cx, cy = 128, 68
    c.fill(c.circle(cx, cy, 19), RAMPS['steel'], c.sphere(cx, cy, 20) * 0.6 + 0.2)
    for r in (17, 14):
        c.tint(c.circle(cx, cy, r) & ~c.circle(cx, cy, r - 2), (12, 12, 14), 0.7)
    glass = c.circle(cx, cy, 12)
    if key:
        gcol = {'red': (200, 40, 30), 'blue': (40, 90, 220), 'yellow': (220, 190, 40)}[key]
        c.paint(glass, gcol)
        c.fill(glass, [tuple(int(v * 0.35) for v in gcol), tuple(int(v * 0.7) for v in gcol), gcol,
                       tuple(min(255, int(v * 1.2)) for v in gcol)], c.sphere(cx, cy, 13, (-0.3, -0.5)))
    else:
        c.fill(glass, [(10, 20, 40), (20, 44, 80), (40, 84, 130), (120, 180, 210)], c.sphere(cx, cy, 13, (-0.3, -0.5)))
    c.paint(c.circle(cx - 4, cy - 4, 2), (230, 240, 255))
    for i in range(6):
        a = i * math.pi / 3
        c.tint(c.circle(cx + math.cos(a) * 15.5, cy + math.sin(a) * 15.5, 1.6), (200, 204, 210), 0.6)
    if key:
        kc = {'red': RAMPS['red'], 'blue': RAMPS['blue'], 'yellow': RAMPS['yellow']}[key]
        bright = kc[3]
        # vertical light bars near the left and right edges with a soft glow
        for bx in (30, 220):
            barm = c.rect(bx, 34, 6, 188)
            d = np.abs(c.xx - (bx + 3))
            halo = (d < 16) & (c.yy > 30) & (c.yy < 226) & ~barm
            c.tint(halo, bright, np.clip(1 - d / 16, 0, 1) ** 2 * 0.55)
            c.fill(barm, kc, 0.55 + (fbm(TEX, TEX, 6, 2, 0.5, rng) - 0.5) * 0.4)
            c.tint(c.rect(bx + 2, 34, 2, 188), kc[4], 0.6)
            c.tint(c.rect(bx - 1, 34, 1, 188) | c.rect(bx + 6, 34, 1, 188), (10, 10, 12), 0.8)
        # keycard emblem on a dark plate in the centre
        c.fill(c.rect(96, 92, 64, 72), RAMPS['dark'], 0.4 + (fbm(TEX, TEX, 8, 2, 0.5, rng) - 0.5) * 0.3)
        bevel(c, 96, 92, 64, 72, 2, True)
        card = c.rrect(106, 100, 44, 56, 4)
        c.fill(card, kc, 0.45 + c.grad_h(106, 150) * 0.2 + (1 - c.grad_v(100, 156)) * 0.25)
        c.paint(c.rect(106, 110, 44, 7), (240, 240, 244))
        c.paint(c.rect(106, 136, 44, 8), (10, 10, 12))
        c.paint(c.rect(112, 121, 10, 8), kc[4])
        c.tint(dilate(card) & ~card, (8, 8, 10), 0.9)
        halo = c.dist(128, 128) < 44
        c.tint(halo & ~card & ~c.rect(96, 92, 64, 72), bright, np.clip(1 - c.dist(128, 128) / 44, 0, 1) * 0.4)
    scratches(c, rng, 10, amt=0.35)
    rust(c, rng, 0.35, (70, 40, 18), 30, 0.66)
    c.grunge(rng, 0.07, 2)
    save_texture(c, 'textures', name + '.png')


FONT5x7 = {
    'E': ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    'X': ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    'I': ["11111", "00100", "00100", "00100", "00100", "00100", "11111"],
    'T': ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
}


def pixel_text(c, text, x, y, scale, ramp, spacing=1):
    """Chunky bitmap letters (5x7 font scaled by `scale`) with a dark outline."""
    m = c.none()
    cx = x
    for ch in text:
        rows = FONT5x7[ch]
        for r, row in enumerate(rows):
            for k, bit in enumerate(row):
                if bit == '1':
                    m |= c.rect(cx + k * scale, y + r * scale, scale, scale)
        cx += (5 + spacing) * scale
    c.fill(m, ramp, 0.55 + (1 - c.grad_v(y, y + 7 * scale)) * 0.35)
    c.paint(dilate(m) & ~m, (8, 8, 10))
    return m


def gen_exit_switch(name, on):
    rng = seed_for(name)
    c = tex_canvas()
    metal_base(c, rng, 'steel', 0.42, 0.25)
    bevel(c, 0, 0, TEX, TEX, 3, True)
    for x, y in ((10, 10), (TEX - 10, 10), (10, TEX - 10), (TEX - 10, TEX - 10)):
        rivet(c, x, y, 3)
    # faint panel seams
    for y in (24, 84):
        c.tint(c.rect(0, y, TEX, 2), (14, 14, 16), 0.6)
        c.tint(c.rect(0, y + 2, TEX, 1), (170, 174, 184), 0.4)
    pixel_text(c, 'EXIT', 128 - (4 * 6 - 1) * 5 // 2, 35, 5, RAMPS['yellow'])
    # switch box
    bx, by, bw, bh = 66, 96, 124, 132
    c.fill(c.rect(bx, by, bw, bh), RAMPS['steel'], 0.35 + (fbm(TEX, TEX, 16, 3, 0.5, rng) - 0.5) * 0.25)
    bevel(c, bx, by, bw, bh, 3, True)
    for x, y in ((bx + 8, by + 8), (bx + bw - 8, by + 8), (bx + 8, by + bh - 8), (bx + bw - 8, by + bh - 8)):
        rivet(c, x, y, 3)
    px, py, pw, ph = bx + 18, by + 18, bw - 36, bh - 36
    plate = c.rect(px, py, pw, ph)
    if on:
        c.fill(plate, [(18, 70, 30), (30, 110, 46), (52, 150, 66), (96, 196, 104)],
               0.45 + c.radial(128, py + ph // 2, 70) * 0.5 + (fbm(TEX, TEX, 10, 2, 0.5, rng) - 0.5) * 0.3)
    else:
        c.fill(plate, RAMPS['dark'], 0.45 + (fbm(TEX, TEX, 10, 2, 0.5, rng) - 0.5) * 0.35)
    bevel(c, px, py, pw, ph, 2, False)
    # lever: pivot at centre, red knob down (off) or up (on)
    pvx, pvy = 128, by + bh // 2 + 8
    tip = (pvx, pvy - 50) if on else (pvx, pvy + 46)
    arm = c.line((pvx, pvy), tip, 12)
    c.fill(arm, RAMPS['gunmetal'], 0.3 + c.cyl(pvx - 6, pvx + 6, 0.4) * 0.5)
    c.paint(dilate(arm) & ~arm, (8, 8, 10))
    c.fill(c.circle(pvx, pvy, 11), RAMPS['steel'], c.sphere(pvx, pvy, 11))
    c.tint(c.circle(pvx, pvy, 12) & ~c.circle(pvx, pvy, 11), (8, 8, 10), 0.9)
    c.paint(c.circle(pvx, pvy, 3), (20, 20, 24))
    knob = c.circle(tip[0], tip[1], 14)
    c.fill(knob, RAMPS['red'], c.sphere(tip[0], tip[1], 14))
    c.paint(dilate(knob) & ~knob, (8, 8, 10))
    # indicator lamp
    lx, ly = bx + bw - 22, by + 30
    lamp = c.circle(lx, ly, 6)
    if on:
        c.glow(lx, ly, 22, (120, 255, 120), 0.7, 2.0, add_alpha=False)
        c.fill(lamp, RAMPS['toxic'], c.sphere(lx, ly, 6) * 0.6 + 0.4)
    else:
        c.fill(lamp, RAMPS['blood'], c.sphere(lx, ly, 6) * 0.6)
    c.tint(dilate(lamp) & ~lamp, (8, 8, 10), 0.9)
    if on:
        c.glow(128, py + ph // 2, 90, (90, 220, 110), 0.35, 2.5, add_alpha=False)
    scratches(c, rng, 8, amt=0.3)
    c.grunge(rng, 0.07, 2)
    save_texture(c, 'textures', name + '.png')


def gen_tech_wall():
    rng = seed_for('tex6')
    c = tex_canvas()
    metal_base(c, rng, 'steel', 0.4, 0.25)
    # four riveted panels
    for px, py in ((0, 0), (128, 0), (0, 128), (128, 128)):
        bevel(c, px, py, 128, 128, 3, True)
        c.tint(c.rect(px + 3, py + 3, 122, 122), (150, 156, 166), 0.05)
        for x, y in ((px + 9, py + 9), (px + 119, py + 9), (px + 9, py + 119), (px + 119, py + 119)):
            rivet(c, x, y, 3)
    # top-left: vertical vent slits
    for i in range(6):
        x = 22 + i * 16
        slit = c.rect(x, 30, 7, 70)
        c.fill(slit, RAMPS['dark'], 0.2 + c.grad_v(30, 100) * 0.3)
        c.tint(c.rect(x, 30, 7, 2), (6, 6, 8), 0.9)
        c.tint(c.rect(x, 99, 7, 2), (170, 174, 184), 0.5)
        c.tint(c.rect(x + 1, 34, 1, 64), (170, 174, 184), 0.25)
    # top-right: indicator lights + small dark screen
    scr = c.rect(150, 26, 84, 40)
    c.fill(scr, RAMPS['dark'], 0.3 + (fbm(TEX, TEX, 8, 2, 0.5, rng) - 0.5) * 0.2)
    bevel(c, 150, 26, 84, 40, 2, False)
    for i in range(7):
        c.tint(c.rect(156 + i * 11, 34 + (i * 7) % 20, 6, 3), (70, 200, 110), 0.8)
    for i in range(5):
        lx, ly = 158 + i * 18, 92
        col = (60, 140, 255) if i % 2 == 0 else (90, 255, 110)
        c.glow(lx, ly, 12, col, 0.5, 2.0, add_alpha=False)
        c.tint(c.circle(lx, ly, 5), (8, 8, 10), 0.9)
        c.paint(c.circle(lx, ly, 3), col)
        c.paint(c.rect(lx - 1, ly - 2, 1, 1), (240, 255, 255))
    # bottom-left: two ribbed pipes
    for x0 in (24, 76):
        pipe = c.rect(x0, 134, 18, 116)
        c.fill(pipe, RAMPS['steel'], c.cyl(x0, x0 + 18, 0.35) * 0.8 + 0.1)
        for y in range(140, 250, 12):
            c.tint(c.rect(x0, y, 18, 2), (14, 14, 16), 0.6)
            c.tint(c.rect(x0, y + 2, 18, 1), (184, 190, 200), 0.4)
        c.tint(dilate(pipe) & ~pipe, (10, 10, 12), 0.8)
    # bottom-right: grate of dark square holes
    for gy in range(150, 236, 8):
        for gx in range(150, 236, 8):
            c.fill(c.rect(gx, gy, 5, 5), RAMPS['dark'], 0.25)
            c.tint(c.rect(gx, gy, 5, 1), (6, 6, 8), 0.9)
            c.tint(c.rect(gx, gy + 5, 5, 1), (170, 174, 184), 0.35)
    scratches(c, rng, 12, amt=0.35)
    rust(c, rng, 0.45, (96, 52, 20), 28, 0.64)
    c.grunge(rng, 0.08, 2)
    save_texture(c, 'textures', '6.png')


def wrapped_line(c, p0, p1, width):
    """Line mask drawn at all 4 wrap offsets so it tiles."""
    m = c.none()
    for ox in (-TEX, 0, TEX):
        for oy in (-TEX, 0, TEX):
            m |= c.line((p0[0] + ox, p0[1] + oy), (p1[0] + ox, p1[1] + oy), width)
    return m


def wrapped_walk(c, rng, n_paths, steps, step_len, width, jitter=0.6):
    """Random-walk crack/vein masks that wrap around the tile edges."""
    m = c.none()
    for _ in range(n_paths):
        x, y = rng.uniform(0, TEX), rng.uniform(0, TEX)
        ang = rng.uniform(0, math.tau)
        for _ in range(steps):
            ang += rng.uniform(-jitter, jitter)
            nx, ny = x + math.cos(ang) * step_len, y + math.sin(ang) * step_len
            m |= wrapped_line(c, (x, y), (nx, ny), width)
            x, y = nx % TEX, ny % TEX
    return m


def gen_flesh_wall():
    rng = seed_for('tex7')
    c = tex_canvas()
    n1 = fbm(TEX, TEX, 40, 5, 0.55, rng)
    creases = ridged(TEX, TEX, 56, 4, rng)
    patches = fbm(TEX, TEX, 90, 2, 0.5, rng)
    t = 0.08 + n1 * 0.5 + (1 - creases) * 0.4 + (patches - 0.5) * 0.5
    c.fill(c.all(), RAMPS['flesh'], np.clip(t, 0, 1), grit=0.2, rng=rng)
    # veins: dark wandering lines with a lighter centre
    veins = wrapped_walk(c, rng, 10, 26, 7, 3, 0.7)
    c.tint(veins, (52, 4, 4), 0.8)
    thin = wrapped_walk(c, rng, 6, 20, 6, 1, 0.9)
    c.tint(thin, (150, 40, 40), 0.7)
    # bone fragments (rotated ellipses) with a dark rim
    for _ in range(9):
        cx, cy = rng.uniform(0, TEX), rng.uniform(0, TEX)
        L, W = rng.randint(12, 30), rng.randint(5, 10)
        ang = rng.uniform(0, math.pi)
        pts = []
        for k in range(14):
            a = k * math.tau / 14
            ex, ey = math.cos(a) * L / 2, math.sin(a) * W / 2
            pts.append((ex * math.cos(ang) - ey * math.sin(ang), ex * math.sin(ang) + ey * math.cos(ang)))
        m = c.none()
        for ox in (-TEX, 0, TEX):
            for oy in (-TEX, 0, TEX):
                m |= c.poly([(cx + ox + px, cy + oy + py) for px, py in pts])
        c.fill(m, RAMPS['bone'], 0.35 + c.noise(6, rng, 2) * 0.55)
        c.tint(dilate(m) & ~m, (30, 4, 4), 0.85)
    # wet highlights
    hi = fbm(TEX, TEX, 14, 2, 0.5, rng) > 0.72
    c.tint(hi, (230, 140, 120), 0.3)
    c.grunge(rng, 0.10, 2)
    save_texture(c, 'textures', '7.png')


def gen_cobble_wall():
    rng = seed_for('tex8')
    c = tex_canvas()
    npts = 64
    pts = rng.random_sample((npts, 2)) * TEX
    allpts = np.concatenate([pts + (ox, oy) for ox in (-TEX, 0, TEX) for oy in (-TEX, 0, TEX)])
    shade = rng.random_sample(npts) * 0.45 + 0.2
    d1 = np.zeros((TEX, TEX), np.float32)
    d2 = np.zeros((TEX, TEX), np.float32)
    sid = np.zeros((TEX, TEX), int)
    for y0 in range(0, TEX, 32):          # chunked nearest / 2nd nearest search
        xx = c.xx[y0:y0 + 32]
        yy = c.yy[y0:y0 + 32]
        d = np.sqrt((xx[..., None] - allpts[:, 0]) ** 2 + (yy[..., None] - allpts[:, 1]) ** 2)
        part = np.argpartition(d, 1, axis=2)[..., :2]
        dd = np.take_along_axis(d, part, axis=2)
        order = np.argsort(dd, axis=2)
        dd = np.take_along_axis(dd, order, axis=2)
        part = np.take_along_axis(part, order, axis=2)
        d1[y0:y0 + 32] = dd[..., 0]
        d2[y0:y0 + 32] = dd[..., 1]
        sid[y0:y0 + 32] = part[..., 0] % npts
    edge = d2 - d1
    n = fbm(TEX, TEX, 12, 3, 0.5, rng)
    mortar = edge < 3.0 + (n - 0.5) * 2
    t = shade[sid] + (n - 0.5) * 0.35 - np.clip(1 - edge / 10, 0, 1) * 0.35
    c.fill(c.all(), RAMPS['cobble'], np.clip(t, 0, 1), grit=0.12, rng=rng)
    c.fill(mortar, RAMPS['dark'], 0.15 + n * 0.3)
    # dried blood splatters (wrapped so the tile stays seamless)
    for _ in range(5):
        cx, cy = rng.uniform(0, TEX), rng.uniform(0, TEX)
        m = c.none()
        for _ in range(rng.randint(6, 14)):
            r = rng.randint(2, 11)
            ox, oy = rng.normal(0, 9), rng.normal(0, 7)
            for wx in (-TEX, 0, TEX):
                for wy in (-TEX, 0, TEX):
                    m |= c.circle(cx + ox + wx, cy + oy + wy, r)
        for _ in range(rng.randint(1, 4)):        # drips
            dx = rng.normal(0, 8)
            for wx in (-TEX, 0, TEX):
                for wy in (-TEX, 0, TEX):
                    m |= c.rect(cx + dx + wx, cy + wy, 2, rng.randint(8, 30))
        nn = fbm(TEX, TEX, 6, 2, 0.5, rng)
        c.tint(m, (72, 6, 6), 0.55 + nn * 0.4)
        c.tint(m & (nn > 0.55), (120, 14, 12), 0.5)
    c.grunge(rng, 0.08, 2)
    save_texture(c, 'textures', '8.png')


def gen_hell_brick():
    rng = seed_for('tex9')
    c = tex_canvas()
    row = (c.yy // 32).astype(int)
    off = (row % 2) * 32
    ux = (c.xx + off) % 64
    uy = c.yy % 32
    dx = np.minimum(ux, 64 - ux)
    dy = np.minimum(uy, 32 - uy)
    dist = np.minimum(dx, dy)                          # px distance to the mortar grid
    n = fbm(TEX, TEX, 10, 3, 0.5, rng)
    mortar_w = 2.2 + (n - 0.5) * 2.5
    mortar = dist < mortar_w
    c.fill(c.all(), RAMPS['hellbrick'], 0.25 + n * 0.6 + (rng.random_sample((TEX, TEX)) - 0.5) * 0.2)
    # extra cracks running through the bricks
    cracks = wrapped_walk(c, rng, 7, 18, 6, 1, 0.8)
    lava = mortar | cracks
    # glow bleeding onto the bricks
    g = blur(lava.astype(np.float32), 6, wrap=True)
    c.tint(~lava, (150, 48, 8), np.clip(g * 2.2, 0, 1) * 0.7)
    core = np.clip(1 - dist / np.maximum(mortar_w, 0.1), 0, 1)
    core = np.where(cracks & ~mortar, 0.8, core)
    c.fill(lava, RAMPS['lava'], np.clip(0.35 + core * 0.55 + (n - 0.5) * 0.4, 0, 1))
    # soot near the mortar
    soot = fbm(TEX, TEX, 20, 3, 0.5, rng) > 0.62
    c.tint(soot & ~lava, (4, 2, 2), 0.5)
    c.grunge(rng, 0.10, 2)
    save_texture(c, 'textures', '9.png')


def gen_sky_hell():
    rng = seed_for('sky_hell')
    W, H = 1200, 400
    c = Canvas(W, H)
    v = c.grad_v(0, H)
    clouds = fbm(H, W, 150, 6, 0.55, rng, tile_x=True, tile_y=False)
    billow = ridged(H, W, 100, 5, rng, tile_x=True, tile_y=False)
    t = 0.05 + v * 0.55 + (clouds - 0.5) * 0.9 + (billow - 0.5) * 0.4
    t = np.clip(t, 0, 1)
    c.fill(c.all(), RAMPS['hellsky'], t, grit=0.12, rng=rng)
    # ember specks drifting in the lower half
    for _ in range(140):
        x, y = rng.randint(0, W), rng.randint(H // 3, H)
        c.tint(c.rect(x, y, rng.randint(1, 3), 1), (255, 200, 90), 0.9)
    save_texture(c, 'textures', 'sky_hell.png')


def gen_sky_night():
    rng = seed_for('sky_night')
    W, H = 1200, 400
    c = Canvas(W, H)
    v = c.grad_v(0, H)
    n = fbm(H, W, 200, 4, 0.5, rng, tile_x=True, tile_y=False)
    c.fill(c.all(), RAMPS['navy'], np.clip(0.1 + v * 0.6 + (n - 0.5) * 0.3, 0, 1), grit=0.08, rng=rng)
    # stars (dense small, some brighter cross shaped)
    for _ in range(700):
        x, y = rng.randint(0, W), int(rng.beta(1.2, 2.2) * H)
        b = rng.randint(120, 255)
        c.tint(c.rect(x, y, 1, 1), (b, b, min(255, b + 20)), 0.9)
    for _ in range(40):
        x, y = rng.randint(0, W), int(rng.beta(1.2, 2.5) * H)
        c.paint(c.rect(x - 1, y, 3, 1) | c.rect(x, y - 1, 1, 3), (235, 240, 255))
    # moon
    mx, my = 930, 84
    moon = c.circle(mx, my, 16)
    c.glow(mx, my, 48, (150, 160, 210), 0.35, 2.0, add_alpha=False)
    c.fill(moon, [(150, 150, 170), (196, 196, 214), (228, 228, 240), (250, 250, 255)], c.sphere(mx, my, 16, (-0.3, -0.3)) * 0.7 + 0.3)
    c.tint(c.circle(mx + 6, my - 4, 12) & moon, (14, 16, 44), 0.85)          # crescent
    # dark purple clouds, denser toward the horizon
    cl = fbm(H, W, 160, 5, 0.55, rng, tile_x=True, tile_y=False) + (v - 0.5) * 0.35
    mask = cl > 0.52
    strength = np.clip((cl - 0.52) * 5, 0, 1)
    shade = np.clip(0.2 + (fbm(H, W, 60, 4, 0.5, rng, True, False) - 0.5) * 1.2 + (1 - v) * 0.3, 0, 1)
    cols = np.asarray(RAMPS['purple'], np.float32)
    q = np.clip(shade, 0, 0.9999) * (len(cols) - 1)
    idx = np.clip((np.floor(q) + ((q - np.floor(q)) > c._bayer)).astype(int), 0, len(cols) - 1)
    ccol = cols[idx]
    s = (np.floor(strength * 6 + c._bayer) / 6)[..., None]
    c.rgb[mask] = c.rgb[mask] * (1 - s[mask]) + ccol[mask] * s[mask]
    save_texture(c, 'textures', 'sky_night.png')


def gen_textures():
    gen_door('door')
    gen_door('door_red', 'red')
    gen_door('door_blue', 'blue')
    gen_door('door_yellow', 'yellow')
    gen_exit_switch('exit_switch', False)
    gen_exit_switch('exit_switch_on', True)
    gen_tech_wall()
    gen_flesh_wall()
    gen_cobble_wall()
    gen_hell_brick()
    gen_sky_hell()
    gen_sky_night()


# ---------------------------------------------------------------------------
# 3a. sprites - pickups (64x64 unless noted, object resting bottom-centre)
# ---------------------------------------------------------------------------
GROUND = 62      # last row used by the object body (outline may use row 63)


def box3d(c, x, y, w, h, d, front, top, side, rng, tf=0.55, tt=0.8, ts=0.3):
    """Three-quarter view box.  Returns (front, top, side) masks.

    (x, y) is the top-left of the front face's bounding box *including* the
    depth offset: the top face and right side extend d px up/right.
    """
    fm = c.rect(x, y + d, w, h - d)
    tm = c.poly([(x, y + d), (x + d, y), (x + w + d, y), (x + w, y + d)])
    sm = c.poly([(x + w, y + d), (x + w + d, y), (x + w + d, y + h - d), (x + w, y + h)])
    c.fill(tm, top, tt + (c.noise(4, rng, 2) - 0.5) * 0.3)
    c.fill(sm, side, ts + c.grad_v(y, y + h) * 0.2 + (c.noise(4, rng, 2) - 0.5) * 0.25)
    c.fill(fm, front, tf + (1 - c.grad_v(y + d, y + h)) * 0.25 + (c.noise(4, rng, 2) - 0.5) * 0.25)
    # edge lines between the faces
    c.tint(c.rect(x, y + d, w, 1), (255, 255, 255), 0.35)
    c.tint(c.rect(x + w - 1, y + d, 1, h - d), (0, 0, 0), 0.45)
    return fm, tm, sm


def cross_mask(c, cx, cy, size, thick):
    return c.rect(cx - thick // 2, cy - size // 2, thick, size) | c.rect(cx - size // 2, cy - thick // 2, size, thick)


def finish(c, rng, grit=0.08):
    c.outline()
    c.grunge(rng, grit, 2)


def gen_stimpack():
    rng = seed_for('stimpack')
    c = Canvas(64, 64)
    box3d(c, 19, 38, 22, 24, 5, RAMPS['white'], RAMPS['white'], RAMPS['white'], rng, 0.6, 0.85, 0.35)
    c.tint(c.rect(19, 47, 22, 1), (80, 80, 90), 0.5)                 # lid seam
    cr = cross_mask(c, 30, 54, 11, 3)
    c.fill(cr, RAMPS['red'], 0.5 + (1 - c.grad_v(48, 60)) * 0.3)
    finish(c, rng)
    save_sprite(c, 'sprites', 'pickups', 'stimpack.png')


def gen_medikit():
    rng = seed_for('medikit')
    c = Canvas(64, 64)
    fm, tm, sm = box3d(c, 12, 34, 34, 28, 5, RAMPS['white'], RAMPS['white'], RAMPS['white'], rng, 0.6, 0.85, 0.35)
    c.fill(c.rect(22, 33, 16, 4), RAMPS['dark'], 0.45)             # handle on the lid
    c.paint(c.rect(24, 34, 12, 2), (70, 70, 80))
    c.tint(c.rect(12, 43, 34, 1), (70, 70, 80), 0.6)                # latch seam
    for lx in (16, 40):
        c.fill(c.rect(lx, 41, 4, 5), RAMPS['gunmetal'], 0.5)
    cr = cross_mask(c, 29, 52, 15, 5)
    c.fill(cr, RAMPS['red'], 0.5 + (1 - c.grad_v(44, 60)) * 0.35)
    c.paint(cross_mask(c, 42, 38, 5, 1), (200, 30, 30))             # small plus on the top face
    finish(c, rng)
    save_sprite(c, 'sprites', 'pickups', 'medikit.png')


def gen_armor(name, ramp):
    rng = seed_for(name)
    c = Canvas(64, 64)
    body = c.poly([(15, 30), (26, 27), (32, 32), (38, 27), (49, 30), (51, 46), (47, 62), (17, 62), (13, 46)])
    body &= ~c.ellipse(8, 28, 12, 18) & ~c.ellipse(44, 28, 12, 18)  # arm holes
    body &= ~c.ellipse(26, 22, 12, 12)                               # neck
    shade = 0.35 + c.cyl(14, 50, 0.4) * 0.45 + (1 - c.grad_v(28, 62)) * 0.15
    c.fill(body, ramp, shade, grit=0.25, rng=rng)
    plate = c.rrect(24, 37, 16, 18, 3) & body
    c.fill(plate, ramp, shade + 0.18, grit=0.2, rng=rng)
    c.tint(dilate(plate) & ~plate & body, (0, 0, 0), 0.45)
    for sy in (44, 50):                                              # straps
        c.tint(c.rect(15, sy, 8, 2) & body, (0, 0, 0), 0.5)
        c.tint(c.rect(41, sy, 8, 2) & body, (0, 0, 0), 0.5)
    c.tint(c.rect(13, 60, 40, 2) & body, (0, 0, 0), 0.4)
    c.tint((dilate(c.ellipse(26, 22, 12, 12)) & body), (0, 0, 0), 0.4)
    finish(c, rng)
    save_sprite(c, 'sprites', 'pickups', name + '.png')


def gen_bullets():
    rng = seed_for('bullets')
    c = Canvas(64, 64)
    # brass rounds sticking out of the magazine
    for i in range(4):
        x = 26 + i * 3
        c.fill(c.rect(x, 36, 3, 8), RAMPS['brass'], 0.45 + (i % 2) * 0.25)
        c.fill(c.rect(x, 34, 3, 3), RAMPS['copper'], 0.55)
        c.paint(c.rect(x + 1, 33, 1, 1), (232, 150, 90))
    mag = c.rect(24, 40, 16, 22)
    c.fill(mag, RAMPS['gunmetal'], 0.3 + c.cyl(24, 40, 0.3) * 0.4 + (1 - c.grad_v(40, 62)) * 0.15, grit=0.2, rng=rng)
    c.tint(c.rect(24, 40, 16, 2), (200, 200, 210), 0.35)             # feed lips
    c.tint(c.rect(31, 44, 1, 16), (0, 0, 0), 0.5)                    # seam
    c.tint(c.rect(24, 59, 16, 3), (0, 0, 0), 0.4)                    # base plate
    c.fill(c.rect(25, 56, 14, 2), RAMPS['dark'], 0.6)
    finish(c, rng)
    save_sprite(c, 'sprites', 'pickups', 'bullets.png')


def gen_bullets_box():
    rng = seed_for('bullets_box')
    c = Canvas(64, 64)
    fm, tm, sm = box3d(c, 12, 38, 34, 24, 6, RAMPS['olive'], RAMPS['olive'], RAMPS['olive'], rng, 0.55, 0.8, 0.3)
    stripe = c.rect(12, 50, 34, 5) | c.poly([(46, 50), (52, 44), (52, 49), (46, 55)])
    c.fill(stripe & (fm | sm), RAMPS['yellow'], 0.45 + (fm * 0.25) + (c.noise(4, rng, 2) - 0.5) * 0.3)
    c.tint(c.rect(12, 44, 34, 1), (0, 0, 0), 0.45)                   # lid seam
    for i in range(3):                                               # stencil dots
        c.tint(c.rect(18 + i * 8, 58, 4, 2), (0, 0, 0), 0.5)
    c.tint(c.rect(20, 40, 18, 2), (0, 0, 0), 0.35)                   # latch on the top
    finish(c, rng)
    save_sprite(c, 'sprites', 'pickups', 'bullets_box.png')


def gen_shells():
    rng = seed_for('shells')
    c = Canvas(64, 64)
    for i in range(4):
        x = 15 + i * 9
        shell = c.rect(x, 38, 7, 18)
        c.fill(shell, RAMPS['red'], 0.35 + c.cyl(x, x + 7, 0.3) * 0.5, grit=0.2, rng=rng)
        base = c.rect(x, 56, 7, 6)
        c.fill(base, RAMPS['brass'], 0.4 + c.cyl(x, x + 7, 0.3) * 0.5)
        c.tint(c.rect(x, 38, 7, 1), (0, 0, 0), 0.5)                  # crimp
        c.tint(c.rect(x, 55, 7, 1), (0, 0, 0), 0.45)
        c.paint(c.rect(x + 1, 40, 1, 12), (250, 140, 110))
    finish(c, rng)
    save_sprite(c, 'sprites', 'pickups', 'shells.png')


def gen_shells_box():
    rng = seed_for('shells_box')
    c = Canvas(64, 64)
    fm, tm, sm = box3d(c, 13, 40, 32, 22, 6, RAMPS['red'], RAMPS['olive'], RAMPS['red'], rng, 0.5, 0.75, 0.25)
    c.tint(c.rect(13, 46, 32, 1), (0, 0, 0), 0.45)
    lab = c.rect(18, 50, 22, 8)
    c.fill(lab, RAMPS['olive'], 0.7)
    for i in range(3):                                               # shell icons on the label
        c.paint(c.rect(21 + i * 6, 52, 3, 3), (190, 28, 18))
        c.paint(c.rect(21 + i * 6, 55, 3, 2), (230, 194, 80))
    c.tint(c.rect(20, 42, 18, 2), (0, 0, 0), 0.35)
    finish(c, rng)
    save_sprite(c, 'sprites', 'pickups', 'shells_box.png')


def rocket_upright(c, x, top, h, rng, w=8):
    """Standing rocket: red cone, grey body, dark fins.  x = left of body."""
    cone = c.poly([(x, top + 8), (x + w, top + 8), (x + w // 2, top)])
    c.fill(cone, RAMPS['red'], 0.4 + c.cyl(x, x + w, 0.35) * 0.5)
    body = c.rect(x, top + 8, w, h - 8)
    c.fill(body, RAMPS['steel'], 0.3 + c.cyl(x, x + w, 0.35) * 0.55, grit=0.2, rng=rng)
    c.tint(c.rect(x, top + 8, w, 1), (0, 0, 0), 0.5)
    fy = top + h - 10
    fins = c.poly([(x, fy), (x - 4, fy + 10), (x, fy + 10)]) | c.poly([(x + w, fy), (x + w + 4, fy + 10), (x + w, fy + 10)])
    fins |= c.rect(x + w // 2 - 1, fy, 2, 10)
    c.fill(fins, RAMPS['gunmetal'], 0.35 + c.grad_v(fy, fy + 10) * 0.3)
    c.fill(c.rect(x + 1, top + h - 3, w - 2, 3), RAMPS['dark'], 0.4)   # nozzle


def gen_rockets():
    rng = seed_for('rockets')
    c = Canvas(64, 64)
    rocket_upright(c, 28, 24, 38, rng)
    finish(c, rng)
    save_sprite(c, 'sprites', 'pickups', 'rockets.png')


def gen_rockets_box():
    rng = seed_for('rockets_box')
    c = Canvas(64, 64)
    x, y, w, h, d = 10, 38, 40, 24, 6
    tm = c.poly([(x, y + d), (x + d, y), (x + w + d, y), (x + w, y + d)])
    c.fill(tm, RAMPS['wood'], 0.7 + (c.noise(4, rng, 2) - 0.5) * 0.3)
    for i in range(5):                                               # rockets standing in the crate
        rx = x + 4 + i * 7
        cone = c.poly([(rx, 36), (rx + 5, 36), (rx + 2, 29)])
        c.fill(cone, RAMPS['red'], 0.4 + c.cyl(rx, rx + 5, 0.35) * 0.5)
        c.fill(c.rect(rx, 36, 5, 8), RAMPS['steel'], 0.3 + c.cyl(rx, rx + 5, 0.35) * 0.5)
    fm = c.rect(x, y + d, w, h - d)
    sm = c.poly([(x + w, y + d), (x + w + d, y), (x + w + d, y + h - d), (x + w, y + h)])
    plank = 0.5 + (c.noise(3, rng, 2) - 0.5) * 0.35 + (((c.yy - y) // 6) % 2) * 0.12
    c.fill(fm, RAMPS['wood'], plank, grit=0.2, rng=rng)
    c.fill(sm, RAMPS['wood'], 0.25 + (c.noise(3, rng, 2) - 0.5) * 0.3)
    for py in range(y + d + 6, y + h, 6):                            # plank gaps
        c.tint(c.rect(x, py, w, 1), (0, 0, 0), 0.55)
    c.tint(c.rect(x, y + d, 1, h - d) | c.rect(x + w - 1, y + d, 1, h - d), (0, 0, 0), 0.4)
    for bx in (x + 2, x + w - 6):                                    # metal corner brackets
        c.fill(c.rect(bx, y + d + 1, 4, 5) | c.rect(bx, y + h - 6, 4, 5), RAMPS['gunmetal'], 0.55)
    c.tint(c.rect(x + w - 1, y + d, 1, h - d), (0, 0, 0), 0.45)
    finish(c, rng)
    save_sprite(c, 'sprites', 'pickups', 'rockets_box.png')


def gen_key(name, ramp):
    rng = seed_for(name)
    c = Canvas(64, 64)
    x, y, w, h = 19, 26, 26, 36
    side = c.rect(x + w, y + 2, 2, h - 2)                            # card thickness
    c.fill(side, ramp, 0.2)
    card = c.rrect(x, y, w, h, 2)
    shade = 0.5 + (1 - c.grad_v(y, y + h)) * 0.25 + (1 - c.grad_h(x, x + w)) * 0.2
    c.fill(card, ramp, shade, grit=0.15, rng=rng)
    c.paint(c.rect(x, y + 7, w, 5), (244, 244, 248))                 # white stripe
    c.paint(c.rect(x, y + 23, w, 6), (8, 8, 10))                     # magnetic band
    chip = c.rect(x + 4, y + 14, 6, 6)
    c.fill(chip, RAMPS['brass'], 0.7)
    c.tint(c.rect(x + 6, y + 14, 1, 6) | c.rect(x + 4, y + 17, 6, 1), (0, 0, 0), 0.5)
    c.tint(c.rect(x + 1, y + 1, w - 2, 1), (255, 255, 255), 0.3)     # top gloss
    finish(c, rng, 0.05)
    save_sprite(c, 'sprites', 'pickups', name + '.png')


def gen_soulsphere():
    for frame in range(4):
        rng = seed_for('soulsphere%d' % frame)
        c = Canvas(64, 64)
        cx, cy, r = 32, 40, 21
        pulse = 0.5 + 0.5 * math.sin(frame * math.pi / 2)            # 0..1..0
        c.glow(cx, cy, r + 10 + int(pulse * 6), (110, 170, 255), 0.5 + pulse * 0.35, 1.5)
        body = c.circle(cx, cy, r)
        shade = np.clip(c.sphere(cx, cy, r, (-0.35, -0.5)) * 0.7 + 0.05 + pulse * 0.1, 0, 1)
        c.fill(body, RAMPS['soul'], shade, grit=0.15, rng=rng, alpha=0.8 + pulse * 0.08)
        rim = body & ~c.circle(cx, cy, r - 2)
        c.tint(rim, (150, 196, 255), 0.5)
        c.alpha[rim] = 0.92
        # ghostly white face floating inside
        face = c.ellipse(cx - 10, cy - 11, 21, 25)
        fa = 0.6 + pulse * 0.3
        c.tint(face, (236, 244, 255), np.floor(fa * (0.45 + 0.55 * c.radial(cx, cy, 14)) * 6 + c._bayer) / 6)
        for ex in (cx - 7, cx + 2):
            eye = c.ellipse(ex, cy - 7, 6, 8)
            c.paint(eye, (18, 26, 96))
            c.paint(c.rect(ex + 2, cy - 4, 2, 2), (110, 150, 240))   # eye glint
        mouth = c.ellipse(cx - 4, cy + 3, 9, 8)
        c.paint(mouth, (18, 26, 96))
        c.tint(c.rect(cx - 1, cy - 1, 2, 2), (18, 26, 96), 0.7)      # nose
        c.paint(c.circle(cx - 9, cy - 10, 3), (230, 240, 255))       # specular
        c.paint(c.rect(cx - 7, cy - 13, 1, 1), (255, 255, 255))
        c.outline((10, 16, 60), thresh=0.6)
        save_sprite(c, 'sprites', 'pickups', 'soulsphere', '%d.png' % frame)


def gen_weapon_shotgun():
    rng = seed_for('weapon_shotgun')
    c = Canvas(96, 48)
    stock = c.poly([(68, 19), (90, 15), (94, 19), (93, 31), (82, 33), (72, 31), (68, 27)])
    c.fill(stock, RAMPS['wood'], 0.35 + c.cyl_v(15, 34, 0.3) * 0.5, grit=0.25, rng=rng)
    rec = c.rect(54, 17, 18, 13)
    c.fill(rec, RAMPS['gunmetal'], 0.3 + c.cyl_v(17, 30, 0.25) * 0.5, grit=0.2, rng=rng)
    c.tint(c.rect(60, 19, 8, 4), (0, 0, 0), 0.5)                     # ejection port
    barrel = c.rect(4, 19, 52, 5)
    c.fill(barrel, RAMPS['gunmetal'], 0.25 + c.cyl_v(19, 24, 0.25) * 0.6, grit=0.15, rng=rng)
    tube = c.rect(8, 24, 46, 4)
    c.fill(tube, RAMPS['gunmetal'], 0.2 + c.cyl_v(24, 28, 0.3) * 0.5)
    pump = c.rect(20, 23, 18, 8)
    c.fill(pump, RAMPS['wood'], 0.3 + c.cyl_v(23, 31, 0.3) * 0.5, grit=0.2, rng=rng)
    for gx in range(23, 37, 3):
        c.tint(c.rect(gx, 24, 1, 6), (0, 0, 0), 0.45)
    c.paint(c.rect(4, 18, 3, 2), (60, 62, 70))                       # bead sight
    guard = c.rect(58, 30, 12, 5) & ~c.rect(60, 30, 8, 3)
    c.fill(guard, RAMPS['gunmetal'], 0.3)
    c.paint(c.rect(62, 30, 2, 3), (40, 40, 46))                      # trigger
    c.tint(c.rect(70, 20, 2, 12), (0, 0, 0), 0.4)
    finish(c, rng)
    save_sprite(c, 'sprites', 'pickups', 'weapon_shotgun.png')


def gen_weapon_chaingun():
    rng = seed_for('weapon_chaingun')
    c = Canvas(96, 48)
    for i, by in enumerate((17, 22, 27)):                            # barrel bundle
        b = c.rect(8, by, 38, 4)
        c.fill(b, RAMPS['gunmetal'], 0.25 + c.cyl_v(by, by + 4, 0.25) * 0.55 - i * 0.05)
    for x, w, h in ((6, 4, 16), (40, 8, 20)):                        # muzzle ring + housing collar
        m = c.rect(x, 24 - h // 2 + 1, w, h)
        c.fill(m, RAMPS['steel'], 0.25 + c.cyl_v(24 - h // 2, 24 + h // 2, 0.3) * 0.55)
    body = c.rect(46, 15, 34, 20)
    c.fill(body, RAMPS['gunmetal'], 0.28 + c.cyl_v(15, 35, 0.25) * 0.4, grit=0.2, rng=rng)
    c.tint(c.rect(48, 17, 30, 1), (255, 255, 255), 0.3)
    c.tint(c.rect(50, 20, 26, 6), (0, 0, 0), 0.35)                   # side vent panel
    for gx in range(52, 76, 4):
        c.tint(c.rect(gx, 21, 2, 4), (0, 0, 0), 0.5)
    handle = c.rect(54, 10, 22, 4) & ~c.rect(58, 12, 14, 2)
    c.fill(handle, RAMPS['gunmetal'], 0.4)
    ammo = c.rect(56, 33, 18, 9)
    c.fill(ammo, RAMPS['olive'], 0.5 + c.cyl_v(33, 42, 0.3) * 0.3, grit=0.2, rng=rng)
    c.tint(c.rect(56, 36, 18, 1), (0, 0, 0), 0.4)
    grip = c.poly([(80, 21), (92, 23), (92, 36), (84, 36), (80, 30)])
    c.fill(grip, RAMPS['gunmetal'], 0.3 + c.cyl_v(21, 36, 0.3) * 0.3)
    c.paint(c.rect(84, 24, 6, 2), (30, 30, 34))
    finish(c, rng)
    save_sprite(c, 'sprites', 'pickups', 'weapon_chaingun.png')


def gen_weapon_rocketlauncher():
    rng = seed_for('weapon_rocketlauncher')
    c = Canvas(96, 48)
    tube = c.rect(6, 15, 84, 15)
    c.fill(tube, RAMPS['steel'], 0.2 + c.cyl_v(15, 30, 0.3) * 0.65, grit=0.2, rng=rng)
    cap = c.rect(6, 14, 7, 17)
    c.fill(cap, RAMPS['gunmetal'], 0.3 + c.cyl_v(14, 31, 0.3) * 0.5)
    c.fill(c.rect(7, 18, 4, 9), RAMPS['dark'], 0.25)                 # bore
    band = c.rect(26, 14, 8, 17)
    c.fill(band, RAMPS['red'], 0.35 + c.cyl_v(14, 31, 0.3) * 0.5)
    c.tint(c.rect(26, 14, 1, 17) | c.rect(33, 14, 1, 17), (0, 0, 0), 0.4)
    rear = c.rect(84, 14, 6, 17)
    c.fill(rear, RAMPS['gunmetal'], 0.3 + c.cyl_v(14, 31, 0.3) * 0.4)
    c.fill(c.rect(86, 18, 3, 9), RAMPS['dark'], 0.2)
    c.fill(c.rect(44, 10, 8, 5), RAMPS['gunmetal'], 0.45)             # sight
    c.paint(c.rect(46, 8, 2, 2), (150, 156, 166))
    grip = c.rect(48, 30, 7, 11)
    c.fill(grip, RAMPS['gunmetal'], 0.3 + c.cyl(48, 55, 0.3) * 0.3)
    guard = c.rect(54, 30, 12, 6) & ~c.rect(56, 30, 8, 4)
    c.fill(guard, RAMPS['gunmetal'], 0.3)
    c.paint(c.rect(58, 30, 2, 3), (40, 40, 46))
    rest = c.rect(72, 30, 14, 6)
    c.fill(rest, RAMPS['gunmetal'], 0.35 + c.cyl_v(30, 36, 0.3) * 0.3)
    c.tint(c.rect(72, 30, 14, 1), (0, 0, 0), 0.45)
    finish(c, rng)
    save_sprite(c, 'sprites', 'pickups', 'weapon_rocketlauncher.png')


def gen_backpack():
    rng = seed_for('backpack')
    c = Canvas(64, 64)
    body = c.rrect(17, 28, 30, 34, 5)
    c.fill(body, RAMPS['leather'], 0.35 + c.cyl(17, 47, 0.38) * 0.4 + (1 - c.grad_v(28, 62)) * 0.15, grit=0.3, rng=rng)
    flap = c.rrect(15, 26, 34, 14, 4) & ~c.rect(15, 38, 34, 2)
    c.fill(flap, RAMPS['leather'], 0.25 + c.cyl(15, 49, 0.38) * 0.4, grit=0.3, rng=rng)
    c.tint(c.rect(15, 38, 34, 1), (0, 0, 0), 0.6)
    pocket = c.rrect(24, 44, 16, 14, 3) & body
    c.fill(pocket, RAMPS['leather'], 0.45 + c.cyl(24, 40, 0.38) * 0.35, grit=0.3, rng=rng)
    c.tint(dilate(pocket) & ~pocket & body, (0, 0, 0), 0.5)
    c.tint(c.rect(26, 48, 12, 1), (0, 0, 0), 0.5)
    for sx in (20, 40):                                              # straps + brass buckles
        strap = c.rect(sx, 38, 4, 20) & body
        c.tint(strap, (0, 0, 0), 0.35)
        c.fill(c.rect(sx, 40, 4, 3), RAMPS['brass'], 0.7)
    c.tint(c.rect(29, 26, 6, 2), (0, 0, 0), 0.4)                     # handle loop
    finish(c, rng)
    save_sprite(c, 'sprites', 'pickups', 'backpack.png')


def gen_pickups():
    gen_stimpack()
    gen_medikit()
    gen_armor('armor_green', RAMPS['green'])
    gen_armor('armor_blue', RAMPS['blue'])
    gen_bullets()
    gen_bullets_box()
    gen_shells()
    gen_shells_box()
    gen_rockets()
    gen_rockets_box()
    gen_key('key_red', [(90, 4, 4), (160, 10, 10), (220, 24, 20), (250, 80, 60), (255, 150, 130)])
    gen_key('key_blue', [(10, 20, 110), (20, 50, 180), (36, 100, 240), (100, 160, 255), (170, 210, 255)])
    gen_key('key_yellow', [(120, 90, 0), (190, 150, 10), (240, 205, 30), (255, 235, 90), (255, 250, 180)])
    gen_soulsphere()
    gen_weapon_shotgun()
    gen_weapon_chaingun()
    gen_weapon_rocketlauncher()
    gen_backpack()


# ---------------------------------------------------------------------------
# 3b. sprites - decorations
# ---------------------------------------------------------------------------
def gen_barrel():
    for frame in range(2):
        rng = seed_for('barrel%d' % frame)
        c = Canvas(64, 96)
        x0, x1 = 10, 54
        body = c.rect(x0, 22, 44, 62) | c.ellipse(x0, 76, 44, 16)
        shade = 0.15 + c.cyl(x0, x1, 0.35) * 0.7
        c.fill(body, RAMPS['barrel'], shade, grit=0.25, rng=rng)
        for ry in (36, 62):                                          # raised rings
            c.fill(c.rect(x0, ry, 44, 4), RAMPS['barrel'], np.clip(shade + 0.25, 0, 1), grit=0.2, rng=rng)
            c.tint(c.rect(x0, ry + 4, 44, 1), (0, 0, 0), 0.55)
            c.tint(c.rect(x0, ry - 1, 44, 1), (0, 0, 0), 0.3)
        # hazard triangle stencil
        tri = c.poly([(32, 44), (24, 58), (40, 58)]) & ~c.poly([(32, 49), (27, 56), (37, 56)])
        c.fill(tri, RAMPS['yellow'], 0.5 + (c.noise(3, rng, 2) - 0.5) * 0.4)
        c.paint(c.rect(31, 50, 2, 4), (222, 182, 28))
        c.paint(c.rect(31, 55, 2, 1), (222, 182, 28))
        # top rim + glowing goo
        rim = c.ellipse(x0, 14, 44, 16)
        c.fill(rim, RAMPS['barrel'], 0.1 + c.grad_v(14, 30) * 0.5, grit=0.2, rng=rng)
        goo = c.ellipse(x0 + 3, 16, 38, 12)
        gt = c.radial(32, 22, 20) * 0.7 + 0.2 + (c.noise(5, rng, 2) - 0.5) * 0.4 + frame * 0.12
        c.fill(goo, RAMPS['toxic'], np.clip(gt, 0, 1), grit=0.2, rng=rng)
        bubbles = [(24, 20, 2), (38, 24, 3), (30, 26, 1)] if frame == 0 else [(28, 24, 3), (40, 19, 2), (22, 23, 1), (34, 21, 1)]
        for bx, by, br in bubbles:
            c.tint(c.circle(bx, by, br), (240, 255, 200), 0.8)
            c.tint(c.circle(bx, by, br + 1) & ~c.circle(bx, by, br), (24, 84, 12), 0.6)
        for dx, dl in ((16, 14), (44, 9)):                           # drips
            drip = c.rect(dx, 28, 2, dl) | c.circle(dx + 1, 28 + dl, 2)
            c.tint(drip & body, (124, 230, 40), 0.85)
        c.tint(c.rect(x0, 26, 44, 12) & body, (120, 230, 40), (1 - c.grad_v(26, 38)) * 0.35)
        finish(c, rng)
        c.glow(32, 20, 30, (120, 255, 80), 0.35 + frame * 0.2, 2.2)
        save_sprite(c, 'sprites', 'decorations', 'barrel', '%d.png' % frame)


def gen_pillar():
    rng = seed_for('pillar')
    c = Canvas(64, 128)
    shaft = c.rect(20, 25, 24, 88)
    c.fill(shaft, RAMPS['stone'], 0.15 + c.cyl(20, 44, 0.35) * 0.65, grit=0.3, rng=rng)
    for fx in (25, 31, 37):                                          # flutes
        c.tint(c.rect(fx, 27, 1, 84), (0, 0, 0), 0.45)
        c.tint(c.rect(fx + 1, 27, 1, 84), (255, 255, 255), 0.2)
    for x, y, w, h, t in ((16, 19, 32, 6, 0.55), (11, 11, 42, 8, 0.6), (16, 113, 32, 6, 0.45), (11, 119, 42, 8, 0.5)):
        m = c.rect(x, y, w, h)
        c.fill(m, RAMPS['stone'], t + c.cyl(x, x + w, 0.35) * 0.3 - c.grad_v(y, y + h) * 0.15, grit=0.3, rng=rng)
        c.tint(c.rect(x, y, w, 1), (255, 255, 255), 0.3)
        c.tint(c.rect(x, y + h - 1, w, 1), (0, 0, 0), 0.5)
    crack = c.line((24, 50), (30, 70), 1) | c.line((30, 70), (27, 82), 1) | c.line((36, 90), (40, 104), 1)
    c.tint(crack, (0, 0, 0), 0.5)
    moss = (c.noise(6, rng, 2) > 0.58) & (c.yy > 88) & (c.alpha > 0)
    c.tint(moss, (60, 92, 40), 0.55)
    finish(c, rng)
    save_sprite(c, 'sprites', 'decorations', 'pillar.png')


def skull(c, cx, cy, r, rng):
    cran = c.circle(cx, cy, r)
    jaw = c.rect(cx - int(r * 0.65), cy, int(r * 1.3), int(r * 0.9))
    m = cran | jaw
    c.tint(dilate(m) & ~m & (c.alpha > 0), (10, 8, 8), 0.7)         # separate it from neighbours
    c.fill(m, RAMPS['bone'], 0.15 + c.sphere(cx, cy, r * 1.15, (-0.4, -0.5)) * 0.75, grit=0.25, rng=rng)
    ew, eh = max(2, int(r * 0.45)), max(2, int(r * 0.55))
    for ex in (cx - int(r * 0.5), cx + int(r * 0.1)):
        c.paint(c.ellipse(ex, cy - int(r * 0.4), ew, eh), (14, 10, 10))
    c.paint(c.rect(cx - 1, cy + 1, 2, 2), (30, 24, 20))
    for tx in range(cx - int(r * 0.5), cx + int(r * 0.5), 2):
        c.paint(c.rect(tx, cy + int(r * 0.6), 1, 2), (30, 24, 20))
    return m


def gen_skulls():
    rng = seed_for('skulls')
    c = Canvas(64, 48)
    for bx, by, bl in ((3, 42, 16), (44, 43, 17)):                   # loose bones
        bone = c.rect(bx + 2, by, bl - 4, 3) | c.circle(bx + 2, by + 1, 2) | c.circle(bx + bl - 2, by + 1, 2)
        c.fill(bone, RAMPS['bone'], 0.3 + c.cyl_v(by - 1, by + 3, 0.3) * 0.5, grit=0.2, rng=rng)
    for cx, cy in ((15, 38), (32, 39), (49, 38)):
        skull(c, cx, cy, 7, rng)
    for cx, cy in ((23, 27), (41, 27)):
        skull(c, cx, cy, 7, rng)
    skull(c, 32, 15, 7, rng)
    finish(c, rng)
    save_sprite(c, 'sprites', 'decorations', 'skulls.png')


def gen_decorations():
    gen_barrel()
    gen_pillar()
    gen_skulls()


# ---------------------------------------------------------------------------
# 3c. sprites - projectiles
# ---------------------------------------------------------------------------
def angular_noise(c, cx, cy, lobes, rng, phase=0.0):
    """Periodic 1-D noise around (cx, cy) as a function of angle, in [0, 1]."""
    ang = np.arctan2(c.yy - cy, c.xx - cx)
    vals = rng.random_sample(lobes)
    u = ((ang / math.tau + phase) % 1.0) * lobes
    i0 = np.floor(u).astype(int) % lobes
    i1 = (i0 + 1) % lobes
    f = u - np.floor(u)
    f = f * f * (3 - 2 * f)
    return vals[i0] * (1 - f) + vals[i1] * f


def tapered_bar(c, p0, p1, w0, w1, ramp, stripes=5, hl=0.35, lo=0.15, hi=0.85, grit=0.15, rng=None):
    """Cylinder along p0 -> p1 drawn as lateral slices with a dithered highlight."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    L = math.hypot(dx, dy)
    nx, ny = -dy / L, dx / L
    total = c.none()
    for k in range(stripes):
        u0 = -0.5 + k / stripes
        u1 = u0 + 1.0 / stripes
        quad = [(p0[0] + nx * u0 * w0, p0[1] + ny * u0 * w0), (p1[0] + nx * u0 * w1, p1[1] + ny * u0 * w1),
                (p1[0] + nx * u1 * w1, p1[1] + ny * u1 * w1), (p0[0] + nx * u1 * w0, p0[1] + ny * u1 * w0)]
        m = c.poly(quad)
        um = (u0 + u1) / 2 + 0.5
        t = lo + (1 - abs(um - hl) / max(hl, 1 - hl)) ** 0.8 * (hi - lo)
        c.fill(m, ramp, t, grit=grit, rng=rng)
        total |= m
    return total


def gen_fireball():
    for frame in range(3):
        rng = seed_for('fireball%d' % frame)
        c = Canvas(48, 48)
        cx = cy = 23.5
        d = c.dist(cx, cy)
        edge = 13 + angular_noise(c, cx, cy, 9, rng, frame * 0.13) * 9 + angular_noise(c, cx, cy, 19, rng) * 3
        inside = d < edge
        t = np.clip(1 - d / edge, 0, 1) ** 0.75 + (c.noise(4, rng, 2) - 0.5) * 0.3
        c.fill(inside, RAMPS['fire'], np.clip(t, 0, 1))
        c.outline((96, 0, 0))
        c.glow(cx, cy, 24, (255, 110, 20), 0.3, 2.5)
        save_sprite(c, 'sprites', 'projectiles', 'fireball', '%d.png' % frame)


def flame(c, tail, direction, length, rng, width=8):
    """Layered exhaust flame trailing from `tail` opposite to `direction`."""
    dx, dy = direction
    nx, ny = -dy, dx
    for ramp_t, ln, wd in ((0.3, length, width), (0.6, length * 0.65, width * 0.6), (0.9, length * 0.35, width * 0.3)):
        pts = [(tail[0] + nx * wd / 2, tail[1] + ny * wd / 2)]
        for k in range(1, 5):
            f = k / 5
            jitter = (rng.random_sample() - 0.5) * wd * 0.6
            pts.append((tail[0] - dx * ln * f + nx * (wd / 2 * (1 - f) + jitter), tail[1] - dy * ln * f + ny * (wd / 2 * (1 - f) + jitter)))
        pts.append((tail[0] - dx * ln, tail[1] - dy * ln))
        for k in range(4, 0, -1):
            f = k / 5
            jitter = (rng.random_sample() - 0.5) * wd * 0.6
            pts.append((tail[0] - dx * ln * f - nx * (wd / 2 * (1 - f) + jitter), tail[1] - dy * ln * f - ny * (wd / 2 * (1 - f) + jitter)))
        pts.append((tail[0] - nx * wd / 2, tail[1] - ny * wd / 2))
        c.fill(c.poly(pts), RAMPS['fire'], ramp_t + (c.noise(3, rng, 2) - 0.5) * 0.25)


def gen_rocket_projectile():
    for frame in range(2):
        rng = seed_for('rocketp%d' % frame)
        c = Canvas(48, 48)
        p0, p1 = (16.0, 33.0), (31.0, 15.0)                          # tail -> nose
        L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        d = ((p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L)
        n = (-d[1], d[0])
        flame(c, (p0[0] - d[0] * 2, p0[1] - d[1] * 2), d, 11 + frame * 5, rng, 9 + frame * 2)
        for sgn in (-1, 1):                                          # fins
            fin = c.poly([(p0[0] + n[0] * sgn * 3, p0[1] + n[1] * sgn * 3), (p0[0] + n[0] * sgn * 9 - d[0] * 3, p0[1] + n[1] * sgn * 9 - d[1] * 3),
                          (p0[0] + n[0] * sgn * 4 + d[0] * 7, p0[1] + n[1] * sgn * 4 + d[1] * 7)])
            c.fill(fin, RAMPS['gunmetal'], 0.35 + (sgn + 1) * 0.15)
        tapered_bar(c, p0, p1, 10, 9, RAMPS['steel'], 5, 0.35, 0.15, 0.85, 0.2, rng)
        cone = c.poly([(p1[0] + n[0] * 4.5, p1[1] + n[1] * 4.5), (p1[0] + d[0] * 9, p1[1] + d[1] * 9), (p1[0] - n[0] * 4.5, p1[1] - n[1] * 4.5)])
        c.fill(cone, RAMPS['red'], 0.3 + c.cyl(p1[0] - 5, p1[0] + 5, 0.35) * 0.5)
        c.tint(c.line(p1, (p1[0] - d[0] * 2, p1[1] - d[1] * 2), 10) & ~cone, (0, 0, 0), 0.4)
        c.outline()
        c.grunge(rng, 0.08, 2)
        save_sprite(c, 'sprites', 'projectiles', 'rocket', '%d.png' % frame)


def gen_explosion():
    for frame in range(6):
        rng = seed_for('explosion%d' % frame)
        c = Canvas(128, 128)
        cx = cy = 63.5
        d = c.dist(cx, cy)
        if frame == 0:
            spikes = angular_noise(c, cx, cy, 14, rng)
            edge = 12 + spikes ** 1.5 * 22
            inside = d < edge
            t = np.clip(1 - d / edge, 0, 1) ** 0.6 + 0.3
            c.fill(inside, RAMPS['fire'], np.clip(t, 0, 1))
            c.outline((150, 30, 0))
            c.glow(cx, cy, 34, (255, 200, 80), 0.5, 2)
        elif frame <= 3:
            R = (36, 50, 58)[frame - 1]
            n = fbm(128, 128, 22, 4, 0.55, rng, False, False)
            field = (1 - d / R) + (n - 0.5) * 0.7 + angular_noise(c, cx, cy, 12, rng) * 0.2
            inside = field > 0.12
            t = np.clip(field * (1.3 - frame * 0.15), 0, 1)
            c.fill(inside, RAMPS['explode'], t, grit=0.2, rng=rng)
            # smoky, semi transparent rim
            rimf = np.clip((0.3 - field) / 0.18, 0, 1)
            c.alpha[inside] = 1 - rimf[inside] * 0.5
            c.outline((30, 14, 10), thresh=0.4)
            c.glow(cx, cy, R + 24, (255, 120, 30), 0.35 - frame * 0.06, 2.5)
        else:
            R = (60, 63)[frame - 4]
            n = fbm(128, 128, 20, 4, 0.55, rng, False, False)
            field = (1 - d / R) + (n - 0.5) * 1.1
            inside = field > 0.32
            t = np.clip(0.15 + field * 0.9 + (n - 0.5) * 0.3, 0, 1)
            c.fill(inside, RAMPS['smoke'], t, grit=0.25, rng=rng)
            fade_a = (0.8, 0.5)[frame - 4]
            c.alpha[inside] = fade_a * np.clip((field[inside] - 0.32) / 0.25 + 0.4, 0.3, 1)
            c.outline((22, 20, 20), thresh=0.35)
        save_sprite(c, 'sprites', 'projectiles', 'explosion', '%d.png' % frame)


def gen_blood():
    for frame in range(3):
        rng = seed_for('blood%d' % frame)
        c = Canvas(32, 32)
        spread = 4 + frame * 3
        drops = []
        if frame == 0:
            drops.append((16, 16, 5))
        for _ in range(9):
            drops.append((16 + rng.normal(0, spread), 16 + rng.normal(0, spread) + frame * 2, rng.randint(1, 4 - min(frame, 2))))
        for x, y, r in drops:
            m = c.circle(x, y, r)
            c.fill(m, RAMPS['blood'], 0.35 + c.sphere(x, y, r + 0.5) * 0.5, grit=0.2, rng=rng)
        c.outline((30, 2, 2))
        c.alpha[c.alpha > 0] *= (1.0, 0.8, 0.55)[frame]
        save_sprite(c, 'sprites', 'projectiles', 'blood', '%d.png' % frame)


def gen_puff():
    for frame in range(3):
        rng = seed_for('puff%d' % frame)
        c = Canvas(32, 32)
        spread = 3 + frame * 2
        for _ in range(7):
            x, y, r = 16 + rng.normal(0, spread), 16 + rng.normal(0, spread) - frame * 2, rng.randint(3, 6) + frame
            m = c.circle(x, y, r)
            c.fill(m, RAMPS['smoke'], 0.45 + c.sphere(x, y, r + 1, (-0.4, -0.5)) * 0.5, grit=0.25, rng=rng)
        c.outline((50, 48, 48))
        c.alpha[c.alpha > 0] *= (0.9, 0.7, 0.45)[frame]
        save_sprite(c, 'sprites', 'projectiles', 'puff', '%d.png' % frame)


def gen_projectiles():
    gen_fireball()
    gen_rocket_projectile()
    gen_explosion()
    gen_blood()
    gen_puff()


# ---------------------------------------------------------------------------
# 3d. sprites - first-person weapons (194x210 art, upscaled 5x -> 970x1050)
# ---------------------------------------------------------------------------
WPN_W, WPN_H = 194, 210


def draw_hand(c, gx, gy, rng, left=False):
    """Gloved fist seen from behind, closed around a grip whose top is (gx, gy).

    Drawn as a right hand (fingers curl to the left of the grip, thumb wraps
    over them) on a scratch canvas and mirrored for a left hand.  The sleeve
    runs off the bottom edge like the shotgun sprite.
    """
    t = Canvas(c.w, c.h)
    if left:
        gx = c.w - 1 - gx
    # sleeve + green cuff (drawn first, the fist sits on top)
    arm = t.poly([(gx - 10, gy + 34), (gx + 40, gy + 34), (gx + 60, c.h + 2), (gx - 18, c.h + 2)])
    t.fill(arm, RAMPS['olive'], 0.25 + t.cyl(gx - 14, gx + 50, 0.35) * 0.45, grit=0.3, rng=rng)
    cuff = arm & (t.yy >= gy + 38) & (t.yy < gy + 54)
    t.fill(cuff, RAMPS['sleeve'], 0.35 + t.cyl(gx - 14, gx + 50, 0.35) * 0.5, grit=0.3, rng=rng)
    t.tint(arm & (t.yy == gy + 54), (0, 0, 0), 0.5)
    t.tint(arm & (t.yy == gy + 38), (0, 0, 0), 0.4)
    # back of the hand with a knuckle ridge along the top
    palm = t.rrect(gx - 4, gy + 4, 42, 38, 10)
    for i in range(4):
        palm |= t.circle(gx + 3 + i * 10, gy + 8, 6)
    t.fill(palm, RAMPS['glove'], 0.15 + t.sphere(gx + 17, gy + 22, 27, (-0.45, -0.5)) * 0.8, grit=0.25, rng=rng)
    for i in range(4):                                               # knuckle highlights / valleys
        t.tint(t.circle(gx + 3 + i * 10, gy + 7, 2), (255, 255, 255), 0.2)
        t.tint(t.rect(gx + 8 + i * 10, gy + 4, 1, 8) & palm, (0, 0, 0), 0.3)
    # four curled fingers wrapping the far side of the grip
    widths = (32, 33, 31, 27)
    for i, w in enumerate(widths):
        fy = gy + 8 + i * 9
        f = t.rrect(gx - 24, fy, w, 10, 4)
        t.fill(f, RAMPS['glove'], 0.2 + t.cyl_v(fy, fy + 10, 0.3) * 0.55 + t.grad_h(gx - 24, gx + 8) * 0.2, grit=0.25, rng=rng)
        t.tint(f & (t.yy == fy + 9), (0, 0, 0), 0.55)               # crease between fingers
        t.tint(t.rect(gx - 18, fy + 2, 6, 2) & f, (255, 255, 255), 0.18)
        t.tint(t.rect(gx - 24, fy, 4, 10) & f, (0, 0, 0), 0.25)     # finger tips in shadow
    # thumb wrapping diagonally over the index finger
    thumb = tapered_bar(t, (gx + 22, gy + 6), (gx - 12, gy + 16), 13, 9, RAMPS['glove'], 4, 0.35, 0.25, 0.85, 0.25, rng)
    tip = t.circle(gx - 12, gy + 16, 4)
    t.fill(tip, RAMPS['glove'], 0.4 + t.sphere(gx - 12, gy + 16, 5) * 0.4, grit=0.2, rng=rng)
    thumb |= tip
    t.tint(dilate(thumb) & ~thumb & (t.alpha > 0), (0, 0, 0), 0.5)
    if left:
        t = t.flipped()
    c.blit(t, 0, 0)


def muzzle_flash(c, cx, cy, r, rng, spikes=11):
    """Layered star burst: orange -> yellow -> white core."""
    for scale, level, a in ((1.0, 0.55, 0.85), (0.66, 0.8, 1.0), (0.36, 1.0, 1.0)):
        pts = []
        for k in range(spikes * 2):
            ang = k * math.pi / spikes + rng.uniform(-0.12, 0.12)
            rr = r * scale * (rng.uniform(0.9, 1.1) if k % 2 == 0 else rng.uniform(0.45, 0.65))
            pts.append((cx + math.cos(ang) * rr, cy + math.sin(ang) * rr))
        m = c.poly(pts)
        c.fill(m, RAMPS['fire'], level + (c.noise(5, rng, 2) - 0.5) * 0.25, alpha=a)
    c.glow(cx, cy, r * 1.5, (255, 160, 40), 0.45, 2.2)


def smoke_puffs(c, cx, cy, spread, n, rng, alpha=0.6, size=(6, 12)):
    for _ in range(n):
        x, y = cx + rng.normal(0, spread), cy + rng.normal(0, spread * 0.6)
        r = rng.randint(size[0], size[1])
        m = c.circle(x, y, r)
        c.fill(m, RAMPS['smoke'], 0.5 + c.sphere(x, y, r + 1, (-0.4, -0.5)) * 0.4, grit=0.25, rng=rng, alpha=alpha)


def save_weapon(c, rng, *rel):
    c.grunge(rng, 0.09, 2)
    big = pg.transform.scale(c.surface(), (WPN_W * 5, WPN_H * 5))
    save_surface(big, *rel)


def draw_pistol(rng, oy=0, slide_back=0, flash=False):
    c = Canvas(WPN_W, WPN_H)
    gx = 111
    # grip with a brown checkered panel
    grip = c.rrect(gx - 12, 126 + oy, 24, 64, 3)
    c.fill(grip, RAMPS['gunmetal'], 0.2 + c.cyl(gx - 12, gx + 12, 0.35) * 0.4, grit=0.2, rng=rng)
    panel = c.rrect(gx - 8, 138 + oy, 16, 44, 2)
    checker = ((c.xx + c.yy) % 2 == 0)
    c.fill(panel & checker, RAMPS['leather'], 0.55)
    c.fill(panel & ~checker, RAMPS['leather'], 0.3)
    draw_hand(c, gx, 136 + oy, rng)
    # frame and trigger guard above the fingers
    frame = c.rect(gx - 14, 116 + oy, 28, 16)
    c.fill(frame, RAMPS['gunmetal'], 0.18 + c.cyl(gx - 14, gx + 14, 0.35) * 0.3, grit=0.2, rng=rng)
    # barrel (only visible when the slide is back)
    sb = slide_back
    top, bot = 72 + oy + sb, 126 + oy + sb
    if slide_back:                                                                   # exposed barrel
        barrel = c.rect(gx - 7, top - 14, 14, 16)
        c.fill(barrel, RAMPS['steel'], 0.3 + c.cyl(gx - 7, gx + 7, 0.35) * 0.55, grit=0.2, rng=rng)
        c.fill(c.ellipse(gx - 7, top - 17, 14, 7), RAMPS['dark'], 0.3)
    slide = c.poly([(gx - 15, top), (gx + 15, top), (gx + 23, bot), (gx - 23, bot)])
    c.fill(slide, RAMPS['gunmetal'], 0.12 + c.grad_h(gx - 23, gx + 23) * 0.15, grit=0.15, rng=rng)
    face = c.poly([(gx - 10, top + 2), (gx + 10, top + 2), (gx + 17, bot), (gx - 17, bot)])
    c.fill(face, RAMPS['gunmetal'], 0.3 + (1 - c.grad_h(gx - 17, gx + 17)) * 0.4 + c.grad_v(top, bot) * 0.1, grit=0.2, rng=rng)
    c.tint(c.rect(gx - 1, top + 4, 2, bot - top - 12) & face, (0, 0, 0), 0.35)      # sight groove
    port = c.rect(gx + 4, top + 16, 9, 18) & face
    c.fill(port, RAMPS['dark'], 0.35)
    for k in range(0, 12, 2):                                                        # rear serrations
        c.tint(c.rect(gx - 22 + k, bot - 16, 1, 12) & slide, (255, 255, 255), 0.18)
        c.tint(c.rect(gx + 12 + k, bot - 16, 1, 12) & slide, (255, 255, 255), 0.18)
    # front sight, rear sight with a notch, hammer
    c.fill(c.rect(gx - 2, top - 4, 4, 9), RAMPS['gunmetal'], 0.4)
    c.paint(c.rect(gx - 1, top - 3, 2, 2), (240, 240, 240))
    rear = c.rect(gx - 20, bot - 7, 40, 10) & ~c.rect(gx - 4, bot - 7, 8, 6)
    c.fill(rear, RAMPS['gunmetal'], 0.28 + c.grad_v(bot - 7, bot + 3) * 0.2)
    c.paint(c.rect(gx - 12, bot - 5, 2, 2) | c.rect(gx + 10, bot - 5, 2, 2), (240, 240, 240))
    hammer = c.ellipse(gx - 6, bot + 1, 12, 10)
    c.fill(hammer, RAMPS['gunmetal'], 0.25 + c.sphere(gx, bot + 6, 6) * 0.4)
    c.outline()
    if flash:
        muzzle_flash(c, gx, top - 22, 40, rng)
    return c


def gen_pistol():
    rng = seed_for('pistol0')
    save_weapon(draw_pistol(rng, 0, 0, False), rng, 'sprites', 'weapon', 'pistol', '0.png')
    rng = seed_for('pistol1')
    save_weapon(draw_pistol(rng, -10, 0, True), rng, 'sprites', 'weapon', 'pistol', '1.png')
    rng = seed_for('pistol2')
    save_weapon(draw_pistol(rng, -18, 9, False), rng, 'sprites', 'weapon', 'pistol', '2.png')


def draw_chaingun(rng, phase_deg=0, flash_r=0):
    c = Canvas(WPN_W, WPN_H)
    cx = 97
    near_y, far_y, r_near, r_far, ry = 122, 62, 27, 19, 0.45
    barrels = []
    for i in range(6):
        a = math.radians(phase_deg + i * 60)
        barrels.append((math.sin(a), a))
    for _, a in sorted(barrels):                                     # back to front
        near = (cx + math.cos(a) * r_near, near_y + math.sin(a) * r_near * ry)
        far = (cx + math.cos(a) * r_far, far_y + math.sin(a) * r_far * ry)
        tapered_bar(c, near, far, 14, 10, RAMPS['gunmetal'], 5, 0.35, 0.12, 0.8, 0.2, rng)
    # solid muzzle plate at the far end with six bores
    plate = c.ellipse(cx - 29, far_y - 13, 58, 26)
    c.fill(plate, RAMPS['steel'], 0.2 + c.cyl(cx - 29, cx + 29, 0.35) * 0.5, grit=0.2, rng=rng)
    c.tint(c.ellipse(cx - 25, far_y - 11, 50, 22) & plate, (0, 0, 0), 0.25)
    for _, a in barrels:
        bx, by = cx + math.cos(a) * r_far * 0.75, far_y + math.sin(a) * r_far * ry * 0.75
        bore = c.ellipse(bx - 4, by - 3, 9, 7)
        c.fill(bore, RAMPS['dark'], 0.15)
        c.tint(dilate(bore) & ~bore & plate, (150, 156, 166), 0.4)
    c.fill(c.circle(cx, far_y, 4), RAMPS['gunmetal'], 0.5)
    # rotating drum housing (near end) + receiver body
    drum = c.ellipse(cx - 36, near_y - 12, 72, 32)
    c.fill(drum, RAMPS['steel'], 0.12 + c.cyl(cx - 36, cx + 36, 0.35) * 0.55, grit=0.2, rng=rng)
    c.tint(c.ellipse(cx - 30, near_y - 9, 60, 26) & drum, (0, 0, 0), 0.3)
    c.fill(c.circle(cx, near_y + 4, 6), RAMPS['gunmetal'], 0.5)
    body = c.rrect(50, near_y + 8, 94, 60, 5)
    c.fill(body, RAMPS['gunmetal'], 0.18 + c.cyl(50, 144, 0.35) * 0.35, grit=0.2, rng=rng)
    c.fill(c.rect(54, near_y + 8, 86, 12) & body, RAMPS['gunmetal'], 0.5 + c.cyl(50, 144, 0.35) * 0.3, grit=0.2, rng=rng)
    c.tint(c.rect(54, near_y + 20, 86, 1), (0, 0, 0), 0.6)
    for k in range(3):                                               # cooling slots
        c.fill(c.rect(70 + k * 20, near_y + 30, 12, 4), RAMPS['dark'], 0.25)
    # feed cover + ammo belt on the left
    cover = c.rrect(28, near_y + 18, 30, 30, 3)
    c.fill(cover, RAMPS['steel'], 0.25 + c.cyl(28, 58, 0.35) * 0.4, grit=0.2, rng=rng)
    for k in range(5):
        bx = 2 + k * 6
        by = near_y + 22 + int(math.sin(k * 0.9) * 3)
        cart = c.rrect(bx, by, 6, 20, 2)
        c.fill(cart, RAMPS['brass'], 0.35 + c.cyl(bx, bx + 6, 0.35) * 0.5)
        c.fill(c.rect(bx, by, 6, 5), RAMPS['copper'], 0.5)
        c.tint(c.rect(bx, by + 9, 6, 2), (0, 0, 0), 0.5)             # belt link
    # grips and both hands
    for gx in (64, 136):
        g = c.rrect(gx - 8, near_y + 56, 16, 40, 3)
        c.fill(g, RAMPS['gunmetal'], 0.2 + c.cyl(gx - 8, gx + 8, 0.35) * 0.35, grit=0.2, rng=rng)
    draw_hand(c, 64, near_y + 62, rng, left=True)
    draw_hand(c, 136, near_y + 62, rng, left=False)
    c.outline()
    if flash_r:
        muzzle_flash(c, cx, far_y - 24, flash_r, rng)
    return c


def gen_chaingun():
    rng = seed_for('chaingun0')
    save_weapon(draw_chaingun(rng, 0, 0), rng, 'sprites', 'weapon', 'chaingun', '0.png')
    rng = seed_for('chaingun1')
    save_weapon(draw_chaingun(rng, 20, 30), rng, 'sprites', 'weapon', 'chaingun', '1.png')
    rng = seed_for('chaingun2')
    save_weapon(draw_chaingun(rng, 40, 42), rng, 'sprites', 'weapon', 'chaingun', '2.png')


def draw_rocket_launcher(rng, oy=0, flash=False, wisp=False):
    c = Canvas(WPN_W, WPN_H)
    p0 = (154.0, 214.0 + oy)                                         # near end (on the shoulder)
    p1 = (108.0, 62.0 + oy)                                          # muzzle
    L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    d = ((p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L)
    n = (-d[1], d[0])

    def axis(s, w0=62, w1=40):
        return (p0[0] + (p1[0] - p0[0]) * s, p0[1] + (p1[1] - p0[1]) * s), w0 + (w1 - w0) * s

    tapered_bar(c, p0, p1, 62, 40, RAMPS['steel'], 7, 0.38, 0.1, 0.8, 0.2, rng)
    # red band, sight rail, rear sling loop
    (pa, wa), (pb, wb) = axis(0.62), axis(0.70)
    tapered_bar(c, pa, pb, wa + 2, wb + 2, RAMPS['red'], 7, 0.38, 0.2, 0.85, 0.2, rng)
    (pa, wa), (pb, wb) = axis(0.40), axis(0.43)
    tapered_bar(c, pa, pb, wa + 2, wb + 2, RAMPS['gunmetal'], 7, 0.38, 0.15, 0.6, 0.2, rng)
    sp, sw = axis(0.55)
    sight = c.rect(sp[0] + n[0] * (-sw / 2) - 4, sp[1] + n[1] * (-sw / 2) - 8, 8, 10)
    c.fill(sight, RAMPS['gunmetal'], 0.35)
    c.paint(c.rect(sp[0] + n[0] * (-sw / 2) - 1, sp[1] + n[1] * (-sw / 2) - 6, 2, 2), (240, 240, 240))
    # muzzle: ring + dark bore
    ring = c.ellipse(p1[0] - 21, p1[1] - 9, 42, 18)
    c.fill(ring, RAMPS['gunmetal'], 0.25 + c.cyl(p1[0] - 21, p1[1] + 21, 0.35) * 0.4, grit=0.2, rng=rng)
    bore = c.ellipse(p1[0] - 15, p1[1] - 6, 30, 12)
    c.fill(bore, RAMPS['dark'], 0.12 + c.grad_v(p1[1] - 6, p1[1] + 6) * 0.25)
    # trigger grip under the tube + right hand
    gx, gy = 112, 172
    grip = c.rrect(gx - 9, gy - 10, 18, 46, 3)
    c.fill(grip, RAMPS['gunmetal'], 0.2 + c.cyl(gx - 9, gx + 9, 0.35) * 0.35, grit=0.2, rng=rng)
    draw_hand(c, gx, gy, rng)
    c.outline()
    if flash:
        muzzle_flash(c, p1[0], p1[1] - 16, 44, rng)
        smoke_puffs(c, p1[0], p1[1] - 30, 22, 8, rng, 0.55, (7, 14))
    if wisp:
        smoke_puffs(c, p1[0], p1[1] - 22, 10, 4, rng, 0.45, (4, 8))
    return c


def gen_rocket_launcher():
    rng = seed_for('rl0')
    save_weapon(draw_rocket_launcher(rng, 0, False, False), rng, 'sprites', 'weapon', 'rocket_launcher', '0.png')
    rng = seed_for('rl1')
    save_weapon(draw_rocket_launcher(rng, -4, True, False), rng, 'sprites', 'weapon', 'rocket_launcher', '1.png')
    rng = seed_for('rl2')
    save_weapon(draw_rocket_launcher(rng, -16, False, True), rng, 'sprites', 'weapon', 'rocket_launcher', '2.png')


def gen_weapons():
    gen_pistol()
    gen_chaingun()
    gen_rocket_launcher()


def gen_sprites():
    gen_pickups()
    gen_decorations()
    gen_projectiles()
    gen_weapons()


# ---------------------------------------------------------------------------
# 4. sound synthesis helpers
# ---------------------------------------------------------------------------
def samples(seconds):
    return int(round(seconds * SR))


def tline(seconds):
    return np.arange(samples(seconds)) / SR


def osc(kind, freq, n=None, seconds=None, duty=0.5, phase=0.0):
    """Retro oscillator; freq may be a scalar or a per-sample array (sweeps)."""
    if n is None:
        n = samples(seconds)
    f = np.broadcast_to(np.asarray(freq, np.float64), (n,))
    ph = (np.cumsum(f) / SR + phase) % 1.0
    if kind == 'sine':
        return np.sin(2 * np.pi * ph)
    if kind == 'square':
        return np.where(ph < duty, 1.0, -1.0)
    if kind == 'saw':
        return 2 * ph - 1
    if kind == 'tri':
        return 4 * np.abs(ph - 0.5) - 1
    raise ValueError(kind)


def white(n, rng):
    return rng.uniform(-1, 1, n)


def lowpass(x, cutoff):
    """One-pole lowpass.  cutoff in Hz, scalar or per-sample array (sweeps).

    Vectorised in blocks: inside a block the coefficient is constant and the
    recurrence y[n] = y[n-1] + a (x[n] - y[n-1]) has the closed form used below.
    """
    x = np.asarray(x, np.float64)
    n = len(x)
    cut = np.broadcast_to(np.asarray(cutoff, np.float64), (n,))
    coef = 1.0 - np.exp(-2 * np.pi * np.clip(cut, 1, SR * 0.45) / SR)
    y = np.empty(n)
    state = 0.0
    B = 64
    k = np.arange(B)
    for s in range(0, n, B):
        a = float(np.clip(coef[s:s + B].mean(), 1e-5, 0.95))
        xs = x[s:s + B]
        m = len(xs)
        kk = k[:m]
        r = 1.0 - a
        decay = r ** (kk + 1)
        ys = decay * state + (r ** kk) * np.cumsum(a * xs * (r ** (-kk)))
        y[s:s + m] = ys
        state = ys[-1]
    return y


def highpass(x, cutoff):
    return np.asarray(x, np.float64) - lowpass(x, cutoff)


def brown(n, rng):
    b = np.cumsum(white(n, rng))
    b = highpass(b, 20)
    return normalize(b, 1.0)


def env_exp(n, tau):
    return np.exp(-np.arange(n) / (tau * SR))


def adsr(n, a, d, s, r):
    """Linear attack/decay/sustain/release envelope (times in seconds)."""
    t = np.arange(n) / SR
    total = n / SR
    env = np.full(n, float(s))
    att = t < a
    env[att] = t[att] / max(a, 1e-6)
    dec = (t >= a) & (t < a + d)
    env[dec] = 1 - (1 - s) * (t[dec] - a) / max(d, 1e-6)
    rel = t > total - r
    env[rel] *= np.clip((total - t[rel]) / max(r, 1e-6), 0, 1)
    return env


def bitcrush(x, bits=8, hold=1):
    q = 2 ** (bits - 1)
    y = np.round(np.asarray(x) * q) / q
    if hold > 1:
        y = np.repeat(y[::hold], hold)[:len(x)]
    return y


def distort(x, drive=4.0):
    return np.tanh(np.asarray(x) * drive) / math.tanh(drive)


def normalize(x, peak=0.8):
    x = np.nan_to_num(np.asarray(x, np.float64))
    m = np.max(np.abs(x)) if len(x) else 0
    return x * (peak / m) if m > 0 else x


def fade(x, ms=2.0):
    k = min(len(x) // 2, samples(ms / 1000.0))
    if k > 0:
        ramp = np.linspace(0, 1, k)
        if x.ndim == 2:
            ramp = ramp[:, None]
        x[:k] *= ramp
        x[-k:] *= ramp[::-1]
    return x


def place(buf, x, at, gain=1.0):
    """Mix x into buf starting at `at` seconds (clipped to the buffer)."""
    i = samples(at)
    n = min(len(x), len(buf) - i)
    if n > 0 and i >= 0:
        buf[i:i + n] += x[:n] * gain
    return buf


def echo(x, delay, feedback=0.4, taps=3):
    out = np.array(x, np.float64)
    for k in range(1, taps + 1):
        place(out, x, delay * k, feedback ** k)
    return out


def fit(x, seconds):
    n = samples(seconds)
    if len(x) >= n:
        return x[:n]
    return np.concatenate([x, np.zeros(n - len(x))])


def write_wav(rel, data):
    """16-bit PCM WAV at SR; data shape (n,) mono or (n, 2) stereo."""
    path = rpath(*rel)
    data = np.asarray(data, np.float64)
    channels = 1 if data.ndim == 1 else data.shape[1]
    pcm = (np.clip(data, -1, 1) * 32767).astype('<i2')
    with wave.open(path, 'wb') as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(np.ascontiguousarray(pcm).tobytes())
    GENERATED_AUDIO.append(path)
    return path


# ---------------------------------------------------------------------------
# 4b. sound effects (mono)
# ---------------------------------------------------------------------------
def sfx_pistol(rng):
    n = samples(0.25)
    crack = lowpass(white(n, rng), np.linspace(8000, 1200, n)) * env_exp(n, 0.04)
    thump = osc('sine', np.linspace(200, 55, n), n) * env_exp(n, 0.07)
    snap = white(n, rng) * env_exp(n, 0.003)
    return bitcrush(crack + thump * 0.8 + snap, 8)


def sfx_chaingun(rng):
    n = samples(0.12)
    crack = highpass(lowpass(white(n, rng), 5000), 300) * env_exp(n, 0.02)
    thump = osc('square', np.linspace(160, 70, n), n) * env_exp(n, 0.03) * 0.5
    return bitcrush(crack + thump + white(n, rng) * env_exp(n, 0.002), 8)


def sfx_rocket_launch(rng):
    n = samples(0.6)
    t = tline(0.6)
    cut = 400 + 2800 * np.sin(np.pi * np.clip(t / 0.5, 0, 1))
    whoosh = lowpass(white(n, rng), cut) * np.sin(np.pi * np.clip(t / 0.6, 0, 1)) ** 0.6
    thump = osc('sine', np.linspace(120, 40, n), n) * env_exp(n, 0.12)
    burst = lowpass(white(n, rng), 1500) * env_exp(n, 0.05)
    return whoosh + thump + burst * 0.8


def sfx_explosion(rng, pitch=1.0, clank=False):
    n = samples(1.0)
    boom = lowpass(brown(n, rng), np.linspace(2500, 150, n) * pitch) * env_exp(n, 0.32)
    sub = osc('sine', np.linspace(70, 35, n) * pitch, n) * env_exp(n, 0.25)
    crack = lowpass(white(n, rng), 6000) * env_exp(n, 0.02)
    x = boom * 1.2 + sub * 0.8 + crack * 0.7
    if clank:
        for f, dl, tau in ((1240, 0.05, 0.12), (1730, 0.07, 0.10), (2460, 0.09, 0.08), (880, 0.12, 0.15)):
            m = samples(0.4)
            place(x, osc('sine', f * pitch, m) * env_exp(m, tau), dl, 0.35)
    return bitcrush(x, 8)


def sfx_barrel_explode(rng):
    return sfx_explosion(rng, 1.5, True)


def sfx_door(rng, opening):
    n = samples(0.6)
    cut = np.linspace(600, 3800, n) if opening else np.linspace(3800, 600, n)
    hiss = highpass(lowpass(white(n, rng), cut), 200) * adsr(n, 0.05, 0.1, 0.7, 0.15)
    mf = np.linspace(50, 110, n) if opening else np.linspace(110, 50, n)
    motor = lowpass(osc('square', mf, n, duty=0.3), 400) * adsr(n, 0.05, 0.1, 0.8, 0.1) * 0.15
    x = hiss * 0.8 + motor
    if not opening:
        m = samples(0.15)
        clunk = osc('sine', np.linspace(110, 60, m), m) * env_exp(m, 0.04) + lowpass(white(m, rng), 900) * env_exp(m, 0.02)
        place(x, clunk, 0.46, 1.2)
    return x


def sfx_door_open(rng):
    return sfx_door(rng, True)


def sfx_door_close(rng):
    return sfx_door(rng, False)


def sfx_door_locked(rng):
    x = np.zeros(samples(0.3))
    for start in (0.0, 0.15):
        m = samples(0.12)
        buzz = osc('square', 110, m) * (osc('square', 30, m) * 0.5 + 0.5)
        place(x, lowpass(buzz, 1800) * adsr(m, 0.005, 0.02, 0.8, 0.03), start)
    return bitcrush(x, 8)


def sfx_pickup_item(rng):
    n = samples(0.15)
    f = np.where(tline(0.15) < 0.06, 880.0, 1320.0)
    return bitcrush(osc('square', f, n) * adsr(n, 0.003, 0.05, 0.5, 0.05), 8)


def sfx_pickup_weapon(rng):
    x = np.zeros(samples(0.5))
    for i, f in enumerate((523.25, 659.25, 783.99)):
        m = samples(0.16 if i < 2 else 0.22)
        vib = 1 + 0.004 * np.sin(2 * np.pi * 6 * np.arange(m) / SR)
        place(x, osc('square', f * vib, m, duty=0.25) * adsr(m, 0.005, 0.05, 0.6, 0.05), i * 0.14)
    return bitcrush(x, 8)


def sfx_pickup_key(rng):
    x = np.zeros(samples(0.4))
    for i, f in enumerate((660.0, 990.0)):
        m = samples(0.2)
        place(x, (osc('tri', f, m) + 0.3 * osc('sine', 2 * f, m)) * adsr(m, 0.005, 0.08, 0.5, 0.08), i * 0.18)
    return x


def sfx_powerup(rng):
    n = samples(0.8)
    t = tline(0.8)
    f = 300 * 4.0 ** (t / 0.8)
    trem = 0.75 + 0.25 * np.sin(2 * np.pi * 12 * t)
    x = (osc('tri', f, n) + 0.5 * osc('sine', f * 1.5, n) + 0.3 * osc('sine', f * 2, n)) * trem
    return echo(x * adsr(n, 0.05, 0.1, 0.8, 0.25), 0.09, 0.45, 3)


def sfx_switch(rng):
    x = np.zeros(samples(0.3))
    k = samples(0.02)
    place(x, white(k, rng) * env_exp(k, 0.004), 0.0)
    m = samples(0.15)
    clunk = osc('sine', np.linspace(140, 70, m), m) * env_exp(m, 0.04) + lowpass(white(m, rng), 1200) * env_exp(m, 0.03)
    place(x, clunk, 0.1)
    return bitcrush(x, 8)


def sfx_secret_found(rng):
    x = np.zeros(samples(0.6))
    for i, f in enumerate((440.0, 523.25, 659.25, 830.61, 987.77, 1318.5)):
        m = samples(0.16)
        place(x, osc('tri', f, m) * adsr(m, 0.005, 0.06, 0.5, 0.08), i * 0.085, 0.9 - i * 0.05)
    return echo(x, 0.12, 0.4, 3)


def sfx_menu_move(rng):
    n = samples(0.08)
    return osc('tri', 1000, n) * env_exp(n, 0.012) + white(n, rng) * env_exp(n, 0.002) * 0.3


def sfx_menu_select(rng):
    n = samples(0.2)
    f = np.where(tline(0.2) < 0.08, 700.0, 1050.0)
    return bitcrush(osc('square', f, n) * adsr(n, 0.003, 0.06, 0.5, 0.06), 8)


def sfx_menu_back(rng):
    n = samples(0.2)
    f = np.where(tline(0.2) < 0.08, 1000.0, 520.0)
    return bitcrush(osc('square', f, n) * adsr(n, 0.003, 0.06, 0.5, 0.06), 8)


def sfx_player_death(rng):
    n = samples(1.2)
    t = tline(1.2)
    f = 220 * (65 / 220) ** (t / 1.2) * (1 + 0.03 * np.sin(2 * np.pi * 7 * t))
    voice = osc('saw', f, n) + 0.5 * osc('square', f * 0.5, n, duty=0.3)
    growl = lowpass(white(n, rng), 1200) * (0.5 + 0.5 * osc('square', f, n))
    x = lowpass(voice * 0.7 + growl * 0.6, np.linspace(2500, 300, n)) * adsr(n, 0.02, 0.3, 0.7, 0.5)
    return bitcrush(x, 8)


def sfx_fireball(rng):
    n = samples(0.4)
    t = tline(0.4)
    cut = 300 + 2400 * np.sin(np.pi * np.clip(t / 0.4, 0, 1)) ** 0.7
    whoosh = lowpass(white(n, rng), cut) * adsr(n, 0.03, 0.1, 0.7, 0.15)
    crackle = np.where(rng.random_sample(n) < 0.004, rng.uniform(-1, 1, n), 0.0)
    crackle = lowpass(crackle, 3000) * adsr(n, 0.02, 0.1, 0.8, 0.15)
    tone = osc('saw', np.linspace(90, 60, n), n) * env_exp(n, 0.15) * 0.3
    return whoosh + crackle * 3 + tone


def sfx_level_complete(rng):
    x = np.zeros(samples(1.5))
    for i, f in enumerate((523.25, 659.25, 783.99, 1046.5)):
        m = samples(0.14)
        place(x, osc('square', f, m, duty=0.25) * adsr(m, 0.005, 0.04, 0.7, 0.04), i * 0.12)
    m = samples(1.0)
    chord = sum(osc('square', f, m, duty=0.5 if k % 2 else 0.25) for k, f in enumerate((523.25, 659.25, 783.99, 1046.5))) / 4
    place(x, chord * adsr(m, 0.01, 0.2, 0.6, 0.4), 0.48, 1.2)
    return bitcrush(echo(x, 0.15, 0.3, 2), 8)


def sfx_tally_tick(rng):
    n = samples(0.05)
    return osc('square', 2000, n) * env_exp(n, 0.008)


def sfx_tally_done(rng):
    n = samples(0.3)
    return (osc('sine', 1320, n) + 0.4 * osc('sine', 2640, n)) * env_exp(n, 0.08)


SOUND_SPECS = [
    ('pistol', 0.25, sfx_pistol), ('chaingun', 0.12, sfx_chaingun),
    ('rocket_launch', 0.6, sfx_rocket_launch), ('explosion', 1.0, sfx_explosion),
    ('barrel_explode', 1.0, sfx_barrel_explode),
    ('door_open', 0.6, sfx_door_open), ('door_close', 0.6, sfx_door_close), ('door_locked', 0.3, sfx_door_locked),
    ('pickup_item', 0.15, sfx_pickup_item), ('pickup_weapon', 0.5, sfx_pickup_weapon),
    ('pickup_key', 0.4, sfx_pickup_key), ('powerup', 0.8, sfx_powerup),
    ('switch', 0.3, sfx_switch), ('secret_found', 0.6, sfx_secret_found),
    ('menu_move', 0.08, sfx_menu_move), ('menu_select', 0.2, sfx_menu_select), ('menu_back', 0.2, sfx_menu_back),
    ('player_death', 1.2, sfx_player_death), ('fireball', 0.4, sfx_fireball),
    ('level_complete', 1.5, sfx_level_complete), ('tally_tick', 0.05, sfx_tally_tick), ('tally_done', 0.3, sfx_tally_done),
]


def gen_sounds():
    for name, secs, fn in SOUND_SPECS:
        rng = seed_for('sfx_' + name)
        x = fit(fn(rng), secs)
        x = fade(normalize(x, 0.8), 2.0)
        write_wav(('sound', name + '.wav'), x)


# ---------------------------------------------------------------------------
# 5. music helpers (stereo, loop friendly)
# ---------------------------------------------------------------------------
def midi_hz(n):
    return 440.0 * 2 ** ((n - 69) / 12.0)


class Track:
    """Stereo mix buffer with constant-power panning."""

    def __init__(self, seconds):
        self.seconds = seconds
        self.n = samples(seconds)
        self.L = np.zeros(self.n)
        self.R = np.zeros(self.n)

    def add(self, x, at, pan=0.0, gain=1.0):
        a = (pan + 1) / 2 * math.pi / 2
        place(self.L, x, at, gain * math.cos(a))
        place(self.R, x, at, gain * math.sin(a))

    def finish(self, peak=0.7, fade_ms=15):
        st = np.stack([self.L, self.R], axis=1)
        st = st - st.mean(axis=0)                                    # remove DC offset
        return fade(normalize(st, peak), fade_ms)


def synth_pad(freq, seconds, rng, detune=(-7, 0, 7), cutoff=900, attack=1.0, release=1.0, kind='saw'):
    n = samples(seconds)
    x = np.zeros(n)
    for cents in detune:
        x += osc(kind, freq * 2 ** (cents / 1200.0), n, phase=rng.random_sample())
    x = lowpass(x / len(detune), cutoff)
    return x * adsr(n, attack, 0.0, 1.0, release)


def synth_bass(freq, seconds, drive=3.0, cutoff=1200, decay=0.2):
    n = samples(seconds)
    x = osc('saw', freq, n) + 0.6 * osc('square', freq, n)
    x = distort(lowpass(x, cutoff), drive)
    return x * adsr(n, 0.005, decay, 0.6, 0.03)


def synth_bell(freq, seconds, rng):
    n = samples(seconds)
    x = (osc('sine', freq, n) * env_exp(n, seconds * 0.35)
         + 0.5 * osc('sine', freq * 2.76, n) * env_exp(n, seconds * 0.12)
         + 0.3 * osc('sine', freq * 5.4, n) * env_exp(n, seconds * 0.06))
    return x * adsr(n, 0.005, 0.0, 1.0, 0.05)


def synth_lead(freq, seconds, duty=0.25, vib=0.006):
    n = samples(seconds)
    t = np.arange(n) / SR
    f = freq * (1 + vib * np.sin(2 * np.pi * 5.5 * t))
    return osc('square', f, n, duty=duty) * adsr(n, 0.01, 0.05, 0.75, 0.04)


def synth_pluck(freq, seconds):
    n = samples(seconds)
    return osc('square', freq, n) * env_exp(n, 0.08) * adsr(n, 0.002, 0.0, 1.0, 0.01)


def drum_kick(rng, seconds=0.35):
    n = samples(seconds)
    return osc('sine', 40 + 120 * env_exp(n, 0.04), n) * env_exp(n, 0.09) + lowpass(white(n, rng), 1200) * env_exp(n, 0.008) * 0.6


def drum_snare(rng, seconds=0.25):
    n = samples(seconds)
    return highpass(white(n, rng), 800) * env_exp(n, 0.07) * 0.9 + osc('sine', 190, n) * env_exp(n, 0.04) * 0.7


def drum_hat(rng, open_=False):
    n = samples(0.25 if open_ else 0.06)
    return highpass(white(n, rng), 6000) * env_exp(n, 0.08 if open_ else 0.012) * 0.6


def drum_tom(rng, freq=90, seconds=0.4):
    n = samples(seconds)
    return osc('sine', freq * (1 + 0.6 * env_exp(n, 0.05)), n) * env_exp(n, 0.16) + lowpass(white(n, rng), 800) * env_exp(n, 0.01) * 0.4


# ---------------------------------------------------------------------------
# 5b. music loops
# ---------------------------------------------------------------------------
def music_menu():
    """40 s dark ambient in D minor: detuned saw pad with a slow filter sweep."""
    rng = seed_for('music_menu')
    secs = 40.0
    tr = Track(secs)
    t = np.arange(tr.n) / SR
    chords = [(38, 45, 50, 53), (46, 50, 53, 58), (43, 50, 55, 58), (45, 49, 52, 57)]   # Dm Bb Gm A
    for i, ch in enumerate(chords):
        for k, m in enumerate(ch):
            x = synth_pad(midi_hz(m), 11.0, rng, (-6, 0, 6), 5000, 2.5, 3.0)
            tr.add(x, i * 10.0 - (0.5 if i else 0.0), -0.5 + k * 0.33, 0.14)
    sweep = 250 + 900 * (0.5 - 0.5 * np.cos(2 * np.pi * t / secs))       # one full cycle = seamless loop
    tr.L = lowpass(tr.L, sweep)
    tr.R = lowpass(tr.R, sweep)
    sub = osc('sine', midi_hz(26), tr.n) * (0.6 + 0.4 * np.sin(2 * np.pi * t / 8.0))
    tr.add(sub, 0, 0, 0.16)
    tr.add(lowpass(brown(tr.n, rng), 60), 0, 0, 0.12)
    for at, m in ((3.0, 74), (9.5, 69), (17.0, 77), (22.5, 72), (29.0, 65), (35.0, 74)):
        b = echo(synth_bell(midi_hz(m), 4.0, rng), 0.37, 0.5, 4)
        tr.add(lowpass(b, 2500), at, rng.uniform(-0.7, 0.7), 0.16)
    return tr.finish(0.7, 30)


def music_intermission():
    """Tense minimal pulse at 100 BPM (8 bars = 19.2 s)."""
    rng = seed_for('music_intermission')
    beat = 60.0 / 100
    bars = 8
    secs = bars * 4 * beat
    tr = Track(secs)
    pattern = [33, 33, 33, 33, 33, 33, 34, 33, 33, 33, 33, 33, 33, 40, 33, 34]      # 8ths over 2 bars
    for bar in range(bars):
        for k in range(8):
            m = pattern[(bar % 2) * 8 + k]
            tr.add(synth_bass(midi_hz(m), beat * 0.45, 1.5, 500, 0.12), bar * 4 * beat + k * beat / 2, 0, 0.35)
    ost = [81, 0, 76, 0, 0, 79, 0, 0, 86, 0, 0, 76, 0, 79, 0, 0]
    buf = np.zeros(tr.n)
    for bar in range(bars):
        if bar % 4 == 3:
            continue
        for k in range(16):
            if ost[k]:
                place(buf, synth_pluck(midi_hz(ost[k]), beat), bar * 4 * beat + k * beat / 4)
    buf = echo(buf, beat * 0.75, 0.4, 3)
    tr.add(buf, 0, -0.35, 0.12)
    tr.add(buf, 0.02, 0.35, 0.10)
    for m, pan in ((69, -0.3), (76, 0.3)):
        tr.add(synth_pad(midi_hz(m), secs, rng, (-4, 4), 1200, 3.0, 3.0, 'tri'), 0, pan, 0.07)
    for bar in range(bars):
        for k in range(8):
            tr.add(drum_hat(rng), bar * 4 * beat + k * beat / 2, 0.3, 0.12 if k % 2 == 0 else 0.07)
    return tr.finish(0.7, 20)


def music_boss():
    """Heavy 140 BPM loop in E minor (18 bars ~ 30.9 s): 16th-note chug + drums."""
    rng = seed_for('music_boss')
    beat = 60.0 / 140
    bars = 18
    secs = bars * 4 * beat
    tr = Track(secs)
    step = beat / 4
    riff_a = [28, 28, 40, 28, 28, 28, 43, 28, 28, 28, 45, 28, 28, 28, 46, 45,
              28, 28, 40, 28, 28, 28, 43, 28, 28, 28, 47, 46, 45, 43, 40, 28]
    riff_b = [28, 28, 28, 40, 28, 28, 28, 43, 28, 28, 28, 46, 28, 28, 28, 47,
              28, 28, 50, 28, 28, 28, 47, 28, 28, 28, 46, 45, 43, 40, 42, 28]
    for bar in range(bars):
        riff = riff_a if (bar % 8) < 4 or bar >= 16 else riff_b
        base = bar * 4 * beat
        for k in range(16):
            m = riff[(bar % 2) * 16 + k]
            accent = m != 28
            x = synth_bass(midi_hz(m), step * (0.9 if accent else 0.6), 5.0, 1400 if accent else 900, 0.08)
            tr.add(x, base + k * step, 0, 0.32 if accent else 0.26)
        for k in (0, 0.75, 1.5, 2, 2.75, 3.5):
            tr.add(drum_kick(rng), base + k * beat, 0, 0.5)
        for k in (1, 3):
            tr.add(drum_snare(rng), base + k * beat, 0.1, 0.4)
        for k in range(8):
            tr.add(drum_hat(rng, open_=(bar % 2 == 1 and k == 7)), base + k * beat / 2, 0.35, 0.16 if k % 2 == 0 else 0.1)
        if bar >= 16:                                                            # 2-bar break with toms
            for k in (2, 2.5, 3, 3.5):
                tr.add(drum_tom(rng, 120 if bar == 16 else 80), base + k * beat, -0.3, 0.4)
    for bar in range(0, bars, 4):                                                # power-chord stabs
        n = samples(beat * 1.2)
        for m in (40, 47, 52):
            x = distort(lowpass(osc('saw', midi_hz(m), n) + osc('square', midi_hz(m) * 1.005, n), 2500), 4.0)
            x *= adsr(n, 0.005, 0.2, 0.5, 0.15)
            tr.add(x, bar * 4 * beat, -0.4, 0.13)
            tr.add(x, bar * 4 * beat + 0.012, 0.4, 0.13)
    return tr.finish(0.7, 15)


def music_hell():
    """Slow menacing 90 BPM loop (12 bars = 32 s): choir pad, tribal toms, stabs."""
    rng = seed_for('music_hell')
    beat = 60.0 / 90
    bars = 12
    secs = bars * 4 * beat
    tr = Track(secs)
    for m, pan in ((40, -0.6), (47, -0.2), (52, 0.2), (55, 0.6)):
        x = synth_pad(midi_hz(m), secs, rng, (-9, -3, 3, 9), 700, 3.0, 3.0)
        x = x + 0.5 * (lowpass(x, 1400) - lowpass(x, 700))                       # vowel-ish formant bump
        t = np.arange(len(x)) / SR
        x *= 1 + 0.08 * np.sin(2 * np.pi * 0.25 * t + rng.uniform(0, 6))
        tr.add(x, 0, pan, 0.16)
    for start_bar in (4, 10):                                                    # b2 dissonance
        tr.add(synth_pad(midi_hz(53), 8 * beat, rng, (-8, 0, 8), 900, 1.5, 1.5), start_bar * 4 * beat, 0, 0.1)
    pat = [(0, 80), (1.5, 80), (2, 120), (3, 80), (3.5, 120), (4, 80), (5, 120), (5.5, 80), (6, 80), (7, 120), (7.5, 120)]
    for bar in range(0, bars, 2):
        for k, f in pat:
            tr.add(drum_tom(rng, f), bar * 4 * beat + k * beat, -0.3 if f == 80 else 0.3, 0.5 if f == 80 else 0.35)
    for bar in range(bars):
        tr.add(drum_kick(rng, 0.5), bar * 4 * beat, 0, 0.5)
    for at_bar, at_beat in ((3, 2.5), (7, 1.0), (9, 3.5), (11, 2.0)):
        n = samples(beat * 1.5)
        x = sum(osc('saw', midi_hz(m), n) for m in (64, 65, 71)) / 3
        x = lowpass(x, 1800) * adsr(n, 0.01, 0.3, 0.3, 0.3)
        tr.add(echo(x, beat * 0.5, 0.4, 3), at_bar * 4 * beat + at_beat * beat, rng.uniform(-0.5, 0.5), 0.14)
    return tr.finish(0.7, 20)


def music_victory():
    """12 s chip-tune fanfare in C major at 120 BPM with drums, clean ending."""
    rng = seed_for('music_victory')
    beat = 0.5
    secs = 12.0
    tr = Track(secs)
    melody = [(72, 0.5), (72, 0.5), (72, 0.5), (76, 1.5), (79, 0.5), (76, 0.5),
              (79, 1), (84, 1), (81, 0.5), (79, 0.5), (76, 0.5), (79, 0.5),
              (81, 1), (84, 1), (83, 0.5), (79, 0.5), (76, 0.5), (79, 0.5),
              (84, 0.5), (84, 0.5), (86, 0.5), (88, 1.5), (84, 1),
              (79, 1), (84, 1), (88, 2),
              (84, 4)]
    pos = 0.0
    for m, b in melody:
        last = (m, b) == (84, 4)
        x = synth_lead(midi_hz(m), beat * b * (1.0 if last else 0.92), 0.25)
        if last:
            x *= adsr(len(x), 0.01, 0.0, 1.0, 1.2)
        tr.add(x, pos * beat, 0.15, 0.22)
        tr.add(synth_lead(midi_hz(m - 12), beat * b * 0.9, 0.5) * (adsr(samples(beat * b * 0.9), 0.01, 0, 1, 1.0) if last else 1), pos * beat, -0.15, 0.09)
        pos += b
    chords = [(60, 64, 67), (65, 69, 72), (67, 71, 74), (60, 64, 67), (67, 71, 74), (60, 64, 67, 72)]
    for bar, ch in enumerate(chords):
        for k in range(4):
            if bar == 5:
                n = samples(beat * 4)
                env = adsr(n, 0.01, 0.0, 1.0, 1.2)
                if k:
                    break
            else:
                n = samples(beat * 0.45)
                env = adsr(n, 0.005, 0.05, 0.7, 0.05)
            for m in ch:
                tr.add(osc('square', midi_hz(m), n, duty=0.5) * env, (bar * 4 + k) * beat, -0.4 if m % 2 else 0.4, 0.06)
    roots = [36, 41, 43, 36, 43, 36]
    for bar, r in enumerate(roots):
        for k in range(8):
            if bar == 5 and k:
                break
            m = r + (12 if k % 2 else 0)
            n = samples(beat * (4 if bar == 5 else 0.45))
            env = adsr(n, 0.005, 0.1, 0.6, 1.0 if bar == 5 else 0.05)
            tr.add(osc('tri', midi_hz(m), n) * env, (bar * 4 + k * 0.5) * beat, 0, 0.3)
    for bar in range(6):
        base = bar * 4 * beat
        if bar == 5:
            tr.add(drum_kick(rng), base, 0, 0.5)
            tr.add(drum_hat(rng, open_=True), base, 0.3, 0.3)
            tr.add(highpass(white(samples(1.2), rng), 3000) * env_exp(samples(1.2), 0.35), base, -0.2, 0.25)
            break
        for k in (0, 2):
            tr.add(drum_kick(rng), base + k * beat, 0, 0.5)
        for k in (1, 3):
            tr.add(drum_snare(rng), base + k * beat, 0.1, 0.35)
        for k in range(8):
            tr.add(drum_hat(rng), base + k * beat / 2, 0.3, 0.12 if k % 2 == 0 else 0.07)
        if bar == 4:                                                             # fill
            for k in range(4):
                tr.add(drum_snare(rng), base + 3 * beat + k * beat / 4, 0.1, 0.3)
    return tr.finish(0.7, 15)


MUSIC_SPECS = [('menu', music_menu), ('intermission', music_intermission), ('boss', music_boss),
               ('hell', music_hell), ('victory', music_victory)]


def gen_music():
    for name, fn in MUSIC_SPECS:
        write_wav(('music', name + '.wav'), fn())


# ---------------------------------------------------------------------------
# 6. contact sheet, verification, CLI
# ---------------------------------------------------------------------------
def write_contact_sheet(path):
    """Every generated image on one labelled sheet (nearest-neighbour scaling)."""
    if not GENERATED_IMAGES:
        return
    font = pg.font.Font(None, 15)
    cell, box, cols = 150, 146, 8
    rows = (len(GENERATED_IMAGES) + cols - 1) // cols
    sheet = pg.Surface((cols * cell, rows * (cell + 18)))
    sheet.fill((40, 40, 60))
    for i, (label, p) in enumerate(GENERATED_IMAGES):
        img = pg.image.load(p).convert_alpha()
        w, h = img.get_size()
        if w <= box and h <= box:
            f = max(1, min(box // w, box // h))
            img = pg.transform.scale(img, (w * f, h * f))
        else:
            f = min(box / w, box / h)
            img = pg.transform.scale(img, (max(1, int(w * f)), max(1, int(h * f))))
        x, y = (i % cols) * cell + 2, (i // cols) * (cell + 18) + 2
        pg.draw.rect(sheet, (72, 72, 96), (x, y, box, box))
        sheet.blit(img, (x + (box - img.get_width()) // 2, y + (box - img.get_height()) // 2))
        sheet.blit(font.render(label, True, (230, 230, 230)), (x, y + box + 2))
    os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
    pg.image.save(sheet, path)
    print('contact sheet: %s (%d images)' % (path, len(GENERATED_IMAGES)))


def expected_images():
    """relative path -> (width, height) for every image this script produces."""
    e = {}
    for n in ('door', 'door_red', 'door_blue', 'door_yellow', 'exit_switch', 'exit_switch_on', '6', '7', '8', '9'):
        e['textures/%s.png' % n] = (256, 256)
    e['textures/sky_hell.png'] = e['textures/sky_night.png'] = (1200, 400)
    for n in ('stimpack', 'medikit', 'armor_green', 'armor_blue', 'bullets', 'bullets_box', 'shells', 'shells_box',
              'rockets', 'rockets_box', 'key_red', 'key_blue', 'key_yellow', 'backpack'):
        e['sprites/pickups/%s.png' % n] = (64, 64)
    for i in range(4):
        e['sprites/pickups/soulsphere/%d.png' % i] = (64, 64)
    for n in ('weapon_shotgun', 'weapon_chaingun', 'weapon_rocketlauncher'):
        e['sprites/pickups/%s.png' % n] = (96, 48)
    for i in range(2):
        e['sprites/decorations/barrel/%d.png' % i] = (64, 96)
    e['sprites/decorations/pillar.png'] = (64, 128)
    e['sprites/decorations/skulls.png'] = (64, 48)
    for i in range(3):
        e['sprites/projectiles/fireball/%d.png' % i] = (48, 48)
    for i in range(2):
        e['sprites/projectiles/rocket/%d.png' % i] = (48, 48)
    for i in range(6):
        e['sprites/projectiles/explosion/%d.png' % i] = (128, 128)
    for i in range(3):
        e['sprites/projectiles/blood/%d.png' % i] = (32, 32)
        e['sprites/projectiles/puff/%d.png' % i] = (32, 32)
    for w in ('pistol', 'chaingun', 'rocket_launcher'):
        for i in range(3):
            e['sprites/weapon/%s/%d.png' % (w, i)] = (970, 1050)
    return e


def expected_audio():
    """relative path -> (seconds, channels)."""
    e = {'sound/%s.wav' % n: (secs, 1) for n, secs, _ in SOUND_SPECS}
    e.update({'music/menu.wav': (40.0, 2), 'music/intermission.wav': (8 * 4 * 60 / 100, 2),
              'music/boss.wav': (18 * 4 * 60 / 140, 2), 'music/hell.wav': (12 * 4 * 60 / 90, 2),
              'music/victory.wav': (12.0, 2)})
    return e


FAMILY_OF = {'textures': 'textures', 'sprites': 'sprites', 'sound': 'sounds', 'music': 'music'}


def verify(families):
    """Assert every expected file of the generated families exists with the
    exact size / format, print a table and exit 1 on any mismatch."""
    rows = []
    ok = True
    for rel, (w, h) in expected_images().items():
        if FAMILY_OF[rel.split('/')[0]] not in families:
            continue
        path = os.path.join(RES_DIR, rel)
        if not os.path.exists(path):
            rows.append((rel, '%dx%d' % (w, h), '-', 'MISSING', 0))
            ok = False
            continue
        img = pg.image.load(path)
        fmt = 'RGBA' if (img.get_bitsize() == 32 and img.get_flags() & pg.SRCALPHA) else 'RGB'
        good = img.get_size() == (w, h) and (fmt == 'RGBA' or not rel.startswith('sprites/'))
        rows.append((rel, '%dx%d' % (w, h), '%dx%d %s' % (img.get_width(), img.get_height(), fmt), 'ok' if good else 'BAD', os.path.getsize(path)))
        ok &= good
    for rel, (secs, ch) in expected_audio().items():
        if FAMILY_OF[rel.split('/')[0]] not in families:
            continue
        path = os.path.join(RES_DIR, rel)
        if not os.path.exists(path):
            rows.append((rel, '%.2fs %dch' % (secs, ch), '-', 'MISSING', 0))
            ok = False
            continue
        with wave.open(path, 'rb') as wv:
            dur = wv.getnframes() / wv.getframerate()
            got = '%.2fs %dch %dbit %dHz' % (dur, wv.getnchannels(), wv.getsampwidth() * 8, wv.getframerate())
            good = abs(dur - secs) < 0.02 and wv.getnchannels() == ch and wv.getsampwidth() == 2 and wv.getframerate() == SR
        rows.append((rel, '%.2fs %dch' % (secs, ch), got, 'ok' if good else 'BAD', os.path.getsize(path)))
        ok &= good
    width = max(len(r[0]) for r in rows) + 2
    print('\n%-*s %-14s %-26s %-8s %s' % (width, 'file (resources/)', 'expected', 'actual', 'status', 'bytes'))
    total = 0
    for rel, exp, got, status, size in rows:
        total += size
        print('%-*s %-14s %-26s %-8s %d' % (width, rel, exp, got, status, size))
    print('%d files, %.1f MB total, %s' % (len(rows), total / 1e6, 'all OK' if ok else 'PROBLEMS FOUND'))
    if not ok:
        sys.exit(1)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Procedurally generate KnotzDoom art, sound and music assets.')
    ap.add_argument('--only', choices=['textures', 'sprites', 'sounds', 'music'],
                    help='generate only this asset family (default: everything)')
    ap.add_argument('--contact-sheet', metavar='PATH',
                    help='additionally write a labelled contact sheet PNG of every generated image')
    args = ap.parse_args(argv)
    families = [args.only] if args.only else ['textures', 'sprites', 'sounds', 'music']
    gens = {'textures': gen_textures, 'sprites': gen_sprites, 'sounds': gen_sounds, 'music': gen_music}
    t0 = time.time()
    for fam in families:
        t1 = time.time()
        gens[fam]()
        print('generated %-8s in %5.1fs' % (fam, time.time() - t1))
    if args.contact_sheet:
        write_contact_sheet(args.contact_sheet)
    verify(families)
    print('finished in %.1fs' % (time.time() - t0))


if __name__ == '__main__':
    main()
