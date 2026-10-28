"""Real-window evaluation plumbing tests; no GPU or external packages required."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from evaluate_real import ROOT, audit, request, response_result, select, summarize
from validate_review import checked_manifest, manifest
from test_validate_review import reviewed, sample, seal


def window(group='session/game-1'):
    value = sample(group)
    value['action_preview'].update({'observed_power_sequence': 12, 'omitted': {'unsupported': 1}})
    value['board'] = {'turn': 4, 'perspective': 1, 'players': []}
    seal(value)
    return value


def response():
    return {'answers': {'action': {'type': 'choice', 'choice': 'c0',
            'probabilities': {'c0': 0.9, 'c1': 0.1}, 'answer_confidence': 0.9,
            'abstention': 'passed'}}, 'usage': {'truncated': False,
            'state_tokens_dropped': 0, 'truncated_questions': []}}


class RealEvaluationTests(unittest.TestCase):
    def test_labels_and_future_evidence_never_enter_request(self):
        value = window()
        before = request(value)
        reviewed(value)
        value['annotation']['reason'] = 'SECRET_ANSWER'
        value['visible_target_card_ids'] = ['FUTURE_EVIDENCE']
        value['user_reported_target_session'] = True
        value['target_deck_confirmed'] = True
        self.assertEqual(before, request(value))
        state, questions, mapping = request(value, True)
        self.assertEqual(mapping, {'c0': 'b', 'c1': 'a'})
        self.assertIn('against entity 3', questions['action']['criteria']['c0'])
        self.assertNotIn('SECRET_ANSWER', json.dumps(state))

    def test_selection_never_uses_held_out_games_for_diagnostics(self):
        samples = [window(f'game-{i}') for i in range(5)]
        splits = checked_manifest(samples, manifest(samples))
        dev, skipped = select(samples, splits, 'diagnostic')
        self.assertEqual(len(dev), 4)
        self.assertEqual(skipped['other_split'], 1)
        self.assertTrue(all(splits[s['sample_id']] == 'development' for s in dev))
        self.assertEqual(select(samples, splits, 'evaluate')[0], [])
        held, _ = select([reviewed(s) for s in samples], splits, 'evaluate')
        self.assertEqual(len(held), 1)

    def test_unlabelled_audit_reports_stability_but_no_correctness(self):
        rows = audit([window()], lambda *_: response(), 'diagnostic')
        self.assertEqual([r['choice'] for r in rows], ['a', 'b'])
        self.assertTrue(all('correct' not in row for row in rows))
        summary = summarize(rows, 'diagnostic')
        self.assertIsNone(summary['accuracy'])
        self.assertEqual(summary['order_repeat_stable_samples'], 0)

    def test_scoring_handles_ties_and_does_not_score_truncated_outputs(self):
        value = reviewed(window())
        rows = audit([value], lambda *_: response(), 'evaluate')
        self.assertTrue(all(r['correct'] for r in rows))
        self.assertEqual(summarize(rows, 'evaluate')['accuracy'], 1)
        truncated = response()
        truncated['usage']['state_tokens_dropped'] = 10
        rows = audit([value], lambda *_: truncated, 'evaluate')
        self.assertTrue(all(r['correct'] is None for r in rows))
        self.assertIsNone(summarize(rows, 'evaluate')['accuracy'])

    def test_malformed_model_output_is_never_accepted(self):
        for field, bad in [('answer_confidence', True), ('answer_confidence', float('nan')),
                           ('probabilities', {'c0': 0.1, 'c1': 0.9}),
                           ('probabilities', ['c0', 'c1']),
                           ('probabilities', {'c0': 1.0}), ('choice', 'unknown')]:
            value = response()
            value['answers']['action'][field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError):
                response_result(value, {'c0': 'a', 'c1': 'b'})
        rows = audit([window()], lambda *_: {}, 'diagnostic')
        self.assertTrue(all(r['status'] == 'invalid_response' for r in rows))

    def test_cli_without_labels_does_not_load_model_or_claim_accuracy(self):
        samples = [window(f'game-{i}') for i in range(2)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset, frozen, profile, output = [root / name for name in
                                               ('data.jsonl', 'manifest.json', 'profile.json', 'out.json')]
            dataset.write_text('\n'.join(json.dumps(s) for s in samples), encoding='utf-8')
            frozen.write_text(json.dumps(manifest(samples)), encoding='utf-8')
            profile.write_text(json.dumps({'deck_code': 'deck'}), encoding='utf-8')
            subprocess.run([sys.executable, str(ROOT / 'services/laya/evaluate_real.py'),
                            str(dataset), '--manifest', str(frozen), '--profile', str(profile),
                            '--output', str(output)], check=True, capture_output=True, timeout=15)
            report = json.loads(output.read_text())
            self.assertFalse(report['model_loaded'])
            self.assertEqual(report['status'], 'no_eligible_samples')
            self.assertIsNone(report['summary']['accuracy'])


if __name__ == '__main__':
    unittest.main()
