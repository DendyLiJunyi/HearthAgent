"""Decision makers. All of them only ever pick from what the game itself offered."""
import json
import re
import time
import math
from collections import Counter
from pathlib import Path

from . import tactics as deck_tactics

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
    """Lethal first, then spend mana, then sensible trades. No search and no deck plan."""
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
        lethal = bool(attackers) and sum(found[s][1]['atk'] for s in attackers) >= enemy_hp
        return [self._score(c, found, lethal) for c in candidates]

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
        scores = self.scores(state, candidates)
        forced = deck_tactics.forced_move(state, candidates, self.cards) if self.tactics and max(scores) < 1000.0 else None
        if forced:
            self.decision_counts[forced[1]] += 1
            self.last_decision = {'source': 'rules', 'reason': forced[1], 'selected': forced[0],
                                  'elapsed_ms': (time.perf_counter() - started) * 1000, 'checkpoint': None}
            return forced[0]
        pool = list(range(len(candidates)))
        if self.aggressive:
            pool = self.face_first(state, candidates, pool)
        # Ties break on list position, which keeps replays reproducible.
        pick = max(pool, key=lambda i: (scores[i], -i))
        reason = 'rules_policy'
        if self.tactics and max(scores) < 1000.0:
            buff = deck_tactics.buff_first(state, candidates, pick, self.cards)
            if buff is not None:
                pick, reason = buff, 'tactics:buff_first'
        self.decision_counts['rules'] += 1
        self.last_decision = {'source': 'rules', 'reason': reason, 'selected': pick,
                              'elapsed_ms': (time.perf_counter() - started) * 1000, 'checkpoint': None}
        return pick

    def mulligan(self, entities, cards_by_entity):
        """Return deck-summoned Patches; otherwise keep the existing low-cost opening curve."""
        if self.tactics:
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
        def value(entity):
            return self.cards.get(cards_by_entity.get(str(entity['id'])) or entity.get('card'), {}).get('cost', 0)
        return max(range(len(choice['entities'])), key=lambda i: (value(choice['entities'][i]), -i))


