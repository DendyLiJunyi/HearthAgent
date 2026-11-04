"""Compare policies against the moves actually played in held-out games.

Agreement with a player is not playing strength. It is a cheap, independent signal that the
project previously had none of. Windows with one legal action prove nothing and are excluded.
"""
import argparse
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, str(os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'laya')))
from features import (TEST_GROUPS, id_only_state, load_cards, load_rows, question, render_candidate,
                      render_id_only, render_state, rules_scores)
from runtime import configure_environment


def summary(hits, ks, flips=None, extra=None):
    n = len(hits)
    result = {'n': n, 'top1': round(sum(h == 0 for h in hits) / n, 4),
              'top3': round(sum(h < 3 for h in hits) / n, 4)}
    if flips is not None:
        result['order_flip_rate'] = round(sum(flips) / len(flips), 4)
    return {**result, **(extra or {})}


def is_rogue(row, cards):
    hero = row['state']['you']['hero'] or {}
    return cards.get(hero.get('card'), {}).get('cardClass') == 'ROGUE'


def baselines(rows, cards):
    rng = random.Random(0)
    output = {}
    for scope, subset in (('all', rows), ('rogue', [r for r in rows if is_rogue(r, cards)])):
        ks = [len(r['candidates']) for r in subset]
        output[scope] = {
            'windows': len(subset), 'mean_options': round(sum(ks) / len(ks), 2),
            'random_top1': round(sum(1 / k for k in ks) / len(ks), 4),
            'random_top3': round(sum(min(3, k) / k for k in ks) / len(ks), 4),
            'first_option_top1': round(sum(r['label'] == 0 for r in subset) / len(subset), 4),
        }
        ranks = []
        for row in subset:
            scores = rules_scores(row, cards)
            # Random tie-break, so a tie cannot be counted as a win by list order.
            order = sorted(range(len(scores)), key=lambda i: (-scores[i], rng.random()))
            ranks.append(order.index(row['label']))
        output[scope]['rules'] = summary(ranks, ks)
    return output


def run_laya(rows, cards, model_dir, mode, orders):
    max_len = 2048 if mode == 'semantic' else 8192
    import laya
    agent = laya.load(model_dir, device='cuda')
    output = {'all': {}, 'rogue': {}}
    rng = random.Random(1)
    records = []
    truncated = 0
    latency = []
    for row in rows:
        if mode == 'semantic':
            state, texts = render_state(row, cards), [render_candidate(row, c, cards) for c in row['candidates']]
        else:
            state, texts = id_only_state(row), [render_id_only(row, c) for c in row['candidates']]
        k = len(texts)
        permutations = [list(range(k)), list(range(k))[::-1]]
        while len(permutations) < orders:
            shuffled = list(range(k))
            rng.shuffle(shuffled)
            permutations.append(shuffled)
        rank_sum, picks, ranks = [0.0] * k, [], []
        for permutation in permutations:
            started = time.perf_counter()
            response = agent.predict(state, question([texts[i] for i in permutation]),
                                     max_len=max_len, head_max_len=1024, min_confidence=0.0)
            latency.append(time.perf_counter() - started)
            usage = response.get('usage', {})
            if usage.get('truncated') or usage.get('options'):
                truncated += 1
            probabilities = response['answers']['action']['probabilities']
            semantic = [0.0] * k
            for slot, original in enumerate(permutation):
                semantic[original] = probabilities[f'c{slot}']
            order = sorted(range(k), key=lambda i: -semantic[i])
            picks.append(order[0])
            ranks.append(order.index(row['label']))
            rank_sum = [a + b for a, b in zip(rank_sum, semantic)]
        averaged = sorted(range(k), key=lambda i: -rank_sum[i])
        records.append({'rogue': is_rogue(row, cards), 'single': ranks[0], 'flip': len(set(picks)) > 1,
                        'ensemble': averaged.index(row['label'])})
    for scope, subset in (('all', records), ('rogue', [r for r in records if r['rogue']])):
        output[scope] = {'single_order': summary([r['single'] for r in subset], None, [r['flip'] for r in subset]),
                         'order_ensemble': summary([r['ensemble'] for r in subset], None)}
    latency.sort()
    output['truncated_or_collapsed_calls'] = truncated
    output['calls'] = len(latency)
    output['latency_ms_p50'] = round(latency[len(latency) // 2] * 1000, 1)
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', action='append', default=[], help='name=path=mode, mode is semantic or id_only')
    parser.add_argument('--orders', type=int, default=4)
    parser.add_argument('--output', default=os.path.join('.data', 'imitation', 'results.json'))
    args = parser.parse_args()
    configure_environment()
    os.environ['HF_HUB_OFFLINE'] = '1'
    cards = load_cards()
    rows = [r for r in load_rows() if r['group'] in TEST_GROUPS and 1 < len(r['candidates']) <= 32]
    report = {'scope': 'Agreement with moves actually played in held-out games, not playing strength.',
              'test_groups': sorted(TEST_GROUPS), 'baselines': baselines(rows, cards), 'models': {}}
    if os.path.exists(args.output):
        report['models'] = json.load(open(args.output, encoding='utf-8')).get('models', {})
    for spec in args.model:
        name, path, mode = spec.split('=')
        report['models'][name] = run_laya(rows, cards, path, mode, args.orders)
        json.dump(report, open(args.output, 'w', encoding='utf-8'), indent=1)
        print(name, json.dumps(report['models'][name]), flush=True)
    print(json.dumps(report['baselines'], indent=1))
    json.dump(report, open(args.output, 'w', encoding='utf-8'), indent=1)


if __name__ == '__main__':
    main()
