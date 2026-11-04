import unittest

from agent import test_agent as helpers
from agent.loop import Stop
from agent.test_agent import Harness, game_lines, option_lines, send_line


class FocusPauseTests(unittest.TestCase):
    def test_waiting_loop_reports_focus_pause_before_terminal_interrupt(self):
        harness = Harness(game_lines() + option_lines())
        harness.inputs.ready = lambda: False
        messages = []
        harness.agent.log = messages.append
        def interrupt_after_wait(seconds):
            harness.clock.sleep(seconds)
            if harness.clock.now > 12:
                raise KeyboardInterrupt
        harness.agent.sleep = interrupt_after_wait
        with self.assertRaises(KeyboardInterrupt):
            harness.agent.run_game()
        self.assertTrue(any('another app has focus' in message for message in messages))
        self.assertEqual(harness.inputs.gestures, [])

    def test_background_pauses_and_resume_uses_new_packet(self):
        harness = Harness(game_lines() + option_lines(), after_input=[send_line()])
        focus = [False]
        harness.inputs.ready = lambda: focus[0]
        self.assertEqual(harness.settled_step(), 'paused')
        self.assertEqual(harness.inputs.gestures, [])
        harness.pending += option_lines(packet=2)
        harness.agent.step()
        focus[0] = True
        self.assertEqual(harness.agent.step(), 'settling')
        harness.clock.now += 2
        self.assertEqual(harness.agent.step(), 'acted')
        self.assertEqual(harness.agent.power.game.sends[-1]['packet']['id'], 2)

    def test_losing_focus_during_decision_does_not_send(self):
        harness = Harness(game_lines() + option_lines())
        focus = [True]
        harness.inputs.ready = lambda: focus[0]
        harness.agent.before_input = lambda event: focus.__setitem__(0, False)
        self.assertEqual(harness.settled_step(), 'paused')
        self.assertEqual(harness.inputs.gestures, [])

    def test_escape_still_stops_while_paused(self):
        harness = Harness(game_lines() + option_lines())
        harness.inputs.ready = lambda: False
        self.assertEqual(harness.settled_step(), 'paused')
        harness.inputs.aborted = lambda: True
        with self.assertRaisesRegex(Stop, 'player'):
            harness.agent.step()

    def test_menu_waits_for_focus_without_consuming_its_timeout(self):
        helper = helpers.MenuTests()
        walker, inputs = helper.walker('HUB', {'hub_buttons', 'hub_bar'})
        inputs.ready = lambda: walker.clock() >= 20
        inputs.on_click = lambda point: walker.lines.append(
            'x OnSceneLoaded() - prevMode=HUB currMode=GAMEPLAY\n')
        walker.to_game()
        self.assertGreaterEqual(walker.clock(), 20)
        self.assertEqual(len(helper.clicks(inputs)), 1)


if __name__ == '__main__':
    unittest.main()
