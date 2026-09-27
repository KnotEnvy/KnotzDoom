"""Game flow: new game, level sequencing, tallies, the ending, saving and loading.

These functions take the ``Game`` so ``game.py`` stays a thin shell around the
window, the clock and the state stack.
"""
import time

from . import saves
from .settings import DIFFICULTIES
from .ui import IntermissionState, PlayState, StoryState, VictoryState


def new_session(difficulty_index):
    return {'difficulty': difficulty_index, 'results': [], 'deaths': 0, 'carry': None, 'started': time.time()}


def start_new_game(game, difficulty_index):
    game.session = new_session(difficulty_index)
    intro = game.episode.get('intro', '')
    if intro:
        game.clear_states()
        game.push(StoryState(game, intro, on_done=lambda: begin_level(game, 0), music='intermission'))
    else:
        begin_level(game, 0)


def begin_level(game, index):
    """Show the level's story text (if any), then start it."""
    level = game.level_data(index)
    difficulty = game.session.get('difficulty', 1)
    if level.story:
        game.clear_states()
        game.push(StoryState(game, level.story,
                             on_done=lambda: start_level(game, index, difficulty, game.session.get('carry')),
                             music='intermission', background=str(level.default_wall)))
    else:
        start_level(game, index, difficulty, game.session.get('carry'))


def start_level(game, index, difficulty_index, carry_state=None, restore=None):
    session = game.session
    session.setdefault('results', [])
    session.setdefault('deaths', 0)
    session['difficulty'] = difficulty_index
    session['carry'] = carry_state
    session['level_index'] = index
    game.clear_states()
    game.push(PlayState(game, index, difficulty_index, carry_state, restore))


def level_complete(game, play):
    world = play.world
    results = dict(world.stats)
    results.update(time=world.time, score=world.player.score, level=world.level.id)
    game.session.setdefault('results', []).append(results)
    game.session['carry'] = world.player.carry_state()
    game.replace(IntermissionState(game, play, results))


def finish_episode(game):
    totals = {'kills': 0, 'kills_total': 0, 'items': 0, 'items_total': 0, 'secrets': 0, 'secrets_total': 0,
              'time': 0, 'score': 0, 'deaths': game.session.get('deaths', 0),
              'difficulty': game.session.get('difficulty', 1)}
    for result in game.session.get('results', []):
        for key in ('kills', 'kills_total', 'items', 'items_total', 'secrets', 'secrets_total', 'time'):
            totals[key] += result.get(key, 0)
        totals['score'] = result.get('score', totals['score'])
    game.clear_states()
    outro = game.episode.get('outro', '')
    if outro:
        game.push(StoryState(game, outro, on_done=lambda: game.replace(VictoryState(game, totals)),
                             music='intermission', background='4'))
    else:
        game.push(VictoryState(game, totals))


# ------------------------------------------------------------------ saving
def save_game(game, slot, play):
    world = play.world
    if not world.player.alive:
        world.message('Cannot save while dead.')
        return False
    payload = {
        'level_index': play.level_index,
        'level_name': world.level.name,
        'level_hash': saves.level_fingerprint(world.level),
        'difficulty': world.difficulty_index,
        'difficulty_name': DIFFICULTIES[world.difficulty_index]['name'],
        'session': {k: v for k, v in game.session.items() if k != 'carry'},
        'carry': game.session.get('carry'),
        'world': world.save_state(),
    }
    try:
        saves.write_save(slot, payload)
    except OSError as exc:
        world.message(f'Could not save: {exc}')
        game.audio.play('door_locked')
        return False
    world.message('Game saved.' if slot else 'Quick save done.')
    game.audio.play('tally_done')
    return True


LOAD_PROBLEMS = {'empty': 'No saved game in that slot.',
                 'incompatible': 'That save is from an older version of the game.',
                 'corrupt': 'That save file is damaged.'}


def load_game(game, slot):
    data, problem = saves.read_save_status(slot, game.level_count)
    if data is None:
        game.notify(LOAD_PROBLEMS.get(problem, 'Cannot load that save.'))
        game.audio.play('door_locked')
        return False
    level = game.level_data(data['level_index'])
    if data.get('level_hash') not in (None, saves.level_fingerprint(level)):
        game.notify('That save was made on a different version of the level.')
        game.audio.play('door_locked')
        return False
    game.session = dict(data.get('session', {}))
    game.session['carry'] = data.get('carry')
    start_level(game, data['level_index'], data['difficulty'], data.get('carry'), restore=data['world'])
    game.state.world.message('Game loaded.')
    return True
