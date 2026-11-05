"""Pirate Warrior knowledge that an imitation model cannot be relied on to learn from a few games.

Each forced move is a narrow pattern with a clear reason. Anything else stays with the model. These
are judgment calls about this deck, tested on constructed boards only, and have not been measured in
live games. A card this module does not know about is left to the general rules.
"""
from itertools import combinations

COIN_NAME = 'The Coin'
SOUTHSEA_CAPTAIN = 'NEW1_027'
BLASTPOWDER_ENGINEER = 'CAP_104'
HOZEN_ROUGHHOUSER = 'VAC_938'
RISKY_SKIPPER = 'YOD_022'
PATCHES = 'CFM_637'
BLOODSAIL_DECKHAND = 'CS3_008'
HAND_CANNON = 'CAP_103'
CORSAIR_CACHE = 'BT_124'
ANIMA_EXTRACTOR = 'REV_332'
# Played before Pirates attack, best first, because each one makes those attacks stronger.
ATTACK_BUFFS = (SOUTHSEA_CAPTAIN, BLASTPOWDER_ENGINEER, HOZEN_ROUGHHOUSER)
LETHAL_PIRATE_BONUS = {SOUTHSEA_CAPTAIN: 1, BLASTPOWDER_ENGINEER: 1}  # Hozen pays out too late to count on.
MULLIGAN_ALWAYS = {'YOD_022', BLOODSAIL_DECKHAND, 'TOY_518', 'CAP_107', 'GVG_075', 'DRG_056', 'CAP_104', 'CAP_105'}
MULLIGAN_CURVE_TOPPERS = {SOUTHSEA_CAPTAIN, HOZEN_ROUGHHOUSER}
KEEP_MAX_COST = 2
HERO_HIT_LIMIT = 4  # A hero attack that kills nothing is not worth this much health.
TOO_SLOW_TO_KEEP = {'CAP_102', 'CAP_106', 'JAIL_421', 'JAIL_384'}  # Land Ho!, Crowley, Warptooth, Hogger


def base_id(card_id):
    return (card_id or '').removeprefix('CORE_')


def is_pirate(card):
    races = card.get('races') or [card.get('race')]
    return 'PIRATE' in races


def _index(state):
    you, opponent = state['you'], state['opponent']
    found = {card['id']: ('hand', card) for card in you.get('hand', [])}
    for minion in you['minions']:
        found[minion['id']] = ('your_minion', minion)
    for minion in opponent['minions']:
        found[minion['id']] = ('enemy_minion', minion)
    if you['hero']:
        found[you['hero']['id']] = ('your_hero', you['hero'])
    if opponent['hero']:
        found[opponent['hero']['id']] = ('enemy_hero', opponent['hero'])
    return found


def _hp(entity):
    return entity['health'] - entity['damage']


def _best_spend(costs, mana):
    reachable = {0}
    for cost in costs:
        reachable |= {total + cost for total in reachable if total + cost <= mana}
    return max(reachable)


def _skipper_risk(state):
    """Risky Skipper hits every minion after a minion is played, which would kill our own 1-health minions."""
    minions = state['you']['minions']
    return any(base_id(m['card']) == RISKY_SKIPPER for m in minions) and any(_hp(m) <= 1 for m in minions)


def _hand_plays(candidates, found):
    """Untargeted plays from hand, one move for each card."""
    plays = {}
    for index, move in enumerate(candidates):
        kind, card = found.get(move['source'], (None, None))
        if kind == 'hand' and not move['target'] and move.get('sub', -1) < 0 and move['source'] not in plays:
            plays[move['source']] = (index, card)
    return plays


