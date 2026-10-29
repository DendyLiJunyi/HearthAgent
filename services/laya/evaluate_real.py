"""Offline real-window ranking audit; never executes game actions.

Diagnostic mode uses development games only and reports no accuracy. Evaluation
mode requires independently reviewed held-out labels. Both use incomplete action
subsets, a zero inference threshold and a post-hoc confidence diagnostic.
"""
import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import sys
import time

from evaluate import ordered
from board_encoding import encode
from runtime import ROOT, MODEL_REPO, MODEL_REVISION, MODEL_SUBFOLDER, configure_environment

sys.path.insert(0, str(ROOT / 'scripts'))
from validate_review import (apply_labels, checked_manifest, digest, load_samples,
                             require, strict_json)


INSTRUCTIONS = ('Rank only the supplied Hearthstone actions for read-only advice. '
                'The observation and candidate list are incomplete; no action will be executed. '
                'Use only the given state.')


def request(sample, reverse=False, representation='raw'):
    """Whitelist prefix data only: no labels, reviewer notes, game outcomes or deck evidence."""
    require(representation in ('raw', 'sparse'), 'unknown representation')
    preview = sample['action_preview']
    candidates = list(preview['candidates'])
    require(1 <= len(candidates) <= 16, 'Rust-compatible candidate limit exceeded')
    if reverse:
        candidates.reverse()
    mapping = {f'c{i}': candidate['id'] for i, candidate in enumerate(candidates)}
    criteria = {}
    for i, candidate in enumerate(candidates):
        attack = candidate['action']['Attack']
        criteria[f'c{i}'] = f"Attack with entity {attack['source']} against entity {attack['target']}"
    # Fixed audit session avoids accidental dependence on paths or label-derived IDs.
    state = {'session_id': 'offline-real-window-audit',
             'revision': preview['observed_power_sequence'],
             'board': {'observation': encode(sample['board']) if representation == 'sparse' else sample['board'],
                       'candidate_coverage_complete': False,
                       'omitted': preview['omitted']}}
    questions = {'action': {'type': 'choice', 'instructions': INSTRUCTIONS, 'criteria': criteria}}
    return ordered(state), ordered(questions), mapping


def response_result(response, mapping):
    """Validate probability and truncation evidence before semantic interpretation."""
    usage = response['usage']
    require(isinstance(usage, dict) and type(usage['truncated']) is bool
            and isinstance(usage['truncated_questions'], list)
            and all(isinstance(item, str) for item in usage['truncated_questions'])
            and isinstance(usage.get('options', {}), dict), 'invalid usage schema')
    if (usage['truncated'] is not False or type(usage['state_tokens_dropped']) is not int
            or usage['state_tokens_dropped'] != 0 or usage['truncated_questions']
            or usage.get('options')):
        return {'status': 'truncated', 'choice': None, 'accepted_at_0_8': False}
    answer = response['answers']['action']
    require(set(response['answers']) == {'action'}, 'unexpected answer set')
    probabilities = answer['probabilities']
    confidence = answer['answer_confidence']
    numeric = lambda value: type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1
    require(answer['type'] == 'choice' and answer['choice'] in mapping, 'invalid choice')
    require(isinstance(probabilities, dict) and set(probabilities) == set(mapping)
            and all(numeric(p) for p in probabilities.values()),
            'invalid probabilities')
    require(abs(sum(probabilities.values()) - 1) <= len(mapping) * 0.000051,
            'probability sum mismatch')
    require(numeric(confidence), 'invalid confidence')
    require(max(probabilities.values()) <= probabilities[answer['choice']] + 0.0001,
            'choice disagrees with probabilities')
    require(answer['abstention'] in ('passed', 'abstained'), 'unknown abstention status')
    return {'status': 'valid', 'choice': mapping[answer['choice']],
            'answer_confidence': confidence,
            'accepted_at_0_8': answer['abstention'] == 'passed' and confidence >= 0.8,
            'probabilities': {mapping[k]: v for k, v in probabilities.items()}}


def select(samples, splits, mode):
    require(mode in ('diagnostic', 'evaluate'), 'unknown mode')
    selected = []
    skipped = Counter()
    for sample in samples:
        if splits[sample['sample_id']] != ('development' if mode == 'diagnostic' else 'evaluation'):
            skipped['other_split'] += 1
        elif sample['annotation']['status'] == 'excluded':
            skipped['excluded'] += 1
        elif mode == 'evaluate' and sample['annotation']['status'] != 'reviewed':
            skipped['unreviewed'] += 1
        elif len(sample['action_preview']['candidates']) > 16:
            skipped['candidate_limit'] += 1
        else:
            selected.append(sample)
    return selected, dict(skipped)


def audit(samples, predict, mode, runs=1, representation='raw', build_request=request):
    rows = []
    for sample in samples:
        for reverse in (False, True):
            state, questions, mapping = build_request(sample, reverse, representation)
            for repeat in range(runs):
                start = time.perf_counter()
                response = predict(state, questions)
                elapsed = (time.perf_counter() - start) * 1000
                try:
                    result = response_result(response, mapping)
                except (KeyError, TypeError, ValueError):
                    result = {'status': 'invalid_response', 'choice': None, 'accepted_at_0_8': False}
                row = {'sample_id': sample['sample_id'], 'group_id': sample['group_id'],
                       'candidate_count': len(mapping), 'order': 'reverse' if reverse else 'original',
                       'repeat': repeat, 'elapsed_ms': elapsed,
                       'rust_state_bytes': len(json.dumps(state['board'], separators=(',', ':'),
                                                         ensure_ascii=False).encode()), **result}
                if mode == 'evaluate':
                    preferred = sample['annotation']['preferred_candidate_ids']
                    row['correct'] = result['choice'] in preferred if result['status'] == 'valid' else None
                    row['first_candidate_correct'] = mapping['c0'] in preferred
                rows.append(row)
    return rows


