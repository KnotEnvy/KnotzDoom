"""Grid raycaster.

For every screen column a ray is stepped across the horizontal and the vertical
grid lines separately (the classic Wolfenstein / Lode Vandevenne approach) and
the nearest hit wins.  Doors are thin slabs in the middle of their tile that
slide sideways: the slab is checked at the midpoint between two grid line
crossings, which is exactly where a ray crosses the centre line of the tile.

The result of a cast is:
    results[ray] = (depth, projected height, texture id, texture u offset, vertical)
    depth[ray]   = numpy float32 depth buffer used to clip sprites
"""
import math

import numpy as np

from .settings import HALF_FOV, MAX_DEPTH


class RayCaster:
    def __init__(self, world, view):
        self.world = world
        self.view = view
        self.results = [(MAX_DEPTH, 1.0, 1, 0.0, False)] * view.num_rays
        self.depth = np.full(view.num_rays, float(MAX_DEPTH), dtype=np.float32)

    def cast(self, cam):
        walls = self.world.walls
        doors_h = self.world.doors_h
        doors_v = self.world.doors_v
        seen = self.world.seen_tiles
        results = self.results
        depth_buf = self.depth
        view = self.view
        num_rays = view.num_rays
        delta_angle = view.delta_angle
        screen_dist = view.screen_dist
        max_proj_height = view.max_proj_height
        sin = math.sin
        cos = math.cos
        inf = float('inf')

        ox, oy = cam.x, cam.y
        x_map, y_map = int(ox), int(oy)
        ray_angle = cam.angle - HALF_FOV + 0.0001
        cam_angle = cam.angle

        for ray in range(num_rays):
            sin_a = sin(ray_angle)
            cos_a = cos(ray_angle)
            if sin_a == 0:
                sin_a = 1e-9
            if cos_a == 0:
                cos_a = 1e-9

            # ---------------------------------------------- horizontal grid lines
            texture_hor = 1
            offset_hor = 0.0
            hit_tile_hor = None
            y_hor, dy = (y_map + 1, 1) if sin_a > 0 else (y_map - 1e-6, -1)
            depth_hor = (y_hor - oy) / sin_a
            x_hor = ox + depth_hor * cos_a
            delta_depth = dy / sin_a
            dx = delta_depth * cos_a
            for _ in range(MAX_DEPTH):
                tile_hor = int(x_hor), int(y_hor)
                tex = walls.get(tile_hor)
                if tex is not None:
                    texture_hor = tex
                    hit_tile_hor = tile_hor
                    x_hor %= 1
                    offset_hor = (1 - x_hor) if sin_a > 0 else x_hor
                    break
                if doors_h:
                    x_mid = x_hor + dx * 0.5
                    tile_mid = int(x_mid), int(y_hor + dy * 0.5)
                    door = doors_h.get(tile_mid)
                    if door is not None:
                        frac = x_mid - tile_mid[0]
                        if frac < 1.0 - door.open:
                            depth_hor += delta_depth * 0.5
                            texture_hor = door.texture
                            hit_tile_hor = tile_mid
                            u = min(0.999, frac + door.open)
                            offset_hor = (1 - u) if sin_a > 0 else u
                            break
                x_hor += dx
                y_hor += dy
                depth_hor += delta_depth
            else:
                depth_hor = inf

            # ---------------------------------------------- vertical grid lines
            texture_vert = 1
            offset_vert = 0.0
            hit_tile_vert = None
            x_vert, dx = (x_map + 1, 1) if cos_a > 0 else (x_map - 1e-6, -1)
            depth_vert = (x_vert - ox) / cos_a
            y_vert = oy + depth_vert * sin_a
            delta_depth = dx / cos_a
            dy = delta_depth * sin_a
            for _ in range(MAX_DEPTH):
                tile_vert = int(x_vert), int(y_vert)
                tex = walls.get(tile_vert)
                if tex is not None:
                    texture_vert = tex
                    hit_tile_vert = tile_vert
                    y_vert %= 1
                    offset_vert = y_vert if cos_a > 0 else (1 - y_vert)
                    break
                if doors_v:
                    y_mid = y_vert + dy * 0.5
                    tile_mid = int(x_vert + dx * 0.5), int(y_mid)
                    door = doors_v.get(tile_mid)
                    if door is not None:
                        frac = y_mid - tile_mid[1]
                        if frac < 1.0 - door.open:
                            depth_vert += delta_depth * 0.5
                            texture_vert = door.texture
                            hit_tile_vert = tile_mid
                            u = min(0.999, frac + door.open)
                            offset_vert = u if cos_a > 0 else (1 - u)
                            break
                x_vert += dx
                y_vert += dy
                depth_vert += delta_depth
            else:
                depth_vert = inf

            # ---------------------------------------------- nearest hit
            if depth_vert < depth_hor:
                depth, texture, offset, vertical, tile = depth_vert, texture_vert, offset_vert, True, hit_tile_vert
            else:
                depth, texture, offset, vertical, tile = depth_hor, texture_hor, offset_hor, False, hit_tile_hor
            if tile is not None:
                seen.add(tile)
            if depth == inf:
                depth = MAX_DEPTH

            # remove the fishbowl effect
            depth *= cos(cam_angle - ray_angle)
            if depth < 1e-4:
                depth = 1e-4
            proj_height = screen_dist / depth
            if proj_height > max_proj_height:
                proj_height = max_proj_height

            results[ray] = (depth, proj_height, texture, offset, vertical)
            depth_buf[ray] = depth
            ray_angle += delta_angle


def cast_single_ray(world, ox, oy, angle, max_depth=MAX_DEPTH, door_open_threshold=0.5):
    """Distance from (ox, oy) along ``angle`` to the first blocking tile.

    Used for line of sight and hitscan checks.  Doors count as blocking while
    they are less than ``door_open_threshold`` open.  Returns ``max_depth`` if
    nothing is hit.
    """
    walls = world.walls
    doors = world.doors
    sin_a = math.sin(angle) or 1e-9
    cos_a = math.cos(angle) or 1e-9
    x_map, y_map = int(ox), int(oy)

    def blocked(tile):
        if tile in walls:
            return True
        door = doors.get(tile)
        return door is not None and door.open < door_open_threshold

    y_hor, dy = (y_map + 1, 1) if sin_a > 0 else (y_map - 1e-6, -1)
    depth_hor = (y_hor - oy) / sin_a
    x_hor = ox + depth_hor * cos_a
    delta_depth = dy / sin_a
    dx = delta_depth * cos_a
    for _ in range(max_depth):
        if blocked((int(x_hor), int(y_hor))):
            break
        x_hor += dx
        y_hor += dy
        depth_hor += delta_depth
    else:
        depth_hor = max_depth

    x_vert, dx = (x_map + 1, 1) if cos_a > 0 else (x_map - 1e-6, -1)
    depth_vert = (x_vert - ox) / cos_a
    y_vert = oy + depth_vert * sin_a
    delta_depth = dx / cos_a
    dy = delta_depth * sin_a
    for _ in range(max_depth):
        if blocked((int(x_vert), int(y_vert))):
            break
        x_vert += dx
        y_vert += dy
        depth_vert += delta_depth
    else:
        depth_vert = max_depth

    return min(depth_hor, depth_vert, max_depth)


def line_of_sight(world, ax, ay, bx, by):
    """True when nothing solid lies between the two points."""
    dist = math.hypot(bx - ax, by - ay)
    if dist < 1e-6:
        return True
    angle = math.atan2(by - ay, bx - ax)
    return cast_single_ray(world, ax, ay, angle, max_depth=int(dist) + 2) >= dist
