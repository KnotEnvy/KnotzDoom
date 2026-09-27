"""Title, menus, options, help, credits, story text, the tally screen and victory."""
import os

import pygame as pg

from .. import saves
from ..fonts import format_time
from ..settings import DIFFICULTIES, HALF_HEIGHT, HALF_WIDTH, HEIGHT, TEX_DIR, WIDTH
from ..view import DETAIL_ORDER
from .demo import build_texture_background
from .menu import MenuItem, MenuState, State, blinking, is_back, is_confirm


# ------------------------------------------------------------------ title
class TitleState(State):
    def enter(self):
        self.game.set_mouse_grab(False)
        self.game.audio.play_music('menu')

    def handle_event(self, event):
        if is_back(event):
            self.game.quit()
        elif is_confirm(event):
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
        fonts.small_big.draw(screen, game.episode.get('subtitle', ''), HALF_WIDTH, HALF_HEIGHT - 40, 'gray', glow=False)
        if blinking(self.time):
            fonts.menu.draw(screen, 'PRESS ENTER', HALF_WIDTH, HALF_HEIGHT + 120, 'gold')
        fonts.pixel.draw(screen, f'KNOTZDOOM v{game.version}  -  {game.episode.get("copyright", "")}', HALF_WIDTH,
                         HEIGHT - 40, (170, 170, 170), align='center')
        best = game.records.get('best_score', 0)
        if best:
            fonts.pixel.draw(screen, f'BEST SCORE {best}', HALF_WIDTH, HEIGHT - 70, (255, 220, 120), align='center')


# ------------------------------------------------------------------ main menu
def usable_saves(game):
    return any(s is not None and 'problem' not in s for s in saves.slot_summaries(game.level_count))


class MainMenuState(MenuState):
    dim = None

    def build_items(self):
        game = self.game
        return [
            MenuItem('NEW GAME', lambda: game.push(DifficultyState(game))),
            MenuItem('LOAD GAME', lambda: game.push(SaveLoadState(game, 'load')), enabled=usable_saves(game)),
            MenuItem('OPTIONS', lambda: game.push(OptionsState(game))),
            MenuItem('HELP', lambda: game.push(HelpState(game))),
            MenuItem('CREDITS', lambda: game.push(CreditsState(game))),
            MenuItem('QUIT', game.quit),
        ]

    def enter(self):
        self.game.set_mouse_grab(False)
        self.game.audio.play_music('menu')

    def resume(self):
        self.enter()
        self.menu.items[1].enabled = usable_saves(self.game)

    def on_back(self):
        self.game.audio.play('menu_back')
        self.game.replace(TitleState(self.game))

    def draw(self, screen):
        self.game.demo.draw(screen)
        self.game.fonts.heading.draw(screen, self.game.episode.get('title', 'KNOTZDOOM'), HALF_WIDTH, 120)
        self.menu.draw(screen)


class DifficultyState(MenuState):
    title = 'CHOOSE SKILL LEVEL'
    title_y = 140
    dim = None

    def build_items(self):
        game = self.game
        return [MenuItem(d['name'], (lambda i=i: game.start_new_game(i)), hint=d['desc'])
                for i, d in enumerate(DIFFICULTIES)]

    def menu_layout(self):
        return {'top': HALF_HEIGHT - 60}

    def __init__(self, game):
        super().__init__(game)
        self.menu.index = 1