def lethal_setup(state, candidates, cards):
    """A card from hand that turns next attacks into exactly enough damage, or None.

    Counts only what the log shows: Charge from hand and flat Pirate buffs on attackers that already reach
    the enemy hero. Random damage and anything that needs a target are not counted.
    """
    found = _index(state)
    opponent = state['opponent']
    if any('TAUNT' in m['keywords'] for m in opponent['minions']) or _skipper_risk(state):
        return None
    enemy = _hp(opponent['hero']) + opponent['hero']['armor']
    attackers = {c['source'] for c in candidates if c['target'] == opponent['hero']['id']
                 and found.get(c['source'], (None,))[0] in ('your_minion', 'your_hero')}
    damage = sum(found[a][1]['atk'] for a in attackers)
    pirates = sum(found[a][0] == 'your_minion' and is_pirate(cards.get(found[a][1]['card'], {})) for a in attackers)
    plays = _hand_plays(candidates, found)
    room = 7 - len(state['you']['minions'])
    best = None
    for size in range(1, min(len(plays), 3) + 1):
        for group in combinations(plays.values(), size):
            if sum(card['cost'] for _, card in group) > state['you']['mana']:
                continue
            minions = [card for _, card in group if card['type'] == 'MINION']
            if len(minions) > room:
                continue
            total = damage
            useful = []
            for index, card in group:
                bonus = LETHAL_PIRATE_BONUS.get(base_id(card['card']), 0) * pirates
                charge = 'CHARGE' in (cards.get(card['card'], {}).get('mechanics') or [])
                gain = bonus + (card['atk'] if charge and card['type'] == 'MINION' else 0)
                total += gain
                useful.append((bonus > 0, gain, index))
            if total >= enemy and all(gain > 0 for _, gain, _ in useful):
                # Aura first, since it also helps a Pirate with Charge played after it.
                order = sorted(useful, key=lambda row: (not row[0], -row[1]))
                cost = sum(card['cost'] for _, card in group)
                if best is None or cost < best[0]:
                    best = (cost, order[0][2])
        if best:
            break
    return best[1] if best else None


def buff_first(state, candidates, pick, cards):
    """If the chosen move is a Pirate attack and a buff is playable, play the buff first, else None.

    This corrects only the attack. Choosing another card first is left alone, because the player's own
    games often do that for good reasons.
    """
    if _skipper_risk(state) or len(state['you']['minions']) >= 7:
        return None
    found = _index(state)
    move = candidates[pick]
    pirate_attack = (found.get(move['source'], (None,))[0] == 'your_minion' and move['target']
                     and is_pirate(cards.get(found[move['source']][1]['card'], {})))
    if not pirate_attack:
        return None
    plays = _hand_plays(candidates, found)
    for wanted in ATTACK_BUFFS:
        for index, card in plays.values():
            if base_id(card['card']) == wanted:
                return index
    return None


def coin_tempo(state, candidates, cards):
    """Spend The Coin only to avoid wasting this turn's mana, such as a two-drop on turn one.

    With a way to spend all current mana it is held, since it is worth more on a later turn.
    """
    found = _index(state)
    plays = {}
    coin = None
    for index, move in enumerate(candidates):
        kind, card = found.get(move['source'], (None, None))
        if kind != 'hand':
            continue
        if cards.get(card['card'], {}).get('name') == COIN_NAME:
            coin = index if coin is None else coin
        else:
            plays[move['source']] = card['cost']
    if coin is None:
        return None
    mana = state['you']['mana']
    # Options list only what is playable now, so cards one mana out of reach come from the hand itself.
    costs = [card['cost'] for card in state['you'].get('hand', [])
             if cards.get(card['card'], {}).get('name') != COIN_NAME and card['cost'] <= mana + 1]
    usable_now = _best_spend(plays.values(), mana)
    return coin if usable_now < mana and _best_spend(costs, mana + 1) > usable_now + 1 else None


def coin_before_passing(state, candidates, cards):
    """About to end the turn, spend The Coin if it pays for a minion or weapon that would otherwise wait.

    Spells are left out because a card one mana out of reach has no option yet, so its targets are unknown.
    Risky Skipper is left out because it can hurt our own board.
    """
    found = _index(state)
    coin = next((i for i, move in enumerate(candidates) if found.get(move['source'], (None, None))[0] == 'hand'
                 and cards.get(found[move['source']][1]['card'], {}).get('name') == COIN_NAME), None)
    if coin is None or _skipper_risk(state):
        return None
    you = state['you']
    for card in you.get('hand', []):
        fits = card['type'] == 'WEAPON' or (card['type'] == 'MINION' and len(you['minions']) < 7)
        if fits and card['cost'] == you['mana'] + 1 and base_id(card['card']) != RISKY_SKIPPER:
            return coin
    return None


def _attacker_stats(state, kind, attacker, cards):
    """Attack and remaining health as the attack lands. Hozen buffs another Pirate as it attacks."""
    if kind == 'your_hero':
        weapon = state['you'].get('weapon')
        return max(attacker['atk'], weapon['atk'] if weapon else 0), _hp(attacker) + attacker['armor']
    buffed = is_pirate(cards.get(attacker['card'], {})) and any(
        base_id(m['card']) == HOZEN_ROUGHHOUSER and m['id'] != attacker['id'] for m in state['you']['minions'])
    return attacker['atk'] + buffed, _hp(attacker) + buffed


