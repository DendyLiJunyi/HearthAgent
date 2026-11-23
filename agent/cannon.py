"""Standard Cannon Warrior rules. Re-evaluate after every client option packet."""
import re
from functools import lru_cache
from random import Random

from .tactics import _index, _hp, base_id, is_pirate, lethal_setup


CANNONEER = 'CAP_107t'
CROWLEY = 'CAP_106'
ENGINEER = 'CAP_104'
CANNON = 'CAP_103'
VOLCANO = 'CATA_584'
FISSURE = 'CATA_582'
TORCH = 'CATA_585'
TOIL = 'END_020'
DEPTHS = 'REV_990'
SUFFUSION = 'FIR_939'
WARPTOOTH = 'JAIL_421'
LIBRARIAN = 'SW_066'
ANNOUNCER = 'TIME_034'
HOGGER = 'JAIL_384'
DUCK = 'EDR_492'
DUCKLING = 'EDR_492t'
SOURCES = {'CAP_105': 2, 'CAP_102': 2, CROWLEY: 2, CANNONEER: 1}
HARD_TO_DAMAGE = {'DIVINE_SHIELD', 'IMMUNE'}
HIGH_SWEEP = {'MAGE', 'SHAMAN', 'PRIEST'}
SLOW = {'DEATHKNIGHT', 'MAGE', 'PRIEST'}
FAST = {'ROGUE', 'DEMONHUNTER', 'HUNTER', 'WARLOCK'}
REMOVAL = {TOIL, TORCH, SUFFUSION, DEPTHS}


def active_cannoneer(minion):
    return active(minion, CANNONEER)


def active(minion, card_id):
    return base_id(minion['card']) == card_id and 'SILENCED' not in minion['keywords']


def metadata(cards, card_id):
    return cards.get(card_id) or cards.get(base_id(card_id), {})


def life(hero):
    return _hp(hero) + hero.get('armor', 0)


def minions(player):
    return [m for m in player['minions'] if m['type'] == 'MINION' and _hp(m) > 0]


def opponent_class(state, cards):
    opponent = state.get('opponent') or {}
    hero = opponent.get('hero') or {}
    return opponent.get('class') or metadata(cards, hero.get('card')).get('cardClass')


def incoming_damage(state):
    enemy = state['opponent']
    return (sum(m['atk'] * (2 if 'WINDFURY' in m['keywords'] else 1) for m in minions(enemy))
            + max(enemy['hero']['atk'], (enemy.get('weapon') or {}).get('atk', 0)))


def has_safe_defense(state, candidates, found, cards):
    """Recognize deterministic plays that take visible enemy damage below lethal."""
    you, enemy = state['you'], state['opponent']
    excess = incoming_damage(state) - life(you['hero'])
    if excess < 0:
        return True
    for move in candidates:
        kind, source = found.get(move['source'], (None, {}))
        side, target = found.get(move['target'], (None, {}))
        card = base_id(source.get('card'))
        if move.get('sub', -1) >= 0 or (kind == 'hand' and source['cost'] > you['mana']):
            continue
        if card == FISSURE and kind == 'hand':
            removed = sum(m['atk'] for m in minions(enemy) if fissure_kills(m, cards)
                          and 'DEATHRATTLE' not in m['keywords'])
            if removed > excess:
                return True
        if side != 'enemy_minion' or HARD_TO_DAMAGE.intersection(target['keywords']) or 'DEATHRATTLE' in target['keywords']:
            continue
        if card in REMOVAL:
            damage, health_cost = spell_damage(source, cards), 0
        elif kind in ('your_hero', 'your_minion') and source['type'] != 'LOCATION':
            damage = source['atk']
            health_cost = target['atk'] if kind == 'your_hero' else 0
        else:
            continue
        removed = target['atk'] * (2 if 'WINDFURY' in target['keywords'] else 1)
        if damage >= _hp(target) and removed - health_cost > excess:
            return True
    return False


def control_mode(state, cards):
    you, enemy = state['you'], state['opponent']
    pressure = incoming_damage(state)
    if pressure >= life(you['hero']):
        return True
    if any({'LIFESTEAL', 'POISONOUS'}.intersection(m['keywords']) or (
            'SILENCED' not in m['keywords']
            and 'AURA' in metadata(cards, m['card']).get('mechanics', ())) for m in minions(enemy)):
        return True
    if len(minions(enemy)) >= 3 and sum(map(active_cannoneer, minions(you))) >= 2:
        return True
    archetype = opponent_class(state, cards)
    attack = sum(m['atk'] for m in minions(you)) + you['hero']['atk']
    if archetype in SLOW or attack * life(you['hero']) >= pressure * life(enemy['hero']):
        return False
    return archetype in FAST or pressure >= 0.4 * life(you['hero'])


