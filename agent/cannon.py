"""Conservative Standard cannon Warrior rules using only offered moves and visible state.

Random cannon/volcano damage and hidden triggers are never counted as certain lethal.
"""
from .tactics import _index, _hp, base_id, lethal_setup


def enabled(policy):
    return getattr(policy, 'deck_profile', {}).get('tactics') == 'standard-cannon'


def mulligan(entities, by_entity, cards):
    rows = [(e['id'], by_entity.get(str(e['id'])) or e.get('card', '')) for e in entities]
    opener = any(base_id(c) in {'CAP_107', 'DRG_024'} for _, c in rows)
    keeps = {'CAP_107', 'DRG_024', 'FIR_929', 'CAP_104', 'CAP_105'}
    return [e for e, c in rows if cards.get(c, {}).get('name') != 'The Coin'
            and base_id(c) not in keeps
            and not (opener and base_id(c) in {'REV_990', 'CAP_103'})]


def forced_move(state, candidates, cards):
    found = _index(state)
    you = state['you']
    lethal = lethal_setup(state, candidates, cards)
    if lethal is not None:
        return lethal, 'tactics:lethal_setup'
    crowley = crowley_setup(state, candidates, cards)
    if crowley is not None:
        return crowley, 'cannon:crowley_setup'
    # Use a remaining weapon swing before replacing it or before drawing at a full hand.
    attacks = [(i, m) for i, m in enumerate(candidates)
               if found.get(m['source'], (None,))[0] == 'your_hero'
               and found.get(m['target'], (None,))[0] == 'enemy_hero'
               and m.get('sub', -1) < 0]
    weapon = you.get('weapon')
    if weapon and attacks and _hp(you['hero']) > 0:
        replacing = any(found.get(m['source'], (None,))[0] == 'hand'
                        and found[m['source']][1]['type'] == 'WEAPON' for m in candidates)
        if replacing and weapon.get('atk', 0) > 0:
            return attacks[0][0], 'cannon:weapon_before_replacement'
    return None


def crowley_setup(state, candidates, cards):
    """Develop Crowley before ordinary value plays and cannon-firing hero swings."""
    you, enemy = state['you'], state['opponent']
    room = 7 - len(you['minions'])
    cannons = sum(base_id(m['card']) == 'CAP_107t' and 'SILENCED' not in m['keywords'] for m in you['minions'])
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
