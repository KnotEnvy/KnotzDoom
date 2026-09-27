"""Drawing the 3D view: sky, floor, walls and billboard sprites.

Everything is drawn into ``self.view.surface`` (the window itself at high
detail, a half size surface at low detail that ``present`` scales up).
Walls come straight from the raycaster.  Sprites are collected as draw
requests during ``project``, sorted far-to-near and clipped column by column
against the depth buffer so an enemy peeking around a corner is cut off by the
wall exactly where it should be.
"""
import math

import numpy as np
import pygame as pg

from .assets import shade_brightness, shade_level
from .raycasting import RayCaster
from .settings import FOV, SHADE_LEVELS, TEXTURE_SIZE
from .view import View


class Renderer:
    def __init__(self, game, world):
        self.game = game
        self.screen = game.screen
        self.assets = game.assets
        self.world = world
        self.light = 0                       # extra brightness levels (muzzle flash)
        self._overlay_cache = {}
        self.view = None
        self.set_detail(game.detail.divisor)

    # ------------------------------------------------------------ setup
    def set_detail(self, divisor):
        """(Re)build the view surface and everything sized by it."""
        if self.view is not None and self.view.divisor == divisor:
            return
        self.view = View(self.screen, divisor)
        self.raycaster = RayCaster(self.world, self.view)
        self.sky = self.assets.sky(self.world.level.sky, (self.view.width, self.view.half_height))
        self.floor = self.make_floor(self.world.level.floor_color, self.view.width, self.view.half_height)
        self._overlay_cache = {}

    @staticmethod
    def make_floor(color, width, height):
        """Vertical gradient: dark at the horizon, the level's colour up close."""
        floor = pg.Surface((width, height))
        r, g, b = color
        for y in range(height):
            t = y / max(1, height - 1)
            k = 0.12 + 0.88 * (t ** 1.6)
            pg.draw.line(floor, (int(r * k), int(g * k), int(b * k)), (0, y), (width, y))
        return floor

    # ------------------------------------------------------------ frame
    def render(self, cam):
        self.set_detail(self.game.detail.divisor)
        self.raycaster.cast(cam)
        self.draw_background(cam)
        self.draw_walls(cam)
        self.sprite_requests = []
        for sprite in self.world.drawable_sprites():
            sprite.project(cam, self)
        self.draw_sprites()

    def present(self):
        self.view.present()

    def draw_background(self, cam):
        view = self.view
        offset = int((cam.angle * view.width / FOV) % view.width)
        surface = view.surface
        surface.blit(self.sky, (-offset, 0))
        surface.blit(self.sky, (view.width - offset, 0))
        surface.blit(self.floor, (0, view.half_height))

    def draw_walls(self, cam):
        view = self.view
        wall_texture = self.assets.wall_texture
        light = self.light
        cam_h = cam.cam_h
        horizon = view.half_height
        height = view.height
        column_w = view.column
        tex_span = TEXTURE_SIZE - column_w
        scale = pg.transform.scale
        blit = view.surface.blit
        darkest = SHADE_LEVELS - 1
        for ray, (depth, proj_height, tex_id, offset, vertical) in enumerate(self.raycaster.results):
            level = shade_level(depth, light)
            if vertical and level < darkest:
                level += 1
            texture = wall_texture(tex_id, level)
            u = int(offset * tex_span)
            y0 = horizon - proj_height * (1.0 - cam_h)
            y1 = y0 + proj_height
            if y0 >= 0 and y1 <= height:
                column = scale(texture.subsurface(u, 0, column_w, TEXTURE_SIZE), (column_w, int(proj_height)))
                blit(column, (ray * column_w, int(y0)))
            else:
                top = 0.0 if y0 < 0 else y0
                bottom = float(height) if y1 > height else y1
                if bottom - top < 1:
                    continue
                v0 = (top - y0) / proj_height * TEXTURE_SIZE
                v1 = (bottom - y0) / proj_height * TEXTURE_SIZE
                tv0 = int(v0)
                tv1 = int(math.ceil(v1))
                if tv0 >= TEXTURE_SIZE:
                    tv0 = TEXTURE_SIZE - 1
                if tv1 <= tv0:
                    tv1 = tv0 + 1
                if tv1 > TEXTURE_SIZE:
                    tv1 = TEXTURE_SIZE
                column = scale(texture.subsurface(u, tv0, column_w, tv1 - tv0), (column_w, int(bottom - top)))
                blit(column, (ray * column_w, int(top)))

    # ------------------------------------------------------------ sprites
    def add_sprite(self, depth, image, left, top, width, height, bright=False):
        self.sprite_requests.append((depth, image, left, top, width, height, bright))

    def draw_sprites(self):
        view = self.view
        depth_buf = self.raycaster.depth
        surface = view.surface
        light = self.light
        vw, vh, column_w = view.width, view.height, view.column
        for depth, image, left, top, width, height, bright in sorted(
                self.sprite_requests, key=lambda r: r[0], reverse=True):
            vx0 = int(left) if left > 0 else 0
            vx1 = int(left + width) if left + width < vw else vw
            vy0 = int(top) if top > 0 else 0
            vy1 = int(top + height) if top + height < vh else vh
            if vx1 <= vx0 or vy1 <= vy0:
                continue
            c0 = vx0 // column_w
            c1 = (vx1 - 1) // column_w + 1
            vis = depth_buf[c0:c1] > depth
            if not vis.any():
                continue
            iw, ih = image.get_size()
            if vx0 == int(left) and vx1 == int(left + width) and vy0 == int(top) and vy1 == int(top + height):
                sub = image
            else:
                sx0 = int((vx0 - left) / width * iw)
                sx1 = int(math.ceil((vx1 - left) / width * iw))
                sy0 = int((vy0 - top) / height * ih)
                sy1 = int(math.ceil((vy1 - top) / height * ih))
                sx0 = max(0, min(iw - 1, sx0))
                sy0 = max(0, min(ih - 1, sy0))
                sx1 = max(sx0 + 1, min(iw, sx1))
                sy1 = max(sy0 + 1, min(ih, sy1))
                sub = image.subsurface((sx0, sy0, sx1 - sx0, sy1 - sy0))
            scaled = pg.transform.scale(sub, (vx1 - vx0, vy1 - vy0))
            if not bright:
                level = shade_level(depth, light)
                if level > 0:
                    k = int(255 * shade_brightness(level))
                    scaled.fill((k, k, k), special_flags=pg.BLEND_RGB_MULT)
            if vis.all():
                surface.blit(scaled, (vx0, vy0))
                continue
            edges = np.diff(np.concatenate(([0], vis.view(np.int8), [0])))
            starts = np.flatnonzero(edges == 1)
            ends = np.flatnonzero(edges == -1)
            h = vy1 - vy0
            for a, b in zip(starts, ends):
                px0 = max(vx0, (c0 + int(a)) * column_w)
                px1 = min(vx1, (c0 + int(b)) * column_w)
                if px1 <= px0:
                    continue
                surface.blit(scaled.subsurface((px0 - vx0, 0, px1 - px0, h)), (px0, vy0))

    # ------------------------------------------------------------ effects
    def overlay(self, color, alpha, target=None):
        """Tint the view (or ``target``) with a colour: damage, pickup, death, fades."""
        alpha = int(max(0, min(255, alpha)))
        if alpha <= 0:
            return
        target = target or self.view.surface
        key = (tuple(color), target.get_size())
        surf = self._overlay_cache.get(key)
        if surf is None:
            surf = pg.Surface(target.get_size())
            surf.fill(color)
            self._overlay_cache[key] = surf
        surf.set_alpha(alpha)
        target.blit(surf, (0, 0))

    def screen_overlay(self, color, alpha):
        self.overlay(color, alpha, target=self.screen)

    def shake(self, dx, dy):
        if not dx and not dy:
            return
        surface = self.view.surface
        w, h = surface.get_size()
        surface.scroll(dx, dy)
        if dx > 0:
            surface.fill((0, 0, 0), (0, 0, dx, h))
        elif dx < 0:
            surface.fill((0, 0, 0), (w + dx, 0, -dx, h))
        if dy > 0:
            surface.fill((0, 0, 0), (0, 0, w, dy))
        elif dy < 0:
            surface.fill((0, 0, 0), (0, h + dy, w, -dy))