def enabled(policy):
    return getattr(policy, 'deck_profile', {}).get('tactics') == 'standard-cannon'


def mulligan(entities, by_entity, cards, state=None):
    rows = [(e['id'], by_entity.get(str(e['id'])) or e.get('card', '')) for e in entities]
    held = {base_id(card) for _, card in rows}
    archetype = opponent_class(state or {}, cards)
    slow, fast = archetype in SLOW, archetype in FAST
    first = ((state or {}).get('you') or {}).get('going_first')
    second = not first if first is not None else 'GAME_005' in held or len(rows) == 4
    opener = bool(held & {'CAP_107', 'DRG_024', 'CAP_105'})
    limits = {'CAP_107': 2, 'DRG_024': 1, 'CAP_105': 2, 'FIR_929': 1 if slow else 2,
              TOIL: 2 if fast else 1, 'GAME_005': 1}
    if not fast and (slow or opener):
        limits.update({CANNON: 1, ENGINEER: 2})
    if not slow:
        limits[SUFFUSION] = 2 if fast else 1
        if second:
            limits[DUCK] = 1
    if fast:
        limits[FISSURE] = 2
        if held & {TOIL, FISSURE, SUFFUSION, DEPTHS}:
            limits[TORCH] = 1
    if slow and held & {'CAP_107', 'DRG_024'}:
        limits[DEPTHS] = 1
    if slow and second:
        limits[CROWLEY] = 1
    replace = []
    for entity, card_id in rows:
        card_id = base_id(card_id)
        if limits.get(card_id, 0):
            limits[card_id] -= 1
        else:
            replace.append(entity)
    return replace


def damage_value(cards, card_id, pattern, fallback):
    result = re.search(pattern, metadata(cards, card_id).get('text', ''), re.IGNORECASE)
    return int(result[1]) if result else fallback


def fire_spell(cards, card_id):
    return metadata(cards, card_id).get('spellSchool') == 'FIRE'


def fire_played(you, cards):
    return any(fire_spell(cards, c) for c in you.get('played_this_turn', ()))


def firing(board, cards):
    token = metadata(cards, CANNONEER)
    per_shot = damage_value(cards, CANNONEER, r'deal \$?(\d+) damage', 1)
    if is_pirate(token):
        per_shot += sum(active(m, ENGINEER) for m in board)
    count = sum(map(active_cannoneer, board)) * (1 + sum(active(m, CROWLEY) for m in board))
    return (per_shot,) * count


def volcano_damage(you, cards):
    return volcano_shots(fire_played(you, cards), cards)


def volcano_shots(charged, cards):
    base = damage_value(cards, VOLCANO, r'deal \$?(\d+) damage', 3)
    bonus = damage_value(cards, VOLCANO, r'deal \$?(\d+) more', base)
    return (1,) * (base + bonus * charged)


def spell_damage(source, cards):
    card_id = base_id(source['card'])
    if card_id == TORCH and source.get('script_value', 0) > 0:
        return source['script_value']
    return damage_value(cards, card_id, r'deal \$?(\d+) damage', {SUFFUSION: 2, TORCH: 0}.get(card_id, 1))


def develop(board, room, source):
    card_id = base_id(source['card'])
    if source['type'] == 'MINION':
        if room < 1:
            return None
        board = board + [source]
        room -= 1
    if card_id == CANNONEER:
        return board
    return board + [{'card': CANNONEER, 'keywords': []}] * min(room, SOURCES.get(card_id, 0))


def damaged_board(board, target, amount):
    if 'IMMUNE' in target['keywords']:
        return board
    if 'DIVINE_SHIELD' in target['keywords']:
        updated = dict(target, keywords=[k for k in target['keywords'] if k != 'DIVINE_SHIELD'])
    elif amount >= _hp(target):
        return [m for m in board if m is not target]
    else:
        updated = dict(target, damage=target['damage'] + amount)
    return [updated if m is target else m for m in board]


