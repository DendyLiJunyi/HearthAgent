import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from rehearse_attack import rehearse
from ui_attempt import run_attempt


class AttackRehearsalTests(unittest.TestCase):
    def setUp(self):
        self.inputs = json.loads((Path(__file__).resolve().parents[1] /
                                 'fixtures/attack-geometry.json').read_text())
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.receipt = Path(self.directory.name) / 'attempt.json'

    def test_recorded_gesture_is_persisted_once_without_execution_claim(self):
        result = rehearse(self.inputs, self.receipt)
        self.assertEqual(len(result['recorded_gestures']), 1)
        self.assertEqual(result['receipt']['expected_input_events'], 4)
        self.assertEqual(result['receipt']['status'], 'recorded_without_game_evidence')
        self.assertFalse(result['game_input_sent'])
        self.assertFalse(result['receipt']['execution_confirmed'])
        self.assertEqual(json.loads(self.receipt.read_text()), result['receipt'])
        with self.assertRaises(FileExistsError):
            rehearse(self.inputs, self.receipt)

    def test_changed_board_after_intent_write_cannot_record_even_if_geometry_same(self):
        changed = copy.deepcopy(self.inputs)
        changed['observation']['board']['players'][0]['in_play'][0]['damage'] = 1
        observe = Mock(side_effect=[copy.deepcopy(self.inputs), changed])
        result = rehearse(self.inputs, self.receipt, observe=observe)
        self.assertEqual(result['recorded_gestures'], [])
        self.assertEqual(result['receipt']['status'], 'preflight_failed')
        self.assertEqual(observe.call_count, 2)

    def test_three_events_are_partial_for_attack_and_do_not_collect_evidence(self):
        result = rehearse(self.inputs, self.receipt, inserted_events=3)
        self.assertEqual(result['receipt']['status'], 'partial_or_failed_input_insertion')
        self.assertNotIn('evidence', result['receipt'])
        self.assertFalse(result['receipt']['automatic_retry_allowed'])

    def test_invalid_event_count_fails_before_reservation_or_callbacks(self):
        callback = Mock()
        for count in [True, 0, -1, 33, 4.0, None]:
            with self.assertRaises(ValueError):
                run_attempt(self.receipt, {}, callback, callback, callback, expected_events=count)
        callback.assert_not_called()
        self.assertFalse(self.receipt.exists())


if __name__ == '__main__':
    unittest.main()