# ------------------------------------------------------------------ options
class OptionsState(MenuState):
    title = 'OPTIONS'
    title_y = 100

    def build_items(self):
        game = self.game
        cfg = game.config

        def slider(key, step, lo, hi, fmt):
            def adjust(direction):
                cfg[key] = round(max(lo, min(hi, cfg[key] + direction * step)), 3)
                game.audio.apply_volumes()
            return MenuItem(key.replace('_', ' ').upper(), value=lambda: fmt(cfg[key]), adjust=adjust)

        def toggle(key):
            def adjust(direction):
                cfg[key] = not cfg[key]
                if key == 'fullscreen':
                    game.apply_fullscreen()
            return MenuItem(key.replace('_', ' ').upper(), value=lambda: 'ON' if cfg[key] else 'OFF', adjust=adjust)

        def cycle(key, choices, label=None, fmt=str, hint=None):
            def adjust(direction):
                idx = choices.index(cfg[key]) if cfg[key] in choices else 0
                cfg[key] = choices[(idx + direction) % len(choices)]
            return MenuItem((label or key).upper(), value=lambda: fmt(cfg[key]), adjust=adjust, hint=hint)

        def bar(v):
            filled = int(round(v * 10))
            return '[' + '#' * filled + '-' * (10 - filled) + ']'

        return [
            slider('music_volume', 0.1, 0.0, 1.0, bar),
            slider('sfx_volume', 0.1, 0.0, 1.0, bar),
            slider('mouse_sensitivity', 0.1, 0.2, 3.0, lambda v: f'{v:.1f}x'),
            toggle('crosshair'),
            toggle('screen_shake'),
            toggle('head_bob'),
            toggle('always_run'),
            toggle('show_fps'),
            toggle('fullscreen'),
            cycle('fps_cap', [30, 60, 90, 120, 144, 0], label='FPS CAP', fmt=lambda v: 'UNLIMITED' if not v else str(v)),
            cycle('detail', list(DETAIL_ORDER), fmt=lambda v: str(v).upper(),
                  hint='AUTO drops to low detail when frames get slow, like the original.'),
            MenuItem('BACK', self.on_back),
        ]

    def menu_layout(self):
        return {'top': 170, 'spacing': 50, 'font': self.game.fonts.small_big, 'x': HALF_WIDTH - 120, 'align': 'right'}

    def on_back(self):
        self.game.config.save()
        super().on_back()

    def draw(self, screen):
        super().draw(screen)
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
        if is_confirm(event):
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
        y += 10
        for tip in self.game.episode.get('tips', []):
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
        if is_confirm(event):
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
        self.total = sum(len(line) + 1 for line in self.lines)

    @staticmethod
    def wrap(text, width=64):
        lines = []
        for paragraph in text.split('\n'):
            line = ''
            for word in paragraph.split(' '):
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
        if not is_confirm(event):
            return
        if not self.done_typing:
            self.done_typing = True
            self.shown = self.total
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
            if self.shown >= self.total:
                self.done_typing = True

    def draw(self, screen):
        screen.blit(self.background, (0, 0))
        from .menu import draw_dim
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
        if self.done_typing and blinking(self.time):
            self.game.fonts.pixel.draw(screen, 'PRESS ANY KEY TO CONTINUE', HALF_WIDTH, HEIGHT - 60,
                                       (255, 220, 120), align='center')


