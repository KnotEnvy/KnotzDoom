"""The Game: window, main loop, state stack and level / save flow."""
import json
import os
import sys
import time

import pygame as pg

from . import __version__, saves
from .assets import Assets
from .audio import Audio
from .config import Config
from .fonts import Fonts
from .level import load_episode, load_level
from .settings import BASE_DIR, DIFFICULTIES, RES, TITLE
from .view import DetailController

RECORDS_PATH = os.path.join(BASE_DIR, 'records.json')
SCREENSHOT_DIR = os.path.join(BASE_DIR, 'screenshots')


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
        self.fonts = Fonts()
        self.audio = Audio(self.config)
        self.episode = load_episode()
        self.level_cache = {}
        self.records = self.load_records()
        self.session = {}
        self.states = []
        self.running = True
        self.mouse_grabbed = False
        self.injected_events = []
        from .states import DemoBackground, TitleState
        self.demo = DemoBackground(self)
        self.push(TitleState(self))

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
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

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
        state = self.states.pop()
        state.exit()
        if self.states:
            self.states[-1].resume()

    def replace(self, state):
        if self.states:
            old = self.states.pop()
            old.exit()
        self.push(state)

    def clear_states(self):
        while self.states:
            self.states.pop().exit()

    def to_title(self):
        from .states import TitleState
        self.clear_states()
        self.push(TitleState(self))

    def to_main_menu(self):
        from .states import MainMenuState
        self.clear_states()
        self.push(MainMenuState(self))

    # ------------------------------------------------------------ game flow
    def start_new_game(self, difficulty_index):
        from .states import StoryState
        self.session = {'difficulty': difficulty_index, 'results': [], 'deaths': 0, 'carry': None,
                        'started': time.time()}
        intro = self.episode.get('intro', '')
        if intro:
            self.clear_states()
            self.push(StoryState(self, intro, on_done=lambda: self.begin_level(0), music='intermission'))
        else:
            self.begin_level(0)

    def begin_level(self, index):
        """Show the level's story text (if any), then start it."""
        from .states import StoryState
        level = self.level_data(index)
        difficulty = self.session.get('difficulty', 1)
        if level.story:
            self.clear_states()
            self.push(StoryState(self, level.story, on_done=lambda: self.start_level(index, difficulty, self.session.get('carry')),
                                 music='intermission', background=str(level.default_wall)))
        else:
            self.start_level(index, difficulty, self.session.get('carry'))

    def start_level(self, index, difficulty_index, carry_state=None, restore=None):
        from .states import PlayState
        self.session.setdefault('difficulty', difficulty_index)
        self.session.setdefault('results', [])
        self.session.setdefault('deaths', 0)
        self.session['difficulty'] = difficulty_index
        self.session['carry'] = carry_state
        self.session['level_index'] = index
        self.clear_states()
        self.push(PlayState(self, index, difficulty_index, carry_state, restore))

    def level_complete(self, play):
        from .states import IntermissionState
        world = play.world
        results = dict(world.stats)
        results['time'] = world.time
        results['score'] = world.player.score
        results['level'] = world.level.id
        self.session.setdefault('results', []).append(results)
        self.session['carry'] = world.player.carry_state()
        self.replace(IntermissionState(self, play, results))

    def finish_episode(self):
        from .states import VictoryState
        totals = {'kills': 0, 'kills_total': 0, 'items': 0, 'items_total': 0,
                  'secrets': 0, 'secrets_total': 0, 'time': 0, 'score': 0,
                  'deaths': self.session.get('deaths', 0), 'difficulty': self.session.get('difficulty', 1)}
        for result in self.session.get('results', []):
            for key in ('kills', 'kills_total', 'items', 'items_total', 'secrets', 'secrets_total', 'time'):
                totals[key] += result.get(key, 0)
            totals['score'] = result.get('score', totals['score'])
        self.clear_states()
        outro = self.episode.get('outro', '')
        if outro:
            from .states import StoryState
            self.push(StoryState(self, outro, on_done=lambda: self.replace(VictoryState(self, totals)),
                                 music='intermission', background='4'))
        else:
            self.push(VictoryState(self, totals))

    # ------------------------------------------------------------ saving
    def save_game(self, slot, play):
        world = play.world
        if not world.player.alive:
            world.message('Cannot save while dead.')
            return False
        payload = {
            'level_index': play.level_index,
            'level_name': world.level.name,
            'difficulty': world.difficulty_index,
            'difficulty_name': DIFFICULTIES[world.difficulty_index]['name'],
            'session': {k: v for k, v in self.session.items() if k != 'carry'},
            'carry': self.session.get('carry'),
            'world': world.save_state(),
        }
        saves.write_save(slot, payload)
        world.message('Game saved.' if slot else 'Quick save done.')
        self.audio.play('tally_done')
        return True

    def load_game(self, slot):
        data = saves.read_save(slot)
        if data is None:
            state = self.state
            if hasattr(state, 'world'):
                state.world.message('No saved game in that slot.')
            self.audio.play('door_locked')
            return False
        self.session = dict(data.get('session', {}))
        self.session['carry'] = data.get('carry')
        self.start_level(int(data['level_index']), int(data['difficulty']), data.get('carry'), restore=data['world'])
        self.state.world.message('Game loaded.')
        return True

    # ------------------------------------------------------------ window
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
        events = list(self.injected_events)
        self.injected_events = []
        events.extend(pg.event.get())
        for event in events:
            if event.type == pg.QUIT:
                self.quit()
                continue
            if event.type == pg.KEYDOWN and event.key == pg.K_F12:
                self.screenshot()
                continue
            state = self.state
            if state is not None:
                state.handle_event(event)
            if not self.running:
                break

    def update(self, dt):
        state = self.state
        if state is not None:
            state.update(dt)

    def draw_backdrop(self, screen, dim=170):
        """Background for overlay menus: the paused game view if we are in a
        game, otherwise the rotating demo level."""
        from .states import PauseState, draw_dim
        snapshot = None
        for state in reversed(self.states):
            if isinstance(state, PauseState) and state.snapshot is not None:
                snapshot = state.snapshot
                break
        if snapshot is not None:
            screen.blit(snapshot, (0, 0))
        else:
            self.demo.draw(screen)
        draw_dim(screen, dim)

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
