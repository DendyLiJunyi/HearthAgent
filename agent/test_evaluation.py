import json
import tempfile
import unittest
from pathlib import Path

from agent import test_agent as helpers
from agent.evaluation import evaluate_suite, load_final_test
from agent.policy import LayaPolicy


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        fixture = helpers.LayaPolicyTests()
        fixture.setUp()
        self.row = {'state': fixture.packet['state'], 'candidates': fixture.candidates, 'cards': {}}
        self.policy = LayaPolicy({}, fixture.prefers('enemy minion'))

    def test_metrics_distinguish_three_policies_and_preserve_case_ids(self):
        report = evaluate_suite(self.policy, [(self.row, 1)])
        self.assertEqual(report['right'], 1)
        self.assertEqual(report['raw_right'], 1)
        self.assertEqual(report['rules_right'], 1)
        self.assertEqual(report['decision_sources'], {'model': 1})
        self.assertEqual(len(report['case_fingerprints'][0]), 64)
        self.assertEqual(report['raw_failures'], 0)

    def test_final_test_rejects_known_cases_games_and_duplicates(self):
        item = {'group': 'new-session/game-1', 'reviewer': 'independent reviewer', 'row': self.row, 'label': 1}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.jsonl'
            path.write_text(json.dumps(item) + '\n', encoding='utf-8')
            self.assertEqual(len(load_final_test(path, [], set())), 1)
            for rows, groups in (([self.row], set()), ([], {item['group']})):
                with self.assertRaisesRegex(ValueError, 'overlaps'):
                    load_final_test(path, rows, groups)
            path.write_text((json.dumps(item) + '\n') * 2, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'duplicates'):
                load_final_test(path, [], set())

    def test_empty_suite_does_not_claim_accuracy(self):
        report = evaluate_suite(self.policy, [])
        self.assertEqual(report['total'], 0)
        self.assertIsNone(report['mean_decision_ms'])


if __name__ == '__main__':
    unittest.main()
