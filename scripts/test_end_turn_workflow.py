import copy
from pathlib import Path
import tempfile
import unittest
from end_turn_geometry import plan_end_turn
from offline_controller import OfflineController
from test_offline_controller import frame, policy
from test_attack_geometry import fixture
from test_ui_result import observations


def end_frame():
    inputs = fixture()
    snapshot = inputs['observation']['snapshot']
    snapshot['revision'] = 8
    inputs['calibration']['binding']['revision'] = 8
    inputs['calibration']['end_turn_box'] = [.78, .43, .84, .49]
    inputs['candidate_id'] = 'end'
    inputs['observation']['candidates'] = [{'id': 'end', 'action': 'EndTurn'}]
    before, after = observations()
    before.update({k: snapshot[k] for k in ('session_id', 'game_number', 'revision')})
    after['game_number'] = before['game_number']
    after['session_id'] = before['session_id']
    inputs['observation']['board'] = copy.deepcopy(before['game']['board'])
    return {'mode': 'end_turn', 'inputs': inputs, 'before': before, 'after': after}


class EndTurnWorkflowTests(unittest.TestCase):
    def test_spell_then_end_turn_completes_supplied_sequence_without_input(self):
        first, end = frame(7), end_frame()
        source = iter([first, first, end, end, None])
        with tempfile.TemporaryDirectory() as directory:
            result = OfflineController(directory).run(lambda: next(source), policy)
        self.assertEqual(result['status'], 'supplied_sequence_complete')
        self.assertEqual([s['mode'] for s in result['steps']], ['spell', 'end_turn'])
        self.assertEqual(result['steps'][-1]['evidence_status'], 'submission_and_handoff_observed')
        self.assertFalse(result['game_input_sent'])

    def test_unresolved_handoff_stops_sequence(self):
        end = end_frame()
        end['after']['game']['board']['turn'] = end['before']['game']['board']['turn']
        source = iter([end, end])
        with tempfile.TemporaryDirectory() as directory:
            result = OfflineController(directory).run(lambda: next(source), policy)
        self.assertEqual(result['status'], 'unresolved_action_evidence')

    def test_stale_and_invalid_button_regions_are_refused(self):
        for mutate in [lambda d: d['calibration'].update(annotation_status='unreviewed'),
                       lambda d: d['calibration'].update(end_turn_box=[0,0,float('nan'),1]),
                       lambda d: d['current_window'].update(pid=999),
                       lambda d: d['observation']['snapshot'].update(phase='OpponentTurn')]:
            inputs = end_frame()['inputs']
            mutate(inputs)
            with self.assertRaises(ValueError): plan_end_turn(**inputs)


if __name__ == '__main__': unittest.main()
