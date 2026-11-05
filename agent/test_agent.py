"""Tests try to make the agent click when it must not. No test can reach real input."""
import glob
import os
import tempfile
import unittest

from agent import geometry
from agent.cli import ClientLog, Tail, request_launch
from agent.loop import Agent, RecordingInput, Stop
from agent.power import PowerLog, candidates_from
from agent.windows_input import path, to_absolute

ME = 'Me#1234'


def line(kind, text):
    return f'D 10:00:00.0000000 GameState.{kind}() - {text}\n'


def power(text):
    return line('DebugPrintPower', text)


def entity(entity_id, card, controller, zone, kind, position=0, **tags):
    rows = [power(f'FULL_ENTITY - Creating ID={entity_id} CardID={card}'),
            power(f'tag=CONTROLLER value={controller}'), power(f'tag=ZONE value={zone}'),
            power(f'tag=CARDTYPE value={kind}'), power(f'tag=ZONE_POSITION value={position}')]
    return rows + [power(f'tag={k} value={v}') for k, v in tags.items()]


def game_lines(game_type='GT_VS_AI', opponent='The Innkeeper'):
    rows = [power('CREATE_GAME'), power('GameEntity EntityID=1'), power('tag=TURN value=3'),
            power('Player EntityID=2 PlayerID=1 GameAccountId=[hi=1 lo=1]'),
            power('tag=HERO_ENTITY value=10'), power('tag=RESOURCES value=3'),
            power('Player EntityID=3 PlayerID=2 GameAccountId=[hi=2 lo=2]'),
            power('tag=HERO_ENTITY value=20'),
            line('DebugPrintGame', f'GameType={game_type}'),
            line('DebugPrintGame', f'PlayerID=1, PlayerName={ME}'),
            line('DebugPrintGame', f'PlayerID=2, PlayerName={opponent}')]
    rows += entity(10, 'HERO_03', 1, 'PLAY', 'HERO', HEALTH=30)
    rows += entity(20, 'HERO_01', 2, 'PLAY', 'HERO', HEALTH=30)
    rows += entity(30, 'CS2_182', 1, 'PLAY', 'MINION', 1, ATK=4, HEALTH=5)
    rows += entity(40, 'CS2_189', 2, 'PLAY', 'MINION', 1, ATK=1, HEALTH=1)
    rows += entity(50, 'EX1_144', 1, 'HAND', 'SPELL', 1, COST=0)
    return rows


def bracket(entity_id, zone='PLAY', card='X', player=1):
    return f'[entityName=N id={entity_id} zone={zone} zonePos=1 cardId={card} player={player}]'


def option_lines(packet=1):
    """End turn, or attack with minion 30 at minion 40 or the enemy hero."""
    return [line('DebugPrintOptions', f'id={packet}'),
            line('DebugPrintOptions', '  option 0 type=END_TURN mainEntity= error=INVALID errorParam='),
            line('DebugPrintOptions', f'  option 1 type=POWER mainEntity={bracket(30)} error=NONE errorParam='),
            line('DebugPrintOptions', f'    target 0 entity={bracket(40, player=2)} error=NONE errorParam='),
            line('DebugPrintOptions', f'    target 1 entity={bracket(20, player=2)} error=NONE errorParam=')]


def send_line(option=1, target=40):
    return line('SendOption', f'selectedOption={option} selectedSubOption=-1 selectedTarget={target} selectedPosition=0')


class FirstAttack:
    def choose(self, state, candidates, cards=None):
        return next(i for i, c in enumerate(candidates) if c['target'] == 40)


class Clock:
    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Harness:
    """A scripted log. `after_input` lines appear only once the agent has clicked."""

    def __init__(self, lines, after_input=(), during_decision=()):
        self.pending, self.after_input = list(lines), list(after_input)
        self.during_decision = list(during_decision)
        self.clock = Clock()
        self.inputs = RecordingInput()
        original = self.inputs.send

        def send(gestures):
            original(gestures)
            self.pending += self.after_input
        self.inputs.send = send
        self.agent = Agent(self.read, FirstAttack(), self.inputs, settle=1.0, confirm_timeout=2.0,
                           clock=self.clock.time, sleep=self.clock.sleep, log=lambda *_: None)

    def read(self):
        lines, self.pending = self.pending, []
        return lines

    def settled_step(self):
        self.agent.step()
        self.clock.now += 2.0
        return self.agent.step()


class SafetyTests(unittest.TestCase):
    def test_ranked_game_is_refused_without_any_input(self):
        for game_type in ('GT_RANKED', 'GT_ARENA', 'GT_CASUAL', None):
            lines = game_lines(game_type or 'GT_UNKNOWN') + option_lines()
            harness = Harness(lines)
            with self.assertRaises(Stop):
                harness.settled_step()
            self.assertEqual(harness.inputs.gestures, [])

    def test_practice_action_is_confirmed_by_the_log(self):
        harness = Harness(game_lines() + option_lines(), after_input=[send_line()])
        self.assertEqual(harness.settled_step(), 'acted')
        self.assertEqual(len(harness.inputs.gestures), 1)
        self.assertEqual(harness.inputs.gestures[0][0][0], 'drag')

    def test_different_action_in_the_log_stops_the_agent(self):
        harness = Harness(game_lines() + option_lines(), after_input=[send_line(option=0, target=0)])
        with self.assertRaisesRegex(Stop, 'different action'):
            harness.settled_step()

    def test_missing_confirmation_resends_a_bounded_number_of_times(self):
        harness = Harness(game_lines() + option_lines())
        with self.assertRaisesRegex(Stop, '3 attempt'):
            harness.settled_step()
        self.assertEqual(len(harness.inputs.gestures), 4)  # Three attempts and the final cancel.

    def test_resend_succeeds_when_a_later_attempt_lands(self):
        harness = Harness(game_lines() + option_lines())
        original = harness.inputs.send

        def lands_second_time(gestures):
            original(gestures)
            if len(harness.inputs.gestures) == 2:
                harness.pending.append(send_line())
        harness.inputs.send = lands_second_time
        self.assertEqual(harness.settled_step(), 'acted')
        self.assertEqual(len(harness.inputs.gestures), 2)

    def test_state_change_after_a_silent_attempt_blocks_the_resend(self):
        harness = Harness(game_lines() + option_lines())
        original = harness.inputs.send

        def changes_state(gestures):
            original(gestures)
            harness.after = harness.clock.now
        harness.inputs.send = changes_state
        notes = []

        def note(event):
            notes.append(event['kind'])
            if event['kind'] == 'no_send':
                harness.pending.append(power('TAG_CHANGE Entity=GameEntity tag=TURN value=4'))
        harness.agent.before_input = note
        with self.assertRaisesRegex(Stop, 'changed before input'):
            harness.settled_step()
        self.assertEqual(len(harness.inputs.gestures), 1)

    def test_no_input_before_the_log_settles(self):
        harness = Harness(game_lines() + option_lines())
        self.assertEqual(harness.agent.step(), 'settling')
        self.assertEqual(harness.inputs.gestures, [])

    def test_state_change_during_decision_cancels_input(self):
        harness = Harness(game_lines() + option_lines())
        policy = harness.agent.policy

        class ChangesState:
            def choose(self, *args):
                harness.pending.append(power('TAG_CHANGE Entity=GameEntity tag=TURN value=4'))
                return policy.choose(*args)
        harness.agent.policy = ChangesState()
        self.assertEqual(harness.settled_step(), 'state_changed')
        self.assertEqual(harness.inputs.gestures, [])

    def test_stale_packet_waits_instead_of_clicking(self):
        lines = game_lines() + option_lines() + [power('TAG_CHANGE Entity=GameEntity tag=TURN value=4')]
        harness = Harness(lines)
        self.assertEqual(harness.settled_step(), 'stale_packet')
        self.assertEqual(harness.inputs.gestures, [])

    def test_escape_stops_before_input(self):
        harness = Harness(game_lines() + option_lines())
        harness.inputs.aborted = lambda: True
        with self.assertRaisesRegex(Stop, 'stopped by the player'):
            harness.settled_step()
        self.assertEqual(harness.inputs.gestures, [])

    def test_action_limit_stops_the_agent(self):
        harness = Harness(game_lines() + option_lines())
        harness.agent.max_actions = 0
        with self.assertRaisesRegex(Stop, 'action limit'):
            harness.settled_step()

    def test_finished_game_is_never_acted_on(self):
        lines = game_lines() + option_lines() + [power(f'TAG_CHANGE Entity={ME} tag=PLAYSTATE value=WON')]
        harness = Harness(lines)
        self.assertEqual(harness.settled_step(), 'game_over')
        self.assertEqual(harness.inputs.gestures, [])


