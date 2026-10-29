import copy
import unittest
from test_end_turn_once import check_baseline, mouse_batch


def baseline():
    return {'game_number': 3, 'ignored_partial_line': False, 'game': {
        'game_entity': 1, 'entities': [{'id': 1, 'last_observed_tags': {'STATE': 'RUNNING', 'STEP': 'MAIN_ACTION'}}],
        'board': {'turn': 4, 'perspective': 1, 'active_player': 1, 'invalid_fields': 0},
        'unresolved_references': 0, 'malformed_records': 0, 'power_structure': {'closed': True},
        'logged_options': {'latest': {'stale': False, 'malformed_records': 0, 'unsupported_records': 0,
            'options': [{'index': 0, 'kind': 'END_TURN', 'entity_id': None, 'targets': [],
                         'sub_options': [], 'error': 'INVALID'}]}}}}


class UiBaselineTests(unittest.TestCase):
    def test_mouse_batch_layout_coordinates_and_release_are_bounded(self):
        batch = mouse_batch({'x': -1920, 'y': 0}, (-1920, 0, 3840, 1080))
        self.assertEqual(len(batch), 3)
        self.assertEqual([item.mouse.dwFlags for item in batch], [0xC001, 2, 4])
        self.assertEqual(batch[0].mouse.dx, 0)
        self.assertEqual(batch[0].mouse.dy, 0)
        edge = mouse_batch({'x': 1919, 'y': 1079}, (-1920, 0, 3840, 1080))
        self.assertEqual((edge[0].mouse.dx, edge[0].mouse.dy), (65535, 65535))
        for point in [{'x': -1921, 'y': 0}, {'x': 1920, 'y': 0}]:
            with self.assertRaises(RuntimeError):
                mouse_batch(point, (-1920, 0, 3840, 1080))

    def test_exact_turn_and_valid_shape_only(self):
        row = baseline()
        original = copy.deepcopy(row)
        self.assertEqual(check_baseline(row, 3, 4), 0)
        self.assertEqual(row, original)
        for game, turn in [(2, 4), (3, 5)]:
            with self.assertRaises(RuntimeError):
                check_baseline(row, game, turn)

    def test_stale_unknown_opponent_and_partial_states_block_input_preconditions(self):
        changes = [(['ignored_partial_line'], True), (['game', 'board', 'perspective'], None),
            (['game', 'board', 'active_player'], 2), (['game', 'power_structure', 'closed'], False),
            (['game', 'logged_options', 'latest', 'stale'], True),
            (['game', 'logged_options', 'latest', 'options', 0, 'targets'], [{'entity_id': 9}]),
            (['game', 'logged_options', 'latest', 'options', 0, 'error'], 'UNKNOWN')]
        for keys, value in changes:
            row = baseline()
            destination = row
            for key in keys[:-1]:
                destination = destination[key]
            destination[keys[-1]] = value
            with self.assertRaises(RuntimeError):
                check_baseline(row, 3, 4)


if __name__ == '__main__':
    unittest.main()
