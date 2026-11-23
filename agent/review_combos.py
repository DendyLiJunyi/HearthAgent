"""Find affordable two-step Pirate Warrior combinations for match reviews."""
import collections

from .policy import index_state

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