class LaunchTests(unittest.TestCase):
    """Timings follow the real cold start in Battle.net's log of 2026-11-04: logged in after 6 seconds, no launch."""

    def on_send(self, count, now, due):
        pass

    def run_launch(self, events, *, old_log=b'', timeout=120):
        """events maps a second to the bytes the client logs then. The game is open once the log says WINDOW."""
        with tempfile.TemporaryDirectory() as folder:
            old = os.path.join(folder, 'battle.net-20261104T000000.000000.log')
            if old_log:
                with open(old, 'wb') as out:
                    out.write(old_log)
            client = ClientLog(folder)
            new = old if old_log else os.path.join(folder, 'battle.net-20261104T085429.000000.log')
            now, sends, due = [0.0], [], dict(events)

            def advance(seconds):
                now[0] += seconds
                for at in sorted(k for k in due if k <= now[0]):
                    with open(new, 'ab') as out:
                        out.write(due.pop(at))

            def game_open():
                if not os.path.exists(new):
                    return False
                with open(new, 'rb') as log:
                    return b'WINDOW' in log.read()

            def send():
                sends.append(now[0])
                self.on_send(len(sends), now[0], due)

            try:
                request_launch(send, game_open, client, timeout=timeout, clock=lambda: now[0], sleep=advance)
            except Stop as stop:
                return sends, str(stop)
            return sends, None

    def test_cold_start_asks_again_after_login_and_that_opens_the_game(self):
        def on_send(count, now, due):
            if count == 2:
                due[now + 2] = ClientLog.LAUNCHED + b' selectedRegion=CN\n'
                due[now + 5] = b'WINDOW\n'
        self.on_send = on_send
        sends, stopped = self.run_launch({6: ClientLog.LOGGED_IN + b'\n'})
        self.assertIsNone(stopped)
        self.assertEqual(len(sends), 2)
        self.assertGreaterEqual(sends[1], 6)

    def test_not_asked_again_before_login(self):
        sends, stopped = self.run_launch({})
        self.assertEqual(len(sends), 1)
        self.assertIn('never logged in', stopped)

    def test_slow_game_is_not_opened_twice(self):
        sends, stopped = self.run_launch({6: ClientLog.LOGGED_IN + b'\n', 8: ClientLog.LAUNCHED + b'\n'})
        self.assertEqual(len(sends), 1)
        self.assertIn('did not appear', stopped)

    def test_requests_are_limited_when_every_one_is_ignored(self):
        sends, stopped = self.run_launch({6: ClientLog.LOGGED_IN + b'\n'})
        self.assertEqual(len(sends), 4)
        self.assertIn('ignored 4 requests', stopped)

    def test_launch_from_before_this_run_does_not_count(self):
        running = ClientLog.LOGGED_IN + b'\n' + ClientLog.LAUNCHED + b'\n'
        sends, stopped = self.run_launch({}, old_log=running)
        self.assertEqual(len(sends), 4)
        self.assertIn('ignored', stopped)

    def test_new_client_log_is_read_from_its_start(self):
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, 'battle.net-20261103T000000.000000.log'), 'wb') as out:
                out.write(b'x' * 1000)
            client = ClientLog(folder)
            with open(os.path.join(folder, 'battle.net-20261104T000000.000000.log'), 'wb') as out:
                out.write(ClientLog.LOGGED_IN + ClientLog.LAUNCHED)
            self.assertEqual(client.read(), (True, True))

    def test_markers_match_the_wording_of_the_real_client_log(self):
        self.assertIn(ClientLog.LOGGED_IN, b'I [BNLogin] {Main} Logged into Battle.net successfully. |bnet=1')
        self.assertIn(ClientLog.LAUNCHED, b'I [GameLaunchController] {Main} LaunchBinary: uid=hs_beta selectedRegion=CN')


class Utf8Tests(unittest.TestCase):
    def test_relaunch_keeps_every_argument(self):
        from agent.cli import utf8_command
        command = utf8_command(['play', '--execute', '--policy', 'rules'])
        self.assertEqual(command[1:5], ['-X', 'utf8', '-m', 'agent.cli'])
        self.assertEqual(command[5:], ['play', '--execute', '--policy', 'rules'])


