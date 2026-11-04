"""Fast pace, staying in the game after failures, and deck tactics. Nothing here sends real input."""
import unittest

from agent.cli import PACES, SessionRecord, build_agent
from agent.loop import CAUTIOUS_MOVES, FocusLost, Stop
from agent.pace_report import report_log, run_lines
from agent.policy import LayaPolicy, RulesPolicy
from agent.power import PowerLog
from agent.screen import region_signature
from agent.tactics import buff_first, coin_tempo, forced_move, mulligan
from agent.test_agent import ME, Harness, game_lines, line, option_lines, send_line


def replayed(rows):
    """The same power lines, as the client logs them when it reaches them in its animation queue."""
    return [row.replace('GameState.DebugPrintPower()', 'PowerTaskList.DebugPrintPower()')
            for row in rows if 'GameState.DebugPrintPower()' in row]


def prefer_minion_then_face(state, candidates, cards=None):
    targets = [c['target'] for c in candidates]
    return targets.index(40) if 40 in targets else targets.index(20)


def fast_harness(rows, after_input=()):
    harness = Harness(rows, after_input=list(after_input))
    harness.agent.backlog_limit, harness.agent.recover, harness.agent.eager_decision = 12, True, True
    return harness


class BacklogTests(unittest.TestCase):
    def test_counts_received_lines_until_the_client_reaches_them(self):
        log = PowerLog()
        rows = game_lines()
        for row in rows:
            log.feed(row)
        received = log.backlog.size
        self.assertGreater(received, 12)
        for row in replayed(rows):
            log.feed(row)
        self.assertEqual(log.backlog.size, 0)

    def test_replaying_lines_does_not_change_the_game_state(self):
        log = PowerLog()
        for row in game_lines():
            log.feed(row)
        revision = log.game.revision
        log.feed('D 10:00:00.0 PowerTaskList.DebugPrintPower() - TAG_CHANGE Entity=GameEntity tag=TURN value=99\n')
        self.assertEqual(log.game.revision, revision)
        self.assertEqual(log.game.snapshot()['turn'], 3)

    def test_a_new_game_starts_with_a_new_backlog(self):
        log = PowerLog()
        for row in game_lines():
            log.feed(row)
        self.assertGreater(log.backlog.size, 0)
        log.feed(game_lines()[0])
        self.assertEqual(log.backlog.size, 0)


class GateTests(unittest.TestCase):
    def test_input_waits_for_the_backlog_then_goes_without_the_screen_settling(self):
        rows = game_lines() + option_lines()
        harness = fast_harness(rows, [send_line()])
        harness.agent.step()
        harness.clock.now += 2
        self.assertEqual(harness.agent.step(), 'animating')
        self.assertEqual(harness.inputs.gestures, [])
        harness.pending += replayed(rows)
        harness.agent.step()
        harness.clock.now += 2
        self.assertEqual(harness.agent.step(), 'acted')

    def test_a_few_lines_that_never_replay_cannot_hold_input(self):
        rows = game_lines() + option_lines()
        harness = fast_harness(rows, [send_line()])
        harness.pending += replayed(rows)[:-10]
        harness.agent.step()
        harness.clock.now += 2
        self.assertLessEqual(harness.agent.power.backlog.size, 12)
        self.assertEqual(harness.agent.step(), 'acted')

    def test_a_stuck_backlog_only_delays_for_the_timeout(self):
        harness = fast_harness(game_lines() + option_lines(), [send_line()])
        harness.agent.step()
        harness.clock.now += 2
        self.assertEqual(harness.agent.step(), 'animating')
        harness.clock.now += harness.agent.drain_timeout + 1
        self.assertEqual(harness.agent.step(), 'acted')

    def test_the_decision_is_made_during_the_animation_and_only_once(self):
        rows = game_lines() + option_lines()
        harness = fast_harness(rows, [send_line()])
        calls = []
        policy = harness.agent.policy
        original = policy.choose

        def choose(*args):
            calls.append(1)
            return original(*args)
        policy.choose = choose
        harness.agent.step()
        harness.clock.now += 0.1
        harness.agent.step()
        self.assertEqual(len(calls), 1)
        self.assertEqual(harness.inputs.gestures, [])
        harness.pending += replayed(rows)
        harness.agent.step()
        harness.clock.now += 2
        self.assertEqual(harness.agent.step(), 'acted')
        self.assertEqual(len(calls), 1)

    def test_an_early_decision_still_refuses_a_wrong_game_type(self):
        harness = fast_harness(game_lines('GT_RANKED') + option_lines())
        harness.agent.policy.choose = lambda *_: self.fail('no decision belongs to a refused game')
        harness.agent.step()
        harness.clock.now += 0.1
        with self.assertRaises(Stop):
            harness.agent.step()
        self.assertEqual(harness.inputs.gestures, [])


