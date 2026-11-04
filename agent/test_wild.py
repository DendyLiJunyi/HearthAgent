"""Ranked Wild routing and input guards, using recorded or synthetic observations only."""
import unittest

from agent.loop import Stop
from agent.menu import MenuWalker, WILD_SCREENS, identify
from agent import test_agent as helpers
from agent.test_agent import Harness, game_lines, line, option_lines, send_line


class WildGameTests(unittest.TestCase):
    def test_lit_button_does_not_skip_opening_delay(self):
        harness = Harness(game_lines() + option_lines(), after_input=[send_line()])
        # Recreate the recorded first-turn packet with a screen that reports ready too early.
        harness.pending = [row.replace('tag=TURN value=3', 'tag=TURN value=1') for row in harness.pending]
        harness.agent.opening_delay = 20.0
        harness.agent.screen_ready = lambda: True
        self.assertEqual(harness.settled_step(), 'opening_animation')
        self.assertEqual(harness.inputs.gestures, [])
        harness.clock.now = 20.1
        self.assertEqual(harness.agent.step(), 'animating')
        self.assertEqual(harness.agent.step(), 'acted')

    def test_resuming_a_later_turn_has_no_opening_delay(self):
        harness = Harness(game_lines() + option_lines(), after_input=[send_line()])
        harness.agent.opening_delay = 20.0
        self.assertEqual(harness.settled_step(), 'acted')

    def harness(self, game_type='GT_RANKED', format_type='FT_WILD'):
        rows = game_lines(game_type)
        if format_type is not None:
            rows.append(line('DebugPrintGame', f'FormatType={format_type}'))
        harness = Harness(rows + option_lines(), after_input=[send_line()])
        harness.agent.mode = 'wild'
        return harness

    def test_ranked_wild_action_is_confirmed(self):
        harness = self.harness()
        self.assertEqual(harness.settled_step(), 'acted')
        self.assertEqual(len(harness.inputs.gestures), 1)

    def test_other_modes_and_missing_format_send_nothing(self):
        for game_type, format_type in [('GT_RANKED', 'FT_STANDARD'), ('GT_RANKED', None),
                                       ('GT_RANKED', 'FT_UNKNOWN'), ('GT_CASUAL', 'FT_WILD'),
                                       ('GT_VS_AI', 'FT_WILD'), ('GT_ARENA', 'FT_WILD'),
                                       ('GT_VS_FRIEND', 'FT_WILD')]:
            with self.subTest(game_type=game_type, format_type=format_type):
                harness = self.harness(game_type, format_type)
                harness.agent.friend_agreed = True
                with self.assertRaisesRegex(Stop, 'Ranked Wild required'):
                    harness.settled_step()
                self.assertEqual(harness.inputs.gestures, [])

    def test_unknown_local_player_is_refused(self):
        harness = self.harness()
        harness.agent.pump()
        harness.agent.power.game.local = None
        with self.assertRaisesRegex(Stop, 'local'):
            harness.agent.check_allowed(harness.agent.power.game)


class WildMenuTests(unittest.TestCase):
    def test_route_requires_wild_title_and_selected_warrior_before_queue(self):
        shown = {'wild_title', 'constructed_choose', 'wild_deck_tile', 'wild_deck_name', 'wild_start'}
        self.assertEqual(identify('TOURNAMENT', shown.__contains__, WILD_SCREENS)[1], 'wild_ready')
        shown.remove('wild_deck_name')
        self.assertEqual(identify('TOURNAMENT', shown.__contains__, WILD_SCREENS)[1], 'wild_deck_pick')
        shown.remove('wild_title')
        self.assertEqual(identify('TOURNAMENT', shown.__contains__, WILD_SCREENS)[1], 'wild_format_open')

    def test_format_picker_and_unknown_scenes(self):
        shown = {'format_wild', 'format_standard'}
        self.assertEqual(identify('TOURNAMENT', shown.__contains__, WILD_SCREENS)[3], (620, 420))
        for scene in ('ADVENTURE', 'DRAFT', 'UNKNOWN'):
            self.assertIsNone(identify(scene, shown.__contains__, WILD_SCREENS))

    def test_wild_walker_queues_and_waits_for_gameplay(self):
        helper = helpers.MenuTests()
        shown = {'wild_title', 'constructed_choose', 'wild_deck_tile', 'wild_deck_name', 'wild_start'}

        def on_click(point):
            self.assertEqual(point, (1400, 890))
            walker.lines.append('x OnSceneLoaded() - prevMode=TOURNAMENT currMode=GAMEPLAY\n')

        walker, inputs = helper.walker('TOURNAMENT', shown, on_click)
        original = walker
        walker = MenuWalker(original.scenes, original.regions, inputs, mode='wild',
                            clock=original.clock, sleep=original.sleep, log=lambda *_: None)
        walker.lines = original.lines
        walker.to_game()
        self.assertEqual(helper.clicks(inputs), [(1400, 890)])

    def test_standard_route_selects_format_then_deck_before_start(self):
        helper = helpers.MenuTests()
        shown = {'constructed_choose'}
        steps = iter([
            ((1402, 55), {'format_wild', 'format_standard'}),
            ((620, 420), {'wild_title', 'constructed_choose', 'wild_deck_tile'}),
            ((480, 280), {'wild_title', 'constructed_choose', 'wild_deck_tile', 'wild_deck_name', 'wild_start'}),
            ((1400, 890), set()),
        ])

        def on_click(point):
            expected, next_screen = next(steps)
            self.assertEqual(point, expected)
            shown.clear()
            shown.update(next_screen)
            if not next_screen:
                walker.lines.append('x OnSceneLoaded() - prevMode=TOURNAMENT currMode=GAMEPLAY\n')

        original, inputs = helper.walker('TOURNAMENT', shown, on_click)
        walker = MenuWalker(original.scenes, original.regions, inputs, mode='wild',
                            clock=original.clock, sleep=original.sleep, log=lambda *_: None)
        walker.lines = original.lines
        walker.to_game()
        self.assertEqual(len(helper.clicks(inputs)), 4)


if __name__ == '__main__':
    unittest.main()
