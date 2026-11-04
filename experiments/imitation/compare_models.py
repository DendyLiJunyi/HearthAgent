"""Compare the current and retrained checkpoints as deployed, on games neither was trained on.

Matching the player's move is not playing strength. Both Laya rows include the blunder checks.
"""
import json
import os
import random
import sys

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.dirname(__file__))
from agent.policy import LayaPolicy, load_cards
from features import TEST_GROUPS
from retrain import ROOT, WARRIOR_TEST, decisions

CHECKPOINTS = {'current': ROOT / '.data/imitation/laya-finetuned', 'retrained': ROOT / '.data/imitation/laya-warrior'}
KEYS = ('option', 'sub', 'target')


def score(rows, policy):
    """Picks through the real policy. Repeats use more orders, so each order set is deterministic."""
    results = []
    for row, label in rows:
        found = row['candidates']
        picked = policy.choose(row['state'], found, row['cards'])
        results.append(picked == label)
    return results


def flip_rate(rows, policy):
    flips = 0
    for row, _ in rows:
        found = row['candidates']
        allowed = policy.allowed(row['state'], found)
        picks = set()
        for order in ([*range(len(found))], [*range(len(found))][::-1]):
            shuffled = [found[i] for i in order]
            totals = policy.rank_one_order(row['state'], shuffled, row['cards'])
            mapped = {order[slot]: value for slot, value in enumerate(totals)}
            picks.add(max(allowed, key=lambda i: mapped[i]))
        flips += len(picks) > 1
    return round(flips / len(rows), 4)


def main():
    cards = load_cards()
    warrior, older = [], []
    for group, _, row, label in decisions():
        if group in WARRIOR_TEST:
            warrior.append((row, label))
        elif group in TEST_GROUPS:
            older.append((row, label))
    report = {'scope': 'Agreement with the player on held-out games, not playing strength.'}
    per_model = {}
    for name, path in CHECKPOINTS.items():
        policy = LayaPolicy.load(cards, path)
        policy.rank_one_order = lambda state, found, card_map, p=policy: _one_order(p, state, found, card_map)
        per_model[name] = {'warrior': score(warrior, policy), 'older': score(older, policy)}
        report[name] = {'warrior_match': round(sum(per_model[name]['warrior']) / len(warrior), 4),
                        'older_match': round(sum(per_model[name]['older']) / len(older), 4),
                        'warrior_flip_rate': flip_rate(warrior, policy), 'fallbacks': policy.fallbacks}
        print(name, report[name], flush=True)
    rules = LayaPolicy.load.__self__(cards, lambda *_: None).rules
    report['rules'] = {'warrior_match': round(sum(rules.choose(r['state'], r['candidates'], r['cards']) == l for r, l in warrior) / len(warrior), 4),
                       'older_match': round(sum(rules.choose(r['state'], r['candidates'], r['cards']) == l for r, l in older) / len(older), 4)}
    report['random'] = {'warrior_match': round(sum(1 / len(r['candidates']) for r, _ in warrior) / len(warrior), 4),
                        'older_match': round(sum(1 / len(r['candidates']) for r, _ in older) / len(older), 4)}
    report['warrior_decisions'] = len(warrior)
    report['older_decisions'] = len(older)
    new, old = per_model['retrained']['warrior'], per_model['current']['warrior']
    report['warrior_only_retrained_right'] = sum(a and not b for a, b in zip(new, old))
    report['warrior_only_current_right'] = sum(b and not a for a, b in zip(new, old))
    print(json.dumps(report, indent=1))
    with open(ROOT / '.data/imitation/retrain-comparison.json', 'w', encoding='utf-8') as out:
        json.dump(report, out, indent=1)


def _one_order(policy, state, found, card_map):
    sys.path.insert(0, str(ROOT / 'experiments/imitation'))
    from features import question, render_candidate, render_state
    row = {'state': state, 'candidates': found, 'cards': card_map or {}}
    answer = policy.predict(render_state(row, policy.cards),
                            question([render_candidate(row, c, policy.cards) for c in found]))['answers']['action']
    return [answer['probabilities'][f'c{i}'] for i in range(len(found))]


if __name__ == '__main__':
    main()
