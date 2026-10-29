import copy
import json
from pathlib import Path
import tempfile
import unittest

from validate_review import (apply_labels, checked_manifest, digest, load_samples,
                             manifest, strict_json, validate, IDENTITY_FIELDS)
from prepare_review import render, sidecar


def sample(group='session/game-1', ordinal=1):
    value = {'schema_version': 2, 'source': 'offline_attack_review',
             'group_id': group, 'window_ordinal': ordinal, 'target_deck_code': 'deck',
             'board': {}, 'actionable': False, 'complete': False,
             'packet_boundary_observed': True,
             'action_preview': {'actionable': False, 'complete': False,
                'legality_verified': False, 'blocked_by': [], 'candidates': [
                    {'id': 'a', 'source_entity': 1, 'action': {'Attack': {'source': 1, 'target': 2}}},
                    {'id': 'b', 'source_entity': 1, 'action': {'Attack': {'source': 1, 'target': 3}}}]},
             'annotation': {'status': 'unreviewed', 'preferred_candidate_ids': [], 'reason': None}}
    seal(value)
    return value


def seal(value):
    value['sample_id'] = digest({k: value[k] for k in IDENTITY_FIELDS})


def reviewed(value):
    value['annotation'] = {'status': 'reviewed', 'preferred_candidate_ids': ['a', 'b'],
                           'reason': 'Equivalent supplied targets in this fixture.', 'reviewer': 'test'}
    return value


class ValidationTests(unittest.TestCase):
    def test_labels_do_not_change_identity_and_ties_are_supported(self):
        value = sample()
        identity = value['sample_id']
        self.assertEqual(validate(reviewed(value), 'deck'), 'reviewed')
        self.assertEqual(identity, value['sample_id'])

    def test_tampering_and_wrong_deck_are_rejected(self):
        value = sample()
        value['board']['future_information'] = True
        with self.assertRaisesRegex(ValueError, 'hash'):
            validate(value, 'deck')
        with self.assertRaisesRegex(ValueError, 'deck'):
            validate(sample(), 'another')

    def test_invalid_annotations_are_rejected(self):
        for change in ({'preferred_candidate_ids': ['unknown']},
                       {'preferred_candidate_ids': ['a', 'a']},
                       {'preferred_candidate_ids': []}, {'reviewer': ''},
                       {'reason': None}, {'status': 'unreviewed'}, {'status': 'excluded'}):
            value = reviewed(sample())
            value['annotation'].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate(value, 'deck')

    def test_unsafe_preview_and_ambiguous_candidates_are_rejected(self):
        for field in ('actionable', 'complete', 'legality_verified'):
            value = sample()
            value['action_preview'][field] = True
            seal(value)
            with self.assertRaises(ValueError):
                validate(value, 'deck')
        value = sample()
        value['action_preview']['candidates'][1]['id'] = 'a'
        seal(value)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            validate(value, 'deck')

    def test_duplicate_windows_rejected_even_with_different_content(self):
        first = sample()
        second = copy.deepcopy(first)
        second['board']['turn'] = 2
        seal(second)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'data.jsonl'
            path.write_text('\n'.join(json.dumps(s) for s in [first, second]), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'line 2: duplicate'):
                load_samples(path, 'deck')

    def test_partition_is_game_grouped_order_independent_and_needs_labels(self):
        samples = [sample(f'session/game-{g}', n) for g in range(5) for n in range(1, 4)]
        report = manifest(samples)
        self.assertFalse(report['evaluation_ready'])
        splits = {}
        for row in report['rows']:
            splits.setdefault(row['group_id'], set()).add(row['split'])
        self.assertTrue(all(len(s) == 1 for s in splits.values()))
        reverse = manifest(list(reversed(samples)))
        self.assertEqual({r['sample_id']: r['split'] for r in report['rows']},
                         {r['sample_id']: r['split'] for r in reverse['rows']})
        self.assertTrue(manifest([reviewed(s) for s in samples])['evaluation_ready'])
        self.assertFalse(manifest([reviewed(sample())])['evaluation_ready'])
        self.assertFalse(manifest([])['evaluation_ready'])

    def test_sidecar_is_bound_unique_and_does_not_mutate_source(self):
        samples = [sample()]
        labels = sidecar(samples)
        labels['labels'][0]['annotation'] = reviewed(sample())['annotation']
        result = apply_labels(samples, labels)
        self.assertEqual(result[0]['annotation']['status'], 'reviewed')
        self.assertEqual(samples[0]['annotation']['status'], 'unreviewed')
        for mutation in ('digest', 'duplicate', 'unknown', 'extra'):
            bad = copy.deepcopy(labels)
            if mutation == 'digest':
                bad['dataset_sha256'] = 'wrong'
            elif mutation == 'duplicate':
                bad['labels'].append(bad['labels'][0])
            elif mutation == 'unknown':
                bad['labels'][0]['sample_id'] = 'unknown'
            else:
                bad['labels'][0]['board'] = {'future': 'information'}
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                apply_labels(samples, bad)

    def test_manifest_cannot_be_rebound_or_change_split(self):
        samples = [sample()]
        frozen = manifest(samples)
        checked_manifest(samples, frozen)
        frozen['rows'][0]['split'] = 'evaluation'
        with self.assertRaises(ValueError):
            checked_manifest(samples, frozen)

    def test_strict_json_rejects_duplicate_keys_and_nonfinite_values(self):
        for text in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'):
            with self.assertRaises(ValueError):
                strict_json(text)

    def test_review_packet_preserves_unknown_values_and_candidate_identity(self):
        value = sample()
        value['board'] = {'turn': 3, 'perspective': 1, 'unknown': None}
        value['action_preview']['omitted'] = {'unsupported_source_action': 2}
        seal(value)
        packet = render([value], manifest([value]))
        self.assertIn(value['sample_id'], packet)
        self.assertIn('"unknown": null', packet)
        self.assertIn('| `a` | 1 | 2 |', packet)
        self.assertIn('development', packet)


if __name__ == '__main__':
    unittest.main()