class ScreenReadyTests(unittest.TestCase):
    def test_measured_button_colors(self):
        # Mean colors from saved live frames, grouped by whether the next click worked.
        for rgb in ((137, 99, 8), (146, 106, 9), (45, 151, 10), (33, 101, 9), (28, 89, 8)):
            self.assertTrue(geometry.end_turn_lit(rgb), rgb)
        for rgb in ((83, 66, 70), (114, 98, 82), (58, 45, 59), (12, 12, 17), (30, 32, 3), (99, 50, 82)):
            self.assertFalse(geometry.end_turn_lit(rgb), rgb)

    def test_waits_for_the_screen_before_any_input(self):
        harness = Harness(game_lines() + option_lines(), after_input=[send_line()])
        answers = iter([False, True, False, True, True, True])
        harness.agent.screen_ready = lambda: next(answers)
        self.assertEqual(harness.settled_step(), 'animating')
        for _ in range(3):
            self.assertEqual(harness.agent.step(), 'animating')
        self.assertEqual(harness.inputs.gestures, [])
        self.assertEqual(harness.agent.step(), 'acted')
        self.assertEqual(len(harness.inputs.gestures), 1)

    def test_button_going_grey_at_the_last_moment_cancels_input(self):
        harness = Harness(game_lines() + option_lines(), after_input=[send_line()])
        answers = iter([True, True, False, True, True, True])
        harness.agent.screen_ready = lambda: next(answers)
        self.assertEqual(harness.settled_step(), 'animating')
        self.assertEqual(harness.agent.step(), 'animating')
        self.assertEqual(harness.inputs.gestures, [])
        self.assertEqual(harness.agent.step(), 'animating')
        self.assertEqual(harness.agent.step(), 'acted')
        self.assertEqual(len(harness.inputs.gestures), 1)

    def test_four_card_choice_clicks_land_on_the_cards(self):
        # Card edges read from a live Marin the Manager choice (.data/live/20261104-145903/final.png).
        cards = [(265, 530), (635, 905), (1010, 1280), (1385, 1660)]
        for index, (left, right) in enumerate(cards):
            x, _ = geometry.choice_point(index, 4)
            self.assertTrue(left < x < right, (index, x))

    def test_retry_cancels_a_stuck_arrow_first(self):
        from agent.loop import CANCEL
        harness = Harness(game_lines() + option_lines())
        inner = harness.inputs.send

        def lands_second_time(gestures):
            inner(gestures)
            if len(harness.inputs.gestures) == 2:
                harness.pending.append(send_line())
        harness.inputs.send = lands_second_time
        self.assertEqual(harness.settled_step(), 'acted')
        first, second = harness.inputs.gestures
        self.assertNotIn(CANCEL, first)
        self.assertEqual(second[0], CANCEL)
        self.assertEqual(second[1:], first)

    def test_giving_up_leaves_no_arrow_behind(self):
        from agent.loop import CANCEL
        harness = Harness(game_lines() + option_lines())
        with self.assertRaisesRegex(Stop, '3 attempt'):
            harness.settled_step()
        self.assertEqual(harness.inputs.gestures[-1], [CANCEL])

    def test_cancel_point_is_on_no_minion_row(self):
        x, y = geometry.CANCEL_POINT
        self.assertTrue(geometry.ENEMY_MINION_Y + 60 < y < geometry.LOCAL_MINION_Y - 60)
        self.assertLess(x, geometry.END_TURN[0] - 100)

    def test_retry_uses_the_careful_speed(self):
        harness = Harness(game_lines() + option_lines())
        speeds = []
        inner = harness.inputs.send

        def lands_second_time(gestures):
            speeds.append(harness.inputs.careful)
            inner(gestures)
            if len(speeds) == 2:
                harness.pending.append(send_line())
        harness.inputs.send = lands_second_time
        self.assertEqual(harness.settled_step(), 'acted')
        self.assertEqual(speeds, [False, True])

    def test_required_lit_readings_can_be_raised(self):
        harness = Harness(game_lines() + option_lines(), after_input=[send_line()])
        harness.agent.lit_required = 3
        harness.agent.screen_ready = lambda: True
        self.assertEqual(harness.settled_step(), 'animating')
        self.assertEqual(harness.agent.step(), 'animating')
        self.assertEqual(harness.agent.step(), 'acted')

    def test_button_color_uses_the_measured_samples(self):
        from agent.screen import BUTTON_XS, BUTTON_YS, average_rgb
        width, height = 1920, 1080
        pixels = bytearray(width * height * 4)
        for y in BUTTON_YS:
            for x in BUTTON_XS:
                pixels[(y * width + x) * 4:(y * width + x) * 4 + 3] = bytes((5, 161, 180))
        self.assertEqual(average_rgb(pixels, width), [180, 161, 5])

    def test_saved_frame_is_a_valid_png(self):
        import struct
        import zlib
        from agent.screen import encode_png
        data = encode_png(bytes((1, 2, 3, 255, 4, 5, 6, 255)), 2, 1)
        self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(struct.unpack('>II', data[16:24]), (2, 1))
        at = data.index(b'IDAT')
        length = struct.unpack('>I', data[at - 4:at])[0]
        self.assertEqual(zlib.decompress(data[at + 4:at + 4 + length]), bytes((0, 3, 2, 1, 6, 5, 4)))

    def test_going_second_mulligan_clicks_land_on_the_four_shown_cards(self):
        # Card edges from a live frame. The Coin is listed fifth in the log but is not on screen.
        cards = [(465, 690), (730, 940), (975, 1205), (1235, 1465)]
        for index, (left, right) in enumerate(cards):
            x, _ = geometry.mulligan_point(index, 5)
            self.assertTrue(left < x < right, (index, x))
        with self.assertRaises(geometry.GeometryError):
            geometry.mulligan_point(4, 5)

    def test_going_first_mulligan_clicks_land_on_the_three_shown_cards(self):
        cards = [(505, 735), (850, 1075), (1190, 1420)]
        for index, (left, right) in enumerate(cards):
            x, _ = geometry.mulligan_point(index, 3)
            self.assertTrue(left < x < right, (index, x))

    def spare_mana_state(self, mana, hand):
        card = lambda entity, card_id, cost: {'id': entity, 'card': card_id, 'cost': cost, 'type': 'MINION', 'atk': 1,
                                              'health': 1, 'damage': 0, 'armor': 0, 'keywords': []}
        hero = lambda entity: dict(card(entity, 'HERO_01', 0), type='HERO', health=30)
        return {'turn': 4, 'you': {'mana': mana, 'max_mana': mana, 'hero': hero(64), 'hero_power': card(65, 'HERO_01bp', 2),
                                   'weapon': None, 'minions': [], 'hand': [card(i + 10, c, cost) for i, (c, cost) in enumerate(hand)]},
                'opponent': {'hero': hero(66), 'hero_power': None, 'weapon': None, 'minions': []}}

    def spare_mana_moves(self, sources):
        end = {'kind': 'end_turn', 'source': None, 'target': 0, 'sub': -1, 'option': 0}
        return [end] + [{'kind': 'power', 'source': s, 'target': 0, 'sub': -1, 'option': i + 1} for i, s in enumerate(sources)]

    def test_small_card_that_blocks_the_big_one_is_refused(self):
        from agent.policy import RulesPolicy
        rules = RulesPolicy({})
        state = self.spare_mana_state(8, [('BIG', 8), ('SMALL', 2)])
        moves = self.spare_mana_moves([10, 11])
        self.assertFalse(rules.is_blunder(state, moves[1], moves))
        self.assertTrue(rules.is_blunder(state, moves[2], moves))

    def test_two_small_cards_may_beat_one_medium_card(self):
        from agent.policy import RulesPolicy
        rules = RulesPolicy({})
        state = self.spare_mana_state(5, [('A', 3), ('B', 2), ('C', 4)])
        moves = self.spare_mana_moves([10, 11, 12])
        self.assertFalse(rules.is_blunder(state, moves[1], moves))
        self.assertFalse(rules.is_blunder(state, moves[2], moves))
        self.assertTrue(rules.is_blunder(state, moves[3], moves))

    def test_equal_spends_are_both_allowed(self):
        from agent.policy import RulesPolicy
        rules = RulesPolicy({})
        state = self.spare_mana_state(4, [('A', 4), ('B', 2), ('C', 2)])
        moves = self.spare_mana_moves([10, 11, 12])
        for move in moves[1:]:
            self.assertFalse(rules.is_blunder(state, move, moves))

    def test_mulligan_keeps_up_to_two_mana(self):
        from agent.policy import RulesPolicy
        rules = RulesPolicy({'A': {'cost': 1}, 'B': {'cost': 2}, 'C': {'cost': 3}, 'D': {'cost': 8}, 'GAME_005': {'cost': 0}})
        entities = [{'id': i, 'card': c} for i, c in enumerate(['A', 'B', 'C', 'D', 'GAME_005'])]
        self.assertEqual(rules.mulligan(entities, {}), [2, 3])

    def test_turn_cannot_end_with_an_untargeted_hero_power_available(self):
        from agent.policy import RulesPolicy
        rules = RulesPolicy({})
        state = self.spare_mana_state(2, [('X', 5)])
        moves = self.spare_mana_moves([65])
        self.assertTrue(rules.is_blunder(state, moves[0], moves))

    def test_one_lit_reading_is_not_enough(self):
        harness = Harness(game_lines() + option_lines(), after_input=[send_line()])
        answers = iter([True, False])
        harness.agent.screen_ready = lambda: next(answers)
        self.assertEqual(harness.settled_step(), 'animating')
        self.assertEqual(harness.agent.step(), 'animating')
        self.assertEqual(harness.inputs.gestures, [])

    def test_button_that_never_lights_only_delays_play(self):
        harness = Harness(game_lines() + option_lines(), after_input=[send_line()])
        harness.agent.screen_ready = lambda: False
        self.assertEqual(harness.settled_step(), 'animating')
        harness.clock.now += 26
        self.assertEqual(harness.agent.step(), 'acted')

    def test_failed_screen_check_only_delays_play(self):
        harness = Harness(game_lines() + option_lines(), after_input=[send_line()])

        def broken():
            raise ValueError('no frame')
        harness.agent.screen_ready = broken
        self.assertEqual(harness.settled_step(), 'animating')
        harness.clock.now += 26
        self.assertEqual(harness.agent.step(), 'acted')

    def test_new_packet_restarts_the_wait(self):
        harness = Harness(game_lines() + option_lines(), after_input=[send_line()])
        harness.agent.screen_ready = lambda: False
        harness.settled_step()
        harness.clock.now += 20
        harness.pending += option_lines(packet=2)
        harness.agent.step()
        harness.clock.now += 20
        self.assertEqual(harness.agent.step(), 'animating')
        self.assertEqual(harness.inputs.gestures, [])


