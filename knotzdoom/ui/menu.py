"""Menu widgets, the State base class and the shared MenuState."""
import math

import pygame as pg

from ..settings import HALF_HEIGHT, HALF_WIDTH, HEIGHT

_dim_cache = {}


def draw_dim(screen, alpha=150):
    """Dim a surface with a cached translucent black layer."""
    key = (screen.get_size(), int(alpha))
    dim = _dim_cache.get(key)
    if dim is None:
        dim = pg.Surface(key[0], pg.SRCALPHA)
        dim.fill((0, 0, 0, key[1]))
        _dim_cache[key] = dim
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


def is_confirm(event):
    """Any key or a left click: the 'press any key' test."""
    return event.type == pg.KEYDOWN or (event.type == pg.MOUSEBUTTONDOWN and event.button == 1)


def is_back(event):
    return event.type == pg.KEYDOWN and event.key == pg.K_ESCAPE


def is_enter(event):
    return event.type == pg.KEYDOWN and event.key in (pg.K_RETURN, pg.K_KP_ENTER, pg.K_SPACE)


def blinking(time_ms, period=500):
    return int(time_ms / period) % 2 == 0


class State:
    transparent = False        # True: the state below is drawn first

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
        for i, item in enumerate(self.items):
            if item.enabled:
                self.index = i
                break

    def move(self, direction):
        if not any(item.enabled for item in self.items):
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
            self.adjust(1)

    def adjust(self, direction):
        item = self.items[self.index]
        if item.adjust:
            self.game.audio.play('menu_move')
            item.adjust(direction)

    def handle_event(self, event):
        if event.type == pg.KEYDOWN:
            if event.key in (pg.K_UP, pg.K_w):
                self.move(-1)
            elif event.key in (pg.K_DOWN, pg.K_s):
                self.move(1)
            elif event.key in (pg.K_RETURN, pg.K_KP_ENTER, pg.K_SPACE):
                self.activate()
            elif event.key in (pg.K_LEFT, pg.K_a):
                self.adjust(-1)
            elif event.key in (pg.K_RIGHT, pg.K_d):
                self.adjust(1)
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
                pixel.draw(screen, item.value(), self.x + 300, y - pixel.height() // 2,
                           (255, 230, 140) if selected else (200, 200, 200))
                rect = rect.union(pg.Rect(self.x + 300, y - 12, 200, 24))
            self.rects.append(rect)
            if selected:
                cx = (rect.left - 34) if self.align != 'right' else rect.right + 34
                draw_skull(screen, cx, y, self.time)
        item = self.items[self.index] if self.items else None
        if item is not None and item.hint:
            pixel.draw(screen, item.hint, HALF_WIDTH, HEIGHT - 70, (200, 200, 200), align='center')


class MenuState(State):
    """A screen with a heading, one Menu and a backdrop.  Escape goes back."""

    title = ''
    title_y = 120
    dim = 170                  # backdrop dimming (None: the demo level as is)

    def __init__(self, game):
        super().__init__(game)
        self.menu = Menu(game, self.build_items(), **self.menu_layout())

    def build_items(self):
        return []

    def menu_layout(self):
        return {'top': HALF_HEIGHT - 120}

    def on_back(self):
        self.game.audio.play('menu_back')
        self.game.pop()

    def handle_event(self, event):
        if is_back(event):
            self.on_back()
        else:
            self.menu.handle_event(event)

    def update(self, dt):
        super().update(dt)
        self.game.demo.update(dt)
        self.menu.update(dt)

    def draw_backdrop(self, screen):
        if self.dim is None:
            self.game.demo.draw(screen)
        else:
            self.game.draw_backdrop(screen, self.dim)

    def draw(self, screen):
        self.draw_backdrop(screen)
        if self.title:
            self.game.fonts.heading.draw(screen, self.title, HALF_WIDTH, self.title_y)
        self.menu.draw(screen)