@lru_cache(maxsize=2048)
def random_damage(hero_hp, targets, shots, samples=500):
    """Return lethal probability, expected face damage and expected minion kills.

    Target tuples contain health, shield and immunity. Random shots can hit Stealth;
    Divine Shield absorbs a shot and dead minions are removed from the pool.
    """
    if hero_hp <= 0:
        return 1.0, 0.0, 0.0
    if not targets:
        total = sum(shots)
        return float(total >= hero_hp), min(total, hero_hp), 0.0
    if not shots:
        return 0.0, 0.0, 0.0
    rng = Random(0)
    wins = face = kills = 0
    for _ in range(samples):
        remaining = list(targets)
        hp = hero_hp
        for amount in shots:
            index = rng.randrange(len(remaining) + 1)
            if index == len(remaining):
                hp -= amount
                if hp <= 0:
                    break
                continue
            health, shield, immune = remaining[index]
            if immune:
                continue
            if shield:
                remaining[index] = health, False, immune
            elif health <= amount:
                remaining.pop(index)
            else:
                remaining[index] = health - amount, False, immune
        wins += hp <= 0
        face += hero_hp - max(0, hp)
        kills += len(targets) - len(remaining)
    return wins / samples, face / samples, kills / samples


def targets(board):
    return tuple(sorted((_hp(m), 'DIVINE_SHIELD' in m['keywords'], 'IMMUNE' in m['keywords']) for m in board))