# ------------------------------------------------------------------ intermission
class IntermissionState(State):
    """The classic end-of-level tally screen."""

    def __init__(self, game, play, results):
        super().__init__(game)
        self.results = results
        self.level = play.level
        self.next_index = play.level_index + 1
        self.is_last = self.next_index >= game.level_count
        self.stage = 0            # rows revealed so far
        self.counter = 0.0
        self.stage_timer = 0.0
        self.entering = False
        self.tick_timer = 0.0
        self.background = build_texture_background(game, '4')
        self.rows = [('KILLS', self.percent(results['kills'], results['kills_total'])),
                     ('ITEMS', self.percent(results['items'], results['items_total'])),
                     ('SECRETS', self.percent(results['secrets'], results['secrets_total']))]

    @staticmethod
    def percent(value, total):
        return 100 if total == 0 else int(100 * value / total)

    def enter(self):
        self.game.set_mouse_grab(False)
        self.game.audio.play_music('intermission')

    def handle_event(self, event):
        if not is_confirm(event):
            return
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
        if self.is_last:
            self.game.finish_episode()
        else:
            self.game.begin_level(self.next_index)

    def update(self, dt):
        super().update(dt)
        self.stage_timer += dt
        if self.entering:
            if self.stage_timer > 2500:
                self.proceed()
            return
        if self.stage < 3:
            target = self.rows[self.stage][1]
            if self.counter < target:
                self.counter = min(target, self.counter + dt * 0.12)
                self.tick_timer += dt
                if self.tick_timer > 60:
                    self.tick_timer = 0
                    self.game.audio.play('tally_tick')
            elif self.stage_timer > 500:
                self.advance()
        elif self.stage < 5 and self.stage_timer > 500:
            self.advance()

    def advance(self):
        self.game.audio.play('tally_done')
        self.stage += 1
        self.counter = 0.0
        self.stage_timer = 0.0

    def draw(self, screen):
        screen.blit(self.background, (0, 0))
        from .menu import draw_dim
        draw_dim(screen, 110)
        fonts = self.game.fonts
        if self.entering:
            fonts.heading.draw(screen, 'ENTERING', HALF_WIDTH, HALF_HEIGHT - 80, 'gray', glow=False)
            name = self.game.level_data(self.next_index).name.upper() if not self.is_last else 'THE END'
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
            self.draw_digits(screen, format_time(self.results['time'], pad_minutes=False), HALF_WIDTH + 120, y)
            fonts.menu.draw(screen, 'PAR', HALF_WIDTH + 260, y, 'red', align='left', glow=False)
            self.draw_digits(screen, format_time(self.level.par_time * 1000, pad_minutes=False), HALF_WIDTH + 560, y)
            y += 90
        if self.stage >= 5:
            fonts.menu.draw(screen, 'SCORE', HALF_WIDTH - 220, y, 'gold', align='right', glow=False)
            self.draw_digits(screen, str(self.results['score']), HALF_WIDTH + 120, y)
            if blinking(self.time):
                fonts.pixel.draw(screen, 'PRESS ANY KEY TO CONTINUE', HALF_WIDTH, HEIGHT - 60, (255, 220, 120), align='center')

    def draw_digits(self, screen, text, x, y):
        font = self.game.fonts.digit_font(48)
        size = font.size
        cx = x - size * len(text) // 2
        for ch in text:
            if ch.isdigit() or ch == '%':
                font.draw(screen, ch, cx, y - size // 2, align='left')
            else:
                self.game.fonts.menu.draw(screen, ch, cx + size // 2, y, 'red', glow=False)
            cx += size


# ------------------------------------------------------------------ victory
class VictoryState(State):
    def __init__(self, game, totals):
        super().__init__(game)
        self.totals = totals
        self.image = pg.transform.smoothscale(
            game.assets.load_image(os.path.join(TEX_DIR, 'win.png'), alpha=False), (WIDTH, HEIGHT))
        self.phase = 0
        self.new_record = False

    def enter(self):
        self.game.set_mouse_grab(False)
        self.game.audio.play_music('victory', loops=0)
        records = self.game.records
        if self.totals['score'] > records.get('best_score', 0):
            records['best_score'] = self.totals['score']
            self.new_record = True
        records['wins'] = records.get('wins', 0) + 1
        self.game.save_records()

    def handle_event(self, event):
        if not is_confirm(event):
            return
        if self.phase == 0:
            self.phase = 1
            self.game.audio.play('menu_select')
        else:
            self.game.push(CreditsState(self.game, on_done=self.game.to_title))

    def draw(self, screen):
        fonts = self.game.fonts
        if self.phase == 0:
            screen.blit(self.image, (0, 0))
            if blinking(self.time):
                fonts.pixel.draw(screen, 'PRESS ANY KEY', HALF_WIDTH, HEIGHT - 60, (255, 220, 120), align='center')
            return
        screen.fill((10, 6, 6))
        fonts.heading.draw(screen, 'MISSION COMPLETE', HALF_WIDTH, 110)
        t = self.totals
        rows = [('KILLS', f"{t['kills']} / {t['kills_total']}"), ('ITEMS', f"{t['items']} / {t['items_total']}"),
                ('SECRETS', f"{t['secrets']} / {t['secrets_total']}"), ('TIME', format_time(t['time'], pad_minutes=False)),
                ('DEATHS', str(t.get('deaths', 0))), ('SKILL', DIFFICULTIES[t['difficulty']]['name']),
                ('SCORE', str(t['score']))]
        y = 230
        for label, value in rows:
            fonts.menu.draw(screen, label, HALF_WIDTH - 60, y, 'red', align='right', glow=False)
            fonts.menu.draw(screen, value, HALF_WIDTH + 60, y, 'gold', align='left', glow=False)
            y += 70
        if self.new_record:
            fonts.small_big.draw(screen, 'NEW BEST SCORE!', HALF_WIDTH, y + 10, 'gold')
        if blinking(self.time):
            fonts.pixel.draw(screen, 'PRESS ANY KEY FOR THE CREDITS', HALF_WIDTH, HEIGHT - 60, (255, 220, 120), align='center')


from .play import SaveLoadState  # noqa: E402  (main menu opens the load screen)