class GameModeTests(unittest.TestCase):
    def run_in(self, game_type, friend_agreed):
        harness = Harness(game_lines(game_type) + option_lines(), after_input=[send_line()])
        harness.agent.friend_agreed = friend_agreed
        return harness

    def test_friendly_game_needs_the_players_say_so(self):
        harness = self.run_in('GT_VS_FRIEND', False)
        with self.assertRaises(Stop):
            harness.settled_step()
        self.assertEqual(harness.inputs.gestures, [])

    def test_friendly_game_runs_when_agreed(self):
        self.assertEqual(self.run_in('GT_VS_FRIEND', True).settled_step(), 'acted')

    def friend_mode(self, game_type, agreed=True):
        harness = self.run_in(game_type, agreed)
        harness.agent.mode = 'friend'
        return harness

    def test_friend_mode_plays_an_agreed_friendly_game(self):
        self.assertEqual(self.friend_mode('GT_VS_FRIEND').settled_step(), 'acted')

    def test_friend_mode_needs_agreement(self):
        harness = self.friend_mode('GT_VS_FRIEND', agreed=False)
        with self.assertRaisesRegex(Stop, 'friendly'):
            harness.settled_step()
        self.assertEqual(harness.inputs.gestures, [])

    def test_friend_mode_refuses_every_other_game_type(self):
        for game_type in ('GT_VS_AI', 'GT_RANKED', 'GT_CASUAL', 'GT_ARENA', 'GT_TAVERNBRAWL', 'GT_UNKNOWN', None):
            with self.subTest(game_type=game_type):
                harness = self.friend_mode(game_type)
                with self.assertRaisesRegex(Stop, 'friendly'):
                    harness.settled_step()
                self.assertEqual(harness.inputs.gestures, [])

    def both_names(self, *hand):
        """A game whose log names both players, as a friendly game may."""
        rows = game_lines('GT_VS_FRIEND', opponent='Friend#5678')
        for entity_id, card, controller in hand:
            rows += entity(entity_id, card, controller, 'HAND', 'MINION', 1)
        harness = Harness(rows + option_lines(), after_input=[send_line()])
        harness.agent.friend_agreed, harness.agent.mode = True, 'friend'
        return harness

    def test_with_both_names_the_local_player_holds_the_readable_hand(self):
        harness = self.both_names((50, 'CS2_182', 2))
        harness.agent.pump()
        self.assertEqual(harness.agent.power.game.local, 2)
        self.assertEqual(harness.agent.power.local_name, 'Friend#5678')

    def test_the_coin_does_not_identify_the_local_player(self):
        harness = self.both_names((50, 'CS2_182', 1), (51, 'GAME_005', 2), (52, '', 2))
        harness.agent.pump()
        self.assertEqual(harness.agent.power.game.local, 1)

    def test_two_readable_hands_are_refused(self):
        harness = self.both_names((50, 'CS2_182', 1), (51, 'CS2_182', 2))
        with self.assertRaisesRegex(Stop, 'local'):
            harness.settled_step()
        self.assertEqual(harness.inputs.gestures, [])

    def test_no_readable_hand_is_refused(self):
        harness = self.both_names((50, '', 1))  # The fixture's own hand card, hidden here.
        with self.assertRaisesRegex(Stop, 'local'):
            harness.settled_step()
        self.assertEqual(harness.inputs.gestures, [])

    def test_agreement_never_unlocks_other_modes(self):
        for game_type in ('GT_RANKED', 'GT_CASUAL', 'GT_ARENA', 'GT_TAVERNBRAWL', 'GT_UNKNOWN'):
            harness = self.run_in(game_type, True)
            with self.assertRaises(Stop):
                harness.settled_step()
            self.assertEqual(harness.inputs.gestures, [])


class AggressiveTests(unittest.TestCase):
    def setUp(self):
        log = PowerLog()
        for row in game_lines() + option_lines():
            log.feed(row)
        self.state = log.game.packet['state']
        self.moves = candidates_from(log.game.packet)

    def laya(self, aggressive):
        from agent.policy import LayaPolicy

        def loves_trades(state, questions):
            criteria = questions['action']['criteria']
            return {'answers': {'action': {'probabilities': {
                k: (0.97 if 'enemy minion' in v else 0.03 / max(len(criteria) - 1, 1)) for k, v in criteria.items()}}}}
        return LayaPolicy({}, loves_trades, aggressive=aggressive)

    def test_aggressive_laya_hits_face_even_if_it_prefers_a_trade(self):
        self.assertEqual(self.moves[self.laya(True).choose(self.state, self.moves, {})]['target'], 20)

    def test_normal_laya_may_still_trade(self):
        self.assertEqual(self.moves[self.laya(False).choose(self.state, self.moves, {})]['target'], 40)

    def test_aggressive_rules_hit_face_over_a_clean_kill(self):
        from agent.policy import RulesPolicy
        self.assertEqual(self.moves[RulesPolicy({}).choose(self.state, self.moves, {})]['target'], 40)
        self.assertEqual(self.moves[RulesPolicy({}, True).choose(self.state, self.moves, {})]['target'], 20)

    def test_taunt_still_allows_the_forced_trade(self):
        forced = [m for m in self.moves if m['target'] != 20]
        picked = forced[self.laya(True).choose(self.state, forced, {})]
        self.assertEqual(picked['target'], 40)


class SessionTests(unittest.TestCase):
    def test_observer_sees_the_plan_before_input(self):
        harness = Harness(game_lines() + option_lines(), after_input=[send_line()])
        seen = []
        harness.agent.before_input = lambda event: seen.append((event['candidate']['target'], len(harness.inputs.gestures)))
        harness.settled_step()
        self.assertEqual(seen, [(40, 0)])

    def test_state_change_during_a_slow_capture_still_cancels_input(self):
        harness = Harness(game_lines() + option_lines())
        harness.agent.before_input = lambda event: harness.pending.append(
            power('TAG_CHANGE Entity=GameEntity tag=TURN value=4'))
        self.assertEqual(harness.settled_step(), 'state_changed')
        self.assertEqual(harness.inputs.gestures, [])

    def test_failed_capture_does_not_stop_play(self):
        harness = Harness(game_lines() + option_lines(), after_input=[send_line()])

        def broken(event):
            raise OSError('no frame')
        harness.agent.before_input = broken
        self.assertEqual(harness.settled_step(), 'acted')

    def test_focus_wait_returns_once_the_game_has_focus(self):
        from agent.cli import wait_for_focus
        answers = iter([111, 111, 222])

        class User:
            def GetForegroundWindow(self):
                return next(answers)

        class Inputs:
            user = User()
        wait_for_focus(Inputs(), {'hwnd': 222}, sleep=lambda _: None)

    def test_focus_wait_gives_up_without_input(self):
        from agent.cli import wait_for_focus
        clock = Clock()

        class User:
            def GetForegroundWindow(self):
                return 111

        class Inputs:
            user = User()
        with self.assertRaisesRegex(Stop, 'never got focus'):
            wait_for_focus(Inputs(), {'hwnd': 222}, timeout=1, clock=clock.time, sleep=clock.sleep)


