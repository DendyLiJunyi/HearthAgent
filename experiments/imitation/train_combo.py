"""Teach combos with lessons built from real boards, then compare against the current checkpoint.

A lesson edits a real position so one combo is available and labels its first step as correct. These
labels are a stated opinion about card order, not the player's moves. Held-out games never feed
training, and their boards are only used to build a separate test set.
"""
import copy
import json
import os
import random
import sys

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'laya'))
from agent.policy import LayaPolicy, index_state, load_cards
from combos import ATTACK_BUFFS, CANNON, DECKHAND, DISTRIBUTOR, combo_setups, is_pirate
from features import TEST_GROUPS, question, render_candidate, render_state
from retrain import WARRIOR_TEST, decisions
from runtime import MODEL_REVISION, ROOT, configure_environment

OUTPUT = ROOT / '.data/imitation/laya-combo'
CURRENT = ROOT / '.data/imitation/laya-finetuned'
HAND_CANNON = 'CAP_103'
PIRATE_PAYOFFS = ['CAP_107', 'YOD_022', 'DRG_056', 'CAP_104', 'VAC_938', 'CORE_NEW1_027']
LESSONS = 420
TEST_LESSONS = 120


def set_card(row, entity, card_id, cards):
    entity['card'] = card_id
    entity['cost'] = cards[card_id].get('cost', 0)
    entity['type'] = cards[card_id]['type']
    row['cards'][str(entity['id'])] = card_id


def build_lesson(base, rng, cards):
    """Returns (row, setup index, combo type), or None if this board cannot hold the lesson."""
    row = copy.deepcopy(base)
    you = row['state']['you']
    hand = you.get('hand', [])
    if len(hand) < 2:
        return None
    kind = rng.choice(['deckhand', 'distributor', 'cannon', 'attack_buff'])
    first, second = rng.sample(hand, 2)
    if kind == 'attack_buff':
        ready = [m for m in you['minions'] if m['type'] == 'MINION']
        if not ready:
            return None
        attacker = rng.choice(ready)
        attacker['card'] = 'CAP_107'
        attacker['atk'] = max(attacker['atk'], 1)
        row['cards'][str(attacker['id'])] = 'CAP_107'
        setup_card = rng.choice(list(ATTACK_BUFFS))
        set_card(row, first, setup_card, cards)
        total = first['cost']
    else:
        setup_card = {'deckhand': DECKHAND, 'distributor': DISTRIBUTOR, 'cannon': CANNON}[kind]
        payoff = HAND_CANNON if kind == 'deckhand' else rng.choice(PIRATE_PAYOFFS)
        set_card(row, first, setup_card, cards)
        set_card(row, second, payoff, cards)
        total = first['cost'] + second['cost']
    you['max_mana'] = max(you['max_mana'], total)
    you['mana'] = min(10, total + rng.randint(0, 1))
    you['max_mana'] = max(you['max_mana'], you['mana'])
    entities = index_state(row['state'])
    kept = [c for c in base['candidates'] if entities.get(c['source'], (None,))[0] != 'hand']
    plays = [{'kind': 'power', 'source': c['id'], 'target': 0, 'sub': -1, 'sub_entity': None, 'sub_card': None,
              'sub_slot': None, 'sub_total': 0} for c in hand if c['cost'] <= you['mana']]
    if kind == 'attack_buff':
        enemy = row['state']['opponent']['hero']['id']
        if not any(c['source'] == attacker['id'] and c['target'] for c in kept):
            kept.append({'kind': 'power', 'source': attacker['id'], 'target': enemy, 'sub': -1, 'sub_entity': None,
                         'sub_card': None, 'sub_slot': None, 'sub_total': 0})
    found = kept + plays
    if not 1 < len(found) <= 32:
        return None
    rng.shuffle(found)
    for number, candidate in enumerate(found):
        candidate['option'] = number
    row['candidates'] = found
    label = next(i for i, c in enumerate(found) if c['source'] == first['id'] and c['kind'] == 'power')
    if not any(label in indices for indices in combo_setups(row, cards).values()):
        return None
    return row, label, kind