def lethal_move(state, candidates, cards):
    """Look for burst lines after direct attacks and up to two known setup plays."""
    you, enemy = state['you'], state['opponent']
    if enemy.get('secrets') or 'IMMUNE' in enemy['hero']['keywords']:
        return None
    found = _index(state)
    friendly, opposing = minions(you), minions(enemy)
    if any(active(m, 'YOD_022') for m in friendly):
        return None
    hero, opponent = you['hero'], enemy['hero']
    weapon = you.get('weapon') or {}
    hand_cannon = base_id(weapon.get('card')) == CANNON
    remaining = life(opponent)
    attackers = {m['source'] for m in candidates if m.get('sub', -1) < 0 and m['target']
                 and found.get(m['source'], (None, {}))[1].get('type') in ('HERO', 'MINION')
                 and found[m['source']][0] != 'hand'}
    face = {m['source']: i for i, m in enumerate(candidates)
            if m['target'] == opponent['id'] and m.get('sub', -1) < 0
            and found.get(m['source'], (None,))[0] in ('your_minion', 'your_hero')}
    volcanoes = [i for i, m in enumerate(candidates)
                 if m['source'] in found and found[m['source']][0] == 'your_minion'
                 and base_id(found[m['source']][1]['card']) == VOLCANO and not m['target']]
    development = {m['source']: found[m['source']][1] for m in candidates
                   if not m['target'] and m.get('sub', -1) < 0 and found.get(m['source'], (None,))[0] == 'hand'
                   and base_id(found[m['source']][1]['card']) in SOURCES.keys() | {ENGINEER, VOLCANO, CANNON}}
    threshold = 0.9 if has_safe_defense(state, candidates, found, cards) else 0.5
    best = None

    def consider(index, damage, board, shots=(), steps=1):
        nonlocal best
        if index is None or (damage < remaining and sum(shots) < remaining - damage):
            return
        if damage < remaining and any('DEATHRATTLE' in m['keywords'] for m in board):
            return
        probability = random_damage(remaining - damage, targets(board), shots)[0]
        if probability < threshold:
            return
        # A sampled 100% with live targets is still a random line.
        certain = damage >= remaining or not board
        key = certain, probability, -steps, -index
        if best is None or key > best[0]:
            best = key, (index, 'cannon:lethal' if certain else 'cannon:probable_lethal')

    end = next((i for i, m in enumerate(candidates) if m['kind'] == 'end_turn'), None)
    shots = firing(friendly, cards)
    attacks = {source: found[source][1]['atk'] for source in face}
    face_total = sum(attacks.values())
    safe_face = next((i for source, i in face.items() if source != hero['id'] or not hand_cannon), None)
    # Prefer ending immediately when the automatic shots already suffice.
    consider(end, 0, opposing, shots)
    if best and best[0][0]:
        return best[1]
    for source, i in face.items():
        if attacks[source] >= remaining:
            return i, 'cannon:lethal'
    swing = face.get(hero['id']) if hand_cannon else None
    consider(safe_face, face_total, opposing, shots, len(face) + 1)
    consider(safe_face if safe_face is not None else swing, face_total, opposing,
             shots * (2 if swing is not None else 1), len(face) + 1)
    volcano_volley = volcano_damage(you, cards) * len(volcanoes)
    if volcanoes:
        consider(safe_face if safe_face is not None else volcanoes[0], face_total, opposing,
                 volcano_volley + shots * (2 if swing is not None else 1), len(face) + len(volcanoes) + 1)

    for i, move in enumerate(candidates):
        if move.get('sub', -1) >= 0 or move['source'] not in found:
            continue
        kind, source = found[move['source']]
        card_id = base_id(source['card'])
        target_kind, target = found.get(move['target'], (None, None))
        if kind == 'hand' and source['cost'] > you['mana']:
            continue
        board, ours = opposing, friendly
        direct = 0
        buff = 0
        hurt = set()
        occupied_slots = 0
        used_hero = kind == 'your_hero'
        used_attack = kind in ('your_hero', 'your_minion') and source['type'] != 'LOCATION'
        equipped = hand_cannon
        charged = fire_played(you, cards) or (kind == 'hand' and fire_spell(cards, source['card']))
        volcano = len(volcanoes)
        if kind == 'hand' and card_id == FISSURE:
            for m in opposing:
                board = damaged_board(board, m, spell_damage(source, cards))
            ours = [m for m in friendly if not fissure_kills(m, cards)]
            buff = damage_value(cards, FISSURE, r'\+(\d+) Attack', 3)
            hurt.update(m['id'] for m in friendly if not HARD_TO_DAMAGE.intersection(m['keywords']))
        elif card_id in REMOVAL | {LIBRARIAN} and target_kind == 'enemy_minion':
            if card_id == LIBRARIAN and kind == 'hand' and 'TAUNT' in target['keywords']:
                if len(you['minions']) >= 7:
                    continue
                board = [dict(m, keywords=[]) if m is target else m for m in opposing]
                occupied_slots = 1
            elif card_id != LIBRARIAN and spell_damage(source, cards):
                board = damaged_board(opposing, target, spell_damage(source, cards))
                if card_id == TOIL and len(board) < len(opposing) and len(you['minions']) < 7:
                    occupied_slots = 1  # Reserve the slot for its random one-drop.
            else:
                continue
        elif used_attack and target_kind == 'enemy_minion':
            if HARD_TO_DAMAGE.intersection(target['keywords']) or source['atk'] < _hp(target):
                continue
            if used_hero and target['atk'] >= life(hero):
                continue
            board = [m for m in opposing if m is not target]
            if target['atk'] > 0 and not HARD_TO_DAMAGE.intersection(source['keywords']):
                hurt.add(source['id'])
            if not used_hero and (target['atk'] >= _hp(source) or 'POISONOUS' in target['keywords']):
                if not HARD_TO_DAMAGE.intersection(source['keywords']):
                    ours = [m for m in friendly if m is not source]
        elif kind == 'hand' and card_id == SUFFUSION and target_kind == 'enemy_hero':
            direct = spell_damage(source, cards)
        elif kind == 'hand' and card_id == WARPTOOTH:
            if len(you['minions']) >= 7 or any('TAUNT' in m['keywords'] for m in opposing):
                continue
            direct = metadata(cards, card_id).get('attack', source['atk'])
            occupied_slots = 1
        elif kind == 'hand' and card_id == CANNON:
            if hand_cannon and hero['id'] in face:
                continue  # The equipped Cannon can fire before replacement.
            equipped = True
        elif kind == 'hand' and card_id == VOLCANO and len(you['minions']) < 7:
            volcano += 1
        elif kind == 'hand' and card_id in SOURCES.keys() | {ENGINEER}:
            ours = develop(friendly, 7 - len(you['minions']), source)
            if ours is None:
                continue
        else:
            continue
        survivors = {m['id'] for m in board}
        if any(m['id'] not in survivors and 'DEATHRATTLE' in m['keywords'] for m in opposing):
            continue
        can_face = not any('TAUNT' in m['keywords'] and 'STEALTH' not in m['keywords'] for m in board)
        already_hurt = set(you.get('damaged_this_turn', ()))
        summons_warptooth = (bool(hurt - already_hurt) and len(already_hurt | hurt) >= 4
                             and len(ours) + len(you['minions']) - len(friendly) < 7
                             and warptooth_count(you) > 0)
        if can_face and summons_warptooth:
            # Count a single known copy. Simultaneous copies and summon ordering are client effects.
            direct += metadata(cards, WARPTOOTH).get('attack', 0)
        new_hero_swing = (not used_hero and can_face
                          and (hero['id'] in face or not hero.get('attacks')
                               and not {'FROZEN', 'CANT_ATTACK'}.intersection(hero['keywords'])
                               and (hero['id'] in attackers or hero['atk'] == 0 and buff
                                    or kind == 'hand' and card_id == CANNON)))
        board_attacks = sum(m['atk'] for m in ours if m.get('id') in attackers
                            and m.get('id') != source['id'] and can_face
                            and (m['id'] in face or not m.get('exhausted') and 'FROZEN' not in m['keywords'])
                            and not ('RUSH' in m['keywords'] and m['id'] not in face
                                     and m.get('turns_in_play', 0) == 0))
        hero_attack = 0
        if new_hero_swing:
            hero_attack = hero['atk'] + buff
            if kind == 'hand' and card_id == CANNON:
                hero_attack = max(0, hero_attack - weapon.get('atk', 0)) + metadata(cards, CANNON).get('attack', 0)
        current_shots = firing(ours, cards)
        volleys = 1 + int(equipped and (hero_attack > 0 or used_hero))
        consider(i, direct + board_attacks + hero_attack, board,
                 volcano_shots(charged, cards) * volcano + current_shots * volleys, 2)
        if kind != 'hand' and source['type'] != 'LOCATION':
            continue
        spent = source['cost'] if kind == 'hand' else 0
        room = 7 - (len(you['minions']) - len(friendly) + len(ours)) - (volcano - len(volcanoes))
        room -= occupied_slots + int(summons_warptooth)
        for other in development.values():
            if other['id'] == source['id'] or spent + other['cost'] > you['mana']:
                continue
            other_card = base_id(other['card'])
            next_attack, next_volcano, next_board, next_equipped = hero_attack, volcano, ours, equipped
            if other_card == VOLCANO:
                if room < 1:
                    continue
                next_volcano += 1
            elif other_card == CANNON:
                if equipped:
                    continue
                next_equipped = True
                if can_face and not hero.get('attacks') and not {'FROZEN', 'CANT_ATTACK'}.intersection(hero['keywords']):
                    next_attack = max(0, hero['atk'] + buff - weapon.get('atk', 0)) + metadata(cards, CANNON).get('attack', 0)
            else:
                next_board = develop(ours, room, other)
                if next_board is None:
                    continue
            next_shots = firing(next_board, cards) * (1 + int(next_equipped and next_attack > 0))
            consider(i, direct + board_attacks + next_attack, board,
                     volcano_shots(charged, cards) * next_volcano + next_shots, 3)
    return best[1] if best else None


