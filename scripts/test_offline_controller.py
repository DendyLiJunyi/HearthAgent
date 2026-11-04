import copy
from pathlib import Path
import tempfile
import unittest
from offline_controller import OfflineController
from test_rehearse_spell_result import bundle
from test_choice_geometry import fixture as choice_fixture
from test_ui_choice_result import pair as choice_pair


def frame(revision):
    inputs, before, after = bundle()
    for value in (inputs['observation']['snapshot'], inputs['calibration']['binding'], before):
        value['revision'] = revision
    return {'mode': 'spell', 'inputs': inputs, 'before': before, 'after': after}


def policy(observation):
    result = {k: observation['snapshot'][k] for k in ('session_id', 'game_number', 'revision')}
    result['candidate_id'] = observation['candidates'][0]['id']
    return result


class OfflineControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)

    def run_frames(self, frames, decide=policy):
        source = iter(frames)
        return OfflineController(self.path).run(lambda: next(source), decide)

    def test_multiple_steps_refresh_and_persist_without_game_input(self):
        first, second = frame(7), frame(8)
        report = self.run_frames([first, first, second, second, None])
        self.assertEqual(report['status'], 'supplied_sequence_complete')
        self.assertEqual(len(report['steps']), 2)
        self.assertFalse(report['game_input_sent'])
        self.assertFalse(report['execution_confirmed'])
        self.assertEqual(len(list(self.path.glob('*.json'))), 3)
        with self.assertRaises(FileExistsError): OfflineController(self.path).run(lambda: None, policy)

    def test_refresh_change_prevents_recording(self):
        first, changed = frame(7), frame(8)
        report = self.run_frames([first, changed])
        self.assertEqual(report['status'], 'state_changed_during_policy')
        self.assertEqual(report['steps'], [])

    def test_spell_then_choice_uses_distinct_event_counts(self):
        first = frame(7)
        inputs = choice_fixture()
        before, after = choice_pair()
        inputs['observation']['snapshot']['revision'] = 8
        inputs['calibration']['binding']['revision'] = 8
        before.update({k: inputs['observation']['snapshot'][k] for k in ('session_id', 'game_number', 'revision')})
        before['game']['choice_preview'] = copy.deepcopy(inputs['observation']['choice_preview'])
        after['session_id'] = before['session_id']
        second = {'mode': 'choice', 'inputs': inputs, 'before': before, 'after': after}
        report = self.run_frames([first, first, second, second, None])
        self.assertEqual(report['status'], 'supplied_sequence_complete')
        import json
        receipts = [json.loads((self.path / step['receipt']).read_text()) for step in report['steps']]
        self.assertEqual([r['expected_input_events'] for r in receipts], [4, 3])

    def test_policy_abstention_stops_without_fallback(self):
        report = self.run_frames([frame(7)], lambda _: None)
        self.assertEqual(report['status'], 'policy_abstained')
        self.assertEqual(len(list(self.path.glob('*.json'))), 1)

    def test_uncertain_result_blocks_next_supplied_action(self):
        first = frame(7)
        first['after']['game']['logged_options']['latest_submission']['selection']['target'] = 999
        report = self.run_frames([first, first, frame(8)])
        self.assertEqual(report['status'], 'unresolved_action_evidence')
        self.assertEqual(len(report['steps']), 1)

    def test_older_state_and_late_policy_never_dispatch(self):
        first = frame(7)
        report = self.run_frames([first, first, first])
        self.assertEqual(report['status'], 'repeated_or_older_state')
        clock = [0]
        def slow(observation):
            clock[0] = 2
            return policy(observation)
        report = OfflineController(self.path / 'late', budget=1, clock=lambda: clock[0]).run(lambda: copy.deepcopy(first), slow)
        self.assertEqual(report['status'], 'budget_expired')
        self.assertEqual(report['steps'], [])


if __name__ == '__main__': unittest.main()