class RecoveryTests(unittest.TestCase):
    def settled(self, rows, after=()):
        harness = fast_harness(rows, after)
        harness.pending += replayed(rows)
        harness.agent.step()
        harness.clock.now += 2
        return harness

    def test_a_move_the_game_refuses_is_dropped_and_another_is_tried(self):
        harness = self.settled(game_lines() + option_lines())
        harness.agent.policy.choose = prefer_minion_then_face
        self.assertEqual(harness.agent.step(), 'recovered')
        self.assertEqual(harness.agent.recoveries[0]['kind'], 'dropped_move')
        self.assertEqual(harness.agent.cautious_moves, CAUTIOUS_MOVES)
        harness.after_input = [send_line(1, 20)]
        self.assertEqual(harness.agent.step(), 'acted')
        self.assertEqual(harness.agent.power.game.sends[-1]['sent']['target'], 20)

    def test_without_recovery_the_old_stop_remains(self):
        harness = self.settled(game_lines() + option_lines())
        harness.agent.recover = False
        with self.assertRaisesRegex(Stop, 'handing the game back'):
            harness.agent.step()

    def test_an_end_turn_the_game_refuses_waits_for_the_timer_with_no_more_input(self):
        rows = game_lines() + [line('DebugPrintOptions', 'id=1'),
                               line('DebugPrintOptions', '  option 0 type=END_TURN mainEntity= error=INVALID errorParam=')]
        harness = self.settled(rows)
        harness.agent.policy.choose = lambda state, candidates, cards=None: 0
        self.assertEqual(harness.agent.step(), 'recovered')
        sent = len(harness.inputs.gestures)
        self.assertEqual(harness.agent.step(), 'waiting')
        self.assertEqual(len(harness.inputs.gestures), sent)

    def test_a_different_accepted_move_continues_until_the_limit(self):
        for wrong_before, stops in ((0, False), (2, True)):
            harness = self.settled(game_lines() + option_lines(), [send_line(0, 0)])
            harness.agent.wrong_actions = wrong_before
            if stops:
                with self.assertRaisesRegex(Stop, 'different action'):
                    harness.agent.step()
            else:
                self.assertEqual(harness.agent.step(), 'acted')
                self.assertEqual(harness.agent.recoveries[0]['kind'], 'wrong_action')

    def test_losing_focus_mid_gesture_pauses_then_cancels_and_replans(self):
        harness = self.settled(game_lines() + option_lines())
        original = harness.inputs.send

        def lost(gestures):
            harness.inputs.send = original
            raise FocusLost('another window')
        harness.inputs.send = lost
        self.assertEqual(harness.agent.step(), 'paused')
        harness.pending.append(send_line())
        harness.agent.step()
        self.assertEqual(harness.inputs.gestures[0][0][0], 'right_click')

    def test_focus_loss_stops_without_recovery(self):
        harness = self.settled(game_lines() + option_lines())
        harness.agent.recover = False

        def lost(gestures):
            raise FocusLost('another window')
        harness.inputs.send = lost
        with self.assertRaises(FocusLost):
            harness.agent.step()

    def test_a_retry_slows_the_next_moves(self):
        harness = self.settled(game_lines() + option_lines(), [send_line()])
        harness.agent.cautious_moves = 2
        self.assertEqual(harness.agent.step(), 'acted')
        self.assertTrue(harness.inputs.careful)
        self.assertEqual(harness.agent.cautious_moves, 1)

    def test_a_choice_that_fails_does_not_end_the_game(self):
        rows = game_lines() + [line('DebugPrintEntityChoices', f'id=7 Player={ME} TaskList=1 ChoiceType=GENERAL CountMin=1 CountMax=3'),
                               line('DebugPrintEntityChoices', 'Entities[0]=[entityName=A id=50 zone=HAND zonePos=1 cardId=X player=1]')]
        for recover, expect_stop in ((True, False), (False, True)):
            harness = self.settled(rows)
            harness.agent.recover = recover
            if expect_stop:
                with self.assertRaisesRegex(Stop, 'unsupported'):
                    harness.agent.step()
            else:
                self.assertEqual(harness.agent.step(), 'choice_skipped')
                self.assertEqual(harness.inputs.gestures, [])

    def test_esc_still_stops_during_recovery(self):
        harness = self.settled(game_lines() + option_lines())
        harness.inputs.aborted = lambda: True
        with self.assertRaisesRegex(Stop, 'stopped by the player'):
            harness.agent.step()