def forced_move(state, candidates, cards):
    found = _index(state)
    you = state['you']
    lethal = lethal_setup(state, candidates, cards)
    if lethal is not None and not state['opponent'].get('secrets'):
        return lethal, 'tactics:lethal_setup'
    if incoming_damage(state) >= life(you['hero']):
        return None  # Let removal and taunts compete when the opponent can kill us.
    plays = [(i, found[move['source']][1]) for i, move in enumerate(candidates)
             if found.get(move['source'], (None,))[0] == 'hand' and not move['target']
             and move.get('sub', -1) < 0 and found[move['source']][1]['cost'] <= you['mana']]
    fissure = next((i for i, card in plays if base_id(card['card']) == FISSURE), None)
    if fissure is not None and any(0 < _hp(m) <= spell_damage({'card': FISSURE}, cards)
                                    for m in minions(state['opponent'])):
        context = turn_context(state, candidates, cards)
        if rule_score(state, candidates[fissure], found, cards, context) >= 65:
            return fissure, 'cannon:fissure_before_development'
    crowley = crowley_setup(state, candidates, cards)
    if crowley is not None:
        return crowley, 'cannon:crowley_setup'
    face = next((i for i, move in enumerate(candidates)
                 if move['source'] == you['hero']['id'] and move['target'] == state['opponent']['hero']['id']
                 and move.get('sub', -1) < 0), None)
    weapon = you.get('weapon')
    if not weapon:
        return None
    cannons = [minion for minion in you['minions'] if active_cannoneer(minion)]
    if base_id(weapon['card']) == 'CAP_103' and cannons:
        fire = face if face is not None else safe_cannon_attack(state, candidates, found, weapon)
        engineer = next((i for i, card in plays if base_id(card['card']) == 'CAP_104'), None)
        if fire is not None and engineer is not None and len(you['minions']) < 7:
            return engineer, 'cannon:engineer_before_firing'
        if fire is not None and minions(state['opponent']):
            context = turn_context(state, candidates, cards)
            clears = [(rule_score(state, m, found, cards, context), i) for i, m in enumerate(candidates)
                      if found.get(m['target'], (None,))[0] == 'enemy_minion'
                      and base_id(found.get(m['source'], (None, {}))[1].get('card')) in REMOVAL]
            clears = [(score, i) for score, i in clears if score is not None and score >= 64]
            if clears:
                return max(clears, key=lambda row: (row[0], -row[1]))[1], 'cannon:clear_before_firing'
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


def fissure_kills(minion, cards=None):
    damage = spell_damage({'card': FISSURE}, cards or {})
    return minion['type'] == 'MINION' and 0 < _hp(minion) <= damage and not HARD_TO_DAMAGE.intersection(minion['keywords'])


