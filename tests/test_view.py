"""View geometry and the automatic detail controller."""
import math

from knotzdoom.settings import FOV, HALF_FOV, HEIGHT, WIDTH
from knotzdoom.view import DetailController, View


def test_full_detail_draws_on_the_window(game):
    view = View(game.screen, 1)
    assert view.surface is game.screen and not view.scaled
    assert view.num_rays == WIDTH // 2
    assert abs(view.screen_dist - (WIDTH // 2) / math.tan(HALF_FOV)) < 1e-9
    assert abs(view.delta_angle * view.num_rays - FOV) < 1e-9


def test_low_detail_uses_half_size_surface(game):
    view = View(game.screen, 2)
    assert view.scaled
    assert view.surface.get_size() == (WIDTH // 2, HEIGHT // 2)
    assert view.num_rays == WIDTH // 4
    view.surface.fill((10, 20, 30))
    view.present()
    assert game.screen.get_at((WIDTH - 1, HEIGHT - 1))[:3] == (10, 20, 30)
    assert view.to_screen(10, 5) == (20, 10)


class FakeConfig(dict):
    pass


def test_detail_controller_follows_config_and_auto_mode():
    cfg = FakeConfig(detail='low')
    ctl = DetailController(cfg)
    assert ctl.divisor == 2
    cfg['detail'] = 'high'
    assert ctl.divisor == 1
    cfg['detail'] = 'auto'
    assert ctl.divisor == 1
    # sustained slow frames drop to low detail
    changed = False
    for _ in range(200):
        changed = ctl.record_frame(30.0) or changed
    assert changed and ctl.divisor == 2
    # sustained fast frames climb back
    changed = False
    for _ in range(400):
        changed = ctl.record_frame(4.0) or changed
    assert changed and ctl.divisor == 1
