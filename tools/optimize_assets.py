"""Slim down the shipped assets (run once, commit the result).

- wall textures 1-5 are stored at 1024x1024 but the engine samples 256x256:
  resize them (and the 512 one) so startup does not decode 4 MiB per texture
- the candelabra prop is 897x1921 for something 0.7 walls tall: 128 px is plenty
- re-saving through pygame also strips the iCCP chunks that make libpng warn
"""
import os
import sys

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame as pg  # noqa: E402

from knotzdoom.settings import SPRITE_DIR, TEXTURE_SIZE, TEX_DIR  # noqa: E402


def resave(path, size=None, alpha=True):
    img = pg.image.load(path)
    img = img.convert_alpha() if alpha else img.convert()
    before = os.path.getsize(path)
    if size and img.get_size() != size:
        img = pg.transform.smoothscale(img, size)
    pg.image.save(img, path)
    print(f'{path}: {before // 1024} KB -> {os.path.getsize(path) // 1024} KB {img.get_size()}')


def main():
    pg.init()
    pg.display.set_mode((1, 1))
    for i in range(1, 6):
        resave(os.path.join(TEX_DIR, f'{i}.png'), (TEXTURE_SIZE, TEXTURE_SIZE))
    cand = os.path.join(SPRITE_DIR, 'static_sprites', 'candlebra.png')
    img = pg.image.load(cand)
    w, h = img.get_size()
    resave(cand, (max(1, int(w * 128 / h)), 128))
    for i in range(11):
        resave(os.path.join(TEX_DIR, 'digits', f'{i}.png'))
    for sub in ('soldier/idle', 'soldier/walk', 'soldier/attack', 'soldier/pain', 'soldier/death',
                'caco_demon/idle', 'caco_demon/walk', 'caco_demon/attack', 'caco_demon/pain', 'caco_demon/death',
                'cyber_demon/idle', 'cyber_demon/walk', 'cyber_demon/attack', 'cyber_demon/pain', 'cyber_demon/death'):
        folder = os.path.join(SPRITE_DIR, 'npc', sub)
        for name in sorted(os.listdir(folder)):
            if name.endswith('.png'):
                resave(os.path.join(folder, name))


if __name__ == '__main__':
    main()