def warptooth_count(you):
    return (sum(base_id(c['card']) == WARPTOOTH for c in you.get('hand', ()))
            + you.get('known_deck', {}).get(WARPTOOTH, 0))


def turn_context(state, candidates, cards, profile=None):
    you, enemy = state['you'], state['opponent']
    found = _index(state)
    own, opposing = minions(you), minions(enemy)
    hurt = set(you.get('damaged_this_turn', ()))
    warptooth = bool(warptooth_count(you))
    if not warptooth and you.get('deck_count', 0) > sum(you.get('known_deck', {}).values()):
        rows = (profile or {}).get('cards', ())
        copies = sum(row['count'] for row in rows if base_id(row['id']) == WARPTOOTH)
        copies *= 1 + any(base_id(row['id']) == HOGGER for row in rows)
        warptooth = copies > you.get('warptooth_seen_outside_deck', 0)
    prospective = set(hurt)
    fissure = next((m for m in candidates if found.get(m['source'], (None,))[0] == 'hand'
                    and base_id(found[m['source']][1]['card']) == FISSURE), None)
    if fissure:
        prospective.update(m['id'] for m in own if not HARD_TO_DAMAGE.intersection(m['keywords']))
        hero = you['hero']
        if (not hero.get('attacks') and 'FROZEN' not in hero['keywords']
                and any(m['atk'] > 0 and _hp(m) > spell_damage({'card': FISSURE}, cards)
                        and 'STEALTH' not in m['keywords'] for m in opposing)):
            prospective.add(hero['id'])
    fire_ready = False
    volcano_ready = False
    duck_damage = 0
    for move in candidates:
        kind, source = found.get(move['source'], (None, {}))
        side, target = found.get(move['target'], (None, {}))
        card = base_id(source.get('card'))
        if kind == 'hand' and fire_spell(cards, source['card']) and side not in ('your_minion', 'your_hero'):
            fire_ready = True
        if card == VOLCANO and kind in ('hand', 'your_minion'):
            volcano_ready = True
        if kind == 'hand' and card == DUCK and source['cost'] <= you['mana']:
            live_targets = [m for m in opposing if 'STEALTH' not in m['keywords']]
            taunts = [m for m in live_targets if 'TAUNT' in m['keywords']]
            duck_attack = metadata(cards, DUCKLING).get('attack', 1)
            if duck_attack > 0:
                hits = sum((_hp(m) + duck_attack - 1) // duck_attack for m in (taunts or live_targets)
                           if m['atk'] > 0 and 'IMMUNE' not in m['keywords'])
                duck_damage = max(0, min(3, 6 - len(you['minions']), hits))
        if (side == 'enemy_minion' and kind in ('your_minion', 'your_hero')
                and source['type'] in ('HERO', 'MINION') and target['atk'] > 0
                and not HARD_TO_DAMAGE.intersection(source['keywords'])
                and (kind != 'your_hero' or target['atk'] < life(source))):
            prospective.add(source['id'])
        if side == 'your_minion' and card in (TOIL, DEPTHS) and not HARD_TO_DAMAGE.intersection(target['keywords']):
            prospective.add(target['id'])
    return {'control': control_mode(state, cards), 'own': own, 'enemy': opposing,
            'shots': firing(own, cards), 'hurt': hurt, 'warptooth': warptooth,
            'trigger': warptooth and len(hurt) < 4 <= len(prospective),
            'duck_trigger': warptooth and len(prospective) < 4 <= len(prospective) + duck_damage,
            'fire_ready': fire_ready, 'volcano_ready': volcano_ready,
            'sweep': opponent_class(state, cards) in HIGH_SWEEP,
            'danger': incoming_damage(state) >= life(you['hero']),
            'ready': {m['source'] for m in candidates if m.get('sub', -1) < 0
                      and found.get(m['target'], (None,))[0] in ('enemy_minion', 'enemy_hero')}}


