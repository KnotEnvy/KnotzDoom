"""Regression tests for the bugs found in the third-party review (findings.md)."""
import pygame as pg

from knotzdoom.npc import NPC
from knotzdoom.pickups import Barrel
from knotzdoom.states import DeathState, IntermissionState, PauseState, PlayState
from knotzdoom.world import World


def start(game, level=0):
    game.session = {'difficulty': 1, 'results': [], 'deaths': 0, 'carry': None}
    game.config['detail'] = 'high'
    game.start_level(level, 1)
    return game.state


def test_b1_dying_during_the_exit_delay_does_not_finish_the_level(game):
    play = start(game)
    world = play.world
    world.trigger_exit()
    world.player.get_damage(500)                  # cannot hurt you after the switch
    assert world.player.alive and world.player.health > 0
    world.exit_triggered = False                  # now die for real, then hit the switch while dying
    world.player.get_damage(500)
    assert not world.player.alive
    world.trigger_exit()
    for _ in range(120):
        game.frame(16)
    assert isinstance(game.state, DeathState)
    assert not any(isinstance(s, IntermissionState) for s in game.states)


def test_b2_door_closing_on_a_monster_does_not_freeze_it(game):
    world = World(game, game.level_data(0), 1)
    door = world.doors[(10, 3)]
    door.open, door.state, door.timer = 1.0, 'open', 10.0
    monster = NPC(world, 'trooper', (11.5, 3.5))
    monster.x = 11.0 + monster.radius - 0.05      # body overlaps the door tile
    world.objects.npcs = [monster]
    world.player.x, world.player.y = 20.5, 3.5
    for _ in range(80):
        world.update(16)
    assert door.state == 'open', 'a door must not close on a body'
    # even if a monster somehow ends up inside a solid tile it can still walk out
    door.open, door.state = 0.0, 'closed'
    monster.alerted = True
    start_x = monster.x
    for _ in range(300):
        world.update(16)
    assert monster.x - start_x > 1.0


def test_b3_monsters_never_path_into_props(game):
    for index in range(game.level_count):
        world = World(game, game.level_data(index), 1)
        graph = world.pathfinding.graph
        assert not any(tile in graph for tile in world.solid_tiles)
        for door in world.doors.values():
            if door.secret:
                assert door.pos not in graph
    # a barrel that blows up opens its tile again
    world = World(game, game.level_data(0), 1)
    barrel = Barrel(world, (3.5, 3.5))
    world.objects.props.append(barrel)
    world.pathfinding.refresh_tile((3, 3))
    assert (3, 3) not in world.pathfinding.graph
    barrel.explode()
    assert (3, 3) in world.pathfinding.graph


def test_b4_mouse_turn_is_independent_of_frame_rate(game):
    world = World(game, game.level_data(0), 1)
    player = world.player
    turns = []
    for dt in (33, 16, 7):
        player.angle = 1.0
        player.turn_by_pixels(10, dt)
        turns.append(player.angle - 1.0)
    assert max(turns) - min(turns) < 1e-9


def test_b7_restart_uses_the_level_start_inventory(game):
    play = start(game)
    play.world.player.score = 5000
    play.world.player.ammo['bullets'] = 180
    game.push(PauseState(game, play))
    game.state.restart()
    assert isinstance(game.state, PlayState)
    assert game.state.world.player.score == 0
    assert game.state.world.player.ammo['bullets'] == 50


def test_b8_splash_damage_needs_line_of_sight(game):
    world = World(game, game.level_data(0), 1)
    player = world.player
    player.x, player.y = 11.3, 1.5                 # wall tile (10,1) between blast and player
    world.splash_damage(9.8, 1.5, 3.0, 100)
    assert player.health == 100
    world.splash_damage(11.6, 1.5, 3.0, 100)
    assert player.health < 100


def test_b9_session_death_counter(game):
    play = start(game)
    game.push(DeathState(game, play))
    assert game.session['deaths'] == 1


def test_b10_fire_rate_does_not_depend_on_frame_rate(game):
    from knotzdoom.renderer import Renderer
    counts = []
    for dt in (16, 33):
        world = World(game, game.level_data(0), 1)
        world.renderer = Renderer(game, world)
        player = world.player
        player.give_weapon('chaingun', announce=False)
        player.select_weapon('chaingun', instant=True)
        player.ammo['bullets'] = 200
        weapon = player.weapon
        weapon.trigger = True
        elapsed = 0
        while elapsed < 2000:
            weapon.update(dt)
            elapsed += dt
        counts.append(200 - player.ammo['bullets'])
    assert abs(counts[0] - counts[1]) <= 1


def test_b15_opposite_keys_do_not_move_or_bob(game, monkeypatch):
    world = World(game, game.level_data(0), 1)
    player = world.player

    class Keys:
        def __getitem__(self, key):
            return key in (pg.K_w, pg.K_s)

    monkeypatch.setattr(pg.key, 'get_pressed', lambda: Keys())
    x, y = player.x, player.y
    player.movement(16)
    assert not player.moving and (player.x, player.y) == (x, y)


def test_b6_last_texel_columns_are_sampled(game):
    """The strip index covers the whole texture width."""
    from knotzdoom.settings import TEXTURE_SIZE
    assert int(0.999 * TEXTURE_SIZE) == TEXTURE_SIZE - 1
