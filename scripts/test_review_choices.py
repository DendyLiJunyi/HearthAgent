import copy
import unittest

from review_choices import summary, visible_source


def window():
    return {'game_number': 1, 'packet_boundary_observed': True,
            'window': {'kind': 'packet', 'packet_id': 7},
            'board': {'perspective': 1, 'players': [
                {'player_id': 1, 'entity_id': 2, 'hand': [], 'in_play': [],
                 'graveyard': [{'entity_id': 10, 'card_id': 'TLC_515'}]}]},
            'logged_choices': {'sets': {'7': {'stale': False, 'malformed_records': 0,
                'source_entity': 10, 'owner_entity': 2, 'kind': 'GENERAL', 'entities': [11, 12]}},
                'latest_submission': None}}


class ChoiceReviewTests(unittest.TestCase):
    def test_source_evidence_uses_only_visible_projection_and_unique_entities(self):
        row = window()
        self.assertEqual(visible_source(row['board'], 10), 'TLC_515')
        row['board']['players'][0]['graveyard'][0]['card_id'] = None
        self.assertIsNone(visible_source(row['board'], 10))
        row = window()
        row['board']['players'][0]['hand'] = copy.deepcopy(row['board']['players'][0]['graveyard'])
        self.assertIsNone(visible_source(row['board'], 10))

    def test_missing_header_or_stale_packet_never_count_as_reviewable_source(self):
        for mutation in ('missing', 'stale'):
            row = window()
            if mutation == 'missing':
                row['window']['packet_id'] = None
            else:
                row['logged_choices']['sets']['7']['stale'] = True
            report = summary([row])
            self.assertEqual(report['visible_source_card_ids'], {})
            self.assertEqual(report['issues']['missing_stale_or_malformed_packet'], 1)

    def test_complete_submission_is_not_execution_confirmation(self):
        row = window()
        row['window']['kind'] = 'submission'
        row['logged_choices']['latest_submission'] = {'id': 7, 'list_complete': True,
            'correlation': {'packet_seen': True, 'owner_matches': True,
                'declared_count_within_bounds': True, 'unobserved_entities': [], 'packet_was_stale': False}}
        report = summary([row])
        self.assertFalse(report['actionable'])
        self.assertFalse(report['complete'])
        self.assertEqual(report['totals']['complete_submitted_lists'], 1)
        row['window']['packet_id'] = 8
        self.assertEqual(summary([row])['issues']['missing_current_submission'], 1)


if __name__ == '__main__':
    unittest.main()
