"""The `friend` command around the play loop. Windows, the screen and the menus are all replaced."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from agent import cli
from agent.test_agent import FirstAttack, ME, game_lines, option_lines, power, send_line
from agent.test_fast_play import replayed


def friendly_game():
    rows = game_lines('GT_VS_FRIEND', opponent='Friend#5678')
    return rows + replayed(rows) + option_lines()


def finished_game(game_type='GT_VS_FRIEND'):
    return game_lines(game_type, opponent='Friend#5678') + [power(f'TAG_CHANGE Entity={ME} tag=PLAYSTATE value=LOST')]


class FakeInputs:
    careful = False

    def __init__(self, session):
        self.session = session

    def send(self, gestures):
        self.session.sent.append(gestures)
        self.session.write(send_line(), power(f'TAG_CHANGE Entity={ME} tag=PLAYSTATE value=WON'))

    def aborted(self):
        return self.session.esc


class FakeWalker:
    def __init__(self, session):
        self.session = session

    def read_scene(self):
        return self.session.scene

    def leave_game(self):
        self.session.left += 1
        self.session.scene = 'HUB'


class FakeRecord:
    """The real record is made after the log position is chosen, which is when a challenge can start."""

    def __init__(self, session):
        self.session = session
        self.outcome = None
        if session.scene == 'GAMEPLAY':
            return  # Already in a game or on its end screen, so no new challenge can start yet.
        if session.upcoming:
            session.write(*session.upcoming.pop(0))
        elif session.args.games is None:
            session.esc = True  # Nothing else is coming, so the player ends the open session.

    def __call__(self, event):
        pass

    def screen_ready(self):
        return True

    def choice_ready(self, key):
        return True

    def reset_screen(self):
        pass

    def focus_on(self, gestures):
        pass

    def finish(self, outcome):
        self.session.outcomes.append(outcome)


class Session:
    def __init__(self, folder, earlier=(), upcoming=(), scene='HUB', games=None):
        self.folder = Path(folder)
        self.log = self.folder / 'Power.log'
        self.log.write_text(''.join(earlier), encoding='utf-8')
        self.upcoming = list(upcoming)
        self.scene = scene
        self.sent, self.outcomes = [], []
        self.left = 0
        self.esc = False
        self.args = SimpleNamespace(policy='laya', aggressive=False, no_tactics=False, games=games, frames=False,
                                    screen_settle=1.5, pace='fast')

    def write(self, *rows):
        with open(self.log, 'a', encoding='utf-8') as out:
            out.write(''.join(rows))

    def run(self):
        policy = FirstAttack()
        policy.name = 'test'
        with mock.patch.object(cli, 'ROOT', self.folder), \
                mock.patch.object(cli, 'game_window', return_value={'hwnd': 1}), \
                mock.patch.object(cli, 'GameScreen'), \
                mock.patch.object(cli, 'current_log', return_value=self.log), \
                mock.patch.object(cli, 'build_policy', return_value=policy), \
                mock.patch.object(cli, 'SessionRecord', side_effect=lambda *_: FakeRecord(self)), \
                mock.patch('agent.menu.Regions'), \
                mock.patch('agent.menu.MenuWalker', side_effect=lambda *_, **__: FakeWalker(self)), \
                mock.patch('agent.windows_input.WindowsInput', side_effect=lambda *_, **__: FakeInputs(self)), \
                mock.patch('builtins.print'):
            cli.run_friend(self.args)
        run = next(self.folder.glob('.data/live/friend-*'))
        return json.loads((run / 'summary.json').read_text(encoding='utf-8'))


class FriendSessionTests(unittest.TestCase):
    def session(self, **settings):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        return Session(folder.name, **settings)

    def test_plays_the_challenge_and_leaves_the_end_screen(self):
        session = self.session(upcoming=[friendly_game()], games=1)
        summary = session.run()
        self.assertEqual((summary['games'], summary['won'], summary['stopped']), (1, 1, None))
        self.assertEqual(session.left, 1)
        self.assertEqual(len(session.sent), 1)

    def test_a_finished_game_earlier_in_the_log_is_not_counted(self):
        session = self.session(earlier=finished_game(), upcoming=[friendly_game()], games=1)
        summary = session.run()
        self.assertEqual((summary['games'], summary['won']), (1, 1))
        self.assertEqual(len(session.sent), 1)

    def test_starting_inside_a_game_plays_it(self):
        session = self.session(earlier=friendly_game(), scene='GAMEPLAY', games=1)
        self.assertEqual(session.run()['games'], 1)
        self.assertEqual(len(session.sent), 1)

    def test_starting_on_an_end_screen_clicks_past_it_without_counting_it(self):
        session = self.session(earlier=finished_game(), scene='GAMEPLAY', upcoming=[friendly_game()], games=1)
        summary = session.run()
        self.assertEqual(session.left, 2)
        self.assertEqual((summary['games'], summary['won']), (1, 1))

    def test_games_follow_one_another_until_the_count(self):
        session = self.session(upcoming=[friendly_game(), friendly_game(), friendly_game()], games=2)
        summary = session.run()
        self.assertEqual(summary['games'], 2)
        self.assertEqual(len(session.upcoming), 1)

    def test_esc_ends_an_open_session_without_an_error_exit(self):
        session = self.session(upcoming=[friendly_game()])
        summary = session.run()
        self.assertEqual(summary['games'], 1)
        self.assertEqual(summary['stopped'], 'stopped by the player')

    def test_any_other_game_type_stops_with_an_error_and_no_input(self):
        rows = game_lines('GT_RANKED', opponent='Friend#5678')
        session = self.session(upcoming=[rows + replayed(rows) + option_lines()], games=1)
        with self.assertRaises(SystemExit) as stopped:
            session.run()
        self.assertEqual(stopped.exception.code, 2)
        self.assertEqual(session.sent, [])
        self.assertIn('friendly', session.outcomes[0]['stopped'])

    def test_the_command_cannot_start_without_the_agreement_flag(self):
        with mock.patch('sys.argv', ['cli', 'friend']), mock.patch('sys.stderr'), self.assertRaises(SystemExit):
            cli.main()


if __name__ == '__main__':
    unittest.main()
