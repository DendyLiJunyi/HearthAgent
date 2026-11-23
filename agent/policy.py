"""Decision makers. All of them only ever pick from what the game itself offered."""
import json
import re
import time
from collections import Counter
from pathlib import Path

from . import tactics as deck_tactics
from . import cannon
from . import rewind

ROOT = Path(__file__).resolve().parents[1]
HOSTILE = ('damage', 'destroy', 'freeze', 'silence', 'transform')


def load_cards():
    return {c['id']: c for c in json.loads((ROOT / '.data/cards-enUS.json').read_text(encoding='utf-8'))}


def clean(text):
    text = re.sub(r'<[^>]+>|\[x\]|[$#]', '', text or '')
    return re.sub(r'\s+', ' ', text.replace('\xa0', ' ')).strip()


def index_state(state):
    you, opponent = state['you'], state['opponent']
    found = {}
    for card in you.get('hand', []):
        found[card['id']] = ('hand', card)
    for side, player in (('your', you), ('enemy', opponent)):
        for minion in player['minions']:
            found[minion['id']] = (f'{side}_minion', minion)
        for slot, suffix in (('hero', 'hero'), ('hero_power', 'power'), ('weapon', 'weapon')):
            if player[slot]:
                found[player[slot]['id']] = (f'{side}_{suffix}', player[slot])
    return found


def hp(entity):
    return entity['health'] - entity['damage']


MULLIGAN_KEEP_COST = 2
MULLIGAN_RETURN_TO_DECK = {'CFM_637'}  # Patches is summoned from the deck by another Pirate.


def _best_spend(costs, mana):
    """The most mana any set of these cards can spend."""
    reachable = {0}
    for cost in costs:
        reachable |= {total + cost for total in reachable if total + cost <= mana}
    return max(reachable)


