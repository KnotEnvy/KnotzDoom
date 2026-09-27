"""The play state and the overlays that sit on it: pause, save / load, death."""
import math
import random

import pygame as pg

from .. import saves
from ..hud import HUD
from ..renderer import Renderer
from ..settings import (DEATH_SCREEN_DELAY, EXIT_DELAY, HALF_HEIGHT, HALF_WIDTH, LEVEL_FADE_IN,
                        LEVEL_TITLE_TIME, WEAPON_BOB_X, WEAPON_BOB_Y)
from ..world import World
from .menu import MenuItem, MenuState, State, blinking, draw_dim, is_back, is_enter

CHEATS = ('iddqd', 'idkfa', 'idclip', 'iddt')
MAX_CHEAT_LEN = 8


class PlayState(State):
    def __init__(self, game, level_index, difficulty_index, carry_state=None, restore=None):
        super().__init__(game)
        self.level_index = level_index
        self.level = game.level_data(level_index)
        self.world = World(game, self.level, difficulty_index, carry_state)
        if restore:
            self.world.restore_state(restore)
        self.renderer = Renderer(game, self.world)
        self.world.renderer = self.renderer
        self.hud = HUD(game)
        self.cheat_buffer = ''
        self.fade = float(LEVEL_FADE_IN)
        self.title_timer = float(LEVEL_TITLE_TIME)
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
        player = self.world.player
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
        world = self.world
        player = world.player
        code = next((c for c in CHEATS if self.cheat_buffer.endswith(c)), None)
        if code is None:
            return
        self.cheat_buffer = ''
        if code == 'iddqd':
            player.god = not player.god
            if player.god:
                player.health = max(player.health, 100)
            world.message('Degreelessness mode ' + ('ON' if player.god else 'OFF'))
        elif code == 'idkfa':
            for name in ('shotgun', 'chaingun', 'rocket_launcher'):
                player.give_weapon(name)
            for ammo in player.ammo:
                player.ammo[ammo] = player.max_ammo[ammo]
            player.keys.update(('red', 'blue', 'yellow'))
            player.give_armor(200, 2)
            world.message('Very happy ammo added')
        elif code == 'idclip':
            player.noclip = not player.noclip
            world.message('No clipping mode ' + ('ON' if player.noclip else 'OFF'))
        elif code == 'iddt':
            world.seen_tiles.update(world.walls.keys())
            world.seen_tiles.update(world.doors.keys())
            world.message('Map revealed')
        self.game.audio.play('secret_found')

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
        self.renderer.light = 2 if world.fx.flash_ms > 0 else 0
        if world.player_dead and not self.death_shown and world.player.death_timer > DEATH_SCREEN_DELAY:
            self.death_shown = True
            self.game.push(DeathState(self.game, self))
        if world.exit_triggered and not self.finished and world.exit_timer > EXIT_DELAY and world.player.alive:
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
            bob_x = math.sin(player.bob_phase) * WEAPON_BOB_X * player.bob_amount
            bob_y = abs(math.cos(player.bob_phase)) * WEAPON_BOB_Y * player.bob_amount
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
            surf = self.game.fonts.small_big.render(f'{self.level_index + 1}: {self.level.name.upper()}', 'red')
            if self.title_timer < 600:
                surf = surf.copy()
                surf.set_alpha(int(255 * self.title_timer / 600))
            screen.blit(surf, surf.get_rect(center=(HALF_WIDTH, 70)))
        if cfg['show_fps']:
            self.hud.draw_fps(screen, self.game.clock.get_fps())
        if self.fade > 0:
            renderer.screen_overlay((0, 0, 0), 255 * self.fade / LEVEL_FADE_IN)


