"""Every asset referenced by the game must exist (no magenta placeholders)."""
import os

from knotzdoom.npc import NPC_DEFS
from knotzdoom.pickups import PICKUP_DEFS, PROP_DEFS
from knotzdoom.projectiles import PROJECTILE_DEFS
from knotzdoom.settings import SOUND_DIR
from knotzdoom.weapons import WEAPON_DEFS
from knotzdoom.audio import SFX_FILES


def test_all_sprites_and_textures_exist(game):
    assets = game.assets
    for d in NPC_DEFS.values():
        for anim in ('idle', 'walk', 'attack', 'pain', 'death'):
            assets.frames(f"{d['sprite']}/{anim}", d['variant'])
    for d in PICKUP_DEFS.values():
        if 'frames' in d:
            assets.frames(d['frames'])
        else:
            assets.frame(d['image'])
    for d in PROP_DEFS.values():
        if 'frames' in d:
            assets.frames(d['frames'])
        else:
            assets.frame(d['image'])
    for d in PROJECTILE_DEFS.values():
        assets.frames(d['frames'])
    for name in WEAPON_DEFS:
        assets.frames('weapon/' + name)
    for name in ('sky', 'sky_hell', 'sky_night'):
        assets.sky(name)
    assert assets.missing == [], assets.missing


def test_all_sounds_exist():
    missing = [f for f in SFX_FILES.values() if not os.path.exists(os.path.join(SOUND_DIR, f))]
    assert missing == [], missing
