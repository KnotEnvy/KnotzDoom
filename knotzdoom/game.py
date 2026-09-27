"""The Game: window, clock, state stack and the main loop.

Level sequencing, tallies and saving live in ``flow``; the screens in ``ui``.
"""
import json
import os
import sys
import time

import pygame as pg

from . import __version__, flow
from .assets import Assets
from .audio import Audio
from .config import Config
from .fonts import Fonts
from .level import load_episode, load_level
from .settings import BASE_DIR, RECORDS_PATH, RES, SCREENSHOT_DIR, TITLE
from .ui import DemoBackground, MainMenuState, PauseState, TitleState, draw_dim
from .view import DetailController


class Game:
    def __init__(self, headless=False):
        pg.init()
        pg.font.init()
        self.headless = headless
        self.version = __version__
        self.config = Config()
        self.detail = DetailController(self.config)
        self.set_window_icon()
        self.screen = self.make_screen()
        pg.display.set_caption(TITLE)
        self.clock = pg.time.Clock()
        self.assets = Assets()
        self.fonts = Fonts(self.assets.digits)
        self.audio = Audio(self.config)
        self.episode = load_episode()
        for key in self.config.rejected:
            print(f'config.json: ignored invalid option {key!r}')
        self.level_cache = {}
        self.records = self.load_records()
        self.session = {}
        self.states = []
        self.running = True
        self.mouse_grabbed = False
        self.injected_events = []
        self.demo = DemoBackground(self)
        self.push(TitleState(self))
        self.report_missing_assets()

    def report_missing_assets(self):
        """Missing files are drawn as magenta checkerboards; say so once."""
        missing = sorted(set(self.assets.missing))
        if missing:
            print(f'WARNING: {len(missing)} asset(s) missing, drawn as placeholders:')
            for path in missing:
                print('   ', os.path.relpath(path, BASE_DIR))

    # ------------------------------------------------------------ levels
    def level_data(self, index):
        level_id = self.episode['levels'][index]
        if level_id not in self.level_cache:
            self.level_cache[level_id] = load_level(level_id)
        return self.level_cache[level_id]

    @property
    def level_count(self):
        return len(self.episode['levels'])

    # ------------------------------------------------------------ records
    def load_records(self):
        try:
            with open(RECORDS_PATH, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        records = {}
        for key in ('best_score', 'wins', 'deaths'):
            try:
                records[key] = max(0, int(data.get(key, 0)))
            except (TypeError, ValueError):
                records[key] = 0
        return records

    def save_records(self):
        try:
            with open(RECORDS_PATH, 'w', encoding='utf-8') as fh:
                json.dump(self.records, fh, indent=2)
        except OSError:
            pass

    # ------------------------------------------------------------ state stack
    @property
    def state(self):
        return self.states[-1] if self.states else None

    def push(self, state):
        self.states.append(state)
        state.enter()

    def pop(self):
        if not self.states:
            return
        self.states.pop().exit()
        if self.states:
            self.states[-1].resume()

    def replace(self, state):
        if self.states:
            self.states.pop().exit()
        self.push(state)

    def clear_states(self):
        while self.states:
            self.states.pop().exit()

    def to_title(self):
        self.clear_states()
        self.push(TitleState(self))

    def to_main_menu(self):
        self.clear_states()
        self.push(MainMenuState(self))

    # ------------------------------------------------------------ flow (see flow.py)
    def start_new_game(self, difficulty_index):
        flow.start_new_game(self, difficulty_index)

    def begin_level(self, index):
        flow.begin_level(self, index)

    def start_level(self, index, difficulty_index, carry_state=None, restore=None):
        flow.start_level(self, index, difficulty_index, carry_state, restore)

    def level_complete(self, play):
        flow.level_complete(self, play)

    def finish_episode(self):
        flow.finish_episode(self)

    def save_game(self, slot, play):
        return flow.save_game(self, slot, play)

    def load_game(self, slot):
        return flow.load_game(self, slot)

    def notify(self, text):
        """Show a message in the game if a world is on screen, else print it."""
        for state in reversed(self.states):
            world = getattr(state, 'world', None)
            if world is not None:
                world.message(text)
                return
        print(text)

    # ------------------------------------------------------------ window
    def make_screen(self):
        """Create the window.  The game renders at a fixed 1600x900; on
        smaller desktops (or in fullscreen) pygame's SCALED mode fits it to
        the display while keeping the aspect ratio."""
        if self.headless:
            return pg.display.set_mode(RES)
        flags = 0
        try:
            info = pg.display.Info()
            if self.config['fullscreen']:
                flags = pg.FULLSCREEN | pg.SCALED
            elif 0 < info.current_w < RES[0] or 0 < info.current_h < RES[1]:
                flags = pg.SCALED
            return pg.display.set_mode(RES, flags)
        except pg.error:
            return pg.display.set_mode(RES)

    def set_window_icon(self):
        try:
            icon = pg.image.load(os.path.join(BASE_DIR, 'resources', 'sprites', 'npc', 'caco_demon', '0.png'))
            pg.display.set_icon(pg.transform.smoothscale(icon, (32, 32)))
        except (pg.error, FileNotFoundError):
            pass

    def apply_fullscreen(self):
        if self.headless:
            return
        self.screen = self.make_screen()
        self.config.save()

    def draw_backdrop(self, screen, dim=170):
        """Background for overlay menus: the paused game view if we are in a
        game, otherwise the rotating demo level."""
        snapshot = next((s.snapshot for s in reversed(self.states)
                         if isinstance(s, PauseState) and s.snapshot is not None), None)
        if snapshot is not None:
            screen.blit(snapshot, (0, 0))
        else:
            self.demo.draw(screen)
        draw_dim(screen, dim)

    def set_mouse_grab(self, grab):
        self.mouse_grabbed = grab
        if self.headless:
            return
        try:
            pg.mouse.set_visible(not grab)
            pg.event.set_grab(grab)
            if grab:
                pg.mouse.get_rel()
        except pg.error:
            pass

    def screenshot(self, path=None):
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        if path is None:
            path = os.path.join(SCREENSHOT_DIR, time.strftime('shot_%Y%m%d_%H%M%S.png'))
        pg.image.save(self.screen, path)
        return path

    def quit(self):
        self.running = False

    # ------------------------------------------------------------ loop
    def check_events(self):
        events = self.injected_events
        self.injected_events = []
        events.extend(pg.event.get())
        for event in events:
            if event.type == pg.QUIT:
                self.quit()
            elif event.type == pg.KEYDOWN and event.key == pg.K_F12:
                self.screenshot()
            elif self.state is not None:
                self.state.handle_event(event)
            if not self.running:
                break

    def update(self, dt):
        if self.state is not None:
            self.state.update(dt)

    def draw(self):
        # draw from the lowest non-transparent state upwards
        start = len(self.states) - 1
        while start > 0 and self.states[start].transparent:
            start -= 1
        for state in self.states[start:]:
            state.draw(self.screen)

    def frame(self, dt=None):
        """One iteration of the loop; ``dt`` can be forced (tests)."""
        if dt is None:
            cap = int(self.config['fps_cap'])
            dt = self.clock.tick(cap) if cap else self.clock.tick()
            self.detail.record_frame(self.clock.get_rawtime())
        dt = min(dt, 60)                # never let a hitch teleport things through walls
        self.check_events()
        if not self.running:
            return
        self.update(dt)
        self.draw()
        pg.display.flip()

    def run(self):
        while self.running:
            self.frame()
        self.config.save()
        pg.quit()
        sys.exit()
