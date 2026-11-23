"""Render the board and legal moves for match reviews."""
from .policy import clean, index_state


def name_of(entity, cards):
    return cards.get(entity.get('card'), {}).get('name') or 'Unknown card'


def body(entity, cards):
    hp = entity['health'] - entity['damage']
    keywords = ', '.join(k.replace('_', ' ').lower() for k in entity['keywords'])
    return f"{name_of(entity, cards)} {entity['atk']}/{hp}" + (f" ({keywords})" if keywords else '')


def hero_line(player):
    hero = player['hero']
    return f"{hero['health'] - hero['damage']} health, {hero['armor']} armor"


def render_state(row, cards):
    """Plain-language state. Costs and stats come from observed tags, not static card data."""
    state, you, opp = row['state'], row['state']['you'], row['state']['opponent']
    lines = [f"Turn {state['turn']}. You have {you['mana']} of {you['max_mana']} mana.",
             f"Your hero: {hero_line(you)}."]
    if you['weapon']:
        lines.append(f"Your weapon: {name_of(you['weapon'], cards)} with {you['weapon']['atk']} attack.")
    lines.append('Your minions: ' + ('; '.join(body(m, cards) for m in you['minions']) or 'none') + '.')
    hand = [f"{name_of(c, cards)} (cost {c['cost']}): {clean(cards.get(c['card'], {}).get('text'))[:90].rstrip('.')}"
            for c in you.get('hand', [])]
    lines.append('Your hand: ' + (' | '.join(hand) or 'empty') + '.')
    lines.append(f"Enemy hero: {hero_line(opp)}. Enemy hand: {opp['hand_count']} cards. Enemy secrets: {opp['secrets']}.")
    if opp['weapon']:
        lines.append(f"Enemy weapon: {name_of(opp['weapon'], cards)} with {opp['weapon']['atk']} attack.")
    lines.append('Enemy minions: ' + ('; '.join(body(m, cards) for m in opp['minions']) or 'none') + '.')
    return ' '.join(lines)


def describe_target(entity_id, found, cards):
    kind, target = found.get(entity_id, (None, None))
    if not target:
        return 'an unknown target'
    label = {'your_minion': 'your minion', 'enemy_minion': 'enemy minion',
             'your_hero': 'your hero', 'enemy_hero': 'the enemy hero'}.get(kind, 'target')
    if kind.endswith('hero'):
        return f"{label} ({target['health'] - target['damage']} health)"
    return f"{label} {body(target, cards)}"


def render_candidate(row, candidate, cards):
    if candidate['kind'] == 'end_turn':
        return 'End your turn.'
    found = index_state(row['state'])
    kind, source = found.get(candidate['source'], (None, None))
    target = candidate['target']
    if kind == 'hand':
        text = f"Play {name_of(source, cards)} (cost {source['cost']})"
        if candidate.get('sub_entity'):
            sub = row['cards'].get(str(candidate['sub_entity']))
            text += f", choosing {cards.get(sub, {}).get('name', 'an option')}"
        return text + (f", targeting {describe_target(target, found, cards)}." if target else '.')
    if kind == 'your_minion' and candidate.get('sub_card'):
        ability = cards.get(candidate['sub_card'], {})
        text = f"Use {name_of(source, cards)}'s ability {ability.get('name', 'unknown')}: {clean(ability.get('text'))[:90]}"
        return text + (f" Target {describe_target(target, found, cards)}." if target else '')
    if kind in ('your_minion', 'your_hero') and target:
        attacker = 'your hero' if kind == 'your_hero' else body(source, cards)
        return f"Attack {describe_target(target, found, cards)} with {attacker}."
    if kind == 'your_power':
        text = f"Use hero power {name_of(source, cards)}"
        return text + (f" on {describe_target(target, found, cards)}." if target else '.')
    name = name_of(source, cards) if source else 'a card'
    return f"Activate {name}" + (f" on {describe_target(target, found, cards)}." if target else '.')