class MultiGameTests(unittest.TestCase):
    def test_send_and_next_game_in_one_read_is_still_confirmed(self):
        harness = Harness(game_lines() + option_lines(), after_input=[send_line()] + game_lines())
        self.assertEqual(harness.settled_step(), 'acted')

    def test_new_game_without_a_send_stops_the_agent(self):
        harness = Harness(game_lines() + option_lines(), after_input=game_lines())
        with self.assertRaisesRegex(Stop, 'new game'):
            harness.settled_step()

    def test_choice_id_reused_in_the_next_game_is_still_answered(self):
        choice = [line('DebugPrintEntityChoices', f'id=1 Player={ME} TaskList=1 ChoiceType=MULLIGAN CountMin=0 CountMax=3')]
        for index, entity_id in enumerate((60, 61, 62)):
            choice.append(line('DebugPrintEntityChoices', f'  Entities[{index}]={bracket(entity_id, "HAND")}'))
        chosen = [line('DebugPrintEntitiesChosen', f'id=1 Player={ME} EntitiesCount=3')]
        chosen += [line('DebugPrintEntitiesChosen', f'Entities[{i}]={bracket(e, "HAND")}')
                   for i, e in enumerate((60, 61, 62))]

        class KeepAll(FirstAttack):
            def mulligan(self, entities, cards):
                return []
        harness = Harness(game_lines() + choice, after_input=chosen)
        harness.agent.policy = KeepAll()
        self.assertEqual(harness.settled_step(), 'acted')
        harness.pending += game_lines() + choice
        harness.after_input = chosen
        self.assertEqual(harness.settled_step(), 'acted')
        self.assertEqual(len(harness.inputs.gestures), 2)


class LayaPolicyTests(unittest.TestCase):
    def setUp(self):
        log = PowerLog()
        for row in game_lines() + option_lines():
            log.feed(row)
        self.packet = log.game.packet
        self.candidates = candidates_from(self.packet)
        self.cards = {}

    def policy(self, predict):
        from agent.policy import LayaPolicy
        return LayaPolicy(self.cards, predict)

    def prefers(self, wanted):
        """A fake model that favors one move wherever the order puts it."""
        def predict(state, questions):
            criteria = questions['action']['criteria']
            count = len(criteria)
            found = {k: (0.9 if wanted in v else 0.1 / max(count - 1, 1)) for k, v in criteria.items()}
            return {'answers': {'action': {'probabilities': found}}}
        return predict

    def test_order_averaging_finds_the_same_move_in_any_order(self):
        picked = self.policy(self.prefers('enemy minion')).choose(self.packet['state'], self.candidates, {})
        self.assertEqual(self.candidates[picked]['target'], 40)

    def test_position_biased_model_cannot_win_by_list_slot(self):
        def first_slot(state, questions):
            count = len(questions['action']['criteria'])
            return {'answers': {'action': {'probabilities': {f'c{i}': (0.9 if i == 0 else 0.1 / (count - 1))
                                                             for i in range(count)}}}}
        totals = self.policy(first_slot).rank(self.packet['state'], self.candidates, {})
        # The reversed order alone gives the last candidate one first-slot vote.
        self.assertGreater(totals[-1], 0.9)

    def test_model_failure_falls_back_to_rules(self):
        def broken(state, questions):
            raise RuntimeError('out of memory')
        policy = self.policy(broken)
        self.assertIn(policy.choose(self.packet['state'], self.candidates, {}), range(len(self.candidates)))
        self.assertEqual(policy.fallbacks, 1)

    def test_rules_take_over_on_lethal(self):
        state = self.packet['state']
        state['opponent']['hero']['damage'] = 28  # The 4-attack minion can now finish the game.
        picked = self.policy(self.prefers('End your turn')).choose(state, self.candidates, {})
        self.assertEqual(self.candidates[picked]['target'], 20)

    def test_mulligan_and_choices_stay_with_rules(self):
        policy = self.policy(lambda *_: self.fail('model must not be called'))
        self.assertEqual(policy.mulligan([], {}), [])


def ability_lines():
    """N'Zoth as logged live: playable abilities first, so log order differs from the screen."""
    rows = entity(18, 'BE_017', 1, 'PLAY', 'MINION', 2, ATK=5, HEALTH=7)
    for entity_id, card in ((19, 'BE_017t5'), (20, 'BE_017t4'), (21, 'BE_017t3'), (22, 'BE_017t6')):
        rows += entity(entity_id, card, 1, 'SETASIDE', 'SPELL')
    rows += [line('DebugPrintOptions', 'id=9'),
             line('DebugPrintOptions', '  option 0 type=END_TURN mainEntity= error=INVALID errorParam='),
             line('DebugPrintOptions', f'  option 1 type=POWER mainEntity={bracket(18)} error=NONE errorParam=')]
    for index, (entity_id, card, error) in enumerate(((19, 'BE_017t5', 'NONE'), (21, 'BE_017t3', 'NONE'),
                                                      (20, 'BE_017t4', 'NONE'), (22, 'BE_017t6', 'REQ_X'))):
        rows.append(line('DebugPrintOptions', f'    subOption {index} entity={bracket(entity_id, "SETASIDE", card)} error={error} errorParam='))
        if entity_id == 20:
            rows.append(line('DebugPrintOptions', f'      target 0 entity={bracket(30)} error=NONE errorParam='))
    return rows


class AbilityTests(unittest.TestCase):
    def setUp(self):
        log = PowerLog()
        for row in game_lines() + ability_lines():
            log.feed(row)
        self.packet = log.game.packet
        self.found = {c['sub_card']: c for c in candidates_from(self.packet) if c['sub'] >= 0}

    def test_ability_uses_screen_order_not_log_order(self):
        call = self.found['BE_017t3']
        self.assertEqual(call['sub'], 1)
        plan = geometry.plan_action(self.packet['state'], call)
        self.assertEqual(plan[0][0], 'click')
        self.assertEqual(plan[1][0], 'wait')
        # Call of N'Zoth was the third of four cards in the captured picker.
        self.assertEqual(plan[2], ('click', (1116, 530)))

    def test_targeted_ability_clicks_the_target_last(self):
        plan = geometry.plan_action(self.packet['state'], self.found['BE_017t4'])
        self.assertEqual(plan[2], ('click', (804, 530)))
        self.assertEqual(plan[-1][0], 'click')
        self.assertEqual(plan[-1][1][1], geometry.LOCAL_MINION_Y)

    def test_unavailable_ability_is_never_offered(self):
        self.assertNotIn('BE_017t6', self.found)

    def test_multi_step_ability_is_not_resent_blindly(self):
        harness = Harness(game_lines() + ability_lines())

        class FirstAbility:
            def choose(self, state, candidates, cards=None):
                return next(i for i, c in enumerate(candidates) if c['sub'] >= 0)
        harness.agent.policy = FirstAbility()
        with self.assertRaisesRegex(Stop, '1 attempt'):
            harness.settled_step()
        self.assertEqual(len(harness.inputs.gestures), 2)  # The move once, then only the final cancel.
        self.assertEqual(harness.inputs.gestures[1], [('right_click', geometry.CANCEL_POINT)])

    def test_rules_use_abilities_and_the_model_is_skipped(self):
        from agent.policy import LayaPolicy, RulesPolicy
        candidates = candidates_from(self.packet)
        picked = RulesPolicy({}).choose(self.packet['state'], candidates, {})
        self.assertGreaterEqual(candidates[picked]['sub'], 0)
        policy = LayaPolicy({}, lambda *_: self.fail('model must not rank abilities'))
        self.assertGreaterEqual(candidates[policy.choose(self.packet['state'], candidates, {})]['sub'], 0)