def _finished_by_others(state, candidate, candidates, found, cards, power):
    """The other legal attacks on this target can kill it this turn."""
    target = found[candidate['target']][1]
    shielded = 'DIVINE_SHIELD' in target['keywords']
    total = 0 if shielded else power  # Our hit only removes a Divine Shield.
    for move in candidates:
        kind, other = found.get(move['source'], (None, None))
        if move['source'] == candidate['source'] or move['target'] != candidate['target']:
            continue
        if kind == 'your_minion' and 'POISONOUS' in other['keywords'] and not shielded:
            return True
        if kind in ('your_minion', 'your_hero'):
            total += _attacker_stats(state, kind, other, cards)[0]
    return total >= _hp(target)


def wasted_attack(state, candidate, candidates, cards):
    """True for an attack on a minion that gives up too much and kills nothing.

    A minion may die without a kill only for a Taunt or when other attacks can finish the target. The hero
    takes no large hit without a kill even then, because the minions can attack first, and never attacks
    into its own death.
    """
    found = _index(state)
    kind, attacker = found.get(candidate['source'], (None, None))
    target_kind, target = found.get(candidate['target'], (None, None))
    if kind not in ('your_minion', 'your_hero') or target_kind != 'enemy_minion':
        return False
    power, life = _attacker_stats(state, kind, attacker, cards)
    words = attacker['keywords']
    if 'IMMUNE' in words:
        return False
    if kind == 'your_hero' and target['atk'] >= life:
        return True
    shielded = 'DIVINE_SHIELD' in target['keywords']
    if not shielded and 'IMMUNE' not in target['keywords'] and (power >= _hp(target) or 'POISONOUS' in words):
        return False
    if 'TAUNT' in target['keywords']:
        return False
    if kind == 'your_hero':
        return target['atk'] >= HERO_HIT_LIMIT
    if 'DIVINE_SHIELD' in words or 'DEATHRATTLE' in words or target['atk'] < life:
        return False
    return not _finished_by_others(state, candidate, candidates, found, cards, power)


def without_wasted_attacks(state, candidates, pool, cards):
    return [i for i in pool if not wasted_attack(state, candidates[i], candidates, cards)] or pool


def forced_move(state, candidates, cards):
    """(candidate index, reason) when a known pattern decides the move, otherwise None."""
    for reason, rule in (('tactics:lethal_setup', lethal_setup), ('tactics:coin_tempo', coin_tempo)):
        index = rule(state, candidates, cards)
        if index is not None:
            return index, reason
    return None


def mulligan(entities, cards_by_entity, cards):
    """Entity IDs to replace. A low curve wins for this deck, so every keep supports turns one to three."""
    # The log offers The Coin going second, but it is not a card that can be replaced.
    rows = []
    for entity in entities:
        card_id = cards_by_entity.get(str(entity['id'])) or entity.get('card') or ''
        rows.append((entity['id'], base_id(card_id), cards.get(card_id, {})))
    real = [row for row in rows if row[2].get('name') != COIN_NAME]
    going_second = len(real) < len(rows)
    ids = {row[1] for row in real}
    cheap = sum(row[1] in MULLIGAN_ALWAYS and row[1] != PATCHES for row in real)
    replace = []
    for entity_id, card_id, card in real:
        if card_id == PATCHES:
            keep = False  # Another Pirate summons it from the deck for free.
        elif card_id in MULLIGAN_ALWAYS:
            keep = True
        elif card_id in MULLIGAN_CURVE_TOPPERS:
            keep = cheap >= 2 or (going_second and cheap >= 1)
        elif card_id == HAND_CANNON:
            keep = BLOODSAIL_DECKHAND in ids or going_second
        elif card_id == CORSAIR_CACHE:
            keep = cheap >= 1
        elif card_id == ANIMA_EXTRACTOR:
            keep = RISKY_SKIPPER in ids
        elif card_id in TOO_SLOW_TO_KEEP:
            keep = False
        else:
            keep = card.get('cost', 0) <= KEEP_MAX_COST  # Not this deck, so use the general curve rule.
        if not keep:
            replace.append(entity_id)
    return replace
