"""Offline regression cases for receipts, file lifecycle, and decision attribution."""
import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import cli
from agent.cli import Tail, outcome_counts
from agent.loop import Stop
from agent.policy import LayaPolicy
from agent.screen import BattlefieldSettler, hand_signature, battlefield_signature
from agent import test_agent as helpers
from agent.test_agent import Harness, Clock, ME, bracket, game_lines, line, entity


def choices(kind='GENERAL'):
    rows = [line('DebugPrintEntityChoices',
                 f'id=1 Player={ME} TaskList=1 ChoiceType={kind} CountMin=0 CountMax={3 if kind == "MULLIGAN" else 1}')]
    return rows + [line('DebugPrintEntityChoices', f'Entities[{i}]={bracket(e, "HAND")}')
                   for i, e in enumerate((60, 61, 62))]


def receipt(selected, player=ME):
    return [line('DebugPrintEntitiesChosen', f'id=1 Player={player} EntitiesCount={len(selected)}')] + [
        line('DebugPrintEntitiesChosen', f'Entities[{i}]={bracket(e, "HAND")}') for i, e in enumerate(selected)]


class ChoicePolicy:
    def pick_choice(self, *_):
        return 1

    def mulligan(self, *_):
        return [60, 62]


class ReceiptTests(unittest.TestCase):
    def test_choice_buttons_use_deliberate_clicks(self):
        harness = self.harness(receipt([61]))
        original = harness.inputs.send
        speeds = []
        def send(gestures):
            speeds.append(harness.inputs.careful)
            original(gestures)
        harness.inputs.send = send
        self.assertEqual(harness.settled_step(), 'acted')
        self.assertEqual(speeds, [True])

    def test_parking_waits_for_release_processing_and_rechecks_focus(self):
        from agent.windows_input import WindowsInput
        from agent import geometry
        inputs = WindowsInput.__new__(WindowsInput)
        inputs.window = {'width': 1920, 'height': 1080, 'left': 0, 'top': 0}
        events = []
        inputs._guard = lambda: events.append('guard')
        inputs._move = lambda point: events.append(('move', point))
        with patch('agent.windows_input.time.sleep', side_effect=lambda delay: events.append(('wait', delay))):
            inputs.park()
        self.assertEqual(events, ['guard', ('wait', 0.15), 'guard', ('move', geometry.CANCEL_POINT)])

    def test_pointer_parks_after_action_before_confirmation(self):
        harness = Harness(game_lines() + helpers.option_lines(), after_input=[helpers.send_line()])
        parked = []
        harness.inputs.park = lambda: parked.append(len(harness.inputs.gestures))
        self.assertEqual(harness.settled_step(), 'acted')
        self.assertEqual(parked, [1])

    def harness(self, after, kind='GENERAL'):
        harness = Harness(game_lines() + choices(kind), after_input=after)
        harness.agent.policy = ChoicePolicy()
        return harness

    def test_selected_entity_matches(self):
        self.assertEqual(self.harness(receipt([61])).settled_step(), 'acted')

    def test_wrong_entity_stops(self):
        harness = self.harness(receipt([60]))
        with self.assertRaisesRegex(Stop, 'different choice entities'):
            harness.settled_step()
        self.assertEqual(len(harness.inputs.gestures), 1)

    def test_partial_receipt_never_resends(self):
        harness = self.harness(receipt([61])[:1])
        with self.assertRaisesRegex(Stop, 'incomplete choice receipt'):
            harness.settled_step()
        self.assertEqual(len(harness.inputs.gestures), 1)

    def test_receipt_can_arrive_in_separate_reads(self):
        harness = self.harness(receipt([61])[:1])
        original = harness.agent.sleep
        def advance(seconds):
            original(seconds)
            harness.pending += receipt([61])[1:]
        harness.agent.sleep = advance
        self.assertEqual(harness.settled_step(), 'acted')

    def test_opponent_receipt_does_not_confirm_our_choice(self):
        harness = self.harness(receipt([61], 'Opponent#111'))
        with self.assertRaisesRegex(Stop, 'choice not answered'):
            harness.settled_step()

    def test_mulligan_receipt_reports_kept_cards(self):
        self.assertEqual(self.harness(receipt([61]), 'MULLIGAN').settled_step(), 'acted')
        with self.assertRaisesRegex(Stop, 'different choice entities'):
            self.harness(receipt([60]), 'MULLIGAN').settled_step()

    def test_live_mulligan_replacing_middle_card_keeps_outer_two(self):
        # The failed live run replaced 16 and received kept entities 20 and 17.
        harness = self.harness(receipt([60, 62]), 'MULLIGAN')
        harness.agent.policy.mulligan = lambda *_: [61]
        self.assertEqual(harness.settled_step(), 'acted')

    def test_replace_all_confirms_an_empty_kept_set(self):
        harness = self.harness(receipt([]), 'MULLIGAN')
        harness.agent.policy.mulligan = lambda *_: [60, 61, 62]
        self.assertEqual(harness.settled_step(), 'acted')

    def test_coin_is_excluded_from_kept_set_when_going_second(self):
        rows = choices('MULLIGAN') + [
            line('DebugPrintEntityChoices', f'Entities[3]={bracket(63, "HAND")}'),
            line('DebugPrintEntityChoices', f'Entities[4]={bracket(64, "HAND", "GAME_005")}')]
        harness = Harness(game_lines() + rows, after_input=receipt([60, 61, 62, 63]))
        harness.agent.policy = ChoicePolicy()
        harness.agent.policy.mulligan = lambda *_: []
        self.assertEqual(harness.settled_step(), 'acted')

    def test_missing_mulligan_screen_stops_without_input(self):
        harness = self.harness([], 'MULLIGAN')
        harness.agent.mulligan_ready = lambda: False
        self.assertEqual(harness.settled_step(), 'animating')
        harness.clock.now += 41
        with self.assertRaisesRegex(Stop, 'mulligan screen'):
            harness.agent.step()
        self.assertEqual(harness.inputs.gestures, [])

    def test_choice_animation_times_out_without_input(self):
        harness = self.harness([])
        harness.agent.choice_ready = lambda key: False
        self.assertEqual(harness.settled_step(), 'animating')
        harness.clock.now += 30
        with self.assertRaisesRegex(Stop, 'choice screen'):
            harness.agent.step()
        self.assertEqual(harness.inputs.gestures, [])

    def test_wrong_minion_placement_stops(self):
        rows = game_lines() + entity(51, 'MINION', 1, 'HAND', 'MINION', 2)
        rows += [line('DebugPrintOptions', 'id=1'), line('DebugPrintOptions',
                 f'option 1 type=POWER mainEntity={bracket(51, "HAND")} error=NONE')]
        for position in (1, 2):
            sent = line('SendOption', f'selectedOption=1 selectedSubOption=-1 selectedTarget=0 selectedPosition={position}')
            harness = Harness(rows, after_input=[sent])
            harness.agent.policy.choose = lambda *_: 0
            if position == 2:
                self.assertEqual(harness.settled_step(), 'acted')
            else:
                with self.assertRaisesRegex(Stop, 'different action'):
                    harness.settled_step()


