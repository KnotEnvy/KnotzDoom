"""Player, weapons, enemies, pickups, doors and save / load round trips."""
import math

import pygame as pg

from knotzdoom.world import World


def test_player_takes_damage_and_armor_absorbs(world):
    player = world.player
    player.give_armor(100, 1)
    player.get_damage(30)
    assert player.health == 100 - (30 - 10)
    assert player.armor == 90
    assert world.fx.damage_flash > 0


def test_player_dies_at_zero(world):
    player = world.player
    player.get_damage(500)
    assert not player.alive and player.health == 0
    assert world.player_dead


def test_god_mode_blocks_damage(world):
    world.player.god = True
    world.player.get_damage(50)
    assert world.player.health == 100


def test_weapon_pickup_switches_and_gives_ammo(world):
    player = world.player
    assert player.weapon.name == 'pistol'
    assert player.give_weapon('shotgun')
    assert player.ammo['shells'] == 8
    assert player.pending_weapon == 'shotgun'
    for _ in range(40):
        player.update_weapon_switch(16)
    assert player.weapon.name == 'shotgun'
    assert not player.give_weapon('shotgun')      # already owned


def test_firing_consumes_ammo_and_hits_enemy(game, world):
    from knotzdoom.renderer import Renderer
    renderer = Renderer(game, world)
    world.renderer = renderer
    player = world.player
    npc = world.objects.npcs[0]
    # put the enemy right in front of the player
    npc.x = player.x + 2.0
    npc.y = player.y
    player.angle = 0.0
    renderer.render(player)
    assert npc.on_screen
    before = player.ammo['bullets']
    hp = npc.hp
    player.weapon.trigger = True
    player.weapon.update(16)
    assert player.ammo['bullets'] == before - 1
    assert npc.hp < hp
    assert npc.alerted


def test_out_of_ammo_switches_weapon(world):
    player = world.player
    player.ammo['bullets'] = 0
    player.give_weapon('shotgun')
    player.select_weapon('pistol', instant=True)
    player.weapon.trigger = True
    player.weapon.update(16)
    assert player.pending_weapon == 'shotgun' or player.weapon.name == 'shotgun'


def test_door_open_close_cycle(world):
    door = next(d for d in world.doors.values() if not d.locked and not d.secret)
    assert world.blocks_movement(door.pos)
    door.use(world.player)
    assert door.state == 'opening'
    for _ in range(60):
        door.update(16)
    assert door.open == 1.0 and door.state == 'open'
    assert not world.blocks_movement(door.pos)
    for _ in range(400):
        door.update(16)
    assert door.state == 'closed' and door.open == 0.0


def test_locked_door_needs_key(world):
    door = next(d for d in world.doors.values() if d.locked)
    assert not door.use(world.player)
    assert door.state == 'closed'
    world.player.keys.add(door.locked)
    assert door.use(world.player)
    assert door.state == 'opening'


def test_secret_door_counts_secret(world):
    door = next(d for d in world.doors.values() if d.secret)
    before = world.stats['secrets']
    door.use(world.player)
    door.use(world.player)
    assert world.stats['secrets'] == before + 1


def test_pickups_apply(world):
    player = world.player
    from knotzdoom.pickups import Pickup
    player.health = 50
    stim = Pickup(world, 'stimpack', player.pos)
    stim.try_pickup(player)
    assert player.health == 60 and not stim.alive
    key = Pickup(world, 'key_blue', player.pos)
    key.try_pickup(player)
    assert 'blue' in player.keys
    player.health = 100
    med = Pickup(world, 'medikit', player.pos)
    med.try_pickup(player)
    assert med.alive                                  # health full: not picked up
    world.stats['items'] = 0
    soul = Pickup(world, 'soulsphere', player.pos)
    soul.try_pickup(player)
    assert player.health == 200 and world.stats['items'] == 1


def test_rocket_explodes_on_wall_and_hurts(world):
    player = world.player
    player.angle = 0.0
    # aim at the wall directly ahead
    rocket = world.spawn_rocket(player.x, player.y, 0.0, owner='player', damage=100)
    for _ in range(200):
        world.objects.update(16)
        if not rocket.alive:
            break
    assert not rocket.alive
    assert any(p for p in world.objects.particles)    # explosion particle spawned


def test_barrel_explodes_and_chains(world):
    from knotzdoom.pickups import Barrel
    a = Barrel(world, (3.5, 3.5))
    b = Barrel(world, (4.5, 3.5))
    world.objects.props += [a, b]
    a.take_damage(50)
    for _ in range(60):
        world.objects.update(16)
    assert not a.alive and not b.alive


def test_enemy_kill_updates_stats(world):
    npc = world.objects.npcs[0]
    kills = world.stats['kills']
    npc.take_damage(10000)
    assert npc.state == 'dying'
    assert world.stats['kills'] == kills + 1
    for _ in range(200):
        npc.update(16)
    assert npc.state == 'dead'


def test_enemy_hears_gunfire(world):
    world.pathfinding.flood(world.player.map_pos)
    near = min(world.objects.npcs, key=lambda n: world.pathfinding.distance(n.map_pos) or 999)
    assert not near.alerted
    world.noise(world.player.pos, 100)
    assert near.alerted


def test_save_and_restore_round_trip(game, world):
    player = world.player
    player.give_weapon('shotgun')
    player.keys.add('blue')
    player.health = 42
    door = next(d for d in world.doors.values() if not d.locked)
    door.use(player)
    world.objects.npcs[0].take_damage(10000)
    world.objects.pickups[0].alive = False
    world.objects.update(16)
    world.stats['secrets'] = 1
    state = world.save_state()
    import json
    json.dumps(state)                                   # must be serialisable

    fresh = World(game, game.level_data(0), difficulty_index=1)
    fresh.restore_state(state)
    assert fresh.player.health == 42
    assert 'blue' in fresh.player.keys
    assert 'shotgun' in fresh.player.weapons
    assert fresh.doors[door.pos].state == 'opening'
    assert fresh.objects.npcs[0].state == 'dead'
    assert len(fresh.objects.pickups) == len(world.objects.pickups)
    assert fresh.stats['secrets'] == 1


def test_difficulty_scaling(game):
    easy = World(game, game.level_data(0), difficulty_index=0)
    hard = World(game, game.level_data(0), difficulty_index=3)
    assert len(easy.objects.npcs) < len(hard.objects.npcs)
    assert easy.objects.npcs[0].max_hp < hard.objects.npcs[0].max_hp


def test_use_action_opens_door_ahead(world):
    player = world.player
    door = next(d for d in world.doors.values() if not d.locked and not d.secret)
    # stand one tile west of the door looking east (works for the e1m1 door at 10,3)
    player.x, player.y = door.x - 0.7, door.y + 0.5
    player.angle = 0.0
    player.use()
    assert door.state == 'opening'


def test_exit_switch_finishes_level(world):
    ex = next(iter(world.level.exits))
    player = world.player
    player.x, player.y = ex[0] + 0.5, ex[1] - 0.6
    player.angle = math.pi / 2
    player.use()
    assert world.exit_triggered
