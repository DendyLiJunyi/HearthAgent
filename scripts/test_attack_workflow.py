import copy
import json
from pathlib import Path
import tempfile
import unittest
from test_audit_attacks import CREATE, SEND, START, END, row
from test_offline_controller import policy
from offline_controller import OfflineController
from ui_attack_result import assess_attack


def frame():
    inputs = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/attack-geometry.json').read_text())
    submission = row()
    submission['submission']['correlation']['packet_id'] = 10
    before = dict(inputs['observation']['snapshot'], game={
        'board': copy.deepcopy(inputs['observation']['board']),
        'logged_options': {'submissions_seen': 0, 'latest': {'id': 10}},
        'power_structure': {'closed': True}})
    after = copy.deepcopy(before)
    after['game']['logged_options'].update(submissions_seen=1, latest_submission=submission['submission'])
    return {'mode': 'attack', 'inputs': inputs, 'before': before, 'after': after,
            'attack_evidence': {'before_log': CREATE, 'after_log': CREATE + SEND + START + END,
                                'before_submissions': [], 'after_submissions': [submission]}}


class AttackWorkflowTests(unittest.TestCase):
    def assess(self, value):
        return assess_attack(value['before'], value['after'], {'source': 10, 'target': 20}, value['attack_evidence'])

    def test_matching_attack_advances_recording_controller(self):
        value = frame()
        with tempfile.TemporaryDirectory() as directory:
            source = iter([value, value, None])
            result = OfflineController(directory).run(lambda: next(source), policy)
            self.assertEqual(result['status'], 'supplied_sequence_complete')
            self.assertFalse(result['game_input_sent'])
            self.assertEqual(result['steps'][0]['evidence_status'], 'matching_attack_block_closed')

    def test_unfinished_wrong_target_and_partial_logs_do_not_pass(self):
        for suffix in (START, START.replace('Target=20', 'Target=99') + END, START + END.rstrip()):
            value = frame()
            value['attack_evidence']['after_log'] = CREATE + SEND + suffix
            self.assertNotEqual(self.assess(value)['status'], 'matching_attack_block_closed')

    def test_evidence_binding_rejects_other_packet_game_and_prefix(self):
        for change in ('packet', 'game', 'prefix', 'count'):
            value = frame()
            if change == 'packet': value['before']['game']['logged_options']['latest']['id'] = 99
            if change == 'game': value['after']['game_number'] = 2
            if change == 'prefix': value['attack_evidence']['before_log'] += END
            if change == 'count': value['after']['game']['logged_options']['submissions_seen'] = 2
            self.assertNotEqual(self.assess(value)['status'], 'matching_attack_block_closed')


if __name__ == '__main__': unittest.main()