class TailLifecycleTests(unittest.TestCase):
    def test_truncation_is_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'Power.log'
            path.write_bytes(b'old complete line\npartial')
            tail = Tail(path)
            tail()
            path.write_bytes(b'new\n')
            with self.assertRaisesRegex(Stop, 'truncated'):
                tail()

    def test_same_size_rewrite_is_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'Power.log'
            path.write_bytes(b'old\n')
            tail = Tail(path)
            tail()
            path.write_bytes(b'new\n')
            with self.assertRaisesRegex(Stop, 'rewritten'):
                tail()

    def test_replacement_and_new_session_are_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'Power.log'
            path.write_bytes(b'old\n')
            tail = Tail(path)
            tail()
            replacement = Path(folder) / 'replacement'
            replacement.write_bytes(b'new\n')
            os.replace(replacement, path)
            with self.assertRaisesRegex(Stop, 'replaced'):
                tail()
            with self.assertRaisesRegex(Stop, 'session changed'):
                Tail(path, session_check=lambda: Path(folder) / 'new-session.log')()


class ReadinessTests(unittest.TestCase):
    def test_mulligan_requires_both_title_and_confirm(self):
        from agent.menu import Regions
        class Screen:
            width, height = 1920, 1080
            def frame(self):
                return b''
        regions = Regions(Screen(), refs={})
        for shown, expected in (({'mulligan_confirm'}, False), ({'mulligan_title'}, False),
                                ({'mulligan_title', 'mulligan_confirm'}, True), (set(), False)):
            regions.matches = lambda name: name in shown
            self.assertEqual(regions.mulligan_ready(), expected)

    def test_verified_region_variants_match_without_relaxing_tolerance(self):
        from agent.menu import Regions
        regions = Regions(None, refs={'confirm': {'box': [0, 0, 1, 1],
                                                  'signature': [0, 0, 0], 'variants': [[200, 200, 200]]}})
        regions.screen = type('Screen', (), {'width': 1})()
        regions.pixels = bytes([200, 200, 200, 255])
        self.assertTrue(regions.matches('confirm'))
        regions.pixels = bytes([100, 100, 100, 255])
        self.assertFalse(regions.matches('confirm'))

    def test_fast_interval_still_restarts_on_motion(self):
        clock = Clock()
        detector = BattlefieldSettler(seconds=0.6, clock=clock.time)
        self.assertFalse(detector.ready(bytes([0] * 12)))
        clock.now = 0.5
        self.assertFalse(detector.ready(bytes([0] * 12)))
        clock.now = 0.61
        self.assertTrue(detector.ready(bytes([0] * 12)))
        self.assertFalse(detector.ready(bytes([100] * 12)))
        clock.now = 1.22
        self.assertTrue(detector.ready(bytes([100] * 12)))

    def test_hand_motion_is_visible_even_when_board_is_unchanged(self):
        pixels = bytearray(1920 * 1080 * 4)
        original_board = battlefield_signature(pixels, 1920)
        original_hand = hand_signature(pixels, 1920)
        for y in range(920, 1060):
            for x in range(470, 1430):
                at = (y * 1920 + x) * 4
                pixels[at:at + 3] = b'\xff\xff\xff'
        self.assertEqual(original_board, battlefield_signature(pixels, 1920))
        clock = Clock()
        detector = BattlefieldSettler(clock=clock.time)
        detector.ready(original_hand)
        clock.now = 2
        self.assertFalse(detector.ready(hand_signature(pixels, 1920)))

    def test_empty_capture_never_becomes_ready(self):
        detector = BattlefieldSettler()
        self.assertFalse(detector.ready(b''))
        self.assertFalse(detector.ready(b''))


