"""Queue failures must interrupt menu recognition and recover without blind start clicks."""
import unittest

from agent.loop import Stop
from agent.menu import QUEUE_ERROR_CONFIRM, QUEUE_ERROR_REGIONS, STANDARD_SCREENS
from agent import test_agent as helpers


class QueueNoticeTests(unittest.TestCase):
    def walker(self, shown, on_click=None):
        walker, inputs = helpers.MenuTests().walker('TOURNAMENT', shown, on_click)
        walker.screens = STANDARD_SCREENS
        return walker, inputs

    def test_notice_takes_priority_over_visible_deck_and_retries_after_cooldown(self):
        shown = set(QUEUE_ERROR_REGIONS) | set(STANDARD_SCREENS[3][2])
        times = []

        def clicked(point):
            times.append((point, walker.clock()))
            if point == QUEUE_ERROR_CONFIRM:
                shown.difference_update(QUEUE_ERROR_REGIONS)
            else:
                walker.lines.append('OnSceneLoaded() - prevMode=TOURNAMENT currMode=GAMEPLAY')

        walker, inputs = self.walker(shown, clicked)
        walker.to_game()
        self.assertEqual([p for p, _ in times], [QUEUE_ERROR_CONFIRM, (1400, 890)])
        self.assertGreaterEqual(times[1][1] - times[0][1], 120)

    def test_persistent_notice_has_bounded_retries(self):
        walker, inputs = self.walker(set(QUEUE_ERROR_REGIONS))
        with self.assertRaisesRegex(Stop, 'three recovery attempts'):
            walker.to_game()
        self.assertEqual(helpers.MenuTests().clicks(inputs), [QUEUE_ERROR_CONFIRM] * 3)

    def test_partial_notice_does_not_get_dismissed(self):
        walker, inputs = self.walker(set(QUEUE_ERROR_REGIONS[:-1]))
        with self.assertRaisesRegex(Stop, 'unrecognized'):
            walker.to_game()
        self.assertEqual(helpers.MenuTests().clicks(inputs), [])

    def test_player_can_stop_during_cooldown(self):
        walker, inputs = self.walker(set(QUEUE_ERROR_REGIONS))
        inputs.aborted = lambda: walker.clock() > 1
        with self.assertRaisesRegex(Stop, 'stopped by the player'):
            walker.to_game()
        self.assertEqual(helpers.MenuTests().clicks(inputs), [QUEUE_ERROR_CONFIRM])

    def test_notice_appearing_after_start_is_handled_before_another_start(self):
        shown = set(STANDARD_SCREENS[3][2])
        clicks = []

        def clicked(point):
            clicks.append(point)
            if len(clicks) == 1:
                shown.update(QUEUE_ERROR_REGIONS)
            elif point == QUEUE_ERROR_CONFIRM:
                shown.difference_update(QUEUE_ERROR_REGIONS)
            else:
                walker.lines.append('OnSceneLoaded() - prevMode=TOURNAMENT currMode=GAMEPLAY')

        walker, inputs = self.walker(shown, clicked)
        walker.to_game()
        self.assertEqual(clicks, [(1400, 890), QUEUE_ERROR_CONFIRM, (1400, 890)])