class FakeMenuInput(RecordingInput):
    def __init__(self, on_click=None):
        super().__init__()
        self.on_click = on_click

    def send(self, gestures):
        super().send(gestures)
        if self.on_click and gestures[0][0] == 'click':
            self.on_click(gestures[0][1])


class MenuTests(unittest.TestCase):
    def walker(self, scene, shown, on_click=None):
        from agent.menu import MenuWalker

        class Fake:
            pixels = None

            def refresh(self):
                pass

            def matches(self, name):
                return name in shown
        inputs = FakeMenuInput(on_click)
        clock = Clock()
        lines = [f'x OnSceneLoaded() - prevMode=A currMode={scene}\n']

        def scenes():
            taken, lines[:] = list(lines), []
            return taken
        walker = MenuWalker(scenes, Fake(), inputs, timeout=5.0, clock=clock.time, sleep=clock.sleep, log=lambda *_: None)
        walker.lines = lines
        return walker, inputs

    def clicks(self, inputs):
        return [g[0][1] for g in inputs.gestures if g[0][0] == 'click']

    def test_ranked_scene_gets_no_click_even_if_the_screen_looks_right(self):
        everything = {'hub_buttons', 'hub_bar', 'deck_title', 'deck_choose', 'deck_tile', 'deck_name', 'opp_title',
                      'opp_warrior', 'opp_selected', 'adv_left', 'adv_right', 'adv_expert', 'mode_title', 'mode_adventure'}
        for scene in ('TOURNAMENT', 'BACON', 'DRAFT', 'FRIENDLY', 'TAVERN_BRAWL', 'COLLECTIONMANAGER', 'UNKNOWN'):
            walker, inputs = self.walker(scene, everything)
            with self.assertRaisesRegex(Stop, 'unrecognized'):
                walker.to_game()
            self.assertEqual(self.clicks(inputs), [])

    def test_login_screens_get_no_click_and_are_waited_for(self):
        from agent import menu

        for scene in ('LOGIN', 'STARTUP'):
            walker, inputs = self.walker(scene, {'hub_buttons', 'hub_bar'})
            original = walker.sleep
            waited = []

            def sleep(seconds):
                original(seconds)
                waited.append(seconds)
                if len(waited) == 300:  # 150 seconds, well past the normal 5 second screen timeout here.
                    walker.lines.append(f'x OnSceneLoaded() - prevMode=LOGIN currMode={menu.GAME_SCENE}\n')
            walker.sleep = sleep
            walker.to_game()
            self.assertEqual(self.clicks(inputs), [])

    def test_entrance_is_clicked_once_and_the_route_carries_on(self):
        from agent import menu
        shown = {'entrance_prompt', 'entrance_notice'}

        def on_click(point):
            shown.clear()
            walker.lines.append(f'x OnSceneLoaded() - prevMode=LOGIN currMode={menu.GAME_SCENE}\n')
        walker, inputs = self.walker('LOGIN', shown, on_click)
        walker.to_game()
        self.assertEqual(self.clicks(inputs), [(960, 872)])

    def test_slow_door_is_not_clicked_again_while_it_opens(self):
        from agent import menu
        walker, inputs = self.walker('LOGIN', {'entrance_prompt', 'entrance_notice'},
                                     lambda point: walker.sleep(4.0) or walker.lines.append(
                                         f'x OnSceneLoaded() - prevMode=LOGIN currMode={menu.GAME_SCENE}\n'))
        walker.to_game()
        self.assertEqual(len(self.clicks(inputs)), 1)

    def test_entrance_needs_both_regions(self):
        for shown in ({'entrance_prompt'}, {'entrance_notice'}):
            walker, inputs = self.walker('LOGIN', shown)
            with self.assertRaisesRegex(Stop, 'main menu'):
                walker.to_game()
            self.assertEqual(self.clicks(inputs), [])

    def test_entrance_look_gets_no_click_outside_login(self):
        for scene in ('STARTUP', 'HUB', 'TOURNAMENT'):
            walker, inputs = self.walker(scene, {'entrance_prompt', 'entrance_notice'})
            with self.assertRaisesRegex(Stop, 'main menu|unrecognized'):
                walker.to_game()
            self.assertEqual(self.clicks(inputs), [])

    def test_entrance_that_never_opens_stops(self):
        walker, inputs = self.walker('LOGIN', {'entrance_prompt', 'entrance_notice'})
        with self.assertRaisesRegex(Stop, 'three times'):
            walker.to_game()
        self.assertEqual(len(self.clicks(inputs)), 3)

    def test_a_game_stuck_on_login_stops_in_the_end(self):
        walker, inputs = self.walker('LOGIN', set())
        with self.assertRaisesRegex(Stop, 'main menu'):
            walker.to_game()
        self.assertEqual(self.clicks(inputs), [])

    def test_unknown_screen_gets_no_click(self):
        walker, inputs = self.walker('ADVENTURE', set())
        with self.assertRaisesRegex(Stop, 'unrecognized'):
            walker.to_game()
        self.assertEqual(self.clicks(inputs), [])

    def test_hub_click_needs_the_screen_as_well_as_the_scene(self):
        walker, inputs = self.walker('HUB', {'hub_bar'})
        with self.assertRaisesRegex(Stop, 'unrecognized'):
            walker.to_game()
        self.assertEqual(self.clicks(inputs), [])

    def test_opponent_list_over_the_deck_screen_is_not_read_as_the_deck_screen(self):
        from agent.menu import identify
        shown = {'deck_title', 'deck_choose', 'deck_tile', 'deck_name', 'opp_title'}
        self.assertEqual(identify('ADVENTURE', shown.__contains__)[1], 'opp_pick')

    def test_start_needs_warrior_selected(self):
        from agent.menu import identify
        self.assertEqual(identify('ADVENTURE', {'opp_title', 'opp_warrior'}.__contains__)[1], 'opp_pick')
        self.assertEqual(identify('ADVENTURE', {'opp_title', 'opp_warrior', 'opp_selected'}.__contains__)[1], 'opp_ready')

    def test_deck_start_needs_the_deck_name_on_the_panel(self):
        from agent.menu import identify
        base = {'deck_title', 'deck_choose', 'deck_tile'}
        self.assertEqual(identify('ADVENTURE', base.__contains__)[1], 'deck_pick')
        self.assertEqual(identify('ADVENTURE', (base | {'deck_name'}).__contains__)[1], 'deck_ready')

    def test_walk_from_deck_screen_to_the_game(self):
        from agent import menu
        shown = {'deck_title', 'deck_choose', 'deck_tile', 'deck_name'}

        def on_click(point):
            if point == (1403, 880):
                shown.add('opp_title')
            elif point == (1392, 258):
                shown.update({'opp_warrior', 'opp_selected'})
            elif point == (1420, 865):
                walker.lines.append(f'x OnSceneLoaded() - prevMode=ADVENTURE currMode={menu.GAME_SCENE}\n')
        walker, inputs = self.walker('ADVENTURE', shown, on_click)
        walker.to_game()
        self.assertEqual(self.clicks(inputs), [(1403, 880), (1392, 258), (1420, 865)])

    def test_deck_screen_seen_during_the_slide_gets_no_click(self):
        from agent import menu
        shown = {'deck_title', 'deck_choose', 'deck_tile', 'deck_name'}

        def on_click(point):
            if point == (1403, 880):
                shown.discard('deck_name')  # Mid-slide: the panel is covered, the list has not arrived.
                walker.clock_ref.now += 0.5
            elif point == (1392, 258):
                shown.update({'opp_warrior', 'opp_selected'})
            elif point == (1420, 865):
                walker.lines.append(f'x OnSceneLoaded() - prevMode=ADVENTURE currMode={menu.GAME_SCENE}\n')

        slides = {'left': 3}

        class Clock2(Clock):
            def sleep(self, seconds):
                super().sleep(seconds)
                if 'deck_name' not in shown and 'opp_title' not in shown:
                    slides['left'] -= 1
                    if slides['left'] <= 0:
                        shown.add('opp_title')
        walker, inputs = self.walker('ADVENTURE', shown, on_click)
        clock = Clock2()
        walker.clock, walker.sleep, walker.clock_ref = clock.time, clock.sleep, clock
        walker.to_game()
        self.assertEqual(self.clicks(inputs), [(1403, 880), (1392, 258), (1420, 865)])

    def test_a_click_that_changes_nothing_stops_after_three_tries(self):
        walker, inputs = self.walker('HUB', {'hub_buttons', 'hub_bar'})
        with self.assertRaisesRegex(Stop, 'three times'):
            walker.to_game()
        self.assertEqual(len(self.clicks(inputs)), 3)

    def test_leaving_clicks_only_while_the_game_scene_shows(self):
        from agent import menu

        def on_click(point):
            self.assertEqual(point, menu.CONTINUE)
            if len(self.clicks(inputs)) == 2:
                walker.lines.append('x OnSceneLoaded() - prevMode=GAMEPLAY currMode=ADVENTURE\n')
        walker, inputs = self.walker(menu.GAME_SCENE, set(), on_click)
        walker.leave_game()
        self.assertEqual(len(self.clicks(inputs)), 2)

    def test_leaving_gives_up_rather_than_clicking_forever(self):
        from agent import menu
        walker, inputs = self.walker(menu.GAME_SCENE, set())
        with self.assertRaisesRegex(Stop, 'could not leave'):
            walker.leave_game()

    def test_deck_id_comes_from_the_latest_search(self):
        from agent.menu import latest_deck_id
        lines = ['I 1 Finding Game With Deck:\n', 'I 1 ### a\n', 'I 1 # Deck ID: 111\n', 'I 2 # Deck ID: 999\n',
                 'I 3 Finding Game With Deck:\n', 'I 3 ### b\n', 'I 3 # Deck ID: 222\n', 'I 4 # Deck ID: 888\n']
        self.assertEqual(latest_deck_id(lines), '222')
        self.assertIsNone(latest_deck_id(['I 2 # Deck ID: 999\n']))

    def test_mulligan_waits_for_the_screen(self):
        rows = [line('DebugPrintEntityChoices', f'id=1 Player={ME} TaskList=1 ChoiceType=MULLIGAN CountMin=0 CountMax=3')]
        for index, entity_id in enumerate((60, 61, 62)):
            rows.append(line('DebugPrintEntityChoices', f'  Entities[{index}]={bracket(entity_id, "HAND")}'))
        harness = Harness(game_lines() + rows)
        answers = iter([False, False])
        harness.agent.mulligan_ready = lambda: next(answers)
        self.assertEqual(harness.settled_step(), 'animating')
        self.assertEqual(harness.agent.step(), 'animating')
        self.assertEqual(harness.inputs.gestures, [])

    def test_silent_log_stops_the_game(self):
        harness = Harness(game_lines())
        harness.agent.idle_limit = 5.0
        with self.assertRaisesRegex(Stop, 'silent'):
            harness.agent.run_game()


