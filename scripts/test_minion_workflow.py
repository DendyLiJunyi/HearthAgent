import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from test_minion_geometry import fixture
from test_minion_result import pair
from test_ui_result import FakeClock
from rehearse_spell_result import run
from ui_spell_result import wait_for_minion


def bundle():
    inputs = fixture()
    before, after = pair()
    before.update(inputs['observation']['snapshot'])
    before['game']['board'] = copy.deepcopy(inputs['observation']['board'])
    before['game']['board']['invalid_fields'] = 0
    before['game']['card_play_preview']['candidates'][0]['id'] = inputs['candidate_id']
    after['session_id'] = before['session_id']
    return inputs, before, after


class MinionWorkflowTests(unittest.TestCase):
    def test_geometry_receipt_and_evidence_are_connected_once(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / 'attempt.json'
            result = run(*bundle(), receipt, mode='minion')
            self.assertEqual(result['receipt']['status'], 'submission_and_source_in_play_observed')
            self.assertFalse(result['game_input_sent'])
            self.assertFalse(result['receipt']['execution_confirmed'])
            with self.assertRaises(FileExistsError): run(*bundle(), receipt, mode='minion')

    def test_partial_gesture_and_changed_session_do_not_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            inputs, before, after = bundle()
            result = run(inputs, before, after, Path(directory) / 'partial.json',
                         inserted_events=2, mode='minion')
            self.assertNotIn('evidence', result['receipt'])
            after['session_id'] = 'other'
            result = run(inputs, before, after, Path(directory) / 'changed.json', mode='minion')
            self.assertEqual(result['receipt']['status'], 'session_changed')

    def test_mismatched_placement_and_unknown_mode_refuse_before_reservation(self):
        for mode in ('minion', 'unknown'):
            inputs, before, after = bundle()
            before['game']['card_play_preview']['candidates'][0]['action']['PlayCard']['position'] = 2
            with tempfile.TemporaryDirectory() as directory:
                receipt = Path(directory) / 'attempt.json'
                with self.assertRaises(ValueError): run(inputs, before, after, receipt, mode=mode)
                self.assertFalse(receipt.exists())

    def test_blocked_or_partial_baseline_never_creates_receipt(self):
        for partial in (True, False):
            inputs, before, after = bundle()
            if partial:
                before['ignored_partial_line'] = True
            else:
                before['game']['card_play_preview']['blocked_by'] = ['stale_options']
            with tempfile.TemporaryDirectory() as directory:
                receipt = Path(directory) / 'attempt.json'
                with self.assertRaises(ValueError):
                    run(inputs, before, after, receipt, mode='minion')
                self.assertFalse(receipt.exists())

    def test_bounded_wait_freezes_baseline_and_waits_for_closed_structure(self):
        before, after = pair()
        pending = copy.deepcopy(after)
        pending['game']['power_structure']['closed'] = False
        ticks, budgets = FakeClock(), []

        def observe(remaining):
            budgets.append(remaining)
            before['game']['card_play_preview']['candidates'].clear()
            return 'session', pending if len(budgets) == 1 else after

        result = wait_for_minion(before, 'play', 'session', observe, 1,
                                 ticks.clock, ticks.sleep)
        self.assertEqual(result['status'], 'submission_and_source_in_play_observed')
        self.assertLess(budgets[1], budgets[0])
        self.assertFalse(result['automatic_retry_allowed'])

    def test_late_evidence_and_session_changes_stop_wait(self):
        before, after = pair()
        ticks = FakeClock()

        def late(remaining):
            ticks.sleep(remaining)
            return 'session', after

        result = wait_for_minion(before, 'play', 'session', late, 1, ticks.clock, ticks.sleep)
        self.assertEqual(result['status'], 'evidence_timeout')
        observe = Mock(return_value=('other', after))
        result = wait_for_minion(before, 'play', 'session', observe)
        self.assertEqual(result['status'], 'session_changed')
        observe.assert_called_once()
        self.assertFalse(result['execution_confirmed'])


if __name__ == '__main__': unittest.main()
