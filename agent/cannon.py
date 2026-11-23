"""Conservative Standard cannon Warrior rules using only offered moves and visible state.

Random cannon/volcano damage and hidden triggers are never counted as certain lethal.
"""
from .tactics import _index, _hp, base_id, lethal_setup


def active_cannoneer(minion):
    return base_id(minion['card']) == 'CAP_107t' and 'SILENCED' not in minion['keywords']


def enabled(policy):
    return getattr(policy, 'deck_profile', {}).get('tactics') == 'standard-cannon'


def mulligan(entities, by_entity, cards):
    rows = [(e['id'], by_entity.get(str(e['id'])) or e.get('card', '')) for e in entities]
    held = {base_id(card) for _, card in rows}
    opener = bool(held & {'CAP_107', 'DRG_024'})
    keeps = {'CAP_107', 'DRG_024', 'FIR_929', 'CAP_104', 'CAP_105'}
    if opener or 'CAP_105' in held:
        keeps.add('CAP_103')
    if 'FIR_929' in held:
        keeps.add('END_020')
    return [e for e, c in rows if cards.get(c, {}).get('name') != 'The Coin'
            and base_id(c) not in keeps
            and not (opener and base_id(c) == 'REV_990')]


def forced_move(state, candidates, cards):
    found = _index(state)
    you = state['you']
    lethal = lethal_setup(state, candidates, cards)
    if lethal is not None:
        return lethal, 'tactics:lethal_setup'
    crowley = crowley_setup(state, candidates, cards)
    if crowley is not None:
        return crowley, 'cannon:crowley_setup'
    face = next((i for i, move in enumerate(candidates)
                 if move['source'] == you['hero']['id'] and move['target'] == state['opponent']['hero']['id']
                 and move.get('sub', -1) < 0), None)
    weapon = you.get('weapon')
    if not weapon:
        return None
    plays = [(i, found[move['source']][1]) for i, move in enumerate(candidates)
             if found.get(move['source'], (None,))[0] == 'hand' and not move['target']
             and move.get('sub', -1) < 0 and found[move['source']][1]['cost'] <= you['mana']]
    cannons = [minion for minion in you['minions'] if active_cannoneer(minion)]
    if base_id(weapon['card']) == 'CAP_103' and cannons:
        fire = face if face is not None else safe_cannon_attack(state, candidates, found, weapon)
        engineer = next((i for i, card in plays if base_id(card['card']) == 'CAP_104'), None)
        if fire is not None and engineer is not None and len(you['minions']) < 7:
            return engineer, 'cannon:engineer_before_firing'
        if fire is not None and any(base_id(card['card']) == 'CATA_582' for _, card in plays) and any(
                fissure_kills(minion) for minion in cannons):
            return fire, 'cannon:fire_before_fissure'
    if face is not None and weapon.get('atk', 0) > 0 and any(card['type'] == 'WEAPON' for _, card in plays):
        return face, 'cannon:weapon_before_replacement'
    return None


def safe_cannon_attack(state, candidates, found, weapon):
    hero = state['you']['hero']
    attack = max(hero['atk'], weapon['atk'])
    life = _hp(hero) + hero['armor']
    for index, move in enumerate(candidates):
        side, target = found.get(move['target'], (None, None))
        if move['source'] == hero['id'] and move.get('sub', -1) < 0 and side == 'enemy_minion' and (
                0 < _hp(target) <= attack and target['atk'] <= 4 and target['atk'] < life
                and not {'DIVINE_SHIELD', 'IMMUNE'}.intersection(target['keywords'])):
            return index
    return None


