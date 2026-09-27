"""Render top-down PNG previews of levels for review and documentation.

    python tools/level_map.py [out_dir] [level ids...]
"""
import os
import sys

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame as pg  # noqa: E402

from knotzdoom.level import DOOR_CHARS, ENEMY_KINDS, load_episode, load_level  # noqa: E402

TILE = 22
WALL_COLORS = {1: (120, 120, 125), 2: (150, 60, 50), 3: (80, 110, 80), 4: (110, 100, 70), 5: (150, 120, 90),
               6: (90, 100, 120), 7: (140, 50, 50), 8: (60, 60, 70), 9: (90, 40, 30)}
THING_COLORS = {
    'trooper': (255, 140, 60), 'sergeant': (255, 90, 30), 'cacodemon': (255, 40, 40), 'knight': (60, 220, 60),
    'cyberdemon': (255, 0, 120), 'barrel': (120, 220, 60), 'pillar': (170, 170, 170),
}


def render(level, font):
    surf = pg.Surface((level.cols * TILE, level.rows * TILE + 30))
    surf.fill((18, 18, 22))
    for y in range(level.rows):
        for x in range(level.cols):
            ch = level.char(x, y)
            rect = (x * TILE, y * TILE + 30, TILE - 1, TILE - 1)
            if (x, y) in level.walls:
                tex = level.walls[(x, y)]
                pg.draw.rect(surf, WALL_COLORS.get(tex, (90, 255, 90)) if tex < 10 else (90, 255, 90), rect)
            elif ch in DOOR_CHARS or ch == 'S':
                color = {'R': (230, 40, 40), 'B': (60, 90, 255), 'Y': (240, 210, 40), 'D': (200, 170, 90), 'S': (120, 120, 200)}[ch]
                pg.draw.rect(surf, color, rect)
            elif ch == '~':
                pg.draw.rect(surf, (45, 45, 75), rect)
            else:
                pg.draw.rect(surf, (40, 40, 46), rect)
            if ch not in '#.~123456789DRBYSX ':
                color = THING_COLORS.get(level.char_kind(ch) if hasattr(level, 'char_kind') else None, None)
                from knotzdoom.level import THING_LEGEND
                kind = THING_LEGEND.get(ch)
                color = THING_COLORS.get(kind, (200, 220, 255))
                if ch == 'P':
                    color = (255, 255, 255)
                label = font.render(ch, True, color)
                surf.blit(label, (x * TILE + 5, y * TILE + 30 + 3))
    title = font.render(f'{level.id}  {level.name}  {level.cols}x{level.rows}  enemies={level.enemy_count}  par={level.par_time}s', True, (240, 240, 240))
    surf.blit(title, (6, 6))
    return surf


def main():
    args = sys.argv[1:]
    out_dir = args[0] if args else os.path.join(os.path.dirname(__file__), '..', 'screenshots', 'maps')
    ids = args[1:] or load_episode()['levels']
    os.makedirs(out_dir, exist_ok=True)
    pg.init()
    pg.display.set_mode((1, 1))
    font = pg.font.Font(None, 20)
    for level_id in ids:
        level = load_level(level_id)
        path = os.path.join(out_dir, f'{level_id}.png')
        pg.image.save(render(level, font), path)
        print(path)


if __name__ == '__main__':
    main()
