"""Drawing the 3D view: sky, floor, walls and billboard sprites.

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
from .settings import (FOV, HALF_HEIGHT, HEIGHT, NUM_RAYS, SCALE, SHADE_LEVELS, TEXTURE_SIZE,
                       WIDTH)


class Renderer:
    def __init__(self, game, world):
        self.game = game
        self.screen = game.screen
        self.assets = game.assets
        self.world = world
        self.raycaster = RayCaster(world)
        self.sky = self.assets.sky(world.level.sky)
        self.floor = self.make_floor(world.level.floor_color)
        self.sprite_requests = []
        self.light = 0                       # extra brightness levels (muzzle flash)
        self._overlay_cache = {}

    # ------------------------------------------------------------ setup
    @staticmethod
    def make_floor(color):
        """Vertical gradient: dark at the horizon, the level's colour up close."""
        floor = pg.Surface((WIDTH, HALF_HEIGHT))
        r, g, b = color
        rows = HALF_HEIGHT
        for y in range(rows):
            t = y / max(1, rows - 1)
            k = 0.12 + 0.88 * (t ** 1.6)
            pg.draw.line(floor, (int(r * k), int(g * k), int(b * k)), (0, y), (WIDTH, y))
        return floor

    # ------------------------------------------------------------ frame
    def render(self, cam):
        self.raycaster.cast(cam)
        self.draw_background(cam)
        self.draw_walls(cam)
        self.sprite_requests = []
        for sprite in self.world.drawable_sprites():
            sprite.project(cam, self)
        self.draw_sprites()

    def draw_background(self, cam):
        offset = int((cam.angle * WIDTH / FOV) % WIDTH)
        self.screen.blit(self.sky, (-offset, 0))
        self.screen.blit(self.sky, (WIDTH - offset, 0))
        self.screen.blit(self.floor, (0, HALF_HEIGHT))

    def draw_walls(self, cam):
        screen = self.screen
        wall_texture = self.assets.wall_texture
        light = self.light
        cam_h = cam.cam_h
        horizon = HALF_HEIGHT
        tex_span = TEXTURE_SIZE - SCALE
        scale = pg.transform.scale
        blit = screen.blit
        for ray, (depth, proj_height, tex_id, offset, vertical) in enumerate(self.raycaster.results):
            level = shade_level(depth, light)
            if vertical and level < SHADE_LEVELS - 1:
                level += 1
            texture = wall_texture(tex_id, level)
            u = int(offset * tex_span)
            y0 = horizon - proj_height * (1.0 - cam_h)
            y1 = y0 + proj_height
            if y0 >= 0 and y1 <= HEIGHT:
                column = texture.subsurface(u, 0, SCALE, TEXTURE_SIZE)
                column = scale(column, (SCALE, int(proj_height)))
                blit(column, (ray * SCALE, int(y0)))
            else:
                top = 0.0 if y0 < 0 else y0
                bottom = float(HEIGHT) if y1 > HEIGHT else y1
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
                column = texture.subsurface(u, tv0, SCALE, tv1 - tv0)
                column = scale(column, (SCALE, int(bottom - top)))
                blit(column, (ray * SCALE, int(top)))

    # ------------------------------------------------------------ sprites
    def add_sprite(self, depth, image, left, top, width, height, bright=False):
        self.sprite_requests.append((depth, image, left, top, width, height, bright))

    def draw_sprites(self):
        depth_buf = self.raycaster.depth
        screen = self.screen
        light = self.light
        for depth, image, left, top, width, height, bright in sorted(
                self.sprite_requests, key=lambda r: r[0], reverse=True):
            vx0 = int(left) if left > 0 else 0
            vx1 = int(left + width) if left + width < WIDTH else WIDTH
            vy0 = int(top) if top > 0 else 0
            vy1 = int(top + height) if top + height < HEIGHT else HEIGHT
            if vx1 <= vx0 or vy1 <= vy0:
                continue
            c0 = vx0 // SCALE
            c1 = (vx1 - 1) // SCALE + 1
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
                screen.blit(scaled, (vx0, vy0))
                continue
            edges = np.diff(np.concatenate(([0], vis.view(np.int8), [0])))
            starts = np.flatnonzero(edges == 1)
            ends = np.flatnonzero(edges == -1)
            h = vy1 - vy0
            for a, b in zip(starts, ends):
                px0 = max(vx0, (c0 + int(a)) * SCALE)
                px1 = min(vx1, (c0 + int(b)) * SCALE)
                if px1 <= px0:
                    continue
                screen.blit(scaled.subsurface((px0 - vx0, 0, px1 - px0, h)), (px0, vy0))

    # ------------------------------------------------------------ effects
    def overlay(self, color, alpha):
        """Tint the whole screen (damage flash, pickup flash, death fade)."""
        alpha = int(max(0, min(255, alpha)))
        if alpha <= 0:
            return
        key = tuple(color)
        surf = self._overlay_cache.get(key)
        if surf is None:
            surf = pg.Surface((WIDTH, HEIGHT))
            surf.fill(color)
            self._overlay_cache[key] = surf
        surf.set_alpha(alpha)
        self.screen.blit(surf, (0, 0))

    def shake(self, dx, dy):
        if not dx and not dy:
            return
        self.screen.scroll(dx, dy)
        if dx > 0:
            self.screen.fill((0, 0, 0), (0, 0, dx, HEIGHT))
        elif dx < 0:
            self.screen.fill((0, 0, 0), (WIDTH + dx, 0, -dx, HEIGHT))
        if dy > 0:
            self.screen.fill((0, 0, 0), (0, 0, WIDTH, dy))
        elif dy < 0:
            self.screen.fill((0, 0, 0), (0, HEIGHT + dy, WIDTH, -dy))

    def set_level(self, world):
        self.world = world
        self.raycaster = RayCaster(world)
        self.sky = self.assets.sky(world.level.sky)
        self.floor = self.make_floor(world.level.floor_color)