def crowley_setup(state, candidates, cards):
    """Develop Crowley before ordinary value plays and cannon-firing hero swings."""
    you, enemy = state['you'], state['opponent']
    room = 7 - len(you['minions'])
    cannons = sum(map(active_cannoneer, you['minions']))
    if room < 1 or (room < 2 and not cannons):
        return None
    # Skipper's minion-play trigger kills the newly summoned 1/1 Cannoneers.
    if any(base_id(m['card']) == 'YOD_022' and 'SILENCED' not in m['keywords'] for m in you['minions']):
        return None
    hand = {c['id']: c for c in you.get('hand', [])}
    plays = [(i, hand[m['source']]) for i, m in enumerate(candidates)
             if m['source'] in hand and not m['target'] and m.get('sub', -1) < 0
             and hand[m['source']]['cost'] <= you['mana']]
    incoming = sum(m['atk'] for m in enemy['minions'] if m['type'] == 'MINION')
    incoming += max(enemy['hero']['atk'], (enemy.get('weapon') or {}).get('atk', 0))
    life = _hp(you['hero']) + you['hero']['armor']
    if incoming >= life and any('TAUNT' in cards.get(c['card'], {}).get('mechanics', []) for _, c in plays):
        return None  # Let survival choices compete instead of forcing cannon development.
    return next((i for i, c in plays if base_id(c['card']) == 'CAP_106'), None)


def fissure_kills(minion):
    return (minion['type'] == 'MINION' and _hp(minion) == 1
            and not {'DIVINE_SHIELD', 'IMMUNE'}.intersection(minion['keywords']))


def rule_score(state, candidate, found):
    """Score the deck's flexible spells and silence using the visible target and board."""
    kind, source = found.get(candidate['source'], (None, None))
    if kind != 'hand' or candidate.get('sub', -1) >= 0:
        return None
    card = base_id(source['card'])
    side, target = found.get(candidate['target'], (None, None))
    if card == 'END_020' and side in ('your_minion', 'enemy_minion') and target['type'] == 'MINION':
        if {'DIVINE_SHIELD', 'IMMUNE'}.intersection(target['keywords']):
            return -5
        if side == 'enemy_minion':
            return 65 + min(target['atk'], 8) * 3 if _hp(target) == 1 else 25
        if _hp(target) > 1:
            return 56 - min(target['atk'], 8)
        if base_id(target['card']) == 'FIR_929' and 'SILENCED' not in target['keywords']:
            return 64
        return -5
    if card == 'SW_066' and target:
        if side != 'enemy_minion' or 'SILENCED' in target['keywords']:
            return -5
        if {'TAUNT', 'DEATHRATTLE', 'LIFESTEAL'}.intersection(target['keywords']):
            return 74
        return 49
    if card == 'CATA_582':
        losses = [m for m in state['you']['minions'] if fissure_kills(m)]
        kills = [m for m in state['opponent']['minions'] if fissure_kills(m)]
        loss = sum(14 + m['atk'] * 2 + 12 * active_cannoneer(m) for m in losses)
        benefit = sum(12 + m['atk'] * 3 for m in kills)
        # Keep it for a useful exchange when it would mostly clear our own board.
        if losses and benefit < loss:
            return -5
        if kills:
            return 53 + benefit - loss
        hero = state['you']['hero']
        can_use_attack = (not hero.get('attacks', 0)
                          and not {'FROZEN', 'CANT_ATTACK'}.intersection(hero['keywords']))
        return 48 if can_use_attack else -5
    return None


def allowed(state, candidates, cards):
    """Avoid obvious waste; never remove every offered action."""
    found = _index(state)
    keep = []
    for i, move in enumerate(candidates):
        kind, source = found.get(move['source'], (None, None))
        target_kind, target = found.get(move['target'], (None, None))
        bad = False
        if kind == 'hand':
            card = base_id(source['card'])
            if source['cost'] > state['you']['mana']:
                bad = True
            if source['type'] == 'MINION' and len(state['you']['minions']) >= 7:
                bad = True
            if card == 'CAP_102' and len(state['you'].get('hand', [])) >= 10:
                bad = True  # Playing one card leaves only one draw slot.
            if card in {'CATA_585', 'FIR_939'} and target_kind in ('your_minion', 'your_hero'):
                bad = True
        if source and base_id(source['card']) == 'REV_990' and kind == 'your_minion':
            bad = target_kind != 'your_minion' or _hp(target) <= 1 or 'IMMUNE' in target['keywords']
        if not bad:
            keep.append(i)
    return keep or list(range(len(candidates)))