# ------------------------------------------------------------------ pause
class PauseState(MenuState):
    title = 'PAUSED'

    def __init__(self, game, play):
        self.play = play
        self.snapshot = None
        super().__init__(game)

    def build_items(self):
        game, play = self.game, self.play
        return [
            MenuItem('RESUME', self.on_back),
            MenuItem('SAVE GAME', lambda: game.push(SaveLoadState(game, 'save', play))),
            MenuItem('LOAD GAME', lambda: game.push(SaveLoadState(game, 'load', play))),
            MenuItem('OPTIONS', self.open_options),
            MenuItem('RESTART LEVEL', self.restart),
            MenuItem('QUIT TO MENU', self.quit_to_menu),
        ]

    def menu_layout(self):
        return {'top': HALF_HEIGHT - 130, 'spacing': 58}

    def open_options(self):
        from .screens import OptionsState
        self.game.push(OptionsState(self.game))

    def enter(self):
        self.game.set_mouse_grab(False)
        self.game.audio.pause_music()
        self.snapshot = self.game.screen.copy()
        draw_dim(self.snapshot, 150)

    def exit(self):
        self.game.audio.resume_music()

    def update(self, dt):
        State.update(self, dt)          # the frozen game does not need the demo level
        self.menu.update(dt)

    def restart(self):
        """Restart from the state the level was entered with (no farming pickups)."""
        self.game.pop()
        self.game.start_level(self.play.level_index, self.play.world.difficulty_index,
                              carry_state=self.game.session.get('carry'))

    def quit_to_menu(self):
        self.game.audio.play('menu_back')
        self.game.to_main_menu()

    def draw_backdrop(self, screen):
        screen.blit(self.snapshot, (0, 0))


# ------------------------------------------------------------------ save / load
class SaveLoadState(MenuState):
    def __init__(self, game, mode, play=None):
        self.mode = mode
        self.play = play
        super().__init__(game)

    @property
    def title(self):
        return 'SAVE GAME' if self.mode == 'save' else 'LOAD GAME'

    def build_items(self):
        items = []
        for slot, summary in enumerate(saves.slot_summaries(self.game.level_count)):
            hint = None
            if summary is None:
                label, enabled = f'SLOT {slot + 1}: EMPTY', self.mode == 'save'
            elif 'problem' in summary:
                label = f'SLOT {slot + 1}: ' + ('INCOMPATIBLE' if summary['problem'] == 'incompatible' else 'DAMAGED')
                enabled = self.mode == 'save'
            else:
                label, enabled = f'SLOT {slot + 1}: {summary["level_name"].upper()}', True
                hint = f'{summary["difficulty"]}  -  {summary["date"]}'
            items.append(MenuItem(label, (lambda s=slot: self.choose(s)), enabled=enabled, hint=hint))
        items.append(MenuItem('BACK', self.on_back))
        return items

    def menu_layout(self):
        return {'top': HALF_HEIGHT - 110, 'spacing': 58, 'font': self.game.fonts.small_big}

    def choose(self, slot):
        if self.mode == 'save':
            if self.play is not None:
                self.game.save_game(slot, self.play)
            self.game.pop()
        else:
            self.game.load_game(slot)


# ------------------------------------------------------------------ death
class DeathState(State):
    transparent = True

    def __init__(self, game, play):
        super().__init__(game)
        self.play = play

    def enter(self):
        self.game.set_mouse_grab(False)
        self.game.records['deaths'] = self.game.records.get('deaths', 0) + 1
        self.game.session['deaths'] = self.game.session.get('deaths', 0) + 1
        self.game.save_records()

    def handle_event(self, event):
        if is_enter(event):
            self.game.audio.play('menu_select')
            self.game.pop()
            self.game.start_level(self.play.level_index, self.play.world.difficulty_index,
                                  carry_state=self.game.session.get('carry'))
        elif event.type == pg.KEYDOWN and event.key == pg.K_F9:
            self.game.load_game(0)
        elif is_back(event):
            self.game.audio.play('menu_back')
            self.game.to_main_menu()

    def update(self, dt):
        super().update(dt)
        self.play.update(dt)      # the world keeps moving while you lie on the floor

    def draw(self, screen):
        fonts = self.game.fonts
        fonts.title.draw(screen, 'YOU DIED', HALF_WIDTH, HALF_HEIGHT - 80)
        if blinking(self.time, 600):
            fonts.menu.draw(screen, 'PRESS ENTER TO TRY AGAIN', HALF_WIDTH, HALF_HEIGHT + 60, 'gold')
        fonts.pixel.draw(screen, 'F9: LOAD QUICK SAVE     ESC: MAIN MENU', HALF_WIDTH, HALF_HEIGHT + 130,
                         (220, 220, 220), align='center')
