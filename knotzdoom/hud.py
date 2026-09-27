"""Heads-up display: Doom style status bar, messages, crosshair and automap."""
import math

import pygame as pg

from .settings import (HALF_HEIGHT, HALF_WIDTH, HEIGHT, STATUS_BAR_HEIGHT, WIDTH)
from .weapons import WEAPON_DEFS, WEAPON_SLOTS

BAR_TOP = HEIGHT - STATUS_BAR_HEIGHT
MESSAGE_TIME = 3000
KEY_COLORS = {'red': (230, 40, 40), 'blue': (60, 90, 255), 'yellow': (240, 210, 40)}


class HUD:
    def __init__(self, game):
        self.game = game
        self.fonts = game.fonts
        self.assets = game.assets
        self.digits = {k: pg.transform.smoothscale(v, (34, 34)) for k, v in self.assets.digits.items()}
        self.small_digits = {k: pg.transform.smoothscale(v, (22, 22)) for k, v in self.assets.digits.items()}
        self.bar = self.build_bar()
        self.face = self.build_face()
        self.face_states = self.build_face_states()
        self.key_icons = {color: self.build_key_icon(color) for color in KEY_COLORS}
        self.messages = []         # [text, remaining ms]
        self.face_hurt_timer = 0.0
        self.automap = False
        self.automap_scale = 14

    # ------------------------------------------------------------ building
    @staticmethod
    def build_bar():
        bar = pg.Surface((WIDTH, STATUS_BAR_HEIGHT))
        for y in range(STATUS_BAR_HEIGHT):
            t = y / STATUS_BAR_HEIGHT
            k = 70 - int(30 * t)
            pg.draw.line(bar, (k, k, k + 4), (0, y), (WIDTH, y))
        pg.draw.line(bar, (120, 120, 125), (0, 0), (WIDTH, 0), 2)
        pg.draw.line(bar, (20, 20, 22), (0, STATUS_BAR_HEIGHT - 1), (WIDTH, STATUS_BAR_HEIGHT - 1), 2)
        # panel dividers
        for x in (170, 400, 660, 800, 1020, 1200, 1440):
            pg.draw.line(bar, (25, 25, 28), (x, 6), (x, STATUS_BAR_HEIGHT - 6), 3)
            pg.draw.line(bar, (105, 105, 110), (x + 3, 6), (x + 3, STATUS_BAR_HEIGHT - 6), 1)
        # rivets
        for x in range(12, WIDTH, 80):
            for y in (8, STATUS_BAR_HEIGHT - 10):
                pg.draw.circle(bar, (110, 110, 115), (x, y), 3)
                pg.draw.circle(bar, (30, 30, 32), (x + 1, y + 1), 1)
        return bar

    def build_face(self):
        head = self.assets.raw_frames('npc/soldier/idle')[0].subsurface((17, 0, 28, 28))
        return pg.transform.scale(head, (72, 72)).convert_alpha()

    def build_face_states(self):
        """Progressively bloodier versions of the face as health drops."""
        states = []
        for i in range(5):
            face = self.face.copy()
            if i:
                tint = pg.Surface(face.get_size(), pg.SRCALPHA)
                tint.fill((255, 255 - 42 * i, 255 - 42 * i, 255))
                face.blit(tint, (0, 0), special_flags=pg.BLEND_RGBA_MULT)
                # scribble blood streaks
                for s in range(i * 3):
                    x = 10 + (s * 17) % 50
                    pg.draw.line(face, (150, 10, 10), (x, 18 + (s * 7) % 20), (x + 2, 40 + (s * 11) % 25), 2)
            states.append(face)
        dead = self.face.copy()
        dead.fill((60, 60, 60), special_flags=pg.BLEND_RGB_MULT)
        pg.draw.line(dead, (200, 20, 20), (22, 22), (34, 34), 3)
        pg.draw.line(dead, (200, 20, 20), (34, 22), (22, 34), 3)
        pg.draw.line(dead, (200, 20, 20), (40, 22), (52, 34), 3)
        pg.draw.line(dead, (200, 20, 20), (52, 22), (40, 34), 3)
        states.append(dead)
        return states

    def build_key_icon(self, color):
        icon = self.assets.frame(f'pickups/key_{color}.png').convert_alpha()
        return pg.transform.scale(icon, (30, 30))

    # ------------------------------------------------------------ messages
    def message(self, text):
        self.messages.append([text, MESSAGE_TIME])
        if len(self.messages) > 3:
            self.messages.pop(0)

    def update(self, dt):
        for item in self.messages:
            item[1] -= dt
        self.messages = [m for m in self.messages if m[1] > 0]
        self.face_hurt_timer = max(0.0, self.face_hurt_timer - dt)

    # ------------------------------------------------------------ drawing
    def draw_number(self, screen, value, x, y, digits=None, align='right'):
        digits = digits or self.digits
        text = str(max(0, int(value)))
        size = digits['0'].get_width()
        width = size * len(text)
        start = x - width if align == 'right' else x
        for i, ch in enumerate(text):
            screen.blit(digits[ch], (start + i * size, y))
        return start

    def draw_percent(self, screen, value, x, y):
        self.draw_number(screen, value, x, y)
        screen.blit(self.digits['10'], (x, y))

    def draw_status_bar(self, screen, world):
        player = world.player
        pixel = self.fonts.pixel
        screen.blit(self.bar, (0, BAR_TOP))
        y_num = BAR_TOP + 22
        # ammo of the current weapon
        weapon = player.weapon
        ammo_type = WEAPON_DEFS[weapon.name]['ammo'] if weapon else None
        if ammo_type:
            self.draw_number(screen, player.ammo[ammo_type], 150, y_num)
        pixel.draw(screen, 'AMMO', 85, BAR_TOP + 64, (200, 200, 200), align='center')
        # health
        self.draw_percent(screen, player.health, 350, y_num)
        pixel.draw(screen, 'HEALTH', 290, BAR_TOP + 64, (200, 200, 200), align='center')
        # arms
        pixel.draw(screen, 'ARMS', 530, BAR_TOP + 8, (200, 200, 200), align='center')
        for slot in range(1, 5):
            name = WEAPON_SLOTS.get(slot)
            owned = name in player.weapons
            active = weapon is not None and weapon.name == name
            color = (255, 220, 60) if owned else (90, 90, 90)
            if active:
                color = (255, 255, 255)
            rx = 430 + (slot - 1) * 56
            pg.draw.rect(screen, (30, 30, 34), (rx, BAR_TOP + 34, 46, 46))
            pg.draw.rect(screen, (120, 120, 125) if owned else (60, 60, 60), (rx, BAR_TOP + 34, 46, 46), 2)
            pixel.draw(screen, str(slot), rx + 23, BAR_TOP + 44, color, align='center')
        # face
        self.draw_face(screen, player)
        # armor
        self.draw_percent(screen, player.armor, 985, y_num)
        pixel.draw(screen, 'ARMOR', 915, BAR_TOP + 64, (200, 200, 200), align='center')
        # keys
        pixel.draw(screen, 'KEYS', 1110, BAR_TOP + 64, (200, 200, 200), align='center')
        for i, color in enumerate(('blue', 'yellow', 'red')):
            kx = 1055 + i * 38
            icon = self.key_icons[color]
            if color in player.keys:
                screen.blit(icon, (kx, BAR_TOP + 18))
            else:
                dim = icon.copy()
                dim.fill((45, 45, 45), special_flags=pg.BLEND_RGB_MULT)
                screen.blit(dim, (kx, BAR_TOP + 18))
        # ammo table
        rows = (('BULL', 'bullets'), ('SHEL', 'shells'), ('RCKT', 'rockets'))
        for i, (label, ammo) in enumerate(rows):
            ty = BAR_TOP + 8 + i * 27
            pixel.draw(screen, label, 1212, ty, (200, 200, 200))
            self.draw_number(screen, player.ammo[ammo], 1340, ty - 2, self.small_digits)
            pixel.draw(screen, '/', 1343, ty, (150, 150, 150))
            self.draw_number(screen, player.max_ammo[ammo], 1430, ty - 2, self.small_digits)
        # score / level info on the far right
        pixel.draw(screen, f'SCORE {player.score}', WIDTH - 12, BAR_TOP + 8, (255, 220, 120), align='right')
        pixel.draw(screen, f'KILLS {world.stats["kills"]}/{world.stats["kills_total"]}', WIDTH - 12, BAR_TOP + 36,
                   (200, 200, 200), align='right')
        pixel.draw(screen, self.format_time(world.time), WIDTH - 12, BAR_TOP + 64, (200, 200, 200), align='right')

    def draw_face(self, screen, player):
        if not player.alive:
            face = self.face_states[-1]
        else:
            idx = min(4, int((100 - min(100, player.health)) / 25))
            face = self.face_states[idx]
        x, y = 694, BAR_TOP + 12
        pg.draw.rect(screen, (25, 25, 28), (x - 4, y - 4, 80, 80))
        if self.face_hurt_timer > 0:
            x += int(3 * math.sin(self.face_hurt_timer / 20.0))
        screen.blit(face, (x, y))
        pg.draw.rect(screen, (110, 110, 115), (690, y - 4, 80, 80), 2)

    @staticmethod
    def format_time(ms):
        seconds = int(ms // 1000)
        return f'{seconds // 60:02d}:{seconds % 60:02d}'

    def draw_messages(self, screen):
        y = 10
        for text, remaining in self.messages:
            surf = self.fonts.pixel.render(text, (235, 235, 235))
            if remaining < 600:
                surf = surf.copy()
                surf.set_alpha(int(255 * remaining / 600))
            screen.blit(surf, (14, y))
            y += surf.get_height() + 2

    def draw_crosshair(self, screen):
        cx, cy = HALF_WIDTH, HALF_HEIGHT
        color = (230, 230, 230)
        pg.draw.line(screen, color, (cx - 12, cy), (cx - 5, cy), 2)
        pg.draw.line(screen, color, (cx + 5, cy), (cx + 12, cy), 2)
        pg.draw.line(screen, color, (cx, cy - 12), (cx, cy - 5), 2)
        pg.draw.line(screen, color, (cx, cy + 5), (cx, cy + 12), 2)

    def draw_fps(self, screen, fps):
        self.fonts.pixel.draw(screen, f'{fps:.0f} FPS', WIDTH - 10, 8, (120, 255, 120), align='right')

    # ------------------------------------------------------------ automap
    def draw_automap(self, screen, world):
        level = world.level
        s = self.automap_scale
        overlay = pg.Surface((WIDTH, HEIGHT - STATUS_BAR_HEIGHT), pg.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        screen.blit(overlay, (0, 0))
        player = world.player
        ox = HALF_WIDTH - player.x * s
        oy = (HEIGHT - STATUS_BAR_HEIGHT) // 2 - player.y * s
        for (x, y) in world.seen_tiles:
            door = world.doors.get((x, y))
            if door is not None:
                color = KEY_COLORS.get(door.locked, (200, 200, 90))
            elif (x, y) in level.exits:
                color = (90, 255, 90)
            else:
                color = (200, 60, 60)
            pg.draw.rect(screen, color, (ox + x * s, oy + y * s, s - 1, s - 1))
        if player.noclip or player.god:
            for npc in world.objects.npcs:
                if npc.is_alive:
                    pg.draw.circle(screen, (255, 120, 40), (ox + npc.x * s, oy + npc.y * s), 4)
            for item in world.objects.pickups:
                pg.draw.circle(screen, (90, 200, 255), (ox + item.x * s, oy + item.y * s), 3)
        # player arrow
        px, py = ox + player.x * s, oy + player.y * s
        a = player.angle
        tip = (px + math.cos(a) * 12, py + math.sin(a) * 12)
        left = (px + math.cos(a + 2.5) * 9, py + math.sin(a + 2.5) * 9)
        right = (px + math.cos(a - 2.5) * 9, py + math.sin(a - 2.5) * 9)
        pg.draw.polygon(screen, (255, 255, 255), (tip, left, right))
        self.fonts.pixel.draw(screen, f'{level.name.upper()}', 14, HEIGHT - STATUS_BAR_HEIGHT - 40, (255, 220, 120))
        self.fonts.pixel.draw(screen, 'TAB: CLOSE MAP', WIDTH - 14, HEIGHT - STATUS_BAR_HEIGHT - 40,
                              (200, 200, 200), align='right')
