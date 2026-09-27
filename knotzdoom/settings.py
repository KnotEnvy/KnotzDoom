"""Engine-wide constants.

Everything that depends on the resolution is derived here so that the rest of
the engine can simply ``from knotzdoom.settings import *``.
"""
import math
import os

# ---------------------------------------------------------------- paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES_DIR = os.path.join(BASE_DIR, 'resources')
TEX_DIR = os.path.join(RES_DIR, 'textures')
SPRITE_DIR = os.path.join(RES_DIR, 'sprites')
SOUND_DIR = os.path.join(RES_DIR, 'sound')
MUSIC_DIR = os.path.join(RES_DIR, 'music')
LEVEL_DIR = os.path.join(BASE_DIR, 'levels')
# user data (saves, options, records) lives next to the game unless KNOTZDOOM_DATA_DIR says otherwise
DATA_DIR = os.environ.get('KNOTZDOOM_DATA_DIR', BASE_DIR)
SAVE_DIR = os.path.join(DATA_DIR, 'saves')
CONFIG_PATH = os.path.join(DATA_DIR, 'config.json')
RECORDS_PATH = os.path.join(DATA_DIR, 'records.json')
SCREENSHOT_DIR = os.path.join(BASE_DIR, 'screenshots')

# ---------------------------------------------------------------- display
RES = WIDTH, HEIGHT = 1600, 900
HALF_WIDTH = WIDTH // 2
HALF_HEIGHT = HEIGHT // 2
FPS = 60                      # frame cap (0 = uncapped)
TITLE = 'KnotzDoom'

# ---------------------------------------------------------------- player
PLAYER_SPEED = 0.004          # world units per millisecond
PLAYER_SPRINT_MULT = 1.45
PLAYER_ROT_SPEED = 0.0025       # radians per millisecond (arrow keys)
PLAYER_RADIUS = 0.25          # collision radius in world units
PLAYER_MAX_HEALTH = 100
PLAYER_SUPER_HEALTH = 200
PLAYER_MAX_ARMOR = 200

MOUSE_RAD_PER_PIXEL = 0.005     # turn per mouse pixel, independent of frame rate
MOUSE_MAX_PIXELS_PER_SEC = 2500 # flicks faster than this are clamped
MOUSE_BORDER = 100              # re-centre the cursor when it gets this close to an edge

# ---------------------------------------------------------------- raycasting
# (ray counts, column width and projection distance depend on the detail level
#  and live in view.View)
FOV = math.pi / 3
HALF_FOV = FOV / 2
MAX_DEPTH = 24                # tiles a ray travels before giving up
TEXTURE_SIZE = 256

# ---------------------------------------------------------------- lighting
SHADE_LEVELS = 10             # number of pre-darkened texture copies
SHADE_MAX_DEPTH = 14.0        # depth at which walls reach the darkest level
SHADE_MIN_BRIGHT = 0.12       # brightness of the darkest level (0..1)

# ---------------------------------------------------------------- hud
STATUS_BAR_HEIGHT = 96         # the 3d view is drawn full screen; the bar overlays it

# ---------------------------------------------------------------- gameplay
DOOR_OPEN_TIME = 450           # ms for a door to slide fully open
DOOR_STAY_OPEN = 4000          # ms a door stays open before closing
DOOR_PASSABLE = 0.9            # open fraction from which things can walk through
DOOR_SLAB_THICKNESS = 0.12     # half thickness of the slab that stops shots and rockets
USE_DISTANCE = 1.2             # how far the "use" action reaches

DIFFICULTIES = [
    # name, description, enemy hp mult, enemy damage mult, ammo mult, enemy speed mult, skip every nth enemy
    {'name': 'ROOKIE',    'desc': 'Half damage, double ammo.',        'hp': 0.8, 'dmg': 0.5,  'ammo': 2.0, 'speed': 0.9,  'skip': 3},
    {'name': 'MARINE',    'desc': 'The way it is meant to be played.', 'hp': 1.0, 'dmg': 1.0,  'ammo': 1.0, 'speed': 1.0,  'skip': 0},
    {'name': 'VETERAN',   'desc': 'Tougher demons, less ammo.',        'hp': 1.2, 'dmg': 1.25, 'ammo': 0.8, 'speed': 1.1,  'skip': 0},
    {'name': 'NIGHTMARE', 'desc': 'Fast, brutal and unforgiving.',     'hp': 1.4, 'dmg': 1.6,  'ammo': 0.7, 'speed': 1.35, 'skip': 0},
]
