import copy
import unittest
from unittest.mock import Mock
from test_ui_result import FakeClock
from test_ui_spell_result import observations
from ui_spell_result import wait_for_spell


class SpellWaitTests(unittest.TestCase):
    def wait(self, before, observe, clock, timeout=1):
        return wait_for_spell(before, 'play', 'session', observe, timeout,
                              clock=clock.clock, sleep=clock.sleep)

    def test_pending_then_complete_preserves_budget_and_baseline(self):
        before, after = observations()
        pending = copy.deepcopy(after)
        pending['game']['power_structure']['closed'] = False
        ticks = FakeClock()
        budgets = []
        def observe(remaining):
            budgets.append(remaining)
            before['game']['card_play_preview']['candidates'].clear()
            return 'session', pending if len(budgets) == 1 else after
        result = self.wait(before, observe, ticks)
        self.assertEqual(result['status'], 'submission_and_source_graveyard_observed')
        self.assertLess(budgets[1], budgets[0])
        self.assertFalse(result['automatic_retry_allowed'])

    def test_late_success_is_discarded_and_pending_times_out(self):
        before, after = observations()
        ticks = FakeClock()
        def late(remaining):
            ticks.sleep(remaining)
            return 'session', after
        self.assertEqual(self.wait(before, late, ticks)['status'], 'evidence_timeout')
        self.assertEqual(self.wait(before, lambda _: ('session', before), FakeClock())['status'], 'evidence_timeout')

    def test_session_schema_and_observer_failures_stop_without_retry(self):
        before, after = observations()
        for observe, status in [
            (Mock(return_value=('other', after)), 'session_changed'),
            (Mock(return_value=('session', {})), 'invalid_observation'),
            (Mock(side_effect=OSError('private details')), 'observation_failed')]:
            result = self.wait(before, observe, FakeClock())
            self.assertEqual(result['status'], status)
            self.assertFalse(result['execution_confirmed'])
            observe.assert_called_once()

    def test_invalid_deadlines_never_observe(self):
        before, _ = observations()
        observe = Mock()
        for value in [0, -1, 31, float('nan'), float('inf')]:
            with self.assertRaises(ValueError): self.wait(before, observe, FakeClock(), value)
        observe.assert_not_called()


if __name__ == '__main__': unittest.main()