def lessons_from(rows, count, seed, cards):
    rng = random.Random(seed)
    built = []
    attempts = 0
    while len(built) < count and attempts < count * 60:
        attempts += 1
        lesson = build_lesson(rng.choice(rows), rng, cards)
        if lesson:
            built.append(lesson)
    return built


def as_training(row, label, cards):
    return {'state': render_state(row, cards),
            'questions': question([render_candidate(row, c, cards) for c in row['candidates']]),
            'gold': {'action': {'probabilities': {f'c{label}': 1.0}}}}


def main():
    configure_environment()
    os.environ['HF_HUB_OFFLINE'] = '1'
    cards = load_cards()
    train, warrior_boards, warrior_test, warrior_test_boards, older = [], [], [], [], []
    for group, hero, row, label in decisions():
        if group in WARRIOR_TEST:
            warrior_test.append((row, label))
            warrior_test_boards.append(row)
        elif group in TEST_GROUPS:
            older.append((row, label))
        else:
            train.append(as_training(row, label, cards))
            if hero == 'WARRIOR':
                warrior_boards.append(row)
    lessons = lessons_from(warrior_boards, LESSONS, 11, cards)
    test_lessons = lessons_from(warrior_test_boards, TEST_LESSONS, 12, cards)
    rows = train + [as_training(r, l, cards) for r, l, _ in lessons]
    random.Random(0).shuffle(rows)
    data = ROOT / '.data/imitation/train-combo.jsonl'
    with open(data, 'w', encoding='utf-8') as out:
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=False) + '\n')
    print(json.dumps({'your_moves': len(train), 'lessons': len(lessons), 'test_lessons': len(test_lessons)}), flush=True)
    base = ROOT / '.tools/huggingface/hub/models--convaiinnovations--laya/snapshots' / MODEL_REVISION / 'multilingual'
    from laya.train import TrainConfig, finetune
    config = TrainConfig(epochs=6, micro_batch=4, grad_accum=2, loss='soft-ce', shuffle_options=('choice',),
                         max_len=2048, head_max_len=1024, log_every=60)
    finetune(str(data), str(base), str(OUTPUT), config, device='cuda')

    report = {'scope': 'Combo lessons are built from held-out boards. Match is agreement with the player.',
              'warrior_decisions': len(warrior_test), 'older_decisions': len(older), 'test_lessons': len(test_lessons)}
    real_combo = [(r, l) for r, l in warrior_test if combo_setups(r, cards)]
    report['real_held_out_combo_positions'] = len(real_combo)
    for name, path in (('current', CURRENT), ('combo', OUTPUT)):
        policy = LayaPolicy.load(cards, path)
        pick = lambda r: policy.choose(r['state'], r['candidates'], r['cards'])
        by_kind = {}
        for row, label, kind in test_lessons:
            right = pick(row) == label
            by_kind.setdefault(kind, []).append(right)
        report[name] = {
            'lesson_start_rate': round(sum(sum(v) for v in by_kind.values()) / len(test_lessons), 4),
            'by_combo': {k: f'{sum(v)}/{len(v)}' for k, v in by_kind.items()},
            'real_combo_start': sum(any(pick(r) in i for i in combo_setups(r, cards).values()) for r, _ in real_combo),
            'warrior_match': round(sum(pick(r) == l for r, l in warrior_test) / len(warrior_test), 4),
            'older_match': round(sum(pick(r) == l for r, l in older) / len(older), 4),
            'fallbacks': policy.fallbacks}
        print(name, json.dumps(report[name]), flush=True)
    rules = LayaPolicy(cards, None).rules
    report['rules'] = {'lesson_start_rate': round(sum(rules.choose(r['state'], r['candidates'], r['cards']) == l
                                                      for r, l, _ in test_lessons) / len(test_lessons), 4)}
    report['random'] = {'lesson_start_rate': round(sum(1 / len(r['candidates']) for r, _, _ in test_lessons) / len(test_lessons), 4)}
    print(json.dumps(report, indent=1))
    with open(ROOT / '.data/imitation/combo-comparison.json', 'w', encoding='utf-8') as out:
        json.dump(report, out, indent=1)


if __name__ == '__main__':
    main()
