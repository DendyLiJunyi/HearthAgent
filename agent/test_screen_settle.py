import unittest

from agent.loop import Stop
from agent.screen import BattlefieldSettler
from agent.test_agent import Clock, Harness, game_lines, option_lines


class BattlefieldSettleTests(unittest.TestCase):
    def test_requires_a_full_quiet_interval_after_movement(self):
        clock = Clock()
        detector = BattlefieldSettler(clock=clock.time)
        self.assertFalse(detector.ready(bytes([0] * 12)))
        clock.now = 1.0
        self.assertFalse(detector.ready(bytes([0] * 12)))
        clock.now = 1.4
        self.assertFalse(detector.ready(bytes([40] * 12)))
        clock.now = 2.0
        self.assertFalse(detector.ready(bytes([40] * 12)))
        clock.now = 3.0
        self.assertTrue(detector.ready(bytes([40] * 12)))
        detector.reset()
        self.assertFalse(detector.ready(bytes([40] * 12)))

    def test_slow_drift_is_compared_to_anchor_not_previous_frame(self):
        clock = Clock()
        detector = BattlefieldSettler(clock=clock.time)
        for value in range(8):
            clock.now = value * 0.2
            self.assertFalse(detector.ready(bytes([value] * 12)))

    def test_strict_live_screen_does_not_act_on_timeout(self):
        harness = Harness(game_lines() + option_lines())
        harness.agent.strict_screen = True
        harness.agent.screen_ready = lambda: False
        self.assertEqual(harness.settled_step(), 'animating')
        harness.clock.now += 30
        with self.assertRaisesRegex(Stop, 'did not settle'):
            harness.agent.step()
        self.assertEqual(harness.inputs.gestures, [])


if __name__ == '__main__':
    unittest.main()