class ChoiceResendTests(unittest.TestCase):
    def mulligan(self):
        rows = [line('DebugPrintEntityChoices', f'id=1 Player={ME} TaskList=1 ChoiceType=MULLIGAN CountMin=0 CountMax=3')]
        for index, entity_id in enumerate((60, 61, 62)):
            rows.append(line('DebugPrintEntityChoices', f'  Entities[{index}]={bracket(entity_id, "HAND")}'))
        return rows

    def harness(self, replace):
        harness = Harness(game_lines() + self.mulligan())

        class Policy(FirstAttack):
            def mulligan(self, entities, cards):
                return replace
        harness.agent.policy = Policy()
        return harness

    def test_resend_repeats_only_the_confirm_click(self):
        harness = self.harness([60])
        with self.assertRaisesRegex(Stop, '3 attempts'):
            harness.settled_step()
        self.assertEqual(len(harness.inputs.gestures[0]), 2)
        self.assertEqual(harness.inputs.gestures[1], [('click', geometry.MULLIGAN_CONFIRM)])
        self.assertEqual(harness.inputs.gestures[2], [('click', geometry.MULLIGAN_CONFIRM)])

    def test_state_change_blocks_a_choice_resend(self):
        harness = self.harness([])

        def note(event):
            if event['kind'] == 'no_send':
                harness.pending.append(power('TAG_CHANGE Entity=GameEntity tag=TURN value=4'))
        harness.agent.before_input = note
        with self.assertRaisesRegex(Stop, 'changed before input'):
            harness.settled_step()
        self.assertEqual(len(harness.inputs.gestures), 1)


class BlunderTests(unittest.TestCase):
    CARDS = {'SPIKE': {'text': 'Deal 3 damage to a minion.'}, 'BUFF': {'text': 'Give a minion +2/+2.'},
             'STEP': {'text': 'Return a friendly minion to your hand.'}}

    def state(self, attack=4, hand=()):
        log = PowerLog()
        rows = game_lines()
        for entity_id, card, cost in hand:
            rows += entity(entity_id, card, 1, 'HAND', 'SPELL', 2, COST=cost)
        for row in rows:
            log.feed(row)
        state = log.game.snapshot()
        state['you']['minions'][0]['atk'] = attack
        return state

    def rules(self):
        from agent.policy import RulesPolicy
        return RulesPolicy(self.CARDS)

    END = {'kind': 'end_turn', 'option': 0, 'sub': -1, 'target': 0, 'source': None}

    def attack(self, target):
        return {'kind': 'power', 'option': 1, 'sub': -1, 'target': target, 'source': 30}

    def spell(self, source, target):
        return {'kind': 'power', 'option': 2, 'sub': -1, 'target': target, 'source': source}

    def test_damage_spell_on_own_minion_is_a_blunder(self):
        state = self.state(hand=[(70, 'SPIKE', 2)])
        self.assertTrue(self.rules().is_blunder(state, self.spell(70, 30), [self.spell(70, 30)]))
        self.assertFalse(self.rules().is_blunder(state, self.spell(70, 40), [self.spell(70, 40)]))

    def test_friendly_spells_may_target_own_minions(self):
        state = self.state(hand=[(70, 'BUFF', 1), (71, 'STEP', 0)])
        self.assertFalse(self.rules().is_blunder(state, self.spell(70, 30), []))
        self.assertFalse(self.rules().is_blunder(state, self.spell(71, 30), []))

    def test_ending_turn_with_free_face_damage_is_a_blunder(self):
        moves = [self.END, self.attack(20)]
        self.assertTrue(self.rules().is_blunder(self.state(), self.END, moves))

    def test_ending_turn_is_fine_when_only_bad_trades_remain(self):
        state = self.state(attack=1)
        state['opponent']['minions'][0].update(atk=9, health=9)
        moves = [self.END, self.attack(40)]
        self.assertFalse(self.rules().is_blunder(state, self.END, moves))

    def test_ending_turn_is_fine_when_only_a_blunder_remains(self):
        state = self.state(hand=[(70, 'SPIKE', 2)])
        moves = [self.END, self.spell(70, 30)]
        self.assertFalse(self.rules().is_blunder(state, self.END, moves))

    def test_strong_model_preference_can_override_an_end_turn_heuristic(self):
        from agent.policy import LayaPolicy

        def loves_ending(state, questions):
            criteria = questions['action']['criteria']
            return {'answers': {'action': {'probabilities': {
                k: (0.97 if 'End your turn' in v else 0.03 / max(len(criteria) - 1, 1)) for k, v in criteria.items()}}}}
        state = self.state()
        moves = [self.END, self.attack(20), self.attack(40)]
        picked = moves[LayaPolicy(self.CARDS, loves_ending).choose(state, moves, {})]
        self.assertEqual(picked['kind'], 'end_turn')

    def test_model_still_chooses_among_safe_moves(self):
        from agent.policy import LayaPolicy

        def loves_minion_attack(state, questions):
            criteria = questions['action']['criteria']
            return {'answers': {'action': {'probabilities': {
                k: (0.97 if 'enemy minion' in v else 0.03 / max(len(criteria) - 1, 1)) for k, v in criteria.items()}}}}
        moves = [self.END, self.attack(20), self.attack(40)]
        picked = moves[LayaPolicy(self.CARDS, loves_minion_attack).choose(self.state(), moves, {})]
        self.assertEqual(picked['target'], 40)


