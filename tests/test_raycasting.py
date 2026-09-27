"""Raycaster geometry, including sliding door slabs."""
import math

import numpy as np

import pygame as pg

from knotzdoom.raycasting import RayCaster, cast_single_ray, line_of_sight
from knotzdoom.settings import RES, WIDTH

HALF_NUM_RAYS = WIDTH // 4
from knotzdoom.view import View


def make_caster(world, divisor=1):
    return RayCaster(world, View(pg.Surface(RES), divisor))


class FakeDoor:
    def __init__(self, x, y, vertical, open_=0.0, locked=None):
        self.x, self.y, self.vertical, self.open, self.locked = x, y, vertical, open_, locked
        self.texture = 10


class FakeWorld:
    """A 12x8 room with a vertical door slab at tile (6, 3)."""

    def __init__(self, door_open=0.0):
        self.walls = {}
        for x in range(12):
            self.walls[(x, 0)] = 1
            self.walls[(x, 7)] = 1
        for y in range(8):
            self.walls[(0, y)] = 1
            self.walls[(11, y)] = 1
        for y in range(1, 7):
            if y != 3:
                self.walls[(6, y)] = 2
        door = FakeDoor(6, 3, vertical=True, open_=door_open)
        self.doors = {(6, 3): door}
        self.doors_v = {(6, 3): door}
        self.doors_h = {}
        self.seen_tiles = set()


class Cam:
    def __init__(self, x, y, angle):
        self.x, self.y, self.angle, self.cam_h = x, y, angle, 0.5


def center_depth(world, cam):
    caster = make_caster(world)
    caster.cast(cam)
    return float(caster.depth[HALF_NUM_RAYS]), caster.results[HALF_NUM_RAYS]


def test_closed_door_blocks_center_ray():
    world = FakeWorld(door_open=0.0)
    depth, result = center_depth(world, Cam(2.5, 3.5, 0.0))
    assert abs(depth - 4.0) < 0.05          # slab sits at x = 6.5
    assert result[2] == 10                  # door texture
    assert (6, 3) in world.seen_tiles


def test_open_door_lets_ray_through():
    world = FakeWorld(door_open=1.0)
    depth, result = center_depth(world, Cam(2.5, 3.5, 0.0))
    assert abs(depth - 8.5) < 0.05          # far wall at x = 11
    assert result[2] == 1


def test_half_open_door_reveals_half_the_doorway():
    # camera looking through the doorway from an angle: rays hitting the part
    # of the slab that slid away pass through, the rest is blocked.
    world = FakeWorld(door_open=0.5)
    caster = make_caster(world)
    caster.cast(Cam(5.0, 3.5, 0.0))
    depths = caster.depth
    assert depths.min() < 2.0               # some rays hit the slab (x = 6.5)
    assert depths.max() > 5.0               # some rays pass to the far wall


def test_walls_are_hit_correctly():
    world = FakeWorld()
    depth, result = center_depth(world, Cam(2.5, 3.5, math.pi))   # looking west
    assert abs(depth - 1.5) < 0.05
    assert result[4] is True                # vertical grid line hit


def test_depth_buffer_is_finite_everywhere():
    world = FakeWorld()
    caster = make_caster(world)
    caster.cast(Cam(2.5, 2.5, 0.7))
    assert np.all(np.isfinite(caster.depth))
    assert caster.depth.min() > 0


def test_low_detail_casts_half_the_rays_with_the_same_geometry():
    world = FakeWorld(door_open=0.0)
    high = make_caster(world, 1)
    low = make_caster(world, 2)
    cam = Cam(2.5, 3.5, 0.0)
    high.cast(cam)
    low.cast(cam)
    assert len(low.results) == len(high.results) // 2
    assert abs(float(low.depth[len(low.depth) // 2]) - float(high.depth[len(high.depth) // 2])) < 0.02


def test_single_ray_and_line_of_sight():
    world = FakeWorld(door_open=0.0)
    assert abs(cast_single_ray(world, 2.5, 3.5, 0.0) - 3.5) < 0.05   # closed door tile at x = 6
    world.doors[(6, 3)].open = 1.0
    assert abs(cast_single_ray(world, 2.5, 3.5, 0.0) - 8.5) < 0.05
    assert line_of_sight(world, 2.5, 3.5, 9.5, 3.5)
    assert not line_of_sight(world, 2.5, 2.5, 9.5, 2.5)               # wall segment at (6, 2)