def rule_score(state, candidate, found, cards=None, context=None):
    """Rank legal plays by role, immediate tempo and their setup for later actions."""
    cards = cards or {}
    context = context or turn_context(state, [candidate], cards)
    kind, source = found.get(candidate['source'], (None, None))
    if not source or candidate.get('sub', -1) >= 0:
        return None
    card = base_id(source['card'])
    side, target = found.get(candidate['target'], (None, None))
    you, enemy = state['you'], state['opponent']
    own, opposing = context['own'], context['enemy']
    cannon = base_id((you.get('weapon') or {}).get('card')) == CANNON
    control, danger = context['control'], context['danger']
    hurt = context['hurt']
    trigger = context['trigger']
    fire_bonus = 14 if context['volcano_ready'] and not fire_played(you, cards) and fire_spell(cards, source['card']) else 0
    room = 7 - len(you['minions'])
    hand_size = len(you.get('hand', ()))
    torch_in_hand = any(base_id(c['card']) == TORCH for c in you.get('hand', ()))
    if card in REMOVAL and side in ('your_minion', 'enemy_minion', 'enemy_hero') and target['type'] != 'LOCATION':
        damage = spell_damage(source, cards)
        if 'IMMUNE' in target['keywords'] or not damage:
            return -5
        if side == 'enemy_hero':
            return (52 if not control else 35) + fire_bonus if card == SUFFUSION else -5
        if 'DIVINE_SHIELD' in target['keywords']:
            return 25 + 12 * control + fire_bonus if side == 'enemy_minion' else -5
        if side == 'enemy_minion':
            if damage >= _hp(target):
                return (65 + min(target['atk'], 8) * 3 + 14 * ('TAUNT' in target['keywords'])
                        + 20 * danger + fire_bonus)
            follow_up = torch_in_hand and you['mana'] >= (source['cost'] if kind == 'hand' else 0) + 1
            return (25 + 20 * follow_up + 6 * (card in (SUFFUSION, TOIL) and hand_size <= 4)
                    - 20 * (card == DEPTHS) + fire_bonus - 8 * (card == TORCH))
        if card == TOIL and damage >= _hp(target) and active(target, 'FIR_929'):
            return 64
        if damage >= _hp(target) or card not in (TOIL, DEPTHS):
            return -5
        setup = (45 if len(hurt) == 3 else 16) * (trigger and target['id'] not in hurt)
        if card == DEPTHS:
            return (65 if target['id'] in context['ready'] else 19) + setup
        return 50 - min(target['atk'], 8) + 8 * (hand_size <= 3) + setup
    if card == LIBRARIAN and kind == 'hand' and target:
        if side != 'enemy_minion' or 'SILENCED' in target['keywords']:
            return -5
        if {'TAUNT', 'DEATHRATTLE', 'LIFESTEAL'}.intersection(target['keywords']):
            return 74
        return 46 if control else 14
    if card == FISSURE:
        losses = [m for m in own if fissure_kills(m, cards)]
        kills = [m for m in opposing if fissure_kills(m, cards)]
        loss = sum(14 + m['atk'] * 2 + 12 * active_cannoneer(m) for m in losses)
        benefit = sum(12 + m['atk'] * 3 for m in kills)
        new_hurt = sum(m['id'] not in hurt and not HARD_TO_DAMAGE.intersection(m['keywords']) for m in own)
        if trigger and new_hurt:
            benefit += 14 + 5 * min(new_hurt, 4 - len(hurt))
        if danger:
            benefit += sum(m['atk'] * 4 for m in kills)
        if losses and benefit < loss:
            return -5
        hero = state['you']['hero']
        can_use_attack = (not hero.get('attacks', 0)
                          and not {'FROZEN', 'CANT_ATTACK'}.intersection(hero['keywords']))
        return 27 + 21 * can_use_attack + benefit - loss + fire_bonus if kills or can_use_attack or fire_bonus else -5
    if card == VOLCANO and kind == 'your_minion':
        charged = fire_played(you, cards)
        if not charged and context['fire_ready']:
            return -1
        _, face, kills = random_damage(life(enemy['hero']), targets(opposing), volcano_damage(you, cards))
        if not charged and kills < 0.7 and not danger:
            return -1
        return 22 + face * (3 if control else 6) + kills * (16 if control else 9)
    if kind in ('your_minion', 'your_hero') and side in ('enemy_minion', 'enemy_hero'):
        if 'IMMUNE' in target['keywords']:
            return -100
        if kind == 'your_hero':
            if side == 'enemy_hero':
                return 41 + min(sum(context['shots']), 20) if cannon else 38
            if target['atk'] >= life(source):
                return -100
        elif side == 'enemy_hero':
            return 40
        health = life(source) if kind == 'your_hero' else _hp(source)
        has_engineer = sum(active(m, ENGINEER) for m in own)
        pirate_bonus = has_engineer if is_pirate(metadata(cards, source['card'])) else 0
        kills = (source['atk'] + pirate_bonus >= _hp(target) or 'POISONOUS' in source['keywords'])
        kills &= 'DIVINE_SHIELD' not in target['keywords']
        survives = target['atk'] < health or bool(HARD_TO_DAMAGE.intersection(source['keywords']))
        taunt = 'TAUNT' in target['keywords']
        score = 5 + 12 * control + 14 * taunt + target['atk']
        score += (22 + 12 * survives + 20 * danger) * kills
        score += (50 if len(hurt) == 3 else 15) * (
            trigger and source['id'] not in hurt and target['atk'] > 0
            and not HARD_TO_DAMAGE.intersection(source['keywords']))
        score -= 20 * active_cannoneer(source)
        score -= target['atk'] * 2 if kind == 'your_hero' else 0
        if kind == 'your_hero' and cannon and kills:
            score += min(sum(context['shots']), 18)
        if base_id(source['card']) == DUCKLING:
            score += 21 if kills else 8
            score += 10 if context['sweep'] and len(own) > 3 else 0
        if active(source, 'FIR_929') and kills and not survives:
            score += 10
        return score
    if kind == 'hand':
        if card == 'CAP_107':
            return 72
        if card in SOURCES or card in {ENGINEER, DUCK, 'FIR_929', VOLCANO}:
            development = SOURCES.get(card, 3 if card == DUCK else 0)
            if source['type'] == 'MINION':
                development += 1 - int(card == CANNONEER)
            over = max(0, len(own) + min(room, development) - (3 if context['sweep'] else 5 if control else 4))
            sweep_penalty = max(0, over - max(0, len(own) - 3)) * (13 if context['sweep'] else 4)
            if card == DUCK and opposing:
                sweep_penalty = 0
            value = {'CAP_105': 65, 'CAP_102': 63 + max(0, 6 - hand_size) * 2,
                     CANNONEER: 55, ENGINEER: 51 + 5 * sum(map(active_cannoneer, own)),
                     CROWLEY: 72, DUCK: 51 + min(len(opposing), 3) * 7 + 17 * context['duck_trigger'],
                     'FIR_929': 58, VOLCANO: 50}[card]
            if card in SOURCES and room == 0:
                value -= 36
            return value - sweep_penalty
        if card == WARPTOOTH:
            return -4 if trigger else 46
        if card == CANNON:
            return 41 + min(sum(context['shots']), 20) - 12 * cannon
        if card == HOGGER:
            return 100 if danger else 12
        if card == ANNOUNCER:
            return 38 - 18 * bool(you.get('weapon')) - 23 * control
        if card == DEPTHS:
            return 48 if own or opposing else 25
    return None


