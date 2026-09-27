"""Heads-up display: Doom style status bar, messages, crosshair and automap.

The status bar is composed once into a cached surface and only rebuilt when
one of the values it shows changes, so a quiet frame costs one blit.
"""
import math

import pygame as pg

from .fonts import format_time
from .settings import HALF_HEIGHT, HALF_WIDTH, HEIGHT, STATUS_BAR_HEIGHT, WIDTH
from .weapons import WEAPON_DEFS, WEAPON_SLOTS

BAR_TOP = HEIGHT - STATUS_BAR_HEIGHT
MESSAGE_TIME = 3000
KEY_COLORS = {'red': (230, 40, 40), 'blue': (60, 90, 255), 'yellow': (240, 210, 40)}
KEY_ORDER = ('blue', 'yellow', 'red')

# status bar layout (window pixels); dividers separate the panels
BAR_DIVIDERS = (170, 400, 660, 800, 1020, 1200, 1440)
LAYOUT = {
    'ammo_right': 150, 'ammo_label': 85,
    'health_right': 350, 'health_label': 290,
    'arms_x': 430, 'arms_label': 530, 'arms_step': 56,
    'face_x': 694,
    'armor_right': 985, 'armor_label': 915,
    'keys_x': 1055, 'keys_label': 1110, 'keys_step': 38,
    'table_x': 1212, 'table_cur': 1340, 'table_slash': 1343, 'table_max': 1430,
    'num_y': 22, 'label_y': 64,
}


