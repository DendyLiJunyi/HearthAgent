"""Prevent validation leakage and checkpoint promotion on regression."""
import copy
import unittest

from experiments.imitation.evaluate_ranked import validate_holdout, eligible
from experiments.imitation.features import render_state, render_candidate, question
from agent.power import PowerLog, candidates_from
from agent.test_agent import game_lines, option_lines


class RankedEvaluationTests(unittest.TestCase):
    def item(self):
        log = PowerLog()
        for line in game_lines() + option_lines():
            log.feed(line)
        packet = log.game.packet
        return {'row': {'state': packet['state'], 'cards': packet['cards'], 'candidates': candidates_from(packet)},
                'label': 0, 'reviewer': 'test-reviewer', 'reason': 'reviewed position', 'group': 'new-game'}

    def test_reviewed_separate_game_is_accepted(self):
        item = self.item()
        self.assertEqual(validate_holdout([item], [], {'training-game'}, [], {}), [(item['row'], 0)])

    def test_same_board_same_game_or_duplicate_is_rejected(self):
        item = self.item()
        for training, groups, items in [([(item['row'], 1)], set(), [item]),
                                         ([], {'new-game'}, [item]), ([], set(), [item, item])]:
            with self.assertRaises(ValueError):
                validate_holdout(items, training, groups, [], {})

    def test_rendered_overlap_is_rejected_even_if_raw_metadata_differs(self):
        item = self.item()
        row = item['row']
        replay = [{'state': render_state(row, {}),
                   'questions': question([render_candidate(row, c, {}) for c in row['candidates']])}]
        with self.assertRaisesRegex(ValueError, 'text'):
            validate_holdout([item], [], set(), replay, {})

    def test_missing_review_or_invalid_label_is_rejected(self):
        for key, value in [('reviewer', ''), ('reason', ''), ('group', ''), ('label', True), ('label', 500)]:
            item = self.item()
            item[key] = value
            with self.assertRaises(ValueError):
                validate_holdout([item], [], set(), [], {})

    def test_gate_requires_retention_no_failures_and_raw_improvement(self):
        suites = ('warrior_validation', 'older_validation', 'wild_retention', 'standard_validation', 'standard_fit')
        before = {s: dict(total=10, right=5, raw_right=4, fallbacks=0, raw_failures=0) for s in suites}
        after = copy.deepcopy(before)
        after['standard_fit']['raw_right'] = 5
        self.assertTrue(eligible(before, after))
        for suite, field, value in [('older_validation', 'right', 4), ('wild_retention', 'right', 4),
                                    ('standard_validation', 'raw_right', 3), ('standard_fit', 'raw_right', 4),
                                    ('warrior_validation', 'fallbacks', 1), ('standard_validation', 'raw_failures', 1)]:
            candidate = copy.deepcopy(after)
            candidate[suite][field] = value
            self.assertFalse(eligible(before, candidate))


if __name__ == '__main__':
    unittest.main()
