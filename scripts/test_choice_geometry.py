import copy
from pathlib import Path
import tempfile
import unittest
from choice_geometry import plan_choice
from rehearse_attack import rehearse
from test_attack_geometry import fixture as attack_fixture


def fixture():
    data = attack_fixture()
    data['observation']['snapshot']['phase'] = 'Choosing'
    data['observation']['choice_preview'] = {'blocked_by': [], 'choice': {
        'choice_id': 7, 'source_card_id': 'WW_411', 'minimum': 1, 'maximum': 1,
        'offered_cards': [{'entity_id': 10, 'card_id': 'WW_325'}, {'entity_id': 20, 'card_id': 'WW_377'}]}}
    data['observation']['candidates'] = [{'id': 'choose-20', 'action': {'ChooseOptions': {'choice_id': 7, 'entities': [20]}}}]
    data['candidate_id'] = 'choose-20'
    data['calibration']['choice_id'] = 7
    data['calibration']['entities'] = [{'entity_id': 10, 'box': [.2,.3,.4,.7]}, {'entity_id': 20, 'box': [.6,.3,.8,.7]}]
    return data


class ChoiceGeometryTests(unittest.TestCase):
    def test_choose_one_records_three_events_without_input(self):
        data = fixture()
        original = copy.deepcopy(data)
        self.assertEqual(len(plan_choice(**data)['gesture']), 3)
        with tempfile.TemporaryDirectory() as directory:
            result = rehearse(data, Path(directory) / 'attempt.json', mode='choice')
        self.assertEqual(result['receipt']['expected_input_events'], 3)
        self.assertEqual(result['receipt']['status'], 'recorded_without_game_evidence')
        self.assertFalse(result['game_input_sent'])
        self.assertEqual(data, original)

    def test_changed_packet_hidden_preview_and_wrong_selection_fail(self):
        for mutate in [lambda d: d['calibration'].update(choice_id=8),
                       lambda d: d['observation']['choice_preview'].update(blocked_by=['no_current_local_choice']),
                       lambda d: d['observation']['candidates'][0]['action']['ChooseOptions'].update(entities=[99]),
                       lambda d: d['observation']['candidates'][0]['action']['ChooseOptions'].update(entities=[10,20]),
                       lambda d: d['observation']['snapshot'].update(phase='OurTurn')]:
            data = fixture()
            mutate(data)
            with self.assertRaises(ValueError): plan_choice(**data)

    def test_missing_overlapping_and_stale_boxes_fail(self):
        for mutate in [lambda d: d['calibration']['entities'].pop(),
                       lambda d: d['calibration']['entities'][0].update(box=[0,0,1,1]),
                       lambda d: d.update(frame_sha256='b'*64),
                       lambda d: d['current_window'].update(hwnd=999)]:
            data = fixture()
            mutate(data)
            with self.assertRaises(ValueError): plan_choice(**data)


if __name__ == '__main__': unittest.main()
