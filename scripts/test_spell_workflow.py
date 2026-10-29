import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from test_attack_geometry import fixture
from test_prepare_attack_calibration import png
from prepare_attack_calibration import prepare
from spell_geometry import plan_spell
from rehearse_attack import rehearse


def spell_fixture():
    data = fixture()
    data['candidate_id'] = 'play-10-20'
    data['observation']['candidates'] = [{'id': data['candidate_id'], 'action': {
        'PlayCard': {'source': 10, 'target': 20, 'position': None}}}]
    local, enemy = data['observation']['board']['players']
    local['in_play'] = []
    local['hand'] = [{'entity_id': 10, 'card_id': 'REV_939', 'card_type': 'SPELL', 'public_zone': False}]
    enemy['in_play'][0]['card_type'] = 'MINION'
    data['calibration']['entities'][0]['box'] = [.4, .85, .5, .95]
    return data


class SpellWorkflowTests(unittest.TestCase):
    def test_prepare_review_plan_and_record_without_private_opponent_hand(self):
        data = spell_fixture()
        board = copy.deepcopy(data['observation']['board'])
        board['players'][1]['hand'] = [{'entity_id': 99, 'card_id': 'PRIVATE'}]
        snapshot = dict(data['observation']['snapshot'], protocol_version=1, status='observed_log_state',
                        backlog=False, pending_bytes=0, game={'board': board, 'card_play_preview': {
                            'blocked_by': [], 'candidates': data['observation']['candidates']}})
        probe = {'status': 'window_found', 'errors': [], 'windows': [data['current_window']]}
        draft = prepare(snapshot, probe, png(), data['candidate_id'], mode='spell')
        self.assertNotIn('PRIVATE', str(draft))
        with self.assertRaises(ValueError): plan_spell(**draft)
        draft['calibration']['annotation_status'] = 'reviewed'
        boxes = {e['entity_id']: e['box'] for e in data['calibration']['entities']}
        for entity in draft['calibration']['entities']: entity['box'] = boxes[entity['entity_id']]
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / 'attempt.json'
            result = rehearse(draft, receipt, mode='spell')
            self.assertEqual(len(result['recorded_gestures']), 1)
            self.assertFalse(result['game_input_sent'])
            with self.assertRaises(FileExistsError): rehearse(draft, receipt, mode='spell')

    def test_target_rules_and_unknown_sources_are_refused(self):
        for card in ['EX1_144', None, 'UNKNOWN']:
            data = spell_fixture()
            data['observation']['board']['players'][0]['hand'][0]['card_id'] = card
            with self.assertRaises(ValueError): plan_spell(**data)
        data = spell_fixture()
        local, enemy = data['observation']['board']['players']
        local['hand'][0]['card_id'] = 'EX1_144'
        local['in_play'], enemy['in_play'] = enemy['in_play'], []
        self.assertFalse(plan_spell(**data)['actionable'])

    def test_changed_hand_after_intent_write_cannot_record(self):
        data = spell_fixture()
        changed = copy.deepcopy(data)
        changed['observation']['board']['players'][0]['hand'][0]['card_id'] = 'JAIL_225'
        with tempfile.TemporaryDirectory() as directory:
            result = rehearse(data, Path(directory) / 'attempt.json', mode='spell',
                              observe=Mock(side_effect=[copy.deepcopy(data), changed]))
        self.assertEqual(result['recorded_gestures'], [])
        self.assertEqual(result['receipt']['status'], 'preflight_failed')

    def test_stale_frame_overlap_and_duplicate_sources_fail(self):
        for mutate in [lambda d: d.update(frame_sha256='b' * 64),
                       lambda d: d['calibration']['entities'].append({'entity_id': 99, 'box': [.4, .85, .5, .95]}),
                       lambda d: d['observation']['board']['players'][1].update(
                           hand=copy.deepcopy(d['observation']['board']['players'][0]['hand']))]:
            data = spell_fixture()
            mutate(data)
            with self.assertRaises(ValueError): plan_spell(**data)


if __name__ == '__main__': unittest.main()
