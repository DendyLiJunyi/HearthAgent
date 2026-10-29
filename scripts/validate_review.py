"""Validate attack-review JSONL and prepare a game-grouped evaluation manifest.

No model calls, labels inferred from play, or game input. Reviewed preferences
rank only the supplied incomplete candidate subset, never all legal actions.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


IDENTITY_FIELDS = ('group_id', 'window_ordinal', 'target_deck_code', 'board', 'action_preview')


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result

    def constant(_):
        raise ValueError('non-finite JSON constant')

    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(sample, deck_code):
    require(sample['schema_version'] == 2, 'unsupported schema')
    require(sample['source'] == 'offline_attack_review', 'unsupported source')
    require(sample['target_deck_code'] == deck_code, 'wrong target deck')
    require(sample['sample_id'] == digest({k: sample[k] for k in IDENTITY_FIELDS}),
            'sample content hash mismatch')
    require(isinstance(sample['group_id'], str) and sample['group_id'].strip(), 'missing game group')
    require(type(sample['window_ordinal']) is int and sample['window_ordinal'] > 0, 'invalid ordinal')
    require(sample['actionable'] is False and sample['complete'] is False
            and sample['packet_boundary_observed'] is True, 'unsafe sample flags')
    preview = sample['action_preview']
    require(all(preview[k] is False for k in ('actionable', 'complete', 'legality_verified'))
            and preview['blocked_by'] == [], 'blocked or executable preview')
    candidates = preview['candidates']
    require(isinstance(candidates, list) and 0 < len(candidates) <= 256, 'invalid candidate count')
    ids = []
    for candidate in candidates:
        require(isinstance(candidate['id'], str) and candidate['id'], 'invalid candidate ID')
        ids.append(candidate['id'])
        require(set(candidate['action']) == {'Attack'}, 'unsupported action')
        attack = candidate['action']['Attack']
        require(set(attack) == {'source', 'target'} and all(
            type(v) is int and 0 < v <= 4294967295 for v in attack.values()), 'invalid attack')
        require(candidate['source_entity'] == attack['source'], 'source mismatch')
    require(len(set(ids)) == len(ids), 'duplicate candidate IDs')
    annotation = sample['annotation']
    status = annotation['status']
    require(status in ('unreviewed', 'reviewed', 'excluded'), 'unknown annotation status')
    preferred = annotation['preferred_candidate_ids']
    require(isinstance(preferred, list) and all(isinstance(x, str) for x in preferred),
            'invalid preferences')
    require(len(set(preferred)) == len(preferred) and set(preferred) <= set(ids),
            'duplicate or unknown preference')
    if status == 'reviewed':
        require(bool(preferred), 'reviewed sample needs preferences')
    else:
        require(not preferred, 'unreviewed/excluded sample must not have preferences')
    if status != 'unreviewed':
        require(isinstance(annotation.get('reviewer'), str) and annotation['reviewer'].strip(),
                'missing reviewer')
        require(isinstance(annotation.get('reason'), str) and annotation['reason'].strip(),
                'missing review reason')
    return status


def load_samples(path, deck_code):
    samples, seen, positions = [], set(), set()
    with Path(path).open('rb') as stream:
        for ordinal in range(1, 100002):
            line = stream.readline(4 * 1024 * 1024 + 1)
            if not line:
                break
            require(ordinal <= 100000 and len(line) <= 4 * 1024 * 1024, 'dataset limit exceeded')
            try:
                sample = strict_json(line)
                validate(sample, deck_code)
                position = (sample['group_id'], sample['window_ordinal'])
                require(sample['sample_id'] not in seen and position not in positions,
                        'duplicate sample or game window')
                seen.add(sample['sample_id'])
                positions.add(position)
                samples.append(sample)
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(f'line {ordinal}: {error}') from error
    return samples


def checked_manifest(samples, frozen):
    """Require the exact frozen source dataset and partition before inference."""
    require(frozen == manifest(samples), 'manifest does not match frozen dataset')
    return {row['sample_id']: row['split'] for row in frozen['rows']}


def apply_labels(samples, labels):
    """Join a sidecar without modifying the frozen source or its model inputs."""
    import copy
    require(labels['schema_version'] == 1 and labels['dataset_sha256'] == digest(samples),
            'labels are not bound to this dataset')
    require(set(labels) == {'schema_version', 'dataset_sha256', 'labels'}, 'unexpected label fields')
    require(isinstance(labels['labels'], list), 'labels must be a list')
    result = copy.deepcopy(samples)
    by_id = {s['sample_id']: s for s in result}
    seen = set()
    for item in labels['labels']:
        require(set(item) == {'sample_id', 'annotation'}, 'unexpected label entry fields')
        identity = item['sample_id']
        require(identity in by_id and identity not in seen, 'unknown or duplicate labelled sample')
        seen.add(identity)
        annotation = item['annotation']
        require(set(annotation) <= {'status', 'preferred_candidate_ids', 'reviewer', 'reason'},
                'unexpected annotation fields')
        by_id[identity]['annotation'] = annotation
        validate(by_id[identity], by_id[identity]['target_deck_code'])
    return result


def manifest(samples):
    # Partition whole games deterministically; never move windows to balance labels.
    groups = sorted({s['group_id'] for s in samples}, key=lambda g: (digest(g), g))
    held_out = set(groups[-max(1, len(groups) // 5):]) if len(groups) >= 2 else set()
    counts = Counter(s['annotation']['status'] for s in samples)
    rows = [{'sample_id': s['sample_id'], 'group_id': s['group_id'],
             'split': 'evaluation' if s['group_id'] in held_out else 'development',
             'status': s['annotation']['status']} for s in samples]
    eligible = sum(r['split'] == 'evaluation' and r['status'] == 'reviewed' for r in rows)
    return {'schema_version': 1, 'actionable': False, 'samples': len(samples),
            'groups': len(groups), 'annotation_counts': dict(counts),
            'dataset_sha256': digest(samples), 'eligible_evaluation_samples': eligible,
            'evaluation_ready': eligible > 0,
            'scope': 'Preferences among supplied incomplete attack candidates only.',
            'rows': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--profile', type=Path, default=Path('config/decks/wild-rogue.json'))
    parser.add_argument('--output', type=Path, default=Path('.data/review-manifest.json'))
    args = parser.parse_args()
    require(args.output.resolve() not in (args.dataset.resolve(), args.profile.resolve()),
            'output must not overwrite inputs')
    profile = json.loads(args.profile.read_text(encoding='utf-8'))
    result = manifest(load_samples(args.dataset, profile['deck_code']))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}, indent=2))


if __name__ == '__main__':
    main()
