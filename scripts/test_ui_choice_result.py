import copy
import unittest
import json
from pathlib import Path
import subprocess
import tempfile
from ui_choice_result import assess_choice


def pair():
    before = {'game_number': 1, 'ignored_partial_line': False, 'game': {
        'unresolved_references': 0, 'malformed_records': 0, 'board': {'perspective': 1},
        'choice_preview': {'blocked_by': [], 'choice': {'choice_id': 7, 'minimum': 1, 'maximum': 1,
                                                     'offered_cards': [{'entity_id': 20}]}},
        'logged_choices': {'latest_submission': None, 'malformed_records': 0, 'unsupported_records': 0}}}
    after = copy.deepcopy(before)
    after['game']['logged_choices']['latest_submission'] = {
        'id': 7, 'expected_count': 1, 'entities': [20], 'malformed_records': 0, 'list_complete': True,
        'correlation': {'packet_seen': True, 'packet_kind': 'GENERAL', 'packet_was_stale': False,
                        'packet_malformed_records': 0, 'owner_matches': True,
                        'declared_count_within_bounds': True, 'unobserved_entities': []}}
    return before, after


class ChoiceResultTests(unittest.TestCase):
    def test_real_parser_preserves_choice_submission_boundary(self):
        root = Path(__file__).resolve().parents[1]
        binary = root / 'target/validation/debug/hearth-agent.exe'
        if not binary.exists(): self.skipTest('build Rust binary first')
        base = (root / 'fixtures/wild-rogue-choice.log').read_text(encoding='utf-8')
        header = 'D 0 GameState.DebugPrintEntitiesChosen() - id=7 Player=2 EntitiesCount=1\n'
        entry = 'D 0 GameState.DebugPrintEntitiesChosen() - Entities[0]=20\n'
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'Power.log'
            rows = []
            for text in [base, base+header, base+header+entry]:
                log.write_text(text, encoding='utf-8')
                output = subprocess.check_output([str(binary), 'replay', str(log), '--json'], timeout=5)
                rows.append(json.loads(output.splitlines()[-1]))
        self.assertEqual(assess_choice(rows[0], rows[1], 20)['status'], 'pending')
        self.assertEqual(assess_choice(rows[0], rows[2], 20)['status'], 'matching_choice_submission_observed')

    def test_matching_new_submission_is_evidence_only(self):
        result = assess_choice(*pair(), 20)
        self.assertEqual(result['status'], 'matching_choice_submission_observed')
        self.assertFalse(result['execution_confirmed'])
        self.assertFalse(result['automatic_retry_allowed'])

    def test_previous_submission_cannot_be_reused(self):
        before, after = pair()
        before['game']['logged_choices']['latest_submission'] = copy.deepcopy(after['game']['logged_choices']['latest_submission'])
        self.assertEqual(assess_choice(before, after, 20)['status'], 'choice_already_submitted')

    def test_incomplete_wrong_owner_or_wrong_selection_cannot_match(self):
        before, after = pair()
        submission = after['game']['logged_choices']['latest_submission']
        submission['list_complete'] = False
        self.assertEqual(assess_choice(before, after, 20)['status'], 'pending')
        submission['list_complete'] = True
        submission['correlation']['owner_matches'] = False
        self.assertEqual(assess_choice(before, after, 20)['status'], 'choice_context_mismatch')
        submission['correlation']['owner_matches'] = True
        submission['entities'] = [21]
        self.assertEqual(assess_choice(before, after, 20)['status'], 'different_choice_selection')


if __name__ == '__main__': unittest.main()
