"""Restarting the game during `loop`. Windows, the screen, Battle.net and the menus are all replaced."""
import json
import random
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from agent import cli, restart
from agent.loop import Stop
from agent.test_agent import Clock, FirstAttack, ME, game_lines, option_lines, power, send_line
from agent.test_fast_play import replayed


def practice_game():
    rows = game_lines()
    return rows + replayed(rows) + option_lines()


class PlanTests(unittest.TestCase):
    def test_a_single_number_restarts_after_that_many_games(self):
        plan = restart.RestartPlan([3])
        self.assertEqual([plan.game_played() for _ in range(3)], [False, False, True])
        plan.restarted()
        self.assertEqual(plan.played, 0)
        self.assertFalse(plan.game_played())

    def test_each_stretch_picks_again_from_the_choices(self):
        plan = restart.RestartPlan([5, 6, 7], random.Random(1))
        targets = set()
        for _ in range(50):
            targets.add(plan.target)
            plan.restarted()
        self.assertEqual(targets, {5, 6, 7})

    def test_without_choices_no_restart_is_ever_due(self):
        plan = restart.RestartPlan(None)
        self.assertFalse(any(plan.game_played() for _ in range(100)))

    def test_parsing(self):
        self.assertEqual(restart.parse_restart_every('5,6,7'), [5, 6, 7])
        self.assertEqual(restart.parse_restart_every('6'), [6])
        for bad in ('0', '-1', '5,x', '', '5,,6'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                restart.parse_restart_every(bad)

    def test_the_command_line_rejects_a_bad_value(self):
        with mock.patch('sys.argv', ['cli', 'loop', '--games', '1', '--restart-every', '0']), \
                mock.patch('sys.stderr'), self.assertRaises(SystemExit):
            cli.main()


class CloseTests(unittest.TestCase):
    def close(self, exits_after, *, post_works=True, exits_after_force=0.0, aborted=lambda: False):
        """exits_after: seconds until the process goes once asked, or None if it never does."""
        clock = Clock()
        self.events = []
        asked_at, forced_at = [], []

        def post(hwnd):
            self.events.append(('post', hwnd))
            asked_at.append(clock.now)
            return post_works

        def force(pid):
            self.events.append(('force', pid))
            forced_at.append(clock.now)

        def running(pid):
            if forced_at and exits_after_force is not None and clock.now >= forced_at[0] + exits_after_force:
                return False
            return not (asked_at and exits_after is not None and clock.now >= asked_at[0] + exits_after)

        return restart.close_game({'hwnd': 7, 'pid': 42}, aborted, post=post, running=running, force=force,
                                  clock=clock.time, sleep=clock.sleep, log=lambda *_: None)

    def test_a_game_that_closes_when_asked_is_not_forced(self):
        self.assertEqual(self.close(3.0), 'closed')
        self.assertEqual(self.events, [('post', 7)])

    def test_a_game_that_stays_open_is_forced(self):
        self.assertEqual(self.close(None), 'forced')
        self.assertEqual(self.events, [('post', 7), ('force', 42)])

    def test_a_failed_request_goes_straight_to_forcing(self):
        self.assertEqual(self.close(None, post_works=False), 'forced')

    def test_a_game_that_survives_being_forced_stops_the_run(self):
        with self.assertRaisesRegex(Stop, 'would not close'):
            self.close(None, exits_after_force=None)

    def test_esc_stops_the_wait_and_nothing_is_forced(self):
        with self.assertRaisesRegex(Stop, 'stopped by the player'):
            self.close(None, aborted=lambda: True)
        self.assertEqual(self.events, [('post', 7)])


class SettledWindowTests(unittest.TestCase):
    def settle(self, windows, **settings):
        clock = Clock()
        feed = iter(windows)

        def get():
            item = next(feed)
            if item is None:
                raise SystemExit('exactly one visible Hearthstone window is required')
            return item
        return cli.settled_window(get, clock=clock.time, sleep=clock.sleep, **settings)

    def window(self, width=1920, height=1080, left=0):
        return {'hwnd': 1, 'left': left, 'top': 0, 'width': width, 'height': height}

    def test_waits_through_a_missing_and_a_resizing_window(self):
        good = self.window()
        windows = [None, self.window(1280, 720), self.window(1280, 720), self.window(1280, 720), good, good, good]
        self.assertEqual(self.settle(windows), good)

    def test_a_moving_window_starts_the_count_again(self):
        windows = [self.window(left=0), self.window(left=0), self.window(left=9), self.window(left=9), self.window(left=9)]
        self.assertEqual(self.settle(windows)['left'], 9)

    def test_a_window_that_never_settles_stops_the_run(self):
        with self.assertRaisesRegex(Stop, '1920x1080'):
            self.settle([self.window(1280, 720)] * 500, timeout=10)


class FakeInputs:
    careful = False

    def __init__(self, run, window):
        self.run, self.window = run, window

    def send(self, gestures):
        self.run.sent.append((self.window['hwnd'], gestures))
        self.run.write(send_line(), power(f'TAG_CHANGE Entity={ME} tag=PLAYSTATE value=WON'))

    def aborted(self):
        return self.run.esc


class FakeWalker:
    def __init__(self, run, scenes):
        self.run = run
        self.run.walker_logs.append(scenes)

    def read_scene(self):
        return self.run.scene

    def to_game(self):
        self.run.events.append('to_game')
        self.run.scene = 'GAMEPLAY'
        self.run.write(*practice_game())

    def leave_game(self):
        self.run.events.append('leave')
        if self.run.stuck_in_game_after is None or self.run.games_left_count < self.run.stuck_in_game_after:
            self.run.scene = 'HUB'
        self.run.games_left_count += 1
        if self.run.esc_after == self.run.games_left_count:
            self.run.esc = True


class FakeRecord:
    def __init__(self, *_):
        pass

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
        pass


class LoopRun:
    def __init__(self, folder, games, every):
        self.folder = Path(folder)
        self.session = 0
        self.scene = 'HUB'
        self.sent, self.events, self.walker_logs = [], [], []
        self.esc = False
        self.esc_after = None
        self.stuck_in_game_after = None
        self.games_left_count = 0
        self.close_error = None
        self.new_session()
        self.args = SimpleNamespace(policy='laya', aggressive=False, no_tactics=False, games=games, frames=False,
                                    screen_settle=1.5, pace='fast', mode='practice', idle_limit=None,
                                    deck_id='DECK', restart_every=every)

    def new_session(self):
        self.session += 1
        self.log = self.folder / f'Hearthstone_{self.session}' / 'Power.log'
        self.log.parent.mkdir(parents=True)
        self.log.write_text('', encoding='utf-8')
        self.window = {'hwnd': 100 + self.session, 'pid': 200 + self.session}

    def write(self, *rows):
        with open(self.log, 'a', encoding='utf-8') as out:
            out.write(''.join(rows))

    def close(self, window, aborted):
        self.events.append(('close', window['hwnd']))
        if self.close_error:
            raise Stop(self.close_error)
        return 'closed'

    def reopen(self):
        self.events.append('reopen')
        self.new_session()
        self.scene = None
        return self.window

    def run(self):
        policy = FirstAttack()
        policy.name = 'test'
        with mock.patch.object(cli, 'ROOT', self.folder), \
                mock.patch.object(cli, 'ensure_game', side_effect=lambda: self.window), \
                mock.patch.object(cli, 'game_window', side_effect=lambda: self.window), \
                mock.patch.object(cli, 'wait_for_focus'), \
                mock.patch.object(cli, 'GameScreen'), \
                mock.patch.object(cli, 'current_log', side_effect=lambda: self.log), \
                mock.patch.object(cli, 'build_policy', return_value=policy), \
                mock.patch.object(cli, 'SessionRecord', FakeRecord), \
                mock.patch.object(cli, 'reopen_game', side_effect=self.reopen), \
                mock.patch.object(cli, 'close_game', side_effect=self.close), \
                mock.patch.object(cli, 'bring_to_front', side_effect=lambda hwnd: self.events.append(('front', hwnd))), \
                mock.patch('agent.menu.Regions'), \
                mock.patch('agent.menu.latest_deck_id', return_value='DECK'), \
                mock.patch('agent.menu.MenuWalker', side_effect=lambda scenes, *_, **__: FakeWalker(self, scenes)), \
                mock.patch('agent.windows_input.WindowsInput', side_effect=lambda window, **_: FakeInputs(self, window)), \
                mock.patch('builtins.print'):
            cli.run_loop(self.args)
        run = next(self.folder.glob('.data/live/loop-*'))
        return json.loads((run / 'summary.json').read_text(encoding='utf-8'))


class LoopRestartTests(unittest.TestCase):
    def run_of(self, games, every):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        return LoopRun(folder.name, games, every)

    def test_restarts_on_schedule_and_finishes_every_game(self):
        run = self.run_of(14, [5])
        summary = run.run()
        self.assertEqual((summary['games'], summary['restarts'], summary['stopped']), (14, 2, None))
        self.assertEqual(run.events.count('reopen'), 2)

    def test_varied_stretches_restart_between_five_and_seven_games_apart(self):
        run = self.run_of(20, [5, 6, 7])
        summary = run.run()
        self.assertEqual((summary['games'], summary['stopped']), (20, None))
        games_per_stretch, count = [], 0
        for event in run.events:
            if event == 'leave':
                count += 1
            elif event == 'reopen':
                games_per_stretch.append(count)
                count = 0
        self.assertTrue(games_per_stretch)
        self.assertTrue(all(5 <= n <= 7 for n in games_per_stretch), games_per_stretch)
        self.assertEqual(summary['restarts'], len(games_per_stretch))

    def test_no_restart_after_the_last_game(self):
        run = self.run_of(10, [5])
        self.assertEqual(run.run()['restarts'], 1)

    def test_no_option_means_no_restart(self):
        run = self.run_of(6, None)
        self.assertEqual(run.run()['restarts'], 0)
        self.assertNotIn('reopen', run.events)

    def test_the_game_is_closed_after_leaving_the_end_screen_and_before_reopening(self):
        run = self.run_of(2, [1])
        run.run()
        leave, close, reopen = (run.events.index(e) for e in ('leave', ('close', 101), 'reopen'))
        self.assertLess(leave, close)
        self.assertLess(close, reopen)

    def test_the_new_window_and_new_log_are_used_after_a_restart(self):
        run = self.run_of(2, [1])
        run.run()
        self.assertEqual([hwnd for hwnd, _ in run.sent], [101, 102])
        self.assertEqual(len({str(scenes.path) for scenes in run.walker_logs}), 2)
        self.assertIn('Hearthstone_2', str(run.walker_logs[-1].path))
        self.assertIn(('front', 102), run.events)

    def test_a_game_scene_is_never_closed(self):
        run = self.run_of(3, [1])
        run.stuck_in_game_after = 0
        with self.assertRaises(SystemExit):
            run.run()
        self.assertFalse([e for e in run.events if isinstance(e, tuple) and e[0] == 'close'])

    def test_esc_before_a_restart_leaves_the_game_open(self):
        run = self.run_of(3, [1])
        run.esc_after = 1
        with self.assertRaises(SystemExit):
            run.run()
        self.assertFalse([e for e in run.events if isinstance(e, tuple) and e[0] == 'close'])

    def test_a_failed_restart_stops_and_saves_the_games_so_far(self):
        run = self.run_of(3, [1])
        run.close_error = 'Hearthstone would not close'
        with self.assertRaises(SystemExit):
            run.run()
        summary = json.loads(next(run.folder.glob('.data/live/loop-*/summary.json')).read_text(encoding='utf-8'))
        self.assertEqual((summary['games'], summary['stopped']), (1, 'Hearthstone would not close'))
        self.assertNotIn('reopen', run.events)


class ReopenTests(unittest.TestCase):
    def test_a_missing_window_becomes_a_stop_that_the_loop_can_report(self):
        with mock.patch.object(cli, 'ensure_game', side_effect=SystemExit('exactly one visible window')), \
                self.assertRaisesRegex(Stop, 'exactly one'):
            cli.reopen_game()


if __name__ == '__main__':
    unittest.main()
