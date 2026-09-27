"""Billboard sprites: static props, animated props and short lived particles.

Every sprite lives at a world position (x, y) plus a height ``z`` above the
floor (in wall-height units) and is drawn with a height of ``scale`` wall
heights.  Projection is handled by ``project`` which hands the renderer a draw
request; the renderer sorts and clips against the wall depth buffer.
"""
import math



class Animation:
    """A list of frames played at ``frame_time`` ms per frame."""

    def __init__(self, frames, frame_time=120, loop=True):
        self.frames = frames
        self.frame_time = frame_time
        self.loop = loop
        self.index = 0
        self.timer = 0.0
        self.done = False

    def reset(self):
        self.index = 0
        self.timer = 0.0
        self.done = False

    def update(self, dt):
        if self.done:
            return
        self.timer += dt
        while self.timer >= self.frame_time:
            self.timer -= self.frame_time
            self.index += 1
            if self.index >= len(self.frames):
                if self.loop:
                    self.index = 0
                else:
                    self.index = len(self.frames) - 1
                    self.done = True
                    break

    @property
    def image(self):
        return self.frames[self.index]


class SpriteObject:
    """A billboard drawn at a world position."""

    bright = False           # ignore distance shading (fire, glowing things)

    def __init__(self, world, image, pos, scale=0.7, z=0.0):
        self.world = world
        self.x, self.y = pos
        self.image = image
        self.scale = scale
        self.z = z
        self.alive = True
        # projection results (used by hitscan and AI code)
        self.screen_x = 0.0
        self.half_width = 0.0
        self.dist = 1.0
        self.norm_dist = 1.0
        self.theta = 0.0
        self.on_screen = False

    @property
    def pos(self):
        return self.x, self.y

    @property
    def map_pos(self):
        return int(self.x), int(self.y)

    def project(self, cam, renderer):
        """Compute the on-screen placement (in view pixels) and queue a draw."""
        dx = self.x - cam.x
        dy = self.y - cam.y
        self.theta = math.atan2(dy, dx)
        delta = (self.theta - cam.angle + math.pi) % math.tau - math.pi
        self.dist = math.hypot(dx, dy)
        self.norm_dist = self.dist * math.cos(delta)
        self.on_screen = False
        if self.norm_dist < 0.2:
            return
        view = renderer.view
        image = self.image
        iw, ih = image.get_size()
        proj = view.screen_dist / self.norm_dist
        height = proj * self.scale
        width = height * iw / ih
        self.screen_x = (view.half_num_rays + delta / view.delta_angle) * view.column
        self.half_width = width / 2
        left = self.screen_x - self.half_width
        if left + width < 0 or left > view.width or height < 1:
            return
        floor_y = view.half_height + proj * cam.cam_h
        bottom = floor_y - proj * self.z
        top = bottom - height
        self.on_screen = True
        renderer.add_sprite(self.norm_dist, image, left, top, width, height, self.bright)

    def update(self, dt):
        pass


class AnimatedSprite(SpriteObject):
    def __init__(self, world, frames, pos, scale=0.7, z=0.0, frame_time=120, loop=True):
        super().__init__(world, frames[0], pos, scale, z)
        self.anim = Animation(frames, frame_time, loop)

    def update(self, dt):
        self.anim.update(dt)
        self.image = self.anim.image


class Particle(AnimatedSprite):
    """A short lived animated billboard with simple physics (blood, puffs, explosions)."""

    def __init__(self, world, frames, pos, scale=0.2, z=0.3, frame_time=80, velocity=(0, 0, 0),
                 gravity=0.0, lifetime=None, bright=False):
        super().__init__(world, frames, pos, scale, z, frame_time, loop=False)
        self.vx, self.vy, self.vz = velocity
        self.gravity = gravity
        self.lifetime = lifetime if lifetime is not None else frame_time * len(frames)
        self.age = 0.0
        self.bright = bright

    def update(self, dt):
        super().update(dt)
        self.age += dt
        seconds = dt / 1000.0
        self.x += self.vx * seconds
        self.y += self.vy * seconds
        self.z += self.vz * seconds
        self.vz -= self.gravity * seconds
        if self.z < 0:
            self.z = 0
            self.vz = 0
            self.vx = self.vy = 0
        if self.age >= self.lifetime:
            self.alive = False
