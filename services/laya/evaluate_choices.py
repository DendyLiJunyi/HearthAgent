"""Offline development-game choice diagnostic; no labels, accuracy or game input."""
import argparse
import hashlib
import json
import os
from pathlib import Path

from board_encoding import encode
from evaluate_real import (INSTRUCTIONS, ROOT, audit, checked_manifest, digest, load_samples,
                           ordered, require, strict_json, summarize)
from runtime import MODEL_REPO, MODEL_REVISION, MODEL_SUBFOLDER, configure_environment


def samples_for_development(windows, source_report, frozen):
    splits = {row['group_id']: row['split'] for row in frozen['rows']}
    samples, skipped = [], 0
    for ordinal, row in enumerate(windows, 1):
        require(row['source'] == 'offline_choice_window' and row['actionable'] is False
                and row['complete'] is False, 'invalid choice-window source')
        group = f"{source_report['session']}/game-{row['game_number']}"
        require(group in splits, 'choice game is absent from frozen game split')
        if splits[group] != 'development':
            skipped += 1
            continue
        preview = row['choice_preview']
        choice = preview['choice']
        if (row['window']['kind'] != 'packet' or not row['packet_boundary_observed']
                or preview['blocked_by'] or choice is None):
            continue
        require(preview['actionable'] is False and preview['complete'] is False
                and preview['legality_verified'] is False, 'invalid choice preview flags')
        require(choice['choice_id'] == row['window']['packet_id']
                and choice['minimum'] == choice['maximum'] == 1, 'unsupported choice identity or bounds')
        offered = choice['offered_cards']
        require(1 <= len(offered) <= 16, 'unsupported choice count')
        ids = [c['entity_id'] for c in offered]
        require(all(type(i) is int and i > 0 for i in ids) and len(ids) == len(set(ids)), 'invalid offered entities')
        value = {'group_id': group, 'window_ordinal': ordinal, 'board': row['board'], 'choice': choice}
        value['sample_id'] = digest(value)
        samples.append(value)
    return samples, skipped


def request_choice(sample, reverse=False, representation='sparse'):
    require(representation == 'sparse', 'choice diagnostic requires the compact representation')
    offered = list(sample['choice']['offered_cards'])
    if reverse:
        offered.reverse()
    choice_id = sample['choice']['choice_id']
    mapping = {f'c{i}': f"choice-{choice_id}-entity-{card['entity_id']}" for i, card in enumerate(offered)}
    criteria = {f'c{i}': f"For choice packet {choice_id}, select entities [{card['entity_id']}]"
                for i, card in enumerate(offered)}
    state = {'session_id': 'offline-choice-window-audit', 'revision': sample['window_ordinal'],
             'board': {'observation': encode(sample['board']), 'candidate_coverage_complete': False,
                       'offered_choice': sample['choice']}}
    questions = {'action': {'type': 'choice', 'instructions': INSTRUCTIONS, 'criteria': criteria}}
    return ordered(state), ordered(questions), mapping


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('windows', type=Path)
    parser.add_argument('--source-report', type=Path, required=True)
    parser.add_argument('--attack-dataset', type=Path, default=ROOT / '.data/attack-review.jsonl')
    parser.add_argument('--manifest', type=Path, default=ROOT / '.data/review-manifest.json')
    parser.add_argument('--device', choices=('cuda', 'cpu'), default='cuda')
    parser.add_argument('--runs', type=int, default=2)
    parser.add_argument('--output', type=Path, default=ROOT / '.data/laya-choice-diagnostic.json')
    args = parser.parse_args()
    require(1 <= args.runs <= 3, 'runs must be 1..3')
    require(args.output.resolve() not in {p.resolve() for p in
        (args.windows, args.source_report, args.attack_dataset, args.manifest)}, 'output must not overwrite input')
    profile = strict_json((ROOT / 'config/decks/wild-rogue.json').read_text(encoding='utf-8'))
    source = strict_json(args.source_report.read_text(encoding='utf-8'))
    frozen = strict_json(args.manifest.read_text(encoding='utf-8'))
    checked_manifest(load_samples(args.attack_dataset, profile['deck_code']), frozen)
    raw = args.windows.read_bytes()
    require(len(raw) <= 64 * 1024 * 1024, 'choice file exceeds 64 MiB')
    require(hashlib.sha256(raw).hexdigest() == source['windows_sha256'], 'choice file hash mismatch')
    windows = [strict_json(line) for line in raw.decode('utf-8').splitlines()]
    samples, skipped = samples_for_development(windows, source, frozen)
    require(len(samples) <= 100, 'diagnostic limited to 100 windows')
    report = {'source': 'offline_choice_ranking_diagnostic', 'actionable': False, 'mode': 'diagnostic',
              'accuracy': None, 'samples': len(samples), 'skipped_held_out_windows': skipped,
              'windows_sha256': source['windows_sha256'], 'manifest_sha256': digest(frozen),
              'runs': args.runs, 'model_loaded': False, 'rows': [],
              'scope': 'Unlabelled development games, incomplete offered-card subsets, '
                       'post-hoc confidence only; no gameplay or legality validation.'}
    if samples:
        configure_environment()
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'
        import laya
        import torch
        require(args.device != 'cuda' or torch.cuda.is_available(), 'CUDA unavailable')
        agent = laya.load(MODEL_REPO, subfolder=MODEL_SUBFOLDER, revision=MODEL_REVISION, device=args.device)
        def predict(state, questions):
            result = agent.predict(state, questions, max_len=8192, head_max_len=1024, min_confidence=0.0)
            if args.device == 'cuda':
                torch.cuda.synchronize()
            return result
        state, questions, _ = request_choice(samples[0])
        predict(state, questions)
        report.update({'model_loaded': True, 'model': MODEL_REPO, 'revision': MODEL_REVISION,
                       'subfolder': MODEL_SUBFOLDER, 'laya_version': laya.__version__,
                       'torch_version': torch.__version__, 'actual_device': str(next(agent.model.parameters()).device),
                       'warmup_calls': 1, 'latency_scope': 'warm direct predictions, excludes load and warmup'})
        report['rows'] = audit(samples, predict, 'diagnostic', args.runs, 'sparse', request_choice)
    report['summary'] = summarize(report['rows'], 'diagnostic')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'rows'}, indent=2))


if __name__ == '__main__':
    main()
