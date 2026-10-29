import copy
import unittest

from evaluate_choices import request_choice, samples_for_development
from validate_review import manifest
from test_evaluate_real import window


def choice_window(game):
    return {'source': 'offline_choice_window', 'game_number': game, 'actionable': False,
            'complete': False, 'packet_boundary_observed': True, 'window': {'kind': 'packet', 'packet_id': 7},
            'board': {'players': []}, 'choice_preview': {'actionable': False, 'complete': False,
            'legality_verified': False, 'blocked_by': [], 'choice': {'choice_id': 7,
                'source_entity': 10, 'source_card_id': 'TLC_515', 'minimum': 1, 'maximum': 1,
                'offered_cards': [{'entity_id': 20, 'card_id': 'CFM_630'}, {'entity_id': 21, 'card_id': 'DED_004'}]}}}


class ChoiceEvaluationTests(unittest.TestCase):
    def test_development_filter_reuses_attack_game_split_and_preserves_choice_identity(self):
        frozen = manifest([window(f'session/game-{i}') for i in (1, 2)])
        samples, skipped = samples_for_development([choice_window(1), choice_window(2)],
                                                  {'session': 'session'}, frozen)
        self.assertEqual(len(samples), 1)
        self.assertEqual(skipped, 1)
        state, questions, mapping = request_choice(samples[0], True)
        self.assertEqual(mapping, {'c0': 'choice-7-entity-21', 'c1': 'choice-7-entity-20'})
        self.assertEqual(state['board']['offered_choice']['choice_id'], 7)
        self.assertIn('[21]', questions['action']['criteria']['c0'])

    def test_untracked_game_rejected_and_partial_or_blocked_choice_excluded(self):
        frozen = manifest([window('session/game-1')])
        with self.assertRaises(ValueError):
            samples_for_development([choice_window(2)], {'session': 'session'}, frozen)
        row = choice_window(1)
        row['packet_boundary_observed'] = False
        self.assertEqual(samples_for_development([row], {'session': 'session'}, frozen)[0], [])
        row = choice_window(1)
        row['choice_preview']['blocked_by'] = ['unknown_perspective']
        self.assertEqual(samples_for_development([row], {'session': 'session'}, frozen)[0], [])

    def test_bad_choice_ids_and_duplicate_entities_are_rejected(self):
        frozen = manifest([window('session/game-1')])
        for mutation in ('id', 'duplicate'):
            row = choice_window(1)
            if mutation == 'id':
                row['choice_preview']['choice']['choice_id'] = 9
            else:
                row['choice_preview']['choice']['offered_cards'][1]['entity_id'] = 20
            with self.assertRaises(ValueError):
                samples_for_development([row], {'session': 'session'}, frozen)


if __name__ == '__main__':
    unittest.main()