def discover(choice, cards_by_entity, cards):
    source = choice.get('source') or {}
    card = base_id(cards_by_entity.get(str(source.get('id'))) or source.get('card'))
    state = choice.get('state')
    if card not in {'CAP_105', SUFFUSION} or not state or not state.get('you') or not state.get('opponent'):
        return None
    mana = state['you']['mana']
    control = control_mode(state, cards)

    def value(entity):
        data = metadata(cards, cards_by_entity.get(str(entity['id'])) or entity.get('card'))
        cost = data.get('cost', 12)
        mechanics = set(data.get('mechanics', ())) | set(data.get('referencedTags', ()))
        text = data.get('text', '').lower()
        impact = bool(re.search(r'deal.*damage|destroy|silence', text.replace('\n', ' ')))
        combat = 5 * ('RUSH' in mechanics) + 7 * impact + 7 * ('TAUNT' in mechanics) if control else (
            9 * ('CHARGE' in mechanics) + 5 * impact + 3 * ('RUSH' in mechanics))
        return (combat + 5 * (cost <= mana) + 2 * (cost <= min(10, state['you'].get('max_mana', mana) + 1))
                + (data.get('attack', 0) + data.get('health', 0)) * 0.6 - cost)

    return max(range(len(choice['entities'])), key=lambda i: (value(choice['entities'][i]), -i))


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
            if source['type'] in ('MINION', 'LOCATION') and len(state['you']['minions']) >= 7:
                bad = True
            if card == 'CAP_102' and len(state['you'].get('hand', [])) >= 10:
                bad = True  # Playing one card leaves only one draw slot.
            if card in {'CATA_585', 'FIR_939'} and target_kind in ('your_minion', 'your_hero'):
                bad = True
            weapon = state['you'].get('weapon') or {}
            if card == ANNOUNCER and base_id(weapon.get('card')) == CANNON:
                remaining = (weapon.get('durability') or weapon.get('health') or metadata(cards, CANNON).get('health', 2))
                remaining -= weapon.get('damage', 0)
                bad = remaining > 1 or not state['you']['hero'].get('attacks')
        if source and base_id(source['card']) == DEPTHS and kind == 'your_minion':
            bad = (target_kind not in ('your_minion', 'enemy_minion') or target['type'] != 'MINION'
                   or 'IMMUNE' in target['keywords'] or target_kind == 'your_minion' and _hp(target) <= 1)
        if not bad:
            keep.append(i)
    return keep or list(range(len(candidates)))
