import copy
import unittest
from review_card_plays import summarize


class CardReviewTests(unittest.TestCase):
    def row(self):
        return {'source': 'offline_card_play_window', 'game_number': 1, 'actionable': False,
                'packet_boundary_observed': True,
                'board': {'players': [{'player_id': 1, 'hand': [{'entity_id': 10, 'card_id': 'EX1_144'}]}]},
                'action_preview': {'actionable': False, 'complete': False, 'legality_verified': False,
                                   'blocked_by': [], 'perspective': 1,
                                   'candidates': [{'action': {'PlayCard': {'source': 10, 'target': 20, 'position': None}}}]}}

    def test_only_closed_unblocked_windows_count_and_occurrences_are_not_deduplicated(self):
        row = self.row()
        open_row = dict(row, packet_boundary_observed=False)
        blocked = copy.deepcopy(row)
        blocked['action_preview']['blocked_by'] = ['stale_options']
        report = summarize([row, row, open_row, blocked])
        self.assertEqual(report['counts']['windows_with_card_plays'], 2)
        self.assertEqual(report['candidate_occurrences_by_card'], {'EX1_144': 2})
        self.assertEqual(report['blocked_windows'], {'stale_options': 1})
        self.assertFalse(report['execution_confirmed'])

    def test_wrong_source_and_execution_claims_are_refused(self):
        row = self.row()
        with self.assertRaises(ValueError):
            summarize([dict(row, source='offline_option_window')])
        for key in ['actionable', 'complete', 'legality_verified']:
            invalid = copy.deepcopy(row)
            invalid['action_preview'][key] = True
            with self.assertRaises(ValueError): summarize([invalid])


if __name__ == '__main__':
    unittest.main()
