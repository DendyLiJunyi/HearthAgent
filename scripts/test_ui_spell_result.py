import copy
import unittest
from ui_spell_result import assess_spell


def observations():
    source = {'entity_id': 10, 'card_type': 'SPELL', 'card_id': 'EX1_144'}
    candidate = {'id': 'play', 'option_index': 1, 'action': {
        'PlayCard': {'source': 10, 'target': 20, 'position': None}}}
    before = {'game_number': 1, 'ignored_partial_line': False, 'game': {
        'card_play_preview': {'blocked_by': [], 'option_packet_id': 7, 'candidates': [candidate]},
        'unresolved_references': 0, 'malformed_records': 0, 'power_structure': {'closed': True},
        'board': {'perspective': 1, 'invalid_fields': 0, 'players': [
            {'player_id': 1, 'hand': [source], 'in_play': [], 'graveyard': []}]},
        'logged_options': {'submissions_seen': 2}}}
    after = copy.deepcopy(before)
    player = after['game']['board']['players'][0]
    player['graveyard'] = player['hand']
    player['hand'] = []
    after['game']['logged_options'] = {'submissions_seen': 3, 'latest_submission': {
        'selection': {'option': 1, 'sub_option': -1, 'target': 20, 'position': 0},
        'correlation': {'packet_id': 7, 'packet_was_stale': False, 'packet_malformed_records': 0,
            'packet_unsupported_records': 0, 'option_kind': 'POWER', 'option_seen': True,
            'source_entity': 10, 'option_error': 'NONE', 'target_seen': True,
            'target_ambiguous': False, 'target_error': 'NONE'}}}
    return before, after


class SpellResultTests(unittest.TestCase):
    def test_matching_submission_and_graveyard_are_evidence_only(self):
        result = assess_spell(*observations(), 'play')
        self.assertEqual(result['status'], 'submission_and_source_graveyard_observed')
        self.assertFalse(result['execution_confirmed'])
        self.assertFalse(result['automatic_retry_allowed'])

    def test_partial_open_blocks_and_missing_send_cannot_complete(self):
        for mutate in [lambda a: a.update(ignored_partial_line=True),
                       lambda a: a['game']['power_structure'].update(closed=False),
                       lambda a: a['game']['logged_options'].update(submissions_seen=2)]:
            before, after = observations()
            mutate(after)
            self.assertEqual(assess_spell(before, after, 'play')['status'], 'pending')

    def test_wrong_packet_target_source_and_repeated_sends_fail(self):
        for key, value in [('packet_id', 8), ('source_entity', 99), ('target_seen', False),
                           ('packet_was_stale', True), ('packet_malformed_records', False)]:
            before, after = observations()
            after['game']['logged_options']['latest_submission']['correlation'][key] = value
            self.assertEqual(assess_spell(before, after, 'play')['status'], 'submission_context_mismatch')
        before, after = observations()
        after['game']['logged_options']['latest_submission']['selection']['target'] = 99
        self.assertEqual(assess_spell(before, after, 'play')['status'], 'different_submission_observed')
        after['game']['logged_options']['submissions_seen'] = 4
        self.assertEqual(assess_spell(before, after, 'play')['status'], 'multiple_submissions_observed')

    def test_card_remaining_in_hand_or_changed_identity_cannot_complete(self):
        before, after = observations()
        player = after['game']['board']['players'][0]
        player['hand'] = copy.deepcopy(player['graveyard'])
        self.assertEqual(assess_spell(before, after, 'play')['status'], 'pending')
        player['hand'] = []
        player['graveyard'][0]['card_id'] = 'OTHER'
        self.assertEqual(assess_spell(before, after, 'play')['status'], 'source_identity_changed')


if __name__ == '__main__': unittest.main()