class HUD:
    def __init__(self, game):
        self.game = game
        self.fonts = game.fonts
        self.assets = game.assets
        self.digits = self.fonts.digit_font(34)
        self.small_digits = self.fonts.digit_font(22)
        self.face = self.build_face()
        self.face_states = self.build_face_states()
        self.key_icons = {color: self.build_key_icon(color) for color in KEY_COLORS}
        self.bar = self.build_bar()
        self.composed = None
        self.composed_key = None
        self.messages = []         # [text, remaining ms]
        self.face_hurt_timer = 0.0
        self.automap = False
        self.automap_scale = 14
        self.automap_layer = None
        self.automap_layer_key = None

    # ------------------------------------------------------------ building
    def build_bar(self):
        """The static bar: metal plate, dividers, rivets, labels and dimmed key icons."""
        bar = pg.Surface((WIDTH, STATUS_BAR_HEIGHT))
        for y in range(STATUS_BAR_HEIGHT):
            k = 70 - int(30 * y / STATUS_BAR_HEIGHT)
            pg.draw.line(bar, (k, k, k + 4), (0, y), (WIDTH, y))
        pg.draw.line(bar, (120, 120, 125), (0, 0), (WIDTH, 0), 2)
        pg.draw.line(bar, (20, 20, 22), (0, STATUS_BAR_HEIGHT - 1), (WIDTH, STATUS_BAR_HEIGHT - 1), 2)
        for x in BAR_DIVIDERS:
            pg.draw.line(bar, (25, 25, 28), (x, 6), (x, STATUS_BAR_HEIGHT - 6), 3)
            pg.draw.line(bar, (105, 105, 110), (x + 3, 6), (x + 3, STATUS_BAR_HEIGHT - 6), 1)
        for x in range(12, WIDTH, 80):
            for y in (8, STATUS_BAR_HEIGHT - 10):
                pg.draw.circle(bar, (110, 110, 115), (x, y), 3)
                pg.draw.circle(bar, (30, 30, 32), (x + 1, y + 1), 1)
        pixel = self.fonts.pixel
        L = LAYOUT
        gray = (200, 200, 200)
        for label, x in (('AMMO', L['ammo_label']), ('HEALTH', L['health_label']),
                         ('ARMOR', L['armor_label']), ('KEYS', L['keys_label'])):
            pixel.draw(bar, label, x, L['label_y'], gray, align='center')
        pixel.draw(bar, 'ARMS', L['arms_label'], 8, gray, align='center')
        for i, label in enumerate(('BULL', 'SHEL', 'RCKT')):
            pixel.draw(bar, label, L['table_x'], 8 + i * 27, gray)
            pixel.draw(bar, '/', L['table_slash'], 8 + i * 27, (150, 150, 150))
        for i, color in enumerate(KEY_ORDER):
            dim = self.key_icons[color].copy()
            dim.fill((45, 45, 45), special_flags=pg.BLEND_RGB_MULT)
            bar.blit(dim, (L['keys_x'] + i * L['keys_step'], 18))
        return bar

    def build_face(self):
        head = self.assets.raw_frames('npc/soldier/idle')[0].subsurface((17, 0, 28, 28))
        return pg.transform.scale(head, (72, 72)).convert_alpha()

    def build_face_states(self):
        """Progressively bloodier versions of the face as health drops, then a dead one."""
        states = []
        for i in range(5):
            face = self.face.copy()
            if i:
                tint = pg.Surface(face.get_size(), pg.SRCALPHA)
                tint.fill((255, 255 - 42 * i, 255 - 42 * i, 255))
                face.blit(tint, (0, 0), special_flags=pg.BLEND_RGBA_MULT)
                for s in range(i * 3):
                    x = 10 + (s * 17) % 50
                    pg.draw.line(face, (150, 10, 10), (x, 18 + (s * 7) % 20), (x + 2, 40 + (s * 11) % 25), 2)
            states.append(face)
        dead = self.face.copy()
        dead.fill((60, 60, 60), special_flags=pg.BLEND_RGB_MULT)
        for x in (22, 40):
            pg.draw.line(dead, (200, 20, 20), (x, 22), (x + 12, 34), 3)
            pg.draw.line(dead, (200, 20, 20), (x + 12, 22), (x, 34), 3)
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

    # ------------------------------------------------------------ status bar
    def face_index(self, player):
        if not player.alive:
            return 5
        return min(4, int((100 - min(100, player.health)) / 25))

    def draw_status_bar(self, screen, world):
        player = world.player
        weapon = player.weapon
        ammo_type = WEAPON_DEFS[weapon.name]['ammo'] if weapon else None
        key = (player.ammo[ammo_type] if ammo_type else -1, player.health, player.armor,
               tuple(sorted(player.keys)), weapon.name if weapon else None, tuple(sorted(player.weapons)),
               player.score, world.stats['kills'], world.stats['kills_total'], int(world.time // 1000),
               self.face_index(player), int(self.face_hurt_timer // 40),
               tuple(player.ammo.values()), tuple(player.max_ammo.values()))
        if key != self.composed_key:
            self.composed_key = key
            self.composed = self.compose(world, player, weapon, ammo_type)
        screen.blit(self.composed, (0, BAR_TOP))

    def compose(self, world, player, weapon, ammo_type):
        bar = self.bar.copy()
        pixel = self.fonts.pixel
        L = LAYOUT
        y_num = L['num_y']
        if ammo_type:
            self.digits.draw(bar, player.ammo[ammo_type], L['ammo_right'], y_num)
        self.digits.draw(bar, f'{player.health}%', L['health_right'] + self.digits.size, y_num)
        for slot in range(1, 5):
            name = WEAPON_SLOTS.get(slot)
            owned = name in player.weapons
            active = weapon is not None and weapon.name == name
            color = (255, 255, 255) if active else (255, 220, 60) if owned else (90, 90, 90)
            rx = L['arms_x'] + (slot - 1) * L['arms_step']
            pg.draw.rect(bar, (30, 30, 34), (rx, 34, 46, 46))
            pg.draw.rect(bar, (120, 120, 125) if owned else (60, 60, 60), (rx, 34, 46, 46), 2)
            pixel.draw(bar, str(slot), rx + 23, 44, color, align='center')
        self.draw_face(bar, player)
        self.digits.draw(bar, f'{player.armor}%', L['armor_right'] + self.digits.size, y_num)
        for i, color in enumerate(KEY_ORDER):
            if color in player.keys:
                bar.blit(self.key_icons[color], (L['keys_x'] + i * L['keys_step'], 18))
        for i, ammo in enumerate(('bullets', 'shells', 'rockets')):
            ty = 8 + i * 27
            self.small_digits.draw(bar, player.ammo[ammo], L['table_cur'], ty - 2)
            self.small_digits.draw(bar, player.max_ammo[ammo], L['table_max'], ty - 2)
        pixel.draw(bar, f'SCORE {player.score}', WIDTH - 12, 8, (255, 220, 120), align='right')
        pixel.draw(bar, f'KILLS {world.stats["kills"]}/{world.stats["kills_total"]}', WIDTH - 12, 36,
                   (200, 200, 200), align='right')
        pixel.draw(bar, format_time(world.time), WIDTH - 12, 64, (200, 200, 200), align='right')
        return bar

    def draw_face(self, bar, player):
        face = self.face_states[self.face_index(player)]
        x, y = LAYOUT['face_x'], 12
        pg.draw.rect(bar, (25, 25, 28), (x - 4, y - 4, 80, 80))
        if self.face_hurt_timer > 0:
            x += int(3 * math.sin(self.face_hurt_timer / 20.0))
        bar.blit(face, (x, y))
        pg.draw.rect(bar, (110, 110, 115), (LAYOUT['face_x'] - 4, y - 4, 80, 80), 2)

    # ------------------------------------------------------------ overlays
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
    def automap_tiles(self, world):
        """A surface of every seen tile in map space, rebuilt only when the map grows."""
        level = world.level
        s = self.automap_scale
        key = (len(world.seen_tiles), world.exit_triggered)
        if key == self.automap_layer_key and self.automap_layer is not None:
            return self.automap_layer
        layer = pg.Surface((level.cols * s, level.rows * s), pg.SRCALPHA)
        for (x, y) in world.seen_tiles:
            door = world.doors.get((x, y))
            if door is not None:
                color = KEY_COLORS.get(door.locked, (200, 200, 90))
            elif (x, y) in level.exits:
                color = (90, 255, 90)
            else:
                color = (200, 60, 60)
            pg.draw.rect(layer, color, (x * s, y * s, s - 1, s - 1))
        self.automap_layer, self.automap_layer_key = layer, key
        return layer

    def draw_automap(self, screen, world):
        s = self.automap_scale
        view_h = HEIGHT - STATUS_BAR_HEIGHT
        dim = self.game.dim_surface((WIDTH, view_h), 170)
        screen.blit(dim, (0, 0))
        player = world.player
        ox = HALF_WIDTH - player.x * s
        oy = view_h // 2 - player.y * s
        screen.blit(self.automap_tiles(world), (ox, oy))
        if player.noclip or player.god:
            for npc in world.objects.npcs:
                if npc.is_alive:
                    pg.draw.circle(screen, (255, 120, 40), (ox + npc.x * s, oy + npc.y * s), 4)
            for item in world.objects.pickups:
                pg.draw.circle(screen, (90, 200, 255), (ox + item.x * s, oy + item.y * s), 3)
        px, py = ox + player.x * s, oy + player.y * s
        a = player.angle
        tip = (px + math.cos(a) * 12, py + math.sin(a) * 12)
        left = (px + math.cos(a + 2.5) * 9, py + math.sin(a + 2.5) * 9)
        right = (px + math.cos(a - 2.5) * 9, py + math.sin(a - 2.5) * 9)
        pg.draw.polygon(screen, (255, 255, 255), (tip, left, right))
        self.fonts.pixel.draw(screen, world.level.name.upper(), 14, view_h - 40, (255, 220, 120))
        self.fonts.pixel.draw(screen, 'TAB: CLOSE MAP', WIDTH - 14, view_h - 40, (200, 200, 200), align='right')
