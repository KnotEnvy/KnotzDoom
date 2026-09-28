"""Grid raycaster: one DDA walk per ray over a flat cell list.

``walk`` steps a single ray from cell to cell (Amanatides-Woo / Lode style)
until it meets a wall or the closed part of a door slab.  Doors are thin slabs
on the centre line of their tile that slide sideways as they open.  The same
walk serves the per-frame renderer, line of sight checks and hitscan weapons,
so what you see, what monsters see and what your bullets hit all agree.

Ray directions are spaced by the tangent of the column position (as Doom's
lookup table did), which keeps straight walls straight.  The result of a cast
is:
    results[ray] = (depth, projected height, texture id, texture u, x_side)
    depth[ray]   = numpy float32 depth buffer used to clip sprites
"""
import math

import numpy as np

from .settings import MAX_DEPTH

NO_HIT = (MAX_DEPTH, 0, 0.0, False, -1)


def walk(cells, cols, doors, ox, oy, angle, max_dist=MAX_DEPTH):
    """Trace one ray. Returns ``(distance, texture, u, x_side, cell)``.

    ``texture`` is 0 and ``cell`` is -1 when nothing is hit within
    ``max_dist``.  ``x_side`` is True when the ray crossed a vertical grid
    line (or a north-south door slab); ``u`` is the texture column in 0..1.
    The caller guarantees the origin lies inside a grid whose border is solid.
    """
    c = math.cos(angle) or 1e-9
    s = math.sin(angle) or 1e-9
    cx, cy = int(ox), int(oy)
    fx, fy = ox - cx, oy - cy
    if c > 0:
        stx, ddx = 1, 1.0 / c
        sdx = (1.0 - fx) * ddx
    else:
        stx, ddx = -1, -1.0 / c
        sdx = fx * ddx
    if s > 0:
        sty, ddy = 1, 1.0 / s
        sdy = (1.0 - fy) * ddy
    else:
        sty, ddy = -1, -1.0 / s
        sdy = fy * ddy

    cell = cy * cols + cx
    v = cells[cell]
    if v < 0:                                   # standing inside a door tile: test its slab first
        hit = _slab(doors[-v - 1], cx, cy, ox, oy, c, s, cell)
        if hit is not None and hit[0] > 0.0:
            return hit
    while True:
        if sdx < sdy:
            t_in = sdx
            x_side = True
            sdx += ddx
            cx += stx
        else:
            t_in = sdy
            x_side = False
            sdy += ddy
            cy += sty
        if t_in > max_dist:
            return NO_HIT
        cell = cy * cols + cx
        v = cells[cell]
        if v > 0:                               # wall: hit where the ray entered the cell
            if x_side:
                f = oy + t_in * s
                f -= int(f)
                u = f if c > 0 else 1.0 - f
            else:
                f = ox + t_in * c
                f -= int(f)
                u = 1.0 - f if s > 0 else f
            return (t_in, v, u, x_side, cell)
        if v < 0:
            hit = _slab(doors[-v - 1], cx, cy, ox, oy, c, s, cell)
            if hit is not None:
                return hit


def _slab(door, cx, cy, ox, oy, c, s, cell):
    """Intersect the ray with the door slab on the tile's centre line."""
    if door.vertical:
        t = (cx + 0.5 - ox) / c
        fr = oy + t * s - cy
    else:
        t = (cy + 0.5 - oy) / s
        fr = ox + t * c - cx
    if 0.0 <= fr < 1.0 - door.open:
        uu = min(0.999, fr + door.open)
        if door.vertical:
            u = uu if c > 0 else 1.0 - uu
        else:
            u = 1.0 - uu if s > 0 else uu
        return (t, door.texture, u, door.vertical, cell)
    return None


class RayCaster:
    def __init__(self, world, view):
        self.world = world
        self.view = view
        n = view.num_rays
        # tangent spaced column directions: column i covers [i*col, (i+1)*col) pixels
        self.offsets = [math.atan(((i + 0.5) * view.column - view.half_width) / view.screen_dist)
                        for i in range(n)]
        self.fish = [math.cos(o) for o in self.offsets]      # fisheye correction
        self.results = [(MAX_DEPTH, 1.0, 1, 0.0, False)] * n
        self.depth = np.full(n, float(MAX_DEPTH), dtype=np.float32)

    def cast(self, cam):
        world = self.world
        view = self.view
        cells, cols, doors = world.cells, world.cols, world.door_list
        results = self.results
        screen_dist, max_proj = view.screen_dist, view.max_proj_height
        ox, oy, angle = cam.x, cam.y, cam.angle
        if not world.inside(ox, oy):                          # noclip outside the map: only sky
            for i in range(len(results)):
                results[i] = (MAX_DEPTH, screen_dist / MAX_DEPTH, 1, 0.0, False)
            self.depth[:] = MAX_DEPTH
            return
        hits = set()
        depths = []
        append = depths.append
        for i, off in enumerate(self.offsets):
            t, tex, u, x_side, cell = walk(cells, cols, doors, ox, oy, angle + off)
            if cell >= 0:
                hits.add(cell)
            depth = t * self.fish[i]
            if depth < 1e-4:
                depth = 1e-4
            proj = screen_dist / depth
            results[i] = (depth, proj if proj < max_proj else max_proj, tex or 1, u, x_side)
            append(depth)
        self.depth[:] = depths
        world.seen_tiles.update((h % cols, h // cols) for h in hits)


def trace(world, ox, oy, angle, max_dist=MAX_DEPTH):
    """Distance from (ox, oy) along ``angle`` to the first wall or closed door
    part; ``max_dist`` when nothing is hit."""
    if not world.inside(ox, oy):
        return 0.0
    return walk(world.cells, world.cols, world.door_list, ox, oy, angle, max_dist)[0]


def line_of_sight(world, ax, ay, bx, by):
    """True when nothing solid lies between the two points."""
    dist = math.hypot(bx - ax, by - ay)
    if dist < 1e-6:
        return True
    return trace(world, ax, ay, math.atan2(by - ay, bx - ax), dist) >= dist
