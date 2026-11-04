"""Is one method really ahead? Pairs methods on the same decisions and resamples whole games.

Decisions inside a game are not independent, so resampling games is the honest test here. With
five test games it is wide and rough. Nothing here feeds back into any model or rule.
"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'laya'))
from features import (TEST_GROUPS, id_only_state, load_cards, load_rows, question, render_candidate,
                      render_id_only, render_state, rules_scores)
from runtime import MODEL_REVISION, ROOT, configure_environment

BASE = str(ROOT / '.tools/huggingface/hub/models--convaiinnovations--laya/snapshots' / MODEL_REVISION / 'multilingual')
MODELS = {'id_only': (BASE, 'id_only'), 'readable': (BASE, 'semantic'),
          'finetuned': (str(ROOT / '.data/imitation/laya-finetuned'), 'semantic')}
ORDERS = 4


def hits_for(rows, cards, path, mode):
    import laya
    agent = laya.load(path, device='cuda')
    rng = random.Random(1)
    hits = []
    for row in rows:
        if mode == 'semantic':
            state, texts = render_state(row, cards), [render_candidate(row, c, cards) for c in row['candidates']]
        else:
            state, texts = id_only_state(row), [render_id_only(row, c) for c in row['candidates']]
        k = len(texts)
        orders = [list(range(k)), list(range(k))[::-1]]
        while len(orders) < ORDERS:
            shuffled = list(range(k))
            rng.shuffle(shuffled)
            orders.append(shuffled)
        total = [0.0] * k
        for order in orders:
            response = agent.predict(state, question([texts[i] for i in order]),
                                     max_len=2048 if mode == 'semantic' else 8192,
                                     head_max_len=1024, min_confidence=0.0)
            probabilities = response['answers']['action']['probabilities']
            for slot, original in enumerate(order):
                total[original] += probabilities[f'c{slot}']
        hits.append(max(range(k), key=lambda i: total[i]) == row['label'])
    return hits


def compare(a, b, groups, rounds=10000):
    """Mean difference and a 95% interval, resampling whole games."""
    rng = random.Random(0)
    names = sorted(set(groups))
    by_game = {n: [(x, y) for x, y, g in zip(a, b, groups) if g == n] for n in names}
    differences = []
    for _ in range(rounds):
        picked = [p for n in rng.choices(names, k=len(names)) for p in by_game[n]]
        differences.append(sum(x - y for x, y in picked) / len(picked))
    differences.sort()
    only_a = sum(x and not y for x, y in zip(a, b))
    only_b = sum(y and not x for x, y in zip(a, b))
    return {'difference': round(sum(x - y for x, y in zip(a, b)) / len(a), 4),
            'ci95': [round(differences[int(rounds * .025)], 4), round(differences[int(rounds * .975)], 4)],
            'only_first_right': only_a, 'only_second_right': only_b}


def main():
    configure_environment()
    os.environ['HF_HUB_OFFLINE'] = '1'
    cards = load_cards()
    rows = [r for r in load_rows() if r['group'] in TEST_GROUPS and 1 < len(r['candidates']) <= 32]
    groups = [r['group'] for r in rows]
    rng = random.Random(0)
    results = {}
    for row in rows:
        scores = rules_scores(row, cards)
        order = sorted(range(len(scores)), key=lambda i: (-scores[i], rng.random()))
        results.setdefault('rules', []).append(order[0] == row['label'])
    for name, (path, mode) in MODELS.items():
        results[name] = hits_for(rows, cards, path, mode)
        print(name, round(sum(results[name]) / len(rows), 4), flush=True)
    report = {'n': len(rows), 'games': len(set(groups)),
              'top1': {k: round(sum(v) / len(rows), 4) for k, v in results.items()},
              'per_game': {g[-27:]: {k: round(sum(h for h, x in zip(v, groups) if x == g) / groups.count(g), 3)
                                     for k, v in results.items()} for g in sorted(set(groups))}}
    for first, second in (('readable', 'id_only'), ('finetuned', 'readable'), ('finetuned', 'rules'), ('rules', 'id_only')):
        report[f'{first}_vs_{second}'] = compare(results[first], results[second], groups)
    print(json.dumps(report, indent=1))
    with open(ROOT / '.data/imitation/paired.json', 'w', encoding='utf-8') as out:
        json.dump(report, out, indent=1)


if __name__ == '__main__':
    main()