class AttributionTests(unittest.TestCase):
    def setUp(self):
        fixture = helpers.LayaPolicyTests()
        fixture.setUp()
        self.state, self.moves = fixture.packet['state'], fixture.candidates
        self.predict = fixture.prefers('enemy minion')

    def test_model_rules_and_forced_decisions_have_distinct_reasons(self):
        policy = LayaPolicy({}, self.predict)
        policy.choose(self.state, self.moves)
        self.assertEqual(policy.last_decision['source'], 'model')
        self.assertIsNotNone(policy.last_decision['raw_selected'])
        policy.choose(self.state, self.moves[:1])
        self.assertEqual(policy.last_decision['reason'], 'single_option')
        self.state['opponent']['hero']['damage'] = 29
        policy.choose(self.state, self.moves)
        self.assertEqual(policy.last_decision['reason'], 'lethal')
        self.assertEqual(policy.fallbacks, 0)
        self.assertEqual(sum(policy.decision_counts.values()), 3)

    def test_nan_probability_is_a_recorded_fallback(self):
        def bad(*args):
            return {'answers': {'action': {'probabilities': {'c0': float('nan')}}}}
        policy = LayaPolicy({}, bad)
        policy.choose(self.state, self.moves)
        self.assertEqual(policy.last_decision['reason'], 'model_error')
        self.assertEqual(policy.fallbacks, 1)
        self.assertIn('invalid model probability', policy.last_decision['error'])

    def test_soft_preferences_break_near_ties_but_leave_all_moves_available(self):
        policy = LayaPolicy({}, self.predict)
        policy.rank = lambda *_: [1.36, 1.32, 1.32]
        self.assertEqual(policy.allowed(self.state, self.moves), [0, 1, 2])
        self.assertNotEqual(policy.choose(self.state, self.moves), 0)
        self.assertTrue(policy.last_decision['preference_changed_pick'])


class ConfigurationTests(unittest.TestCase):
    def test_profile_paths_are_relative_to_profile_and_deck_is_configurable(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / 'profile.json'
            profile.write_text(json.dumps({'install': 'game', 'checkpoint': 'model', 'deck_id': '123'}), encoding='utf-8')
            with patch.multiple(cli, INSTALL=cli.INSTALL, BATTLE_NET=cli.BATTLE_NET,
                                DECK_ID=cli.DECK_ID, CHECKPOINT=cli.CHECKPOINT):
                cli.configure(profile)
                self.assertEqual(cli.INSTALL, (Path(folder) / 'game').resolve())
                self.assertEqual(cli.CHECKPOINT, (Path(folder) / 'model').resolve())
                self.assertEqual(cli.DECK_ID, '123')

    def test_unknown_profile_options_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / 'profile.json'
            profile.write_text('{"instal": "game"}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'only'):
                cli.configure(profile)

    def test_draws_do_not_count_as_losses(self):
        self.assertEqual(outcome_counts([{'won': True}, {'won': False}, {'won': None}]),
                         {'games': 3, 'won': 1, 'lost': 1, 'drawn': 1})


if __name__ == '__main__':
    unittest.main()
