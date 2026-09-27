"""Headless walkthrough of the whole game used for development and CI.

Runs the real Game object with SDL's dummy video / audio drivers, injects
input events and saves screenshots of every state to a directory.

    python tools/smoke_test.py [output_dir]
"""
import os
import sys

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame as pg  # noqa: E402

from knotzdoom.game import Game  # noqa: E402
from knotzdoom import states  # noqa: E402


class FakeKeys:
    """Stand-in for pygame.key.get_pressed() so tests can hold keys down."""

    def __init__(self):
        self.down = set()

    def __getitem__(self, key):
        return key in self.down


def key_event(key, unicode=''):
    return pg.event.Event(pg.KEYDOWN, key=key, unicode=unicode, mod=0, scancode=0)


class Walkthrough:
    def __init__(self, out_dir):
        self.out_dir = out_dir
        os.makedirs(out_dir, exist_ok=True)
        self.game = Game(headless=True)
        self.keys = FakeKeys()
        pg.key.get_pressed = lambda: self.keys
        self.shots = []

    def run_frames(self, n, dt=16):
        for _ in range(n):
            self.game.frame(dt)

    def shot(self, name):
        path = os.path.join(self.out_dir, name + '.png')
        pg.image.save(self.game.screen, path)
        self.shots.append(path)
        return path

    def press(self, key, unicode='', frames=2):
        self.game.injected_events.append(key_event(key, unicode))
        self.run_frames(frames)

    def click(self, frames=2):
        self.game.injected_events.append(pg.event.Event(pg.MOUSEBUTTONDOWN, button=1, pos=(0, 0)))
        self.game.injected_events.append(pg.event.Event(pg.MOUSEBUTTONUP, button=1, pos=(0, 0)))
        self.run_frames(frames)

    def choose(self, index):
        """Select and activate menu item ``index`` of the current state."""
        self.game.state.menu.index = index
        self.press(pg.K_RETURN)

    def skip_stories(self):
        """Press through any story screens (intro, per-level, outro)."""
        for _ in range(6):
            if self.state_name() != 'StoryState':
                return
            self.press(pg.K_RETURN)      # finish typing
            self.press(pg.K_RETURN)      # continue
            self.run_frames(3)

    def state_name(self):
        return type(self.game.state).__name__

    def expect(self, name):
        assert self.state_name() == name, f'expected {name}, got {self.state_name()}'

    def play(self):
        g = self.game
        self.run_frames(30)
        self.expect('TitleState')
        self.shot('01_title')
        self.press(pg.K_RETURN)
        self.expect('MainMenuState')
        self.run_frames(10)
        self.shot('02_main_menu')
        # help & credits & options round trip
        self.choose(3)
        self.expect('HelpState'); self.shot('03_help'); self.press(pg.K_ESCAPE)
        self.choose(4)
        self.expect('CreditsState'); self.run_frames(60); self.shot('04_credits'); self.press(pg.K_ESCAPE)
        self.choose(2)
        self.expect('OptionsState'); self.press(pg.K_RIGHT); self.press(pg.K_LEFT); self.shot('05_options'); self.press(pg.K_ESCAPE)
        self.expect('MainMenuState')
        # new game
        self.choose(0)
        self.expect('DifficultyState'); self.shot('06_difficulty')
        self.press(pg.K_RETURN)
        self.expect('StoryState'); self.run_frames(120); self.shot('07_story')
        self.skip_stories()
        self.expect('PlayState')
        play = g.state
        self.run_frames(50)
        self.shot('08_play_start')
        # walk forward and fire
        self.keys.down.add(pg.K_w)
        self.run_frames(60)
        self.keys.down.discard(pg.K_w)
        g.injected_events.append(pg.event.Event(pg.MOUSEBUTTONDOWN, button=1, pos=(800, 450)))
        self.run_frames(3)
        self.shot('09_firing')
        g.injected_events.append(pg.event.Event(pg.MOUSEBUTTONUP, button=1, pos=(800, 450)))
        self.run_frames(40)
        # open the door in front (level 1 start looks east towards a door)
        self.keys.down.add(pg.K_w)
        self.run_frames(200)
        self.keys.down.discard(pg.K_w)
        play = g.state
        door = play.world.doors[(10, 3)]
        self.press(pg.K_e)               # opens the door unless a monster beat us to it
        assert door.state != 'closed', door.state
        self.run_frames(40)
        self.shot('10_door')
        self.keys.down.add(pg.K_w)
        self.run_frames(90)
        self.keys.down.discard(pg.K_w)
        assert play.world.player.x > 11.0, f'player should have walked through the door, x={play.world.player.x:.2f}'
        self.shot('11_after_door')
        # automap
        self.press(pg.K_TAB); self.run_frames(5); self.shot('12_automap'); self.press(pg.K_TAB)
        # cheats
        for ch in 'idkfa':
            self.press(getattr(pg, 'K_' + ch), ch, frames=1)
        self.run_frames(5)
        self.shot('13_idkfa')
        self.press(pg.K_4); self.run_frames(40)
        g.injected_events.append(pg.event.Event(pg.MOUSEBUTTONDOWN, button=1, pos=(800, 450)))
        self.run_frames(2)
        g.injected_events.append(pg.event.Event(pg.MOUSEBUTTONUP, button=1, pos=(800, 450)))
        self.run_frames(12)
        self.shot('14_rocket')
        self.run_frames(60)
        self.shot('15_explosion_after')
        # quick save / load
        self.press(pg.K_F5); self.run_frames(5); self.shot('16_saved')
        self.press(pg.K_F9); self.run_frames(10); self.expect('PlayState'); self.shot('17_loaded')
        # pause menu
        self.press(pg.K_ESCAPE); self.expect('PauseState'); self.shot('18_pause')
        self.press(pg.K_DOWN); self.press(pg.K_RETURN); self.expect('SaveLoadState'); self.shot('19_save_menu'); self.press(pg.K_ESCAPE)
        self.press(pg.K_ESCAPE); self.expect('PlayState')
        # kill the player to see the death screen
        play = g.state
        play.world.player.get_damage(500)
        self.run_frames(120)
        self.expect('DeathState'); self.shot('20_death')
        self.press(pg.K_RETURN); self.run_frames(5); self.expect('PlayState')
        # finish the level via the exit trigger to see the intermission
        play = g.state
        play.world.trigger_exit()
        self.run_frames(80)
        self.expect('IntermissionState'); self.run_frames(400); self.shot('21_intermission')
        self.press(pg.K_RETURN); self.run_frames(5); self.shot('22_entering'); self.press(pg.K_RETURN)
        self.run_frames(5)
        self.skip_stories()
        self.expect('PlayState')
        self.run_frames(30); self.shot('22b_level2')
        # outro story, victory screen and credits
        g.finish_episode(); self.run_frames(60); self.expect('StoryState'); self.shot('23_outro')
        self.press(pg.K_RETURN); self.press(pg.K_RETURN); self.expect('VictoryState'); self.run_frames(5); self.shot('24_victory')
        self.press(pg.K_RETURN); self.run_frames(5); self.shot('25_victory_stats')
        self.press(pg.K_RETURN); self.expect('CreditsState')
        print('missing assets:', len(g.assets.missing))
        for m in g.assets.missing[:20]:
            print('  ', m)
        return self.shots


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..', 'screenshots', 'smoke')
    shots = Walkthrough(out).play()
    print('\n'.join(shots))
