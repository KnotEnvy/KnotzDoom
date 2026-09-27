"""Flow field pathfinding."""


def test_flow_field_distances_decrease_towards_player(world):
    pf = world.pathfinding
    pf.flood(world.player.map_pos)
    assert pf.distance(world.player.map_pos) == 0
    far = max(pf.dist, key=pf.dist.get)
    tile = far
    steps = 0
    while tile != world.player.map_pos and steps < 500:
        nxt = pf.next_step(tile)
        assert nxt is not None
        assert pf.distance(nxt) < pf.distance(tile)
        tile = nxt
        steps += 1
    assert tile == world.player.map_pos


def test_no_corner_cutting(world):
    pf = world.pathfinding
    for tile, neighbours in pf.graph.items():
        x, y = tile
        for nx, ny in neighbours:
            dx, dy = nx - x, ny - y
            if dx and dy:
                assert pf.passable((x + dx, y)) and pf.passable((x, y + dy))


def test_locked_doors_block_monsters(world):
    pf = world.pathfinding
    for pos, door in world.doors.items():
        if door.locked or door.secret:
            assert pos not in pf.graph        # monsters neither unlock doors nor give away secrets
        else:
            assert pos in pf.graph


def test_occupied_tiles_are_avoided(world):
    pf = world.pathfinding
    pf.flood(world.player.map_pos)
    px, py = world.player.map_pos
    tile = (px + 3, py)
    if tile in pf.graph:
        best = pf.next_step(tile)
        alt = pf.next_step(tile, occupied={best})
        assert alt != best
