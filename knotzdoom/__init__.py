"""KnotzDoom - a Doom-style raycasting shooter built with pygame.

Package layout:
    settings     - engine constants (resolution, FOV, ray counts, paths)
    config       - user options persisted to config.json
    assets       - texture / sprite / sound / music loading and caching
    fonts        - the glowing red "Doom" font and the small pixel font
    audio        - sound effect and music playback with volume control
    level        - level (map) loading from levels/*.json, doors, specials
    raycasting   - the wall raycaster (with sliding doors) and depth buffer
    renderer     - sky/floor/walls/sprites drawing with distance shading
    sprites      - billboard sprites, animations, particles
    player       - the player: movement, inventory, damage, "use" action
    weapons      - weapon definitions, firing, hitscan and rockets
    npc          - enemy AI (troopers, sergeants, cacodemons, knights, cyberdemon)
    projectiles  - fireballs, rockets, explosions
    pickups      - items and decorations (barrels, torches, ...)
    pathfinding  - flow-field breadth-first search from the player
    world        - ties a level, its entities and the player together
    hud          - status bar, messages, crosshair, automap
    states       - the game state machine (title, menus, play, pause, ...)
    saves        - save / load slots
    game         - the Game object and main loop
"""

__version__ = "1.0.0"