class RulesPolicy:
    """Lethal first, with deck-specific sequencing when tactics are enabled."""
    name = 'rules'

    def __init__(self, cards, aggressive=False, tactics=False):
        self.cards, self.aggressive = cards, aggressive
        self.tactics = tactics
        self.decision_counts = Counter()
        self.last_decision = None

    def face_first(self, state, candidates, pool):
        """Aggressive play: an attacker that can reach the enemy hero may not attack a minion.

        Taunt removes the hero from an attacker's options, so forced trades stay available.
        """
        found = index_state(state)
        enemy_hero = state['opponent']['hero']['id']
        can_hit_face = {c['source'] for c in candidates if c['target'] == enemy_hero}

        def trades_instead(index):
            move = candidates[index]
            return (found.get(move['source'], (None,))[0] in ('your_minion', 'your_hero')
                    and found.get(move['target'], (None,))[0] == 'enemy_minion'
                    and move['source'] in can_hit_face and move.get('sub', -1) < 0)
        return [i for i in pool if not trades_instead(i)] or list(pool)

    def text(self, card_id):
        return clean(self.cards.get(card_id, {}).get('text')).lower()

    def scores(self, state, candidates):
        found = index_state(state)
        opponent = state['opponent']
        enemy_hp = hp(opponent['hero']) + opponent['hero']['armor']
        face = [c for c in candidates if c['target'] == opponent['hero']['id']
                and found.get(c['source'], (None,))[0] in ('your_minion', 'your_hero')]
        # An attacker offered the enemy hero as a target can reach it, so Taunt is already respected.
        attackers = {c['source'] for c in face}
        cannon_rules = self.tactics and cannon.enabled(self)
        lethal = not cannon_rules and bool(attackers) and sum(found[s][1]['atk'] for s in attackers) >= enemy_hp
        scores = [self._score(c, found, lethal) for c in candidates]
        if cannon_rules:
            context = cannon.turn_context(state, candidates, self.cards, self.deck_profile)
            for index, candidate in enumerate(candidates):
                score = cannon.rule_score(state, candidate, found, self.cards, context)
                if score is not None:
                    scores[index] = score
        return scores

    def _score(self, candidate, found, lethal):
        if candidate['kind'] == 'end_turn':
            return 0.0
        kind, source = found.get(candidate['source'], (None, None))
        target_kind, target = found.get(candidate['target'], (None, None))
        if kind == 'your_minion' and candidate.get('sub', -1) >= 0:
            # A Titan or Old God ability is free and limited, so use it before anything else.
            if not target:
                return 910.0  # An untargeted ability cannot be aimed badly.
            text = self.text(candidate.get('sub_card'))
            wants_enemy = any(w in text for w in HOSTILE) and 'friendly' not in text
            is_enemy = target_kind in ('enemy_minion', 'enemy_hero')
            return 900.0 + min(target['atk'], 9) if is_enemy == wants_enemy else 870.0
        if kind == 'hand':
            score = 50.0 + 5 * source['cost']
            if target:
                text = self.text(source['card'])
                wants_enemy = any(w in text for w in HOSTILE) and 'friendly' not in text
                is_enemy = target_kind in ('enemy_minion', 'enemy_hero')
                score += target['atk'] if is_enemy == wants_enemy else -30
            return score
        if kind in ('your_minion', 'your_hero') and target:
            if target_kind == 'enemy_hero':
                return 1000.0 if lethal else 35.0
            kills = source['atk'] >= hp(target)
            dies = target['atk'] >= hp(source) and kind == 'your_minion'
            if kills and not dies:
                return 40.0 + target['atk']
            if kills:
                return 30.0 if target['atk'] + target['health'] >= source['atk'] + source['health'] else 10.0
            return 5.0
        return 20.0 if kind == 'your_power' else 15.0

    def is_blunder(self, state, candidate, candidates):
        """Review flags and soft preferences, not proof that a move is wrong."""
        found = index_state(state)
        if candidate['kind'] == 'end_turn':
            return any(self._free_value(c, found, candidates, state) for c in candidates)
        return self._hits_own_side(candidate, found) or self.wastes_mana(state, candidate, candidates)

    def wastes_mana(self, state, candidate, candidates):
        """True for a card that cannot be part of any set of cards spending the most mana this turn.

        With 8 mana, an 8-cost and a 2-cost card, the 2-cost card is out. Two small cards that spend as
        much as one bigger card are both fine, so setting up a combo with cheap cards stays allowed.
        """
        found = index_state(state)
        kind, source = found.get(candidate['source'], (None, None))
        if kind != 'hand':
            return False
        mana = state['you']['mana']
        costs = {}
        for move in candidates:
            move_kind, card = found.get(move['source'], (None, None))
            if move_kind == 'hand' and card['cost'] <= mana:
                costs[move['source']] = card['cost']
        if candidate['source'] not in costs:
            return False
        best = _best_spend(costs.values(), mana)
        others = [cost for card, cost in costs.items() if card != candidate['source']]
        return costs[candidate['source']] + _best_spend(others, mana - costs[candidate['source']]) < best

    def _hits_own_side(self, candidate, found):
        kind, source = found.get(candidate['source'], (None, None))
        target_kind = found.get(candidate['target'], (None,))[0]
        if kind != 'hand' or target_kind not in ('your_minion', 'your_hero'):
            return False
        text = self.text(source['card'])
        return any(w in text for w in HOSTILE) and 'friendly' not in text

    def is_useful(self, state, candidate, candidates):
        return self._free_value(candidate, index_state(state), candidates, state)

    def _free_value(self, candidate, found, candidates, state):
        """Worth doing instead of ending the turn: face damage, a clean kill, a real card, or spare mana."""
        if candidate['kind'] == 'end_turn' or self._hits_own_side(candidate, found):
            return False
        kind, source = found.get(candidate['source'], (None, None))
        target_kind, target = found.get(candidate['target'], (None, None))
        if kind == 'hand':
            return source['cost'] > 0
        if kind == 'your_power':
            return not target
        if kind not in ('your_minion', 'your_hero') or not target:
            return False
        if target_kind == 'enemy_hero':
            return source['atk'] > 0
        kills = source['atk'] >= hp(target)
        dies = kind == 'your_minion' and target['atk'] >= hp(source)
        return kills and not dies

    def choose(self, state, candidates, cards=None):
        started = time.perf_counter()
        cannon_rules = self.tactics and cannon.enabled(self)
        scores = self.scores(state, candidates)
        forced = None
        if self.tactics and max(scores) < 1000.0:
            if cannon_rules:
                forced = cannon.lethal_move(state, candidates, self.cards) or cannon.forced_move(state, candidates, self.cards)
                if not forced:
                    coin = deck_tactics.coin_tempo(state, candidates, self.cards)
                    if coin is not None and not cannon.incoming_damage(state) >= cannon.life(state['you']['hero']):
                        forced = coin, 'tactics:coin_tempo'
            else:
                forced = deck_tactics.forced_move(state, candidates, self.cards)
        if forced:
            self.decision_counts[forced[1]] += 1
            self.last_decision = {'source': 'rules', 'reason': forced[1], 'selected': forced[0],
                                  'elapsed_ms': (time.perf_counter() - started) * 1000}
            return forced[0]
        pool = list(range(len(candidates)))
        if cannon_rules and max(scores) < 1000.0:
            pool = cannon.allowed(state, candidates, self.cards)
        if self.aggressive:
            pool = self.face_first(state, candidates, pool)
        if self.tactics and not cannon_rules and max(scores) < 1000.0:
            pool = deck_tactics.without_wasted_attacks(state, candidates, pool, self.cards)
        # Ties break on list position, which keeps replays reproducible.
        pick = max(pool, key=lambda i: (scores[i], -i))
        reason = 'rules_policy'
        if self.tactics and max(scores) < 1000.0:
            coin = deck_tactics.coin_before_passing(state, candidates, self.cards) if candidates[pick]['kind'] == 'end_turn' else None
            if coin is not None:
                pick, reason = coin, 'tactics:coin_before_passing'
            buff = deck_tactics.buff_first(state, candidates, pick, self.cards) if not cannon_rules else None
            if buff is not None:
                pick, reason = buff, 'tactics:buff_first'
        self.decision_counts['rules'] += 1
        self.last_decision = {'source': 'rules', 'reason': reason, 'selected': pick,
                              'elapsed_ms': (time.perf_counter() - started) * 1000}
        return pick

    def mulligan(self, entities, cards_by_entity, state=None):
        """Return deck-summoned Patches; otherwise keep the existing low-cost opening curve."""
        if self.tactics:
            if cannon.enabled(self):
                return cannon.mulligan(entities, cards_by_entity, self.cards, state)
            return deck_tactics.mulligan(entities, cards_by_entity, self.cards)
        replace = []
        for entity in entities:
            card_id = cards_by_entity.get(str(entity['id'])) or entity.get('card') or ''
            card = self.cards.get(card_id, {})
            if card_id.removeprefix('CORE_') in MULLIGAN_RETURN_TO_DECK or card.get('cost', 0) > MULLIGAN_KEEP_COST:
                replace.append(entity['id'])
        return replace

    def pick_choice(self, choice, cards_by_entity):
        """Highest-cost offer, a rough proxy for card power on Discover-style choices."""
        timeline = rewind.choose(choice, cards_by_entity)
        if timeline:
            index, reason = timeline
            self.last_choice_decision = {'reason': reason, 'selected': index}
            return index
        if self.tactics and cannon.enabled(self):
            index = cannon.discover(choice, cards_by_entity, self.cards)
            if index is not None:
                self.last_choice_decision = {'reason': 'cannon:discover', 'selected': index}
                return index
        def value(entity):
            return self.cards.get(cards_by_entity.get(str(entity['id'])) or entity.get('card'), {}).get('cost', 0)
        index = max(range(len(choice['entities'])), key=lambda i: (value(choice['entities'][i]), -i))
        self.last_choice_decision = {'reason': 'discover:highest_cost', 'selected': index}
        return index