def summarize(rows, mode):
    valid = [r for r in rows if r['status'] == 'valid']
    multi = [r for r in valid if r['candidate_count'] > 1]
    groups = {}
    for row in rows:
        groups.setdefault(row['sample_id'], []).append(row)
    eligible_groups = [group for group in groups.values() if all(r['status'] == 'valid' for r in group)
                       and group[0]['candidate_count'] > 1]
    summary = {'trials': len(rows), 'status_counts': dict(Counter(r['status'] for r in rows)),
               'valid_trials': len(valid), 'valid_multi_candidate_trials': len(multi),
               'accepted_at_0_8': sum(r['accepted_at_0_8'] for r in valid),
               'fully_valid_multi_candidate_samples': len(eligible_groups),
               'order_repeat_stable_samples': sum(len({r['choice'] for r in g}) == 1 for g in eligible_groups),
               'accuracy': None}
    summary['trials_within_rust_state_byte_limit'] = sum(r.get('rust_state_bytes', 16385) <= 16384 for r in rows)
    summary['accepted_multi_candidate_trials'] = sum(r['accepted_at_0_8'] for r in multi)
    summary['stable_and_all_confident_multi_samples'] = sum(
        len({r['choice'] for r in group}) == 1 and all(r['accepted_at_0_8'] for r in group)
        for group in eligible_groups)
    if mode == 'evaluate':
        summary.update({'correct_multi_candidate_trials': sum(r['correct'] for r in multi),
                        'first_candidate_correct_multi_trials': sum(r['first_candidate_correct'] for r in multi),
                        'accuracy': sum(r['correct'] for r in multi) / len(multi) if multi else None})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--labels', type=Path)
    parser.add_argument('--profile', type=Path, default=ROOT / 'config/decks/wild-rogue.json')
    parser.add_argument('--mode', choices=('diagnostic', 'evaluate'), default='evaluate')
    parser.add_argument('--representation', choices=('raw', 'sparse'), default='sparse')
    parser.add_argument('--device', choices=('cuda', 'cpu'), default='cuda')
    parser.add_argument('--runs', type=int, default=1)
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--output', type=Path, default=ROOT / '.data/laya-real-evaluation.json')
    args = parser.parse_args()
    require(1 <= args.runs <= 3 and 1 <= args.limit <= 100, 'runs must be 1..3 and limit 1..100')
    inputs = [args.dataset, args.manifest, args.profile] + ([args.labels] if args.labels else [])
    require(args.output.resolve() not in {p.resolve() for p in inputs}, 'output must not overwrite inputs')
    samples = load_samples(args.dataset, strict_json(args.profile.read_text(encoding='utf-8'))['deck_code'])
    frozen = strict_json(args.manifest.read_text(encoding='utf-8'))
    splits = checked_manifest(samples, frozen)
    if args.labels:
        samples = apply_labels(samples, strict_json(args.labels.read_text(encoding='utf-8')))
    selected, skipped = select(samples, splits, args.mode)
    report = {'schema_version': 1, 'actionable': False, 'mode': args.mode,
              'representation': args.representation,
              'dataset_sha256': frozen['dataset_sha256'], 'labelled_dataset_sha256': digest(samples),
              'manifest_sha256': digest(frozen), 'selected_before_limit': len(selected),
              'limit': args.limit, 'runs': args.runs, 'skipped': skipped,
              'scope': 'Incomplete attack subsets; post-hoc 0.8 confidence is not Rust execution acceptance.',
              'status': 'no_eligible_samples', 'model_loaded': False, 'rows': []}
    selected = selected[:args.limit]
    if selected:
        configure_environment()
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'
        import laya
        import torch
        require(args.device != 'cuda' or torch.cuda.is_available(), 'CUDA unavailable; select CPU explicitly')
        agent = laya.load(MODEL_REPO, subfolder=MODEL_SUBFOLDER, revision=MODEL_REVISION, device=args.device)

        def predict(state, questions):
            response = agent.predict(state, questions, max_len=8192, head_max_len=1024, min_confidence=0.0)
            if args.device == 'cuda':
                torch.cuda.synchronize()
            return response

        state, questions, _ = request(selected[0], representation=args.representation)
        predict(state, questions)  # Untimed warmup, also counted in documented call count.
        report.update({'model_loaded': True, 'model': MODEL_REPO, 'revision': MODEL_REVISION,
                       'subfolder': MODEL_SUBFOLDER, 'laya_version': laya.__version__,
                       'torch_version': torch.__version__, 'actual_device': str(next(agent.model.parameters()).device),
                       'status': 'completed', 'warmup_calls': 1,
                       'latency_scope': 'warm direct prediction, excludes load and one warmup'})
        report['rows'] = audit(selected, predict, args.mode, args.runs, args.representation)
    report['summary'] = summarize(report['rows'], args.mode)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'rows'}, indent=2))


if __name__ == '__main__':
    main()
