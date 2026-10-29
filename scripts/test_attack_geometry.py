import copy
import json
from pathlib import Path
import unittest
from attack_geometry import plan_attack


def fixture():
    return json.loads((Path(__file__).resolve().parents[1] / 'fixtures/attack-geometry.json').read_text())


class AttackGeometryTests(unittest.TestCase):
    def test_boolean_aliases_cannot_impersonate_numeric_identities(self):
        for path in [('observation', 'board', 'perspective'),
                     ('calibration', 'binding', 'game_number'),
                     ('current_window', 'dpi')]:
            data = fixture()
            target = data
            for key in path[:-1]: target = target[key]
            target[path[-1]] = True
            with self.assertRaises(ValueError): plan_attack(**data)
        data = fixture()
        data['observation']['board']['players'][0]['in_play'][0]['entity_id'] = True
        with self.assertRaises(ValueError): plan_attack(**data)

    def test_subpixel_boxes_and_invalid_dimensions_are_rejected(self):
        data = fixture()
        data['calibration']['entities'][0]['box'] = [.4, .5, .40001, .6]
        with self.assertRaises(ValueError): plan_attack(**data)
        for right in [-1920, 99999, True]:
            data = fixture()
            for window in (data['current_window'], data['calibration']['window']):
                window['client_screen_rect']['right'] = right
            with self.assertRaises(ValueError): plan_attack(**data)

    def test_plan_preserves_binding_and_maps_entities_without_enabling_execution(self):
        data = fixture()
        original = copy.deepcopy(data)
        plan = plan_attack(**data)
        self.assertEqual(plan['gesture'][0]['point'], {'x': -1056, 'y': 621})
        self.assertEqual(plan['gesture'][2]['point'], {'x': -960, 'y': 189})
        self.assertEqual([step['kind'] for step in plan['gesture']], ['move', 'left_down', 'move', 'left_up'])
        self.assertFalse(plan['actionable'])
        self.assertFalse(plan['legality_verified'])
        self.assertFalse(plan['game_input_sent'])
        self.assertEqual(data, original)

    def test_changed_frame_revision_session_game_or_window_rejects_old_calibration(self):
        for key, value in [('revision', 8), ('session_id', 'other'), ('game_number', 2)]:
            data = fixture()
            data['observation']['snapshot'][key] = value
            with self.assertRaises(ValueError): plan_attack(**data)
        for mutate in [lambda d: d.update(frame_sha256='b' * 64),
                       lambda d: d['current_window'].update(hwnd=999),
                       lambda d: d['current_window']['client_screen_rect'].update(left=0),
                       lambda d: d['observation']['snapshot'].update(phase='Choosing')]:
            data = fixture()
            mutate(data)
            with self.assertRaises(ValueError): plan_attack(**data)

    def test_missing_duplicate_overlapping_and_nonfinite_boxes_are_rejected(self):
        for entries in [[],
                        [{'entity_id': 10, 'box': [.4, .5, .5, .65]}] * 2,
                        [{'entity_id': 10, 'box': [0, 0, 1, 1]}, {'entity_id': 20, 'box': [0, 0, 1, 1]}],
                        [{'entity_id': 10, 'box': [0, 0, float('nan'), 1]}],
                        [{'entity_id': 10, 'box': [-.1, 0, 1, 1]}]]:
            data = fixture()
            data['calibration']['entities'] = entries
            with self.assertRaises(ValueError): plan_attack(**data)

    def test_hidden_wrong_owner_and_missing_board_entities_cannot_be_mapped(self):
        for mutate in [lambda d: d['observation']['board']['players'][0]['in_play'].clear(),
                       lambda d: d['observation']['board']['players'][0]['in_play'][0].update(public_zone=False),
                       lambda d: d['observation']['board']['players'][0]['in_play'][0].update(card_type='SPELL'),
                       lambda d: d['observation']['board']['players'][1].update(player_id=1),
                       lambda d: d['observation']['board'].update(active_player=2)]:
            data = fixture()
            mutate(data)
            with self.assertRaises(ValueError): plan_attack(**data)

    def test_ambiguous_candidate_or_unsupported_action_never_generates_gesture(self):
        for action in ['EndTurn', {'Attack': {'source': 10, 'target': 10}},
                       {'Attack': {'source': True, 'target': 20}},
                       {'PlayCard': {'source': 10, 'target': 20}}]:
            data = fixture()
            data['observation']['candidates'][0]['action'] = action
            with self.assertRaises(ValueError): plan_attack(**data)
        data = fixture()
        data['observation']['candidates'] *= 2
        with self.assertRaises(ValueError): plan_attack(**data)


if __name__ == '__main__':
    unittest.main()
