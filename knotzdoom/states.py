"""Game states: title, menus, options, help, credits, story, play, pause,
save/load, death, intermission and victory.

The Game keeps a stack of states; the top one receives input and is updated.
States flagged ``transparent`` let the state below them draw first (pause and
death overlays on top of the frozen or still running game view).
"""
import math
import os
import random

import pygame as pg

from . import saves
from .settings import DIFFICULTIES, HALF_HEIGHT, HALF_WIDTH, HEIGHT, WIDTH
from .world import World

CHEATS = ('iddqd', 'idkfa', 'idclip', 'iddt')
MAX_CHEAT_LEN = 8


def draw_dim(screen, alpha=150):
    dim = pg.Surface((WIDTH, HEIGHT), pg.SRCALPHA)
    dim.fill((0, 0, 0, alpha))
    screen.blit(dim, (0, 0))


def draw_skull(screen, x, y, t):
    """A small pulsing bone-white skull used as the menu cursor."""
    pulse = 1.0 + 0.08 * math.sin(t / 150.0)
    r = int(11 * pulse)
    bone = (225, 220, 200)
    dark = (30, 20, 20)
    pg.draw.circle(screen, bone, (x, y - 3), r)
    pg.draw.rect(screen, bone, (x - r // 2, y + r // 2 - 2, r, r // 2 + 3))
    pg.draw.circle(screen, dark, (x - r // 2 + 1, y - 4), max(2, r // 3))
    pg.draw.circle(screen, dark, (x + r // 2 - 1, y - 4), max(2, r // 3))
    pg.draw.polygon(screen, dark, ((x, y), (x - 2, y + 4), (x + 2, y + 4)))
    for i in (-4, 0, 4):
        pg.draw.line(screen, dark, (x + i, y + r // 2 + 2), (x + i, y + r - 1), 1)


class State:
    transparent = False

    def __init__(self, game):
        self.game = game
        self.time = 0.0

    def enter(self):
        pass

    def exit(self):
        pass

    def resume(self):
        """Called when a state above this one was popped."""
        pass

    def handle_event(self, event):
        pass

    def update(self, dt):
        self.time += dt

    def draw(self, screen):
        pass


# ------------------------------------------------------------------ menu helper
class MenuItem:
    def __init__(self, label, action=None, enabled=True, value=None, adjust=None, hint=None):
        self.label = label
        self.action = action
        self.enabled = enabled
        self.value = value          # callable returning a string, drawn to the right
        self.adjust = adjust        # callable(direction) for option sliders
        self.hint = hint


class Menu:
    def __init__(self, game, items, top, spacing=62, font=None, x=HALF_WIDTH, align='center'):
        self.game = game
        self.items = items
        self.top = top
        self.spacing = spacing
        self.font = font or game.fonts.menu
        self.x = x
        self.align = align
        self.index = 0
        self.rects = []
        self.time = 0.0
        while self.items and not self.items[self.index].enabled:
            self.index = (self.index + 1) % len(self.items)

    def move(self, direction):
        if not self.items:
            return
        for _ in range(len(self.items)):
            self.index = (self.index + direction) % len(self.items)
            if self.items[self.index].enabled:
                break
        self.game.audio.play('menu_move')

    def activate(self):
        item = self.items[self.index]
        if not item.enabled:
            return
        if item.action is not None:
            self.game.audio.play('menu_select')
            item.action()
        elif item.adjust is not None:
            self.game.audio.play('menu_move')
            item.adjust(1)

    def handle_event(self, event):
        if event.type == pg.KEYDOWN:
            if event.key in (pg.K_UP, pg.K_w):
                self.move(-1)
            elif event.key in (pg.K_DOWN, pg.K_s):
                self.move(1)
            elif event.key in (pg.K_RETURN, pg.K_KP_ENTER, pg.K_SPACE):
                self.activate()
            elif event.key in (pg.K_LEFT, pg.K_a):
                item = self.items[self.index]
                if item.adjust:
                    self.game.audio.play('menu_move')
                    item.adjust(-1)
            elif event.key in (pg.K_RIGHT, pg.K_d):
                item = self.items[self.index]
                if item.adjust:
                    self.game.audio.play('menu_move')
                    item.adjust(1)
        elif event.type == pg.MOUSEMOTION:
            for i, rect in enumerate(self.rects):
                if rect and rect.collidepoint(event.pos) and self.items[i].enabled and i != self.index:
                    self.index = i
                    self.game.audio.play('menu_move')
        elif event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
            for i, rect in enumerate(self.rects):
                if rect and rect.collidepoint(event.pos) and self.items[i].enabled:
                    self.index = i
                    self.activate()

    def update(self, dt):
        self.time += dt

    def draw(self, screen):
        self.rects = []
        pixel = self.game.fonts.pixel
        for i, item in enumerate(self.items):
            y = self.top + i * self.spacing
            selected = i == self.index
            palette = 'gold' if selected else ('red' if item.enabled else 'gray')
            rect = self.font.draw(screen, item.label, self.x, y, palette, align=self.align, glow=selected)
            if item.value is not None:
                value = item.value()
                pixel.draw(screen, value, self.x + 300, y - pixel.height() // 2, (255, 230, 140) if selected else (200, 200, 200))
                rect = rect.union(pg.Rect(self.x + 300, y - 12, 200, 24))
            self.rects.append(rect)
            if selected:
                cx = (rect.left - 34) if self.align != 'right' else rect.right + 34
                draw_skull(screen, cx, y, self.time)
        item = self.items[self.index] if self.items else None
        if item is not None and item.hint:
            pixel.draw(screen, item.hint, HALF_WIDTH, HEIGHT - 70, (200, 200, 200), align='center')


# ------------------------------------------------------------------ demo background
class DemoBackground:
    """Renders a slowly rotating view of the first level behind the menus."""

    def __init__(self, game):
        self.game = game
        self.world = None
        self.renderer = None
        self.angle = 0.0
        try:
            from .renderer import Renderer
            level = game.level_data(0)
            self.world = World(game, level, difficulty_index=1)
            self.renderer = Renderer(game, self.world)
            self.cam = self.world.player
            self.cam.x, self.cam.y = self.pick_camera_spot(level)
        except Exception as exc:      # the menus must work even without levels
            print('demo background unavailable:', exc)
            self.world = None

    def pick_camera_spot(self, level):
        sx, sy = level.player_start
        return sx, sy

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


# ------------------------------------------------------------------ title
class TitleState(State):
    def enter(self):
        self.game.set_mouse_grab(False)
        self.game.audio.play_music('menu')

    def handle_event(self, event):
        if event.type == pg.KEYDOWN and event.key == pg.K_ESCAPE:
            self.game.quit()
        elif event.type == pg.KEYDOWN or (event.type == pg.MOUSEBUTTONDOWN and event.button == 1):
            self.game.audio.play('menu_select')
            self.game.replace(MainMenuState(self.game))

    def update(self, dt):
        super().update(dt)
        self.game.demo.update(dt)

    def draw(self, screen):
        game = self.game
        game.demo.draw(screen)
        fonts = game.fonts
        fonts.title.draw(screen, game.episode.get('title', 'KNOTZDOOM'), HALF_WIDTH, HALF_HEIGHT - 150)
        fonts.small_big.draw(screen, game.episode.get('subtitle', 'KNEE DEEP IN THE KNOTZ'), HALF_WIDTH, HALF_HEIGHT - 40, 'gray', glow=False)
        if int(self.time / 500) % 2 == 0:
            fonts.menu.draw(screen, 'PRESS ENTER', HALF_WIDTH, HALF_HEIGHT + 120, 'gold')
        fonts.pixel.draw(screen, f'KNOTZDOOM v{game.version}  -  {game.episode.get("copyright", "")}', HALF_WIDTH,
                         HEIGHT - 40, (170, 170, 170), align='center')
        best = game.records.get('best_score', 0)
        if best:
            fonts.pixel.draw(screen, f'BEST SCORE {best}', HALF_WIDTH, HEIGHT - 70, (255, 220, 120), align='center')


# ------------------------------------------------------------------ main menu
class MainMenuState(State):
    def __init__(self, game):
        super().__init__(game)
        has_saves = any(s is not None for s in saves.slot_summaries())
        self.menu = Menu(game, [
            MenuItem('NEW GAME', lambda: game.push(DifficultyState(game))),
            MenuItem('LOAD GAME', lambda: game.push(SaveLoadState(game, 'load')), enabled=has_saves),
            MenuItem('OPTIONS', lambda: game.push(OptionsState(game))),
            MenuItem('HELP', lambda: game.push(HelpState(game))),
            MenuItem('CREDITS', lambda: game.push(CreditsState(game))),
            MenuItem('QUIT', game.quit),
        ], top=HALF_HEIGHT - 120)

    def enter(self):
        self.game.set_mouse_grab(False)
        self.game.audio.play_music('menu')

    def resume(self):
        self.enter()
        has_saves = any(s is not None for s in saves.slot_summaries())
        self.menu.items[1].enabled = has_saves

    def handle_event(self, event):
        if event.type == pg.KEYDOWN and event.key == pg.K_ESCAPE:
            self.game.audio.play('menu_back')
            self.game.replace(TitleState(self.game))
            return
        self.menu.handle_event(event)

    def update(self, dt):
        super().update(dt)
        self.game.demo.update(dt)
        self.menu.update(dt)

    def draw(self, screen):
        self.game.demo.draw(screen)
        self.game.fonts.heading.draw(screen, self.game.episode.get('title', 'KNOTZDOOM'), HALF_WIDTH, 120)
        self.menu.draw(screen)


# ------------------------------------------------------------------ difficulty
class DifficultyState(State):
    def __init__(self, game):
        super().__init__(game)
        items = [MenuItem(d['name'], (lambda i=i: game.start_new_game(i)), hint=d['desc'])
                 for i, d in enumerate(DIFFICULTIES)]
        self.menu = Menu(game, items, top=HALF_HEIGHT - 60)
        self.menu.index = 1

    def handle_event(self, event):
        if event.type == pg.KEYDOWN and event.key == pg.K_ESCAPE:
            self.game.audio.play('menu_back')
            self.game.pop()
            return
        self.menu.handle_event(event)

    def update(self, dt):
        super().update(dt)
        self.game.demo.update(dt)
        self.menu.update(dt)

    def draw(self, screen):
        self.game.demo.draw(screen)
        self.game.fonts.heading.draw(screen, 'CHOOSE SKILL LEVEL', HALF_WIDTH, 140)
        self.menu.draw(screen)


# ------------------------------------------------------------------ options
class OptionsState(State):

    def __init__(self, game):
        super().__init__(game)
        cfg = game.config

        def slider(key, step, lo, hi, fmt):
            def adjust(direction):
                cfg[key] = round(max(lo, min(hi, cfg[key] + direction * step)), 3)
                game.audio.apply_volumes()
            return MenuItem(key.replace('_', ' ').upper(), value=lambda: fmt(cfg[key]), adjust=adjust)

        def toggle(key, label=None):
            def adjust(direction):
                cfg[key] = not cfg[key]
                if key == 'fullscreen':
                    game.apply_fullscreen()
            return MenuItem((label or key.replace('_', ' ')).upper(), value=lambda: 'ON' if cfg[key] else 'OFF', adjust=adjust)

        def fps_adjust(direction):
            caps = [30, 60, 90, 120, 144, 0]
            idx = caps.index(cfg['fps_cap']) if cfg['fps_cap'] in caps else 1
            cfg['fps_cap'] = caps[(idx + direction) % len(caps)]

        def detail_adjust(direction):
            from .view import DETAIL_ORDER
            idx = DETAIL_ORDER.index(cfg['detail']) if cfg['detail'] in DETAIL_ORDER else 0
            cfg['detail'] = DETAIL_ORDER[(idx + direction) % len(DETAIL_ORDER)]

        bar = lambda v: '[' + '#' * int(round(v * 10)) + '-' * (10 - int(round(v * 10))) + ']'
        self.menu = Menu(game, [
            slider('music_volume', 0.1, 0.0, 1.0, bar),
            slider('sfx_volume', 0.1, 0.0, 1.0, bar),
            slider('mouse_sensitivity', 0.1, 0.2, 3.0, lambda v: f'{v:.1f}x'),
            toggle('crosshair'),
            toggle('screen_shake'),
            toggle('head_bob'),
            toggle('always_run'),
            toggle('show_fps'),
            toggle('fullscreen'),
            MenuItem('FPS CAP', value=lambda: 'UNLIMITED' if not cfg['fps_cap'] else str(cfg['fps_cap']), adjust=fps_adjust),
            MenuItem('DETAIL', value=lambda: str(cfg['detail']).upper(), adjust=detail_adjust,
                     hint='AUTO drops to low detail when frames get slow, like the original.'),
            MenuItem('BACK', self.back),
        ], top=170, spacing=50, font=game.fonts.small_big, x=HALF_WIDTH - 120, align='right')

    def back(self):
        self.game.config.save()
        self.game.audio.play('menu_back')
        self.game.pop()

    def handle_event(self, event):
        if event.type == pg.KEYDOWN and event.key == pg.K_ESCAPE:
            self.back()
            return
        self.menu.handle_event(event)

    def update(self, dt):
        super().update(dt)
        self.game.demo.update(dt)
        self.menu.update(dt)

    def draw(self, screen):
        self.game.draw_backdrop(screen, 170)
        self.game.fonts.heading.draw(screen, 'OPTIONS', HALF_WIDTH, 100)
        self.menu.draw(screen)
        self.game.fonts.pixel.draw(screen, 'LEFT / RIGHT TO CHANGE   ESC TO GO BACK', HALF_WIDTH, HEIGHT - 50,
                                   (200, 200, 200), align='center')


# ------------------------------------------------------------------ help
HELP_LINES = [
    ('W A S D / ARROWS', 'Move and turn'),
    ('MOUSE', 'Look around'),
    ('LEFT MOUSE', 'Fire'),
    ('SHIFT', 'Sprint'),
    ('E / SPACE', 'Use doors and switches'),
    ('1 - 4 / MOUSE WHEEL', 'Select weapon'),
    ('TAB', 'Automap'),
    ('F5 / F9', 'Quick save / quick load'),
    ('F11', 'Toggle fullscreen'),
    ('F12', 'Screenshot'),
    ('ESC', 'Pause menu'),
]


class HelpState(State):

    def update(self, dt):
        super().update(dt)
        self.game.demo.update(dt)

    def handle_event(self, event):
        if event.type == pg.KEYDOWN or (event.type == pg.MOUSEBUTTONDOWN and event.button == 1):
            self.game.audio.play('menu_back')
            self.game.pop()

    def draw(self, screen):
        self.game.draw_backdrop(screen, 190)
        fonts = self.game.fonts
        fonts.heading.draw(screen, 'HOW TO PLAY', HALF_WIDTH, 90)
        y = 190
        for key, desc in HELP_LINES:
            fonts.pixel_large.draw(screen, key, HALF_WIDTH - 40, y, (255, 220, 120), align='right')
            fonts.pixel_large.draw(screen, desc, HALF_WIDTH + 40, y, (220, 220, 220))
            y += 46
        tips = self.game.episode.get('tips', [])
        y += 10
        for tip in tips:
            fonts.pixel.draw(screen, tip, HALF_WIDTH, y, (180, 180, 180), align='center')
            y += 28
        fonts.pixel.draw(screen, 'PRESS ANY KEY', HALF_WIDTH, HEIGHT - 50, (200, 200, 200), align='center')


# ------------------------------------------------------------------ credits
class CreditsState(State):

    def __init__(self, game, on_done=None):
        super().__init__(game)
        self.lines = game.episode.get('credits', ['KNOTZDOOM'])
        self.scroll = 0.0
        self.on_done = on_done

    def enter(self):
        self.game.set_mouse_grab(False)

    def handle_event(self, event):
        if event.type == pg.KEYDOWN or (event.type == pg.MOUSEBUTTONDOWN and event.button == 1):
            self.finish()

    def finish(self):
        self.game.audio.play('menu_back')
        if self.on_done:
            self.on_done()
        else:
            self.game.pop()

    def update(self, dt):
        super().update(dt)
        self.game.demo.update(dt)
        self.scroll += dt * 0.045
        if self.scroll > len(self.lines) * 44 + HEIGHT + 100:
            self.finish()

    def draw(self, screen):
        self.game.draw_backdrop(screen, 200)
        fonts = self.game.fonts
        y = HEIGHT - self.scroll
        for line in self.lines:
            if -60 < y < HEIGHT + 20:
                if line.startswith('#'):
                    fonts.menu.draw(screen, line[1:].strip(), HALF_WIDTH, y)
                elif line:
                    fonts.pixel_large.draw(screen, line, HALF_WIDTH, y - 14, (220, 220, 220), align='center')
            y += 44


# ------------------------------------------------------------------ story
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


class StoryState(State):
    """Typewriter story text between levels (and the intro / ending)."""

    def __init__(self, game, text, on_done, music='intermission', background='7'):
        super().__init__(game)
        self.on_done = on_done
        self.music = music
        self.shown = 0.0
        self.done_typing = False
        self.background = build_texture_background(game, background)
        self.lines = self.wrap(text)

    def wrap(self, text, width=64):
        lines = []
        for paragraph in text.split('\n'):
            words = paragraph.split(' ')
            line = ''
            for word in words:
                if len(line) + len(word) + 1 > width:
                    lines.append(line)
                    line = word
                else:
                    line = (line + ' ' + word).strip()
            lines.append(line)
        return lines

    def enter(self):
        self.game.set_mouse_grab(False)
        self.game.audio.play_music(self.music)

    def handle_event(self, event):
        if event.type == pg.KEYDOWN or (event.type == pg.MOUSEBUTTONDOWN and event.button == 1):
            if not self.done_typing:
                self.done_typing = True
                self.shown = sum(len(l) + 1 for l in self.lines)
            else:
                self.game.audio.play('menu_select')
                self.on_done()

    def update(self, dt):
        super().update(dt)
        if not self.done_typing:
            before = int(self.shown)
            self.shown += dt * 0.05
            if int(self.shown) > before and int(self.shown) % 3 == 0:
                self.game.audio.play('tally_tick', volume=0.3)
            if self.shown >= sum(len(l) + 1 for l in self.lines):
                self.done_typing = True

    def draw(self, screen):
        screen.blit(self.background, (0, 0))
        draw_dim(screen, 120)
        remaining = int(self.shown)
        y = 120
        font = self.game.fonts.pixel_large
        for line in self.lines:
            if remaining <= 0:
                break
            font.draw(screen, line[:remaining], 160, y, (230, 220, 200))
            remaining -= len(line) + 1
            y += 40
        if self.done_typing and int(self.time / 500) % 2 == 0:
            self.game.fonts.pixel.draw(screen, 'PRESS ANY KEY TO CONTINUE', HALF_WIDTH, HEIGHT - 60, (255, 220, 120), align='center')


# ------------------------------------------------------------------ play
class PlayState(State):
    def __init__(self, game, level_index, difficulty_index, carry_state=None, restore=None):
        super().__init__(game)
        from .hud import HUD
        from .renderer import Renderer
        self.level_index = level_index
        self.level = game.level_data(level_index)
        self.world = World(game, self.level, difficulty_index, carry_state)
        if restore:
            self.world.restore_state(restore)
        self.renderer = Renderer(game, self.world)
        self.world.renderer = self.renderer
        self.hud = HUD(game)
        self.cheat_buffer = ''
        self.fade = 700.0
        self.title_timer = 3500.0
        self.death_shown = False
        self.finished = False

    def enter(self):
        self.game.set_mouse_grab(True)
        pg.mouse.get_rel()
        self.game.audio.play_music(self.level.music)
        self.game.audio.listener = self.world.player

    def resume(self):
        self.enter()

    # ------------------------------------------------------------ input
    def handle_event(self, event):
        world = self.world
        player = world.player
        if event.type == pg.KEYDOWN:
            if event.key == pg.K_ESCAPE:
                self.game.push(PauseState(self.game, self))
                return
            if event.key == pg.K_TAB:
                self.hud.automap = not self.hud.automap
                return
            if event.key == pg.K_F5:
                self.game.save_game(0, self)
                return
            if event.key == pg.K_F9:
                self.game.load_game(0)
                return
            if event.key == pg.K_F11:
                self.game.config['fullscreen'] = not self.game.config['fullscreen']
                self.game.apply_fullscreen()
                return
            if event.unicode and event.unicode.isalpha():
                self.cheat_buffer = (self.cheat_buffer + event.unicode.lower())[-MAX_CHEAT_LEN:]
                self.check_cheats()
        player.handle_event(event)

    def check_cheats(self):
        player = self.world.player
        buf = self.cheat_buffer
        for code in CHEATS:
            if buf.endswith(code):
                self.cheat_buffer = ''
                if code == 'iddqd':
                    player.god = not player.god
                    if player.god:
                        player.health = max(player.health, 100)
                    self.world.message('Degreelessness mode ' + ('ON' if player.god else 'OFF'))
                elif code == 'idkfa':
                    for name in ('shotgun', 'chaingun', 'rocket_launcher'):
                        player.give_weapon(name, announce=False)
                    for ammo in player.ammo:
                        player.ammo[ammo] = player.max_ammo[ammo]
                    player.keys.update(('red', 'blue', 'yellow'))
                    player.give_armor(200, 2)
                    self.world.message('Very happy ammo added')
                elif code == 'idclip':
                    player.noclip = not player.noclip
                    self.world.message('No clipping mode ' + ('ON' if player.noclip else 'OFF'))
                elif code == 'iddt':
                    self.world.seen_tiles.update(self.world.walls.keys())
                    self.world.seen_tiles.update(self.world.doors.keys())
                    self.world.message('Map revealed')
                self.game.audio.play('secret_found')
                return

    # ------------------------------------------------------------ update
    def update(self, dt):
        super().update(dt)
        world = self.world
        world.update(dt)
        self.hud.update(dt)
        for text in world.messages:
            self.hud.message(text)
        world.messages.clear()
        if world.fx.damage_flash > 0 and world.player.last_hurt > world.time - 200:
            self.hud.face_hurt_timer = 300
        self.fade = max(0.0, self.fade - dt)
        self.title_timer = max(0.0, self.title_timer - dt)
        self.renderer.light = 2 if world.fx.light > 0 else 0
        if world.player_dead and not self.death_shown and world.player.death_timer > 1300:
            self.death_shown = True
            self.game.push(DeathState(self.game, self))
        if world.exit_triggered and not self.finished and world.exit_timer > 900:
            self.finished = True
            self.game.level_complete(self)

    # ------------------------------------------------------------ draw
    def draw(self, screen):
        world = self.world
        player = world.player
        cfg = self.game.config
        renderer = self.renderer
        renderer.render(player)
        if player.weapon is not None:
            bob_x = math.sin(player.bob_phase) * 9 * player.bob_amount
            bob_y = abs(math.cos(player.bob_phase)) * 7 * player.bob_amount
            if not player.alive:
                bob_y = 80 * min(1.0, player.death_timer / 600.0)
            player.weapon.draw(renderer.view, bob_x, bob_y, player.switch_progress)
        if cfg['screen_shake'] and world.fx.shake > 0:
            amount = max(1, int(world.fx.shake) // renderer.view.divisor)
            renderer.shake(random.randint(-amount, amount), random.randint(-amount, amount))
        if world.fx.damage_flash > 0:
            renderer.overlay((255, 0, 0), world.fx.damage_flash)
        if world.fx.bonus_flash > 0:
            renderer.overlay((255, 230, 60), world.fx.bonus_flash * 0.5)
        if not player.alive:
            renderer.overlay((120, 0, 0), min(160, player.death_timer * 0.12))
        renderer.present()
        self.hud.draw_status_bar(screen, world)
        if self.hud.automap:
            self.hud.draw_automap(screen, world)
        elif cfg['crosshair'] and player.alive:
            self.hud.draw_crosshair(screen)
        self.hud.draw_messages(screen)
        if self.title_timer > 0 and not self.hud.automap:
            label = f'{self.level_index + 1}: {self.level.name.upper()}'
            surf = self.game.fonts.small_big.render(label, 'red')
            if self.title_timer < 600:
                surf = surf.copy()
                surf.set_alpha(int(255 * self.title_timer / 600))
            screen.blit(surf, surf.get_rect(center=(HALF_WIDTH, 70)))
        if cfg['show_fps']:
            self.hud.draw_fps(screen, self.game.clock.get_fps())
        if self.fade > 0:
            self.renderer.screen_overlay((0, 0, 0), 255 * self.fade / 700.0)


# ------------------------------------------------------------------ pause
class PauseState(State):
    transparent = True

    def __init__(self, game, play):
        super().__init__(game)
        self.play = play
        self.menu = Menu(game, [
            MenuItem('RESUME', self.resume_game),
            MenuItem('SAVE GAME', lambda: game.push(SaveLoadState(game, 'save', play))),
            MenuItem('LOAD GAME', lambda: game.push(SaveLoadState(game, 'load', play))),
            MenuItem('OPTIONS', lambda: game.push(OptionsState(game))),
            MenuItem('RESTART LEVEL', self.restart),
            MenuItem('QUIT TO MENU', self.quit_to_menu),
        ], top=HALF_HEIGHT - 130, spacing=58)
        self.snapshot = None

    def enter(self):
        self.game.set_mouse_grab(False)
        self.game.audio.pause_music()
        self.snapshot = self.game.screen.copy()

    def exit(self):
        self.game.audio.resume_music()

    def resume_game(self):
        self.game.audio.play('menu_back')
        self.game.pop()

    def restart(self):
        self.game.pop()
        self.game.start_level(self.play.level_index, self.play.world.difficulty_index,
                              carry_state=self.play.world.player.carry_state() if self.play.world.player.alive else None)

    def quit_to_menu(self):
        self.game.audio.play('menu_back')
        self.game.to_main_menu()

    def handle_event(self, event):
        if event.type == pg.KEYDOWN and event.key == pg.K_ESCAPE:
            self.resume_game()
            return
        self.menu.handle_event(event)

    def update(self, dt):
        super().update(dt)
        self.menu.update(dt)

    def draw(self, screen):
        if self.snapshot is not None:
            screen.blit(self.snapshot, (0, 0))
        draw_dim(screen, 150)
        self.game.fonts.heading.draw(screen, 'PAUSED', HALF_WIDTH, 120)
        self.menu.draw(screen)


# ------------------------------------------------------------------ save / load
class SaveLoadState(State):

    def __init__(self, game, mode, play=None):
        super().__init__(game)
        self.mode = mode
        self.play = play
        self.build_menu()

    def build_menu(self):
        game = self.game
        items = []
        for slot, summary in enumerate(saves.slot_summaries()):
            if summary is None:
                label = f'SLOT {slot + 1}: EMPTY'
                enabled = self.mode == 'save'
            else:
                label = f'SLOT {slot + 1}: {summary["level_name"].upper()}'
                enabled = True
            items.append(MenuItem(label, (lambda s=slot: self.choose(s)), enabled=enabled,
                                  hint=None if summary is None else f'{summary["difficulty"]}  -  {summary["date"]}'))
        items.append(MenuItem('BACK', self.back))
        self.menu = Menu(game, items, top=HALF_HEIGHT - 110, spacing=58, font=game.fonts.small_big)

    def choose(self, slot):
        if self.mode == 'save':
            if self.play is not None:
                self.game.save_game(slot, self.play)
            self.game.pop()
        else:
            self.game.load_game(slot)

    def back(self):
        self.game.audio.play('menu_back')
        self.game.pop()

    def handle_event(self, event):
        if event.type == pg.KEYDOWN and event.key == pg.K_ESCAPE:
            self.back()
            return
        self.menu.handle_event(event)

    def update(self, dt):
        super().update(dt)
        self.game.demo.update(dt)
        self.menu.update(dt)

    def draw(self, screen):
        self.game.draw_backdrop(screen, 160)
        self.game.fonts.heading.draw(screen, 'SAVE GAME' if self.mode == 'save' else 'LOAD GAME', HALF_WIDTH, 120)
        self.menu.draw(screen)


# ------------------------------------------------------------------ death
class DeathState(State):
    transparent = True

    def __init__(self, game, play):
        super().__init__(game)
        self.play = play

    def enter(self):
        self.game.set_mouse_grab(False)
        self.game.records['deaths'] = self.game.records.get('deaths', 0) + 1
        self.game.save_records()

    def handle_event(self, event):
        if event.type == pg.KEYDOWN:
            if event.key in (pg.K_RETURN, pg.K_KP_ENTER, pg.K_SPACE):
                self.game.audio.play('menu_select')
                self.game.pop()
                self.game.start_level(self.play.level_index, self.play.world.difficulty_index,
                                      carry_state=self.game.session.get('carry'))
            elif event.key == pg.K_F9:
                self.game.load_game(0)
            elif event.key == pg.K_ESCAPE:
                self.game.audio.play('menu_back')
                self.game.to_main_menu()

    def update(self, dt):
        super().update(dt)
        self.play.update(dt)      # the world keeps moving while you lie on the floor

    def draw(self, screen):
        fonts = self.game.fonts
        fonts.title.draw(screen, 'YOU DIED', HALF_WIDTH, HALF_HEIGHT - 80)
        if int(self.time / 600) % 2 == 0:
            fonts.menu.draw(screen, 'PRESS ENTER TO TRY AGAIN', HALF_WIDTH, HALF_HEIGHT + 60, 'gold')
        fonts.pixel.draw(screen, 'F9: LOAD QUICK SAVE     ESC: MAIN MENU', HALF_WIDTH, HALF_HEIGHT + 130,
                         (220, 220, 220), align='center')


# ------------------------------------------------------------------ intermission
class IntermissionState(State):
    """The classic end-of-level tally screen."""

    def __init__(self, game, play, results):
        super().__init__(game)
        self.play = play
        self.results = results
        self.level = play.level
        self.next_index = play.level_index + 1
        self.is_last = self.next_index >= len(game.episode['levels'])
        self.stage = 0            # rows revealed so far
        self.counter = 0.0
        self.stage_timer = 0.0
        self.entering = False
        self.tick_timer = 0.0
        self.background = build_texture_background(game, '4')
        stats = results
        self.rows = [
            ('KILLS', self.percent(stats['kills'], stats['kills_total'])),
            ('ITEMS', self.percent(stats['items'], stats['items_total'])),
            ('SECRETS', self.percent(stats['secrets'], stats['secrets_total'])),
        ]

    @staticmethod
    def percent(value, total):
        return 100 if total == 0 else int(100 * value / total)

    def enter(self):
        self.game.set_mouse_grab(False)
        self.game.audio.play_music('intermission')

    def handle_event(self, event):
        if event.type == pg.KEYDOWN or (event.type == pg.MOUSEBUTTONDOWN and event.button == 1):
            if self.stage < 5:
                self.stage = 5
                self.counter = 100
            elif not self.entering:
                self.entering = True
                self.game.audio.play('menu_select')
                self.stage_timer = 0.0
            else:
                self.proceed()

    def proceed(self):
        game = self.game
        if self.is_last:
            game.finish_episode()
        else:
            game.begin_level(self.next_index)

    def update(self, dt):
        super().update(dt)
        if self.entering:
            self.stage_timer += dt
            if self.stage_timer > 2500:
                self.proceed()
            return
        self.stage_timer += dt
        if self.stage < 3:
            target = self.rows[self.stage][1]
            if self.counter < target:
                self.counter = min(target, self.counter + dt * 0.12)
                self.tick_timer += dt
                if self.tick_timer > 60:
                    self.tick_timer = 0
                    self.game.audio.play('tally_tick')
            elif self.stage_timer > 500:
                self.game.audio.play('tally_done')
                self.stage += 1
                self.counter = 0.0
                self.stage_timer = 0.0
        elif self.stage < 5 and self.stage_timer > 500:
            self.stage += 1
            self.stage_timer = 0.0
            self.game.audio.play('tally_done')

    def draw(self, screen):
        screen.blit(self.background, (0, 0))
        draw_dim(screen, 110)
        fonts = self.game.fonts
        if self.entering:
            fonts.heading.draw(screen, 'ENTERING', HALF_WIDTH, HALF_HEIGHT - 80, 'gray', glow=False)
            next_level = self.game.level_data(self.next_index) if not self.is_last else None
            name = next_level.name.upper() if next_level else 'THE END'
            fonts.heading.draw(screen, name, HALF_WIDTH, HALF_HEIGHT + 10)
            return
        fonts.heading.draw(screen, self.level.name.upper(), HALF_WIDTH, 110)
        fonts.menu.draw(screen, 'FINISHED', HALF_WIDTH, 185, 'gray', glow=False)
        y = 300
        for i, (label, value) in enumerate(self.rows):
            if i > self.stage:
                break
            shown = value if i < self.stage else int(self.counter)
            fonts.menu.draw(screen, label, HALF_WIDTH - 220, y, 'red', align='right', glow=False)
            self.draw_digits(screen, f'{shown}%', HALF_WIDTH + 120, y)
            y += 90
        if self.stage >= 4:
            fonts.menu.draw(screen, 'TIME', HALF_WIDTH - 220, y, 'red', align='right', glow=False)
            self.draw_digits(screen, self.format_time(self.results['time']), HALF_WIDTH + 120, y)
            fonts.menu.draw(screen, 'PAR', HALF_WIDTH + 260, y, 'red', align='left', glow=False)
            self.draw_digits(screen, self.format_time(self.level.par_time * 1000), HALF_WIDTH + 560, y)
            y += 90
        if self.stage >= 5:
            fonts.menu.draw(screen, 'SCORE', HALF_WIDTH - 220, y, 'gold', align='right', glow=False)
            self.draw_digits(screen, str(self.results['score']), HALF_WIDTH + 120, y)
            if int(self.time / 500) % 2 == 0:
                fonts.pixel.draw(screen, 'PRESS ANY KEY TO CONTINUE', HALF_WIDTH, HEIGHT - 60, (255, 220, 120), align='center')

    def draw_digits(self, screen, text, x, y):
        size = 48
        if not hasattr(self, '_digits'):
            self._digits = {k: pg.transform.smoothscale(v, (size, size)) for k, v in self.game.assets.digits.items()}
        cx = x - size * len(text) // 2
        for ch in text:
            if ch.isdigit():
                screen.blit(self._digits[ch], (cx, y - size // 2))
            elif ch == '%':
                screen.blit(self._digits['10'], (cx, y - size // 2))
            else:
                self.game.fonts.menu.draw(screen, ch, cx + size // 2, y, 'red', glow=False)
            cx += size

    @staticmethod
    def format_time(ms):
        seconds = int(ms // 1000)
        return f'{seconds // 60}:{seconds % 60:02d}'


# ------------------------------------------------------------------ victory
class VictoryState(State):
    def __init__(self, game, totals):
        super().__init__(game)
        self.totals = totals
        from .settings import TEX_DIR
        self.image = pg.transform.smoothscale(
            game.assets.load_image(os.path.join(TEX_DIR, 'win.png'), alpha=False), (WIDTH, HEIGHT))
        self.phase = 0

    def enter(self):
        self.game.set_mouse_grab(False)
        self.game.audio.play_music('victory', loops=0)
        records = self.game.records
        if self.totals['score'] > records.get('best_score', 0):
            records['best_score'] = self.totals['score']
            self.new_record = True
        else:
            self.new_record = False
        records['wins'] = records.get('wins', 0) + 1
        self.game.save_records()

    def handle_event(self, event):
        if event.type == pg.KEYDOWN or (event.type == pg.MOUSEBUTTONDOWN and event.button == 1):
            if self.phase == 0:
                self.phase = 1
                self.game.audio.play('menu_select')
            else:
                self.game.push(CreditsState(self.game, on_done=self.game.to_title))

    def draw(self, screen):
        fonts = self.game.fonts
        if self.phase == 0:
            screen.blit(self.image, (0, 0))
            if int(self.time / 500) % 2 == 0:
                fonts.pixel.draw(screen, 'PRESS ANY KEY', HALF_WIDTH, HEIGHT - 60, (255, 220, 120), align='center')
            return
        screen.fill((10, 6, 6))
        fonts.heading.draw(screen, 'MISSION COMPLETE', HALF_WIDTH, 110)
        t = self.totals
        rows = [
            ('KILLS', f"{t['kills']} / {t['kills_total']}"),
            ('ITEMS', f"{t['items']} / {t['items_total']}"),
            ('SECRETS', f"{t['secrets']} / {t['secrets_total']}"),
            ('TIME', IntermissionState.format_time(t['time'])),
            ('DEATHS', str(t.get('deaths', 0))),
            ('SKILL', DIFFICULTIES[t['difficulty']]['name']),
            ('SCORE', str(t['score'])),
        ]
        y = 230
        for label, value in rows:
            fonts.menu.draw(screen, label, HALF_WIDTH - 60, y, 'red', align='right', glow=False)
            fonts.menu.draw(screen, value, HALF_WIDTH + 60, y, 'gold', align='left', glow=False)
            y += 70
        if self.new_record:
            fonts.small_big.draw(screen, 'NEW BEST SCORE!', HALF_WIDTH, y + 10, 'gold')
        if int(self.time / 500) % 2 == 0:
            fonts.pixel.draw(screen, 'PRESS ANY KEY FOR THE CREDITS', HALF_WIDTH, HEIGHT - 60, (255, 220, 120), align='center')
