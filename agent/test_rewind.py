"""Timeline UI and Standard Crowley priority regressions, without live input."""
import unittest

from agent import geometry, rewind, cannon
from agent.policy import RulesPolicy, LayaPolicy, load_cards
from agent.deck_profile import STANDARD_WARRIOR, load_profile
from agent.test_standard import entity
from agent.test_agent import Harness, ME, bracket, game_lines, line, entity as log_entity
from agent.screen import choice_signature


def board(own=5, enemy=17):
    hero = lambda i: entity('HERO_01', 'HERO', id=i, health=30, atk=0)
    return {'you': {'hero': hero(10), 'hero_power': None, 'weapon': entity('END_016', 'WEAPON', id=11, atk=own),
                    'minions': [], 'hand': [], 'mana': 5},
            'opponent': {'hero': hero(20), 'hero_power': None, 'weapon': entity('CORE_LOOT_044', 'WEAPON', id=21, atk=enemy),
                         'minions': []}}


def timeline(state=None, reverse=False, source='TIME_034'):
    entities = [{'id': 60, 'card': rewind.KEEP}, {'id': 61, 'card': rewind.REWIND}]
    if reverse:
        entities.reverse()
    return {'id': 1, 'type': 'GENERAL', 'min': 1, 'max': 1, 'entities': entities,
            'source': {'id': 50, 'card': source}, 'state': state}


class RewindTests(unittest.TestCase):
    def test_bad_weapon_result_rewinds_and_good_result_keeps_for_both_policies(self):
        for policy in (RulesPolicy(load_cards()), LayaPolicy(load_cards(), None)):
            for reverse in (False, True):
                for state, expected in ((board(5, 17), rewind.REWIND), (board(5, 2), rewind.KEEP),
                                        (board(1, 2), rewind.REWIND), (None, rewind.KEEP)):
                    choice = timeline(state, reverse)
                    pick = policy.pick_choice(choice, {})
                    self.assertEqual(choice['entities'][pick]['card'], expected)

    def test_unknown_source_keeps_and_unrelated_discover_is_unchanged(self):
        choice = timeline(board(), source='UNREVIEWED')
        self.assertEqual(rewind.choose(choice, {})[0], 0)
        choice['entities'][0]['card'] = 'CAP_106'
        self.assertIsNone(rewind.choose(choice, {}))
        self.assertEqual(geometry.entity_choice_point(0, choice['entities'], {}), geometry.choice_point(0, 2))

    def test_bottom_left_buttons_are_bound_to_ids_not_offer_order(self):
        for reverse in (False, True):
            choice = timeline(reverse=reverse)
            for i, e in enumerate(choice['entities']):
                expected = (580, 805) if e['card'] == rewind.KEEP else (350, 805)
                self.assertEqual(geometry.entity_choice_point(i, choice['entities'], {}), expected)

    def test_choice_loop_uses_timeline_geometry_and_confirms_selected_entity(self):
        rows = game_lines() + log_entity(11, 'END_016', 1, 'PLAY', 'WEAPON', ATK=5, HEALTH=4)
        rows += log_entity(21, 'CORE_LOOT_044', 2, 'PLAY', 'WEAPON', ATK=17, HEALTH=2)
        rows += [line('DebugPrintEntityChoices', f'id=1 Player={ME} TaskList=1 ChoiceType=GENERAL CountMin=1 CountMax=1'),
                 line('DebugPrintEntityChoices', 'Source=' + bracket(59, card='TIME_034')),
                 line('DebugPrintEntityChoices', 'Entities[0]=' + bracket(60, 'SETASIDE', rewind.KEEP)),
                 line('DebugPrintEntityChoices', 'Entities[1]=' + bracket(61, 'SETASIDE', rewind.REWIND))]
        receipt = [line('DebugPrintEntitiesChosen', f'id=1 Player={ME} EntitiesCount=1'),
                   line('DebugPrintEntitiesChosen', 'Entities[0]=' + bracket(61, 'SETASIDE', rewind.REWIND))]
        h = Harness(rows, after_input=receipt)
        h.agent.policy = RulesPolicy(load_cards())
        self.assertEqual(h.settled_step(), 'acted')
        self.assertEqual(h.inputs.gestures, [[('click', (350, 805))]])

    def test_timeline_button_animation_is_in_choice_signature(self):
        pixels = bytearray(1920 * 1080 * 4)
        before = choice_signature(pixels, 1920)
        pixels[(805 * 1920 + 350) * 4] = 255
        self.assertNotEqual(choice_signature(pixels, 1920), before)


class CrowleyTests(unittest.TestCase):
    def setup(self):
        state = board(3, 2)
        state['you']['hand'] = [entity('CAP_106', id=30, cost=5), entity('CAP_102', 'SPELL', id=31, cost=4)]
        moves = [dict(kind='power', source=31, target=None, sub=-1),
                 dict(kind='power', source=30, target=None, sub=-1),
                 dict(kind='power', source=10, target=20, sub=-1)]
        return state, moves

    def test_crowley_before_draw_and_weapon_attack_in_both_policies(self):
        state, moves = self.setup()
        profile = load_profile(STANDARD_WARRIOR, 'standard')
        for policy in (RulesPolicy(load_cards(), tactics=True), LayaPolicy(load_cards(), None, tactics=True)):
            policy.deck_profile = profile
            if hasattr(policy, 'rules'):
                policy.rules.deck_profile = profile
            self.assertEqual(policy.choose(state, moves), 1)
            self.assertEqual(policy.last_decision['reason'], 'cannon:crowley_setup')

    def test_full_board_insufficient_mana_and_skipper_defer(self):
        for condition in ('full', 'mana', 'skipper'):
            state, moves = self.setup()
            if condition == 'full':
                state['you']['minions'] = [entity('CAP_107t', id=i) for i in range(40, 47)]
            elif condition == 'mana':
                state['you']['mana'] = 4
            else:
                state['you']['minions'] = [entity('YOD_022', id=40)]
            self.assertIsNone(cannon.crowley_setup(state, moves, load_cards()))

    def test_existing_cannoneers_allow_last_board_slot(self):
        state, moves = self.setup()
        state['you']['minions'] = [entity('CAP_107t', id=i) for i in range(40, 46)]
        self.assertEqual(cannon.crowley_setup(state, moves, load_cards()), 1)

    def test_survival_taunt_can_compete_and_visible_lethal_still_wins(self):
        state, moves = self.setup()
        state['you']['hero']['health'] = 1
        state['you']['hand'].append(entity('JAIL_384', id=32, cost=5))
        moves.append(dict(kind='power', source=32, target=None, sub=-1))
        self.assertIsNone(cannon.crowley_setup(state, moves, load_cards()))
        state['opponent']['hero']['health'] = 3
        state['you']['hero']['atk'] = 3
        p = RulesPolicy(load_cards(), tactics=True)
        p.deck_profile = load_profile(STANDARD_WARRIOR, 'standard')
        self.assertEqual(p.choose(state, moves), 2)


if __name__ == '__main__':
    unittest.main()
