"""The slowly rotating 3D view of the first level drawn behind the menus."""
import math

import pygame as pg

from ..renderer import Renderer
from ..settings import HEIGHT, WIDTH
from ..world import World
from .menu import draw_dim


def build_texture_background(game, tex_id):
    """A screen sized surface tiled with a darkened wall texture."""
    try:
        tex = game.assets.wall_texture(int(tex_id), 6)
    except (ValueError, KeyError):
        tex = game.assets.wall_texture(1, 6)
    bg = pg.Surface((WIDTH, HEIGHT))
    size = tex.get_width()
    for y in range(0, HEIGHT, size):
        for x in range(0, WIDTH, size):
            bg.blit(tex, (x, y))
    return bg


class DemoBackground:
    def __init__(self, game):
        self.game = game
        self.world = None
        self.angle = 0.0
        try:
            self.world = World(game, game.level_data(0), difficulty_index=1)
            self.renderer = Renderer(game, self.world, divisor=2)     # menus never need full detail
            self.cam = self.world.player
        except Exception as exc:      # the menus must work even without levels
            print('demo background unavailable:', exc)
            self.world = None

    def update(self, dt):
        if self.world is None:
            return
        self.angle += dt * 0.00025
        self.cam.angle = self.angle % math.tau
        self.cam.cam_h = 0.5
        for prop in self.world.objects.props:
            prop.update(dt)
        for pickup in self.world.objects.pickups:
            pickup.anim.update(dt)
            pickup.image = pickup.anim.image

    def draw(self, screen):
        if self.world is None:
            screen.fill((12, 8, 8))
            return
        self.renderer.render(self.cam)
        self.renderer.present()
        draw_dim(screen, 120)
