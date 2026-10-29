import unittest
import tempfile
from pathlib import Path
from rehearse_attack import rehearse
from test_spell_workflow import spell_fixture
from minion_geometry import plan_minion


def fixture():
    data = spell_fixture()
    data['observation']['board']['players'][0]['hand'][0].update(card_type='MINION', card_id='LOOT_412')
    data['observation']['candidates'][0]['action']['PlayCard'].update(target=None, position=1)
    data['calibration']['minion_drop_boxes'] = [[.45, .5, .55, .6]]
    return data


class MinionGeometryTests(unittest.TestCase):
    def test_rehearsal_records_minion_placement_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'attempt.json'
            result = rehearse(fixture(), path, mode='minion')
            self.assertEqual(result['receipt']['source'], 'offline_minion_rehearsal')
            self.assertEqual(len(result['recorded_gestures']), 1)
            self.assertFalse(result['game_input_sent'])
            with self.assertRaises(FileExistsError): rehearse(fixture(), path, mode='minion')

    def test_empty_board_maps_only_slot_without_execution(self):
        result = plan_minion(**fixture())
        self.assertEqual(result['source'], 'read_only_minion_geometry_plan')
        self.assertEqual(len(result['gesture']), 4)
        self.assertFalse(result['game_input_sent'])

    def test_missing_calibration_invalid_slot_and_unreviewed_source_fail(self):
        for mutate in [lambda d: d['calibration'].update(minion_drop_boxes=[]),
                       lambda d: d['observation']['candidates'][0]['action']['PlayCard'].update(position=2),
                       lambda d: d['observation']['candidates'][0]['action']['PlayCard'].update(position=True),
                       lambda d: d['observation']['board']['players'][0]['hand'][0].update(card_id='BE_017')]:
            data = fixture()
            mutate(data)
            with self.assertRaises(ValueError): plan_minion(**data)

    def test_placement_requires_contiguous_positions_and_free_click_region(self):
        data = fixture()
        data['observation']['board']['players'][0]['in_play'] = [
            {'entity_id': 30, 'card_type': 'MINION', 'position': 1, 'public_zone': True}]
        data['calibration']['entities'].append({'entity_id': 30, 'box': [.45,.5,.55,.6]})
        data['calibration']['minion_drop_boxes'] = [[.35,.5,.4,.6], [.6,.5,.65,.6]]
        self.assertFalse(plan_minion(**data)['actionable'])
        data['calibration']['minion_drop_boxes'][0] = [.45,.5,.55,.6]
        with self.assertRaises(ValueError): plan_minion(**data)
        data['observation']['board']['players'][0]['in_play'][0]['position'] = 3
        with self.assertRaises(ValueError): plan_minion(**data)


if __name__ == '__main__': unittest.main()
