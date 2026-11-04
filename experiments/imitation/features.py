"""Shared rendering, the fixed game-level split, and a deterministic rules baseline."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Fixed before any model was run: two Rogue games plus one game per other class.
TEST_GROUPS = {
    'Hearthstone_2026_11_03_16_11_04/game-1',  # Rogue
    'Hearthstone_2026_11_03_16_20_27/game-2',  # Rogue
    'Hearthstone_2026_11_03_16_20_27/game-6',  # Priest
    'Hearthstone_2026_11_03_19_12_50/game-4',  # Hunter
    'Hearthstone_2026_11_03_19_12_50/game-8',  # Shaman
}
INSTRUCTIONS = ("You are playing Hearthstone as the current player. "
                "Choose the single best next action from the legal actions.")


def load_cards():
    return {c['id']: c for c in json.loads((ROOT / '.data/cards-enUS.json').read_text(encoding='utf-8'))}


def load_rows(path=None):
    path = path or ROOT / '.data/imitation/windows.jsonl'
    return [json.loads(line) for line in open(path, encoding='utf-8')]


def clean(text):
    text = re.sub(r'<[^>]+>|\[x\]|[$#]', '', text or '')
    return re.sub(r'\s+', ' ', text.replace('\xa0', ' ')).strip()


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


def index(row):
    you, opp = row['state']['you'], row['state']['opponent']
    found = {}
    for card in you.get('hand', []):
        found[card['id']] = ('hand', card)
    for side, player in (('your', you), ('enemy', opp)):
        for minion in player['minions']:
            found[minion['id']] = (f'{side}_minion', minion)
        if player['hero']:
            found[player['hero']['id']] = (f'{side}_hero', player['hero'])
        if player['hero_power']:
            found[player['hero_power']['id']] = (f'{side}_power', player['hero_power'])
        if player['weapon']:
            found[player['weapon']['id']] = (f'{side}_weapon', player['weapon'])
    return found


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
    found = index(row)
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


def render_id_only(row, candidate):
    """Same form as Action::description in src/protocol.rs: entity numbers and no meaning."""
    if candidate['kind'] == 'end_turn':
        return 'End the current turn'
    found = index(row)
    kind = found.get(candidate['source'], (None,))[0]
    target = candidate['target'] or None
    if kind in ('your_minion', 'your_hero') and target:
        return f"Attack with entity {candidate['source']} against entity {target}"
    if kind == 'your_power':
        return f"Use hero power; target {target}"
    return f"Play card {candidate['source']}; target {target}; board position None"


def id_only_state(row):
    """Raw card IDs and numbers, approximating the compact board that Rust sends."""
    return json.loads(json.dumps(row['state']))


def question(descriptions):
    return {'action': {'type': 'choice', 'instructions': INSTRUCTIONS,
                       'criteria': {f'c{i}': text for i, text in enumerate(descriptions)}}}


def rules_scores(row, cards):
    """A deliberately plain policy: lethal, then spend mana, then sensible trades, then end."""
    found = index(row)
    you, opp = row['state']['you'], row['state']['opponent']
    enemy_hp = opp['hero']['health'] - opp['hero']['damage'] + opp['hero']['armor']
    face = [c for c in row['candidates'] if c['target'] == opp['hero']['id']
            and found.get(c['source'], (None,))[0] in ('your_minion', 'your_hero')]
    # An attacker with a legal face option can reach it, so this sum respects Taunt.
    attackers = {c['source'] for c in face}
    lethal = sum(found[s][1]['atk'] for s in attackers) >= enemy_hp and bool(attackers)
    scores = []
    for candidate in row['candidates']:
        if candidate['kind'] == 'end_turn':
            scores.append(0.0)
            continue
        kind, source = found.get(candidate['source'], (None, None))
        target_kind, target = found.get(candidate['target'], (None, None))
        if kind == 'hand':
            score = 50.0 + 5 * source['cost']
            text = clean(cards.get(source['card'], {}).get('text')).lower()
            if target:
                hostile = any(w in text for w in ('damage', 'destroy', 'freeze', 'silence', 'transform'))
                wants_enemy = hostile and 'friendly' not in text
                is_enemy = target_kind in ('enemy_minion', 'enemy_hero')
                score += (target['atk'] if is_enemy == wants_enemy else -30)
        elif kind in ('your_minion', 'your_hero') and target:
            if target_kind == 'enemy_hero':
                score = 1000.0 if lethal else 35.0
            else:
                attack, hp = source['atk'], source['health'] - source['damage']
                kills = attack >= target['health'] - target['damage']
                dies = target['atk'] >= hp and kind == 'your_minion'
                if kills and not dies:
                    score = 40.0 + target['atk']
                elif kills:
                    score = 30.0 if target['atk'] + target['health'] >= source['atk'] + source['health'] else 10.0
                else:
                    score = 5.0
        elif kind == 'your_power':
            score = 20.0
        else:
            score = 15.0
        scores.append(score)
    return scores