class LayaPolicy:
    """Fine-tuned Laya ranks moves with soft heuristic preferences.

    Scores are averaged across option orders because the model still changes its pick on about
    64% of decisions when the order changes. Lethal, mulligan and choices stay with the rules.
    Any model failure falls back to the rules, and the fallback count is kept for reporting.
    """
    name = 'laya'
    MAX_OPTIONS = 32

    def __init__(self, cards, predict, orders=4, aggressive=False, preference_penalty=0.05, tactics=False):
        if orders < 1 or not math.isfinite(preference_penalty) or not 0 <= preference_penalty <= 1:
            raise ValueError('positive orders and a preference penalty in [0, 1] are required')
        self.cards, self.predict, self.orders = cards, predict, orders
        self.rules = RulesPolicy(cards, aggressive, tactics=tactics)
        self.aggressive = aggressive
        self.tactics = tactics
        self.fallbacks = 0
        self.preference_penalty = preference_penalty
        self.decision_counts = Counter()
        self.last_decision = None

    @classmethod
    def load(cls, cards, path=None, device='cuda', aggressive=False, tactics=False):
        import os
        import sys
        sys.path.insert(0, str(ROOT / 'services/laya'))
        from runtime import configure_environment
        configure_environment()
        os.environ['HF_HUB_OFFLINE'] = '1'
        import laya
        checkpoint = Path(path or ROOT / '.data/imitation/laya-combo').resolve()
        agent = laya.load(str(checkpoint), device=device)

        def predict(state, questions):
            return agent.predict(state, questions, max_len=2048, head_max_len=1024, min_confidence=0.0)
        policy = cls(cards, predict, aggressive=aggressive, tactics=tactics)
        policy.checkpoint = str(checkpoint)
        return policy

    def _orders(self, count):
        import random
        rng = random.Random(count)
        orders = [list(range(count)), list(range(count))[::-1]]
        while len(orders) < self.orders:
            shuffled = list(range(count))
            rng.shuffle(shuffled)
            orders.append(shuffled)
        return orders[:self.orders]

    def rank(self, state, candidates, cards):
        import sys
        sys.path.insert(0, str(ROOT / 'experiments/imitation'))
        from features import question, render_candidate, render_state
        row = {'state': state, 'candidates': candidates, 'cards': cards or {}}
        text = render_state(row, self.cards)
        descriptions = [render_candidate(row, c, self.cards) for c in candidates]
        totals = [0.0] * len(candidates)
        for order in self._orders(len(candidates)):
            answer = self.predict(text, question([descriptions[i] for i in order]))['answers']['action']
            for slot, original in enumerate(order):
                value = answer['probabilities'][f'c{slot}']
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError('invalid model probability')
                totals[original] += value
        return totals

    def allowed(self, state, candidates):
        """Only the user's explicit aggressive preference filters legal moves."""
        safe = list(range(len(candidates)))
        return self.rules.face_first(state, candidates, safe) if self.aggressive else safe

    def choose(self, state, candidates, cards=None):
        started = time.perf_counter()
        self._reason, self._raw_pick, self._error = 'model', None, None
        pick = self._choose(state, candidates, cards)
        self.decision_counts[self._reason] += 1
        self.last_decision = {
            'source': 'model' if self._reason == 'model' else 'forced' if self._reason == 'single_option' else 'rules',
            'reason': self._reason, 'selected': pick, 'raw_selected': self._raw_pick,
            'preference_changed_pick': self._raw_pick is not None and pick != self._raw_pick,
            'elapsed_ms': (time.perf_counter() - started) * 1000,
            'checkpoint': getattr(self, 'checkpoint', None), 'error': self._error,
        }
        return pick

    def _choose(self, state, candidates, cards=None):
        scores = self.rules.scores(state, candidates)
        if len(candidates) == 1:
            self._reason = 'single_option'
            return 0
        # The model has never been trained on Titan or Old God abilities.
        ability = any(c.get('sub', -1) >= 0 and index_state(state).get(c['source'], (None,))[0] == 'your_minion'
                      for c in candidates)
        if max(scores) >= 1000.0 or ability or len(candidates) > self.MAX_OPTIONS:
            self._reason = 'lethal' if max(scores) >= 1000.0 else 'ability' if ability else 'option_limit'
            return self.rules.choose(state, candidates, cards)
        forced = deck_tactics.forced_move(state, candidates, self.cards) if self.tactics else None
        if forced:
            self._reason = forced[1]
            return forced[0]
        try:
            totals = self.rank(state, candidates, cards)
        except Exception as error:
            self._reason, self._error = 'model_error', f'{type(error).__name__}: {error}'
            self.fallbacks += 1
            return self.rules.choose(state, candidates, cards)
        self._raw_pick = max(range(len(totals)), key=lambda i: (totals[i], -i))
        for i, candidate in enumerate(candidates):
            if self.rules.is_blunder(state, candidate, candidates):
                totals[i] -= self.preference_penalty * self.orders
        pool = self.allowed(state, candidates)
        pick = max(pool, key=lambda i: (totals[i], -i))
        if self.tactics and candidates[pick]['kind'] == 'end_turn':
            # An aggressive deck does not pass with damage or mana left: take the model's best real alternative.
            useful = [i for i in pool if self.rules.is_useful(state, candidates[i], candidates)]
            if useful:
                self._reason = 'tactics:no_early_end_turn'
                pick = max(useful, key=lambda i: (totals[i], -i))
        if self.tactics:
            buff = deck_tactics.buff_first(state, candidates, pick, self.cards)
            if buff is not None:
                self._reason = 'tactics:buff_first'
                return buff
        return pick

    def mulligan(self, entities, cards_by_entity):
        return self.rules.mulligan(entities, cards_by_entity)

    def pick_choice(self, choice, cards_by_entity):
        return self.rules.pick_choice(choice, cards_by_entity)