class ScreenTests(unittest.TestCase):
    class Screen:
        width, height = 1920, 1080

        def __init__(self, button=(137, 99, 8)):
            self.pixels = bytearray(1920 * 1080 * 4)
            self.button = button

        def frame(self):
            for y in range(480, 516, 5):
                for x in range(1515, 1601, 5):
                    at = (y * 1920 + x) * 4
                    self.pixels[at:at + 3] = bytes((self.button[2], self.button[1], self.button[0]))
            return bytes(self.pixels)

    def record(self, folder, screen):
        now = [0.0]
        record = SessionRecord(folder, 'missing.log', screen, pace='fast', clock=lambda: now[0])
        return record, now

    def test_fast_screen_needs_a_lit_button_even_after_the_cap(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            record, now = self.record(folder, self.Screen(button=(83, 66, 70)))
            record.focus_on([('click', (100, 100))])
            self.assertFalse(record.screen_ready())
            now[0] = 5
            self.assertFalse(record.screen_ready())

    def test_endless_motion_at_the_target_only_delays_until_the_cap(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            screen = self.Screen()
            record, now = self.record(folder, screen)
            record.focus_on([('drag', (100, 100), (300, 300))])
            for value in range(3):
                screen.pixels[(100 * 1920 + 100) * 4:] = bytes([value * 90]) * (len(screen.pixels) - (100 * 1920 + 100) * 4)
                self.assertFalse(record.screen_ready())
                now[0] += 0.1
            now[0] = 0.6
            screen.pixels[(100 * 1920 + 100) * 4:] = bytes([200]) * (len(screen.pixels) - (100 * 1920 + 100) * 4)
            self.assertTrue(record.screen_ready())

    def test_region_signature_watches_only_the_given_points(self):
        pixels = bytearray(1920 * 1080 * 4)
        before = region_signature(bytes(pixels), 1920, [(500, 500)])
        pixels[(100 * 1920 + 100) * 4] = 255
        self.assertEqual(region_signature(bytes(pixels), 1920, [(500, 500)]), before)
        pixels[(500 * 1920 + 500) * 4] = 255
        self.assertNotEqual(region_signature(bytes(pixels), 1920, [(500, 500)]), before)

    def test_region_signature_stays_inside_the_frame(self):
        region_signature(bytes(1920 * 1080 * 4), 1920, [(0, 0), (1919, 1079)])

    def test_paces_build_the_expected_agents(self):
        fast = build_agent(lambda: [], object(), object(), None, pace='fast', mode='wild')
        self.assertEqual((fast.opening_delay, fast.backlog_limit, fast.recover), (0.0, 12, True))
        careful = build_agent(lambda: [], object(), object(), None, pace='careful', mode='practice')
        self.assertEqual((careful.opening_delay, careful.backlog_limit, careful.recover), (20.0, None, False))
        self.assertEqual(careful.settle, 0.5)
        self.assertEqual(set(PACES), {'fast', 'careful'})


CARDS = {
    'CORE_NEW1_027': {'name': 'Southsea Captain', 'race': 'PIRATE', 'cost': 3},
    'CAP_104': {'name': 'Blastpowder Engineer', 'race': 'PIRATE', 'cost': 2},
    'CAP_107': {'name': 'Cannonmaster', 'race': 'PIRATE', 'cost': 1},
    'DRG_056': {'name': 'Parachute Brigand', 'race': 'PIRATE', 'cost': 2},
    'YOD_022': {'name': 'Risky Skipper', 'race': 'PIRATE', 'cost': 1},
    'CS3_008': {'name': 'Bloodsail Deckhand', 'race': 'PIRATE', 'cost': 1},
    'JAIL_421': {'name': 'Warptooth', 'race': 'BEAST', 'cost': 4, 'mechanics': ['CHARGE']},
    'GAME_005': {'name': 'The Coin', 'cost': 0},
    'CFM_637': {'name': 'Patches the Pirate', 'race': 'PIRATE', 'cost': 1},
    'JAIL_384': {'name': 'Chainbreaker Hogger', 'cost': 8},
    'CAP_102': {'name': 'Land Ho!', 'cost': 4},
    'CAP_103': {'name': 'Hand Cannon', 'cost': 3},
    'REV_332': {'name': 'Anima Extractor', 'cost': 2},
    'BT_124': {'name': 'Corsair Cache', 'cost': 2},
    'VAC_938': {'name': 'Hozen Roughhouser', 'race': 'PIRATE', 'cost': 3},
    'OTHER_2': {'name': 'A two drop', 'cost': 2},
    'OTHER_5': {'name': 'A five drop', 'cost': 5},
}


def card(entity, card_id, kind='MINION', cost=1, atk=1, health=1, damage=0, keywords=()):
    return {'id': entity, 'card': card_id, 'type': kind, 'cost': cost, 'atk': atk, 'health': health, 'damage': damage,
            'armor': 0, 'keywords': list(keywords)}


ENEMY_HERO = card(90, 'HERO_01', 'HERO', 0, 0, 30)
MY_HERO = card(91, 'HERO_01', 'HERO', 0, 0, 30)
END = {'option': 0, 'sub': -1, 'target': 0, 'kind': 'end_turn', 'source': None}


def state(hand=(), minions=(), enemy=(), mana=3, enemy_hp=30):
    hero = dict(ENEMY_HERO, health=enemy_hp)
    return {'turn': 5, 'you': {'hero': MY_HERO, 'hero_power': None, 'weapon': None, 'mana': mana, 'hand': list(hand),
                               'minions': list(minions)},
            'opponent': {'hero': hero, 'hero_power': None, 'weapon': None, 'minions': list(enemy)}}


def play(entity, option=1):
    return {'option': option, 'sub': -1, 'target': 0, 'kind': 'power', 'source': entity}


def attack(entity, target=90, option=2):
    return {'option': option, 'sub': -1, 'target': target, 'kind': 'power', 'source': entity}


PIRATE = card(10, 'CAP_107', atk=3, health=1)
CAPTAIN = card(20, 'CORE_NEW1_027', cost=3, atk=3, health=3)


class TacticsTests(unittest.TestCase):
    def test_southsea_captain_goes_before_a_pirate_attacks(self):
        candidates = [END, attack(10), play(20)]
        self.assertEqual(buff_first(state([CAPTAIN], [PIRATE]), candidates, 1, CARDS), 2)

    def test_choosing_another_card_first_is_left_alone(self):
        other = card(21, 'DRG_056', cost=2)
        candidates = [END, attack(10), play(20), play(21, 3)]
        self.assertIsNone(buff_first(state([CAPTAIN, other], [PIRATE]), candidates, 3, CARDS))

    def test_a_non_pirate_attack_is_left_alone(self):
        beast = card(10, 'JAIL_421', atk=3, health=3)
        self.assertIsNone(buff_first(state([CAPTAIN], [beast]), [END, attack(10), play(20)], 1, CARDS))

    def test_a_full_board_cannot_take_the_buff(self):
        board = [dict(PIRATE, id=10 + i, health=3) for i in range(7)]
        self.assertIsNone(buff_first(state([CAPTAIN], board), [END, attack(10), play(20)], 1, CARDS))

    def test_risky_skipper_would_kill_our_one_health_attacker_so_attack_first(self):
        skipper = card(11, 'YOD_022', atk=1, health=3)
        self.assertIsNone(buff_first(state([CAPTAIN], [PIRATE, skipper]), [END, attack(10), play(20)], 1, CARDS))

    def test_charge_from_hand_completes_lethal(self):
        warptooth = card(30, 'JAIL_421', cost=4, atk=3, health=3)
        board = [card(10, 'JAIL_421', atk=3, health=3)]
        result = forced_move(state([warptooth], board, mana=4, enemy_hp=6), [END, attack(10), play(30)], CARDS)
        self.assertEqual(result, (2, 'tactics:lethal_setup'))

    def test_buff_counts_toward_lethal_only_when_it_is_enough(self):
        pirates = [card(10, 'CAP_107', atk=3, health=2), card(11, 'CAP_107', atk=3, health=2)]
        moves = [END, attack(10), attack(11, option=3), play(20)]
        self.assertEqual(forced_move(state([CAPTAIN], pirates, enemy_hp=8), moves, CARDS)[1], 'tactics:lethal_setup')
        self.assertIsNone(forced_move(state([CAPTAIN], pirates, enemy_hp=9), moves, CARDS))

    def test_taunt_blocks_a_lethal_line(self):
        warptooth = card(30, 'JAIL_421', cost=4, atk=9, health=3)
        taunt = card(40, 'OTHER_2', atk=1, health=1, keywords=['TAUNT'])
        self.assertIsNone(forced_move(state([warptooth], [], [taunt], mana=4, enemy_hp=5), [END, play(30)], CARDS))

    def test_coin_only_when_it_gains_tempo(self):
        coin = card(40, 'GAME_005', 'SPELL', 0)
        two = card(41, 'DRG_056', cost=2)
        one = card(42, 'CAP_107', cost=1)
        self.assertEqual(coin_tempo(state([coin, two], mana=1), [END, play(40)], CARDS), 1)
        self.assertIsNone(coin_tempo(state([coin, one], mana=1), [END, play(40), play(42, 2)], CARDS))
        self.assertIsNone(coin_tempo(state([coin], mana=1), [END, play(40)], CARDS))
        # Mana can already be fully spent, or there is no mana left to waste.
        self.assertIsNone(coin_tempo(state([coin, one, two], mana=1), [END, play(40), play(42, 2)], CARDS))
        self.assertIsNone(coin_tempo(state([coin, one], mana=0), [END, play(40)], CARDS))

    def test_the_model_cannot_pass_with_damage_available(self):
        policy = LayaPolicy(CARDS, lambda *_: None, tactics=True)
        policy.rank = lambda *_: [3.0, 0.5]
        current = state([], [card(10, 'JAIL_421', atk=3, health=3)])
        self.assertEqual(policy.choose(current, [END, attack(10)], {}), 1)
        self.assertEqual(policy.last_decision['reason'], 'tactics:no_early_end_turn')
        policy.tactics = False
        self.assertEqual(policy.choose(current, [END, attack(10)], {}), 0)

    def test_laya_uses_a_forced_move_without_asking_the_model(self):
        policy = LayaPolicy(CARDS, None, tactics=True)
        policy.rank = lambda *_: self.fail('the model should not be asked')
        warptooth = card(30, 'JAIL_421', cost=4, atk=3, health=3)
        current = state([warptooth], [card(10, 'JAIL_421', atk=3, health=3)], mana=4, enemy_hp=6)
        self.assertEqual(policy.choose(current, [END, attack(10), play(30)], {}), 2)
        self.assertEqual(policy.last_decision['source'], 'rules')

    def test_laya_attack_before_the_captain_is_corrected_but_its_other_picks_stand(self):
        policy = LayaPolicy(CARDS, None, tactics=True)
        other = card(21, 'DRG_056', cost=2)
        moves = [END, attack(10), play(20), play(21, 3)]
        policy.rank = lambda *_: [0.0, 3.0, 0.1, 0.2]
        self.assertEqual(policy.choose(state([CAPTAIN, other], [PIRATE], mana=5), moves, {}), 2)
        self.assertEqual(policy.last_decision['reason'], 'tactics:buff_first')
        policy.rank = lambda *_: [0.0, 0.1, 0.2, 3.0]
        self.assertEqual(policy.choose(state([CAPTAIN, other], [PIRATE], mana=5), moves, {}), 3)
        self.assertEqual(policy.last_decision['reason'], 'model')

    def test_existing_lethal_comes_before_any_buff(self):
        policy = RulesPolicy(CARDS, tactics=True)
        current = state([CAPTAIN], [PIRATE], enemy_hp=3)
        self.assertEqual(policy.choose(current, [END, attack(10), play(20)]), 1)

    def test_rules_policy_uses_tactics_only_when_asked(self):
        current = state([CAPTAIN], [PIRATE])
        moves = [END, attack(10), play(20)]
        self.assertEqual(RulesPolicy(CARDS, tactics=True).choose(current, moves), 2)
        plain = RulesPolicy(CARDS)
        plain.choose(current, moves)
        self.assertEqual(plain.last_decision['reason'], 'rules_policy')


class MulliganTests(unittest.TestCase):
    def replace(self, *card_ids):
        entities = [{'id': i, 'card': c} for i, c in enumerate(card_ids)]
        return [card_ids[i] for i in mulligan(entities, {}, CARDS)]

    def test_slow_cards_and_patches_go_back(self):
        self.assertEqual(self.replace('CAP_107', 'CFM_637', 'JAIL_384', 'CAP_102'), ['CFM_637', 'JAIL_384', 'CAP_102'])

    def test_a_three_drop_needs_a_curve_under_it(self):
        self.assertEqual(self.replace('VAC_938', 'CAP_107', 'JAIL_384'), ['VAC_938', 'JAIL_384'])
        self.assertEqual(self.replace('VAC_938', 'CAP_107', 'DRG_056'), [])

    def test_the_coin_is_never_replaced_and_helps_a_three_drop(self):
        self.assertEqual(self.replace('VAC_938', 'CAP_107', 'OTHER_5', 'JAIL_384', 'GAME_005'), ['OTHER_5', 'JAIL_384'])

    def test_weapon_needs_deckhand_or_the_coin(self):
        self.assertEqual(self.replace('CAP_103', 'CAP_107', 'CAP_107'), ['CAP_103'])
        self.assertEqual(self.replace('CAP_103', 'CS3_008', 'CAP_107'), [])
        self.assertEqual(self.replace('CAP_103', 'CAP_107', 'CAP_107', 'CAP_107', 'GAME_005'), [])

    def test_conditional_cheap_cards(self):
        self.assertEqual(self.replace('REV_332', 'CAP_107', 'CAP_107'), ['REV_332'])
        self.assertEqual(self.replace('REV_332', 'YOD_022', 'CAP_107'), [])
        self.assertEqual(self.replace('BT_124', 'OTHER_5', 'JAIL_384'), ['BT_124', 'OTHER_5', 'JAIL_384'])
        self.assertEqual(self.replace('BT_124', 'CAP_107', 'JAIL_384'), ['JAIL_384'])

    def test_other_cards_use_the_general_curve(self):
        self.assertEqual(self.replace('OTHER_2', 'OTHER_5', 'CAP_107'), ['OTHER_5'])

    def test_core_copies_count_as_the_same_card(self):
        self.assertEqual(self.replace('CORE_NEW1_027', 'CAP_107', 'DRG_056'), [])


class PaceReportTests(unittest.TestCase):
    def test_run_lines_drop_earlier_games_from_the_session(self):
        import json
        import tempfile
        import time
        from pathlib import Path
        at = time.mktime((2026, 11, 4, 10, 0, 30, 0, 0, -1))
        with tempfile.TemporaryDirectory() as folder:
            moves = Path(folder) / 'moves.jsonl'
            rows = ['D 09:00:00.0 early\n', 'D 10:00:40.0 late\n']
            self.assertEqual(run_lines(rows, moves), rows)
            moves.write_text(json.dumps({'kind': 'choice'}) + '\n' + json.dumps({'kind': 'option', 'at': at}) + '\n')
            self.assertEqual(run_lines(rows, moves), rows[1:])

    def test_measures_the_wait_after_the_client_finished(self):
        def at(stamp, text):
            return f'D 10:00:{stamp} {text}\n'
        rows = [at('00.0000', 'GameState.DebugPrintPower() - CREATE_GAME'),
                at('00.0000', 'GameState.DebugPrintPower() - TAG_CHANGE A'),
                at('00.1000', 'GameState.DebugPrintOptions() - id=1'),
                at('01.0000', 'PowerTaskList.DebugPrintPower() - CREATE_GAME'),
                at('01.0000', 'PowerTaskList.DebugPrintPower() - TAG_CHANGE A'),
                at('05.0000', 'GameState.SendOption() - selectedOption=1 selectedSubOption=-1 selectedTarget=0 selectedPosition=0')]
        report = report_log(rows)
        self.assertEqual(report['moves'], 1)
        self.assertAlmostEqual(report['options_to_send']['median'], 4.9)
        self.assertAlmostEqual(report['gate_would_open']['median'], 1.05)
        self.assertAlmostEqual(report['time_saved_per_move']['median'], 3.85)


if __name__ == '__main__':
    unittest.main()
