"""Find positions where a two-step Warrior combo was available, and who would start it.

A combo here is an order that matters: the setup must come first and both steps must be affordable
or already available this turn. Positions come from the player's games, so nothing is invented.
"""
import collections
import json
import os
import sys

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.dirname(__file__))
from agent.policy import index_state, load_cards

DECKHAND = 'CS3_008'
DISTRIBUTOR = 'TOY_518'
CANNON = 'GVG_075'
CAPTAIN = 'CORE_NEW1_027'
ENGINEER = 'CAP_104'
HOZEN = 'VAC_938'
ATTACK_BUFFS = {CAPTAIN: 'Southsea Captain before attacks', ENGINEER: 'Blastpowder Engineer before pirate attacks',
                HOZEN: 'Hozen Roughhouser before pirate attacks'}


def races(cards, card_id):
    card = cards.get(card_id, {})
    return set(card.get('races') or ([card['race']] if card.get('race') else []))


def is_pirate(cards, card_id):
    return 'PIRATE' in races(cards, card_id)


def combo_setups(row, cards):
    """Returns {combo name: indices of candidates that start it}."""
    state, found = row['state'], row['candidates']
    you = state['you']
    entities = index_state(state)
    hand = you.get('hand', [])
    mana = you['mana']
    plays = {}
    for index, candidate in enumerate(found):
        kind, source = entities.get(candidate['source'], (None, None))
        if kind == 'hand':
            plays.setdefault(source['id'], []).append(index)
    in_hand = lambda card_id: [c for c in hand if c['card'] == card_id and c['id'] in plays]
    result = {}
    weapons = [c for c in hand if c['type'] == 'WEAPON']
    for deckhand in in_hand(DECKHAND):
        if any(deckhand['cost'] + max(w['cost'] - 1, 0) <= mana for w in weapons):
            result['Bloodsail Deckhand before a weapon'] = plays[deckhand['id']]
    for setup, name in ((DISTRIBUTOR, 'Treasure Distributor before another Pirate'),
                        (CANNON, "Ship's Cannon before another Pirate")):
        for card in in_hand(setup):
            others = [c for c in hand if c['id'] != card['id'] and c['type'] == 'MINION' and is_pirate(cards, c['card'])]
            if any(card['cost'] + o['cost'] <= mana for o in others):
                result[name] = plays[card['id']]
    ready_pirates = {c['source'] for c in found
                     if entities.get(c['source'], (None,))[0] == 'your_minion' and c['target']
                     and is_pirate(cards, entities[c['source']][1]['card'])}
    if ready_pirates:
        for setup, name in ATTACK_BUFFS.items():
            for card in in_hand(setup):
                result[name] = plays[card['id']]
    return result


def main():
    from agent.policy import LayaPolicy
    from retrain import decisions
    cards = load_cards()
    laya = LayaPolicy.load(cards)
    table = collections.defaultdict(collections.Counter)
    examples = []
    for group, hero, row, label in decisions():
        if hero != 'WARRIOR':
            continue
        setups = combo_setups(row, cards)
        if not setups:
            continue
        picks = {'you': label, 'rules': laya.rules.choose(row['state'], row['candidates'], row['cards']),
                 'laya': laya.choose(row['state'], row['candidates'], row['cards'])}
        for name, indices in setups.items():
            table[name]['positions'] += 1
            for who, pick in picks.items():
                table[name][who] += pick in indices
            if len(examples) < 5 and picks['laya'] not in indices and picks['you'] in indices:
                examples.append((group[-6:], row['state']['turn'], name))
    report = {name: dict(values) for name, values in table.items()}
    total = collections.Counter()
    for values in table.values():
        total.update(values)
    report['ALL'] = dict(total)
    print(json.dumps(report, indent=1, ensure_ascii=False))
    print('Laya missed, you started:', examples)


if __name__ == '__main__':
    main()