class ParserTests(unittest.TestCase):
    def read(self, lines):
        log = PowerLog()
        for row in lines:
            log.feed(row)
        return log

    def test_innkeeper_game_finds_the_local_player(self):
        game = self.read(game_lines()).game
        self.assertEqual(game.local, 1)

    def test_power_task_list_is_not_applied_twice(self):
        extra = 'D 10:00:00.0000000 PowerTaskList.DebugPrintPower() -     TAG_CHANGE Entity=30 tag=ATK value=99\n'
        game = self.read(game_lines() + [extra]).game
        self.assertEqual(game.view(30)['atk'], 4)

    def test_opponent_renamed_after_placeholder_still_resolves(self):
        rows = game_lines(opponent='UNKNOWN HUMAN PLAYER')
        rows += [power('TAG_CHANGE Entity=UNKNOWN HUMAN PLAYER tag=RESOURCES value=1'),
                 power('TAG_CHANGE Entity=Rival#99 tag=RESOURCES value=2')]
        log = self.read(rows)
        self.assertEqual(log.malformed, 0)
        self.assertEqual(log.game.number_tag(3, 'RESOURCES'), 2)
        self.assertEqual(log.game.number_tag(2, 'RESOURCES'), 3)

    def test_candidates_skip_rejected_options_and_targets(self):
        rows = game_lines() + [line('DebugPrintOptions', 'id=1'),
            line('DebugPrintOptions', '  option 0 type=END_TURN mainEntity= error=INVALID errorParam='),
            line('DebugPrintOptions', f'  option 1 type=POWER mainEntity={bracket(50, "HAND")} error=REQ_X errorParam='),
            line('DebugPrintOptions', f'  option 2 type=POWER mainEntity={bracket(30)} error=NONE errorParam='),
            line('DebugPrintOptions', f'    target 0 entity={bracket(40, player=2)} error=REQ_Y errorParam='),
            line('DebugPrintOptions', f'    target 1 entity={bracket(20, player=2)} error=NONE errorParam=')]
        found = candidates_from(self.read(rows).game.packet)
        self.assertEqual([(c['option'], c['target']) for c in found], [(0, 0), (2, 20)])

    def test_tail_holds_back_a_partial_line(self):
        with tempfile.TemporaryDirectory() as folder:
            target = os.path.join(folder, 'Power.log')
            with open(target, 'wb') as out:
                out.write('complete\npart'.encode())
            tail = Tail(target)
            self.assertEqual(tail(), ['complete\n'])
            with open(target, 'ab') as out:
                out.write('ial\n'.encode())
            self.assertEqual(tail(), ['partial\n'])


class GeometryTests(unittest.TestCase):
    def state(self):
        game = None
        log = PowerLog()
        for row in game_lines():
            log.feed(row)
        game = log.game
        return game.snapshot()

    def test_measured_positions_match_the_capture(self):
        self.assertEqual(geometry.plan_action(self.state(), {'kind': 'end_turn'}), [('click', geometry.END_TURN)])

    def test_attack_drags_from_source_to_target(self):
        plan = geometry.plan_action(self.state(), {'kind': 'power', 'source': 30, 'target': 40, 'sub': -1})
        self.assertEqual(plan, [('drag', (965, geometry.LOCAL_MINION_Y), (965, geometry.ENEMY_MINION_Y))])

    def test_six_card_hand_lands_on_cards_measured_in_the_capture(self):
        # Horizontal extent of each visible card face in .data/game-window.png.
        measured = [(620, 730), (725, 815), (815, 910), (910, 1005), (1005, 1100), (1100, 1215)]
        for index, (left, right) in enumerate(measured):
            x, y = geometry.hand_point(index, 6)
            self.assertTrue(left <= x <= right, f'card {index} at {x}')
            self.assertEqual(y, geometry.HAND_Y)

    def test_ten_card_hand_lands_on_cards_measured_live(self):
        # Visible strip of each card at y=1030 in .data/live/20261104-150635/006.png.
        measured = [(610, 666), (666, 727), (727, 783), (783, 835), (835, 883),
                    (883, 935), (935, 987), (987, 1044), (1044, 1104), (1104, 1235)]
        for index, (left, right) in enumerate(measured):
            x, y = geometry.hand_point(index, 10)
            self.assertTrue(left < x < right, f'card {index} at {x}')
            self.assertEqual(y, geometry.LARGE_HAND_Y)

    def test_only_a_leftmost_card_in_a_wider_hand_is_nudged_left(self):
        self.assertEqual(geometry.hand_point(0, 6)[0], geometry.row_x(0, 6, 100, geometry.HAND_CENTER_X) - 15)
        self.assertEqual(geometry.hand_point(1, 6)[0], geometry.row_x(1, 6, 100, geometry.HAND_CENTER_X))
        self.assertEqual(geometry.hand_point(0, 4)[0], geometry.row_x(0, 4, 140, geometry.HAND_CENTER_X))
        self.assertEqual(geometry.hand_point(0, 9)[0], geometry.row_x(0, 9, 60, 884) - 15)

    def test_unknown_entity_is_refused_not_guessed(self):
        with self.assertRaises(geometry.GeometryError):
            geometry.plan_action(self.state(), {'kind': 'power', 'source': 999, 'target': 0, 'sub': -1})

    def test_only_16_by_9_windows_are_supported(self):
        with self.assertRaises(geometry.GeometryError):
            geometry.scale((10, 10), {'width': 1024, 'height': 768})
        self.assertEqual(geometry.scale((1920, 1080), {'width': 1280, 'height': 720, 'left': 5, 'top': 7}), (1285, 727))

    def test_input_coordinates_stay_on_the_desktop(self):
        self.assertEqual(to_absolute((0, 0), (0, 0, 1920, 1080)), (0, 0))
        self.assertEqual(to_absolute((1919, 1079), (0, 0, 1920, 1080)), (65535, 65535))
        with self.assertRaises(geometry.GeometryError):
            to_absolute((1920, 0), (0, 0, 1920, 1080))
        self.assertEqual(path((0, 0), (12, 24))[-1], (12, 24))


@unittest.skipUnless(glob.glob('.data/logs/*/Power.log'), 'archived logs are not available')
class RecordedGameTests(unittest.TestCase):
    def test_every_recorded_decision_has_a_plannable_choice(self):
        from agent.replay import check
        stats = check(sorted(glob.glob('.data/logs/*/Power.log')))['stats']
        self.assertEqual(stats['games'], 17)
        self.assertEqual(stats['decisions'], 714)
        self.assertEqual(stats['malformed'], 0)
        self.assertEqual(stats['send_with_no_state_change_after_packet'], 714)


if __name__ == '__main__':
    unittest.main()
