"""Standard deck, menu, tactics and restart regressions. No live input."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent import cannon, cli, menu_profile
from agent.deck_profile import STANDARD_WARRIOR, decode, load_profile
from agent.loop import Stop
from agent.menu import STANDARD_SCREENS, Regions, MenuWalker, identify
from agent.policy import RulesPolicy, LayaPolicy, load_cards
from agent.test_agent import MenuTests, game_lines, line, option_lines, send_line, Harness
from agent.test_restart import LoopRun
from agent.test_agent import Clock
from agent.screen import encode_png


class StandardTests(unittest.TestCase):
    def test_deck_identity_and_metadata(self):
        profile = load_profile(STANDARD_WARRIOR, 'standard')
        mode, hero, cards = decode(profile['deck_code'])
        self.assertEqual((mode, hero, sum(cards.values()), len(cards)), ('standard', 7, 30, 18))
        metadata = load_cards()
        for card in profile['cards']:
            self.assertEqual(metadata[card['id']]['dbfId'], card['dbfId'])
        with self.assertRaises(ValueError):
            load_profile(STANDARD_WARRIOR, 'wild')

    def test_standard_action_and_guards(self):
        for game_type, fmt, allowed in [('GT_RANKED', 'FT_STANDARD', True),
                                       ('GT_RANKED', 'FT_WILD', False), ('GT_CASUAL', 'FT_STANDARD', False),
                                       ('GT_VS_AI', 'FT_STANDARD', False), ('GT_RANKED', 'FT_UNKNOWN', False)]:
            h = Harness(game_lines(game_type) + [line('DebugPrintGame', f'FormatType={fmt}')] + option_lines(),
                        after_input=[send_line()])
            h.agent.mode = 'standard'
            if allowed:
                self.assertEqual(h.settled_step(), 'acted')
                h.agent.power.game.local = None
                with self.assertRaisesRegex(Stop, 'local'):
                    h.agent.check_allowed(h.agent.power.game)
            else:
                with self.assertRaisesRegex(Stop, 'Standard'):
                    h.settled_step()
                self.assertEqual(h.inputs.gestures, [])

    def test_route_changes_format_selects_deck_then_queues(self):
        helper = MenuTests()
        shown = {'constructed_choose'}
        steps = iter([((1402, 55), {'format_wild', 'format_standard'}),
                      ((950, 420), {'standard_title', 'constructed_choose', 'standard_deck_tile'}),
                      ((720, 510), {'standard_title', 'constructed_choose', 'standard_deck_tile',
                                    'standard_deck_name', 'standard_start'}), ((1400, 890), set())])
        def click(point):
            expected, next_screen = next(steps)
            self.assertEqual(point, expected)
            shown.clear()
            shown.update(next_screen)
            if not shown:
                walker.lines.append('x OnSceneLoaded() - prevMode=TOURNAMENT currMode=GAMEPLAY\n')
        original, inputs = helper.walker('TOURNAMENT', shown, click)
        walker = MenuWalker(original.scenes, original.regions, inputs, mode='standard', deck_click=(720, 510),
                            clock=original.clock, sleep=original.sleep, log=lambda *_: None)
        walker.lines = original.lines
        walker.to_game()
        self.assertEqual(len(helper.clicks(inputs)), 4)
        self.assertIsNone(identify('DRAFT', shown.__contains__, STANDARD_SCREENS))

    def test_missing_reference_stops(self):
        with self.assertRaisesRegex(Stop, 'calibrated'):
            Regions(None, refs={}).matches('standard_title')

    def test_calibration_roundtrip_binding_and_invalid_signature(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / 'ready.png'
            image.write_bytes(encode_png(bytes([20, 30, 40, 255]) * (1920 * 1080), 1920, 1080))
            profile = menu_profile.calibrate(image, '123', (383, 282, 465, 309), (480, 280))
            path = Path(folder) / 'menu.json'
            path.write_text(json.dumps(profile), encoding='utf-8')
            self.assertEqual(menu_profile.load(path, 'standard', '123')['deck_click'], [480, 280])
            for mode, deck in [('wild', '123'), ('standard', '456')]:
                with self.assertRaises(ValueError):
                    menu_profile.load(path, mode, deck)
            profile['regions']['standard_title']['signature'] = []
            path.write_text(json.dumps(profile), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'signature'):
                menu_profile.load(path, 'standard', '123')

    def test_reopened_log_waits_for_new_session_or_stops(self):
        with tempfile.TemporaryDirectory() as folder:
            previous = Path(folder) / 'old/Power.log'
            fresh = Path(folder) / 'new/Power.log'
            fresh.parent.mkdir()
            fresh.touch()
            clock = Clock()
            with patch.object(cli, 'current_log', side_effect=[previous, previous, fresh]):
                self.assertEqual(cli.reopened_log(previous, lambda: False, clock=clock.time, sleep=clock.sleep), fresh)
            with patch.object(cli, 'current_log', return_value=previous):
                with self.assertRaisesRegex(Stop, 'new log session'):
                    cli.reopened_log(previous, lambda: False, timeout=1, clock=clock.time, sleep=clock.sleep)
            with self.assertRaisesRegex(Stop, 'player'):
                cli.reopened_log(previous, lambda: True)

    def test_mulligan_for_both_policies_and_disabled_tactics(self):
        cards = load_cards()
        entities = [{'id': i, 'card': card} for i, card in enumerate(
            ['CAP_107', 'CORE_REV_990', 'CATA_585', 'JAIL_384', 'GAME_005'])]
        profile = load_profile(STANDARD_WARRIOR, 'standard')
        for policy in [RulesPolicy(cards, tactics=True), LayaPolicy(cards, None, tactics=True)]:
            policy.deck_profile = profile
            if hasattr(policy, 'rules'):
                policy.rules.deck_profile = profile
            self.assertEqual(policy.mulligan(entities, {}), [2, 3])
        self.assertEqual(cannon.mulligan([{'id': 1, 'card': 'CORE_REV_990'}], {}, cards), [1])

    def test_ranked_restarts_keep_mode_fresh_window_and_log(self):
        for mode in ('wild', 'standard'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                run = LoopRun(folder, 14, [5, 6, 7])
                run.args.mode = mode
                run.args.menu_profile = 'calibrated.json'
                profile = {'regions': {}, 'deck_click': [480, 280]}
                with patch('agent.menu_profile.load', return_value=profile):
                    summary = run.run()
                self.assertEqual((summary['games'], summary['mode'], summary['stopped']), (14, mode, None))
                self.assertGreaterEqual(summary['restarts'], 1)
                self.assertGreater(len({hwnd for hwnd, _ in run.sent}), 1)
                self.assertEqual(len({str(t.path) for t in run.walker_logs}), summary['restarts'] + 1)

    def test_ranked_failures_preserve_results_and_stop_input(self):
        for mode in ('wild', 'standard'):
            for failure in ('close', 'esc', 'deck'):
                with self.subTest(mode=mode, failure=failure), tempfile.TemporaryDirectory() as folder:
                    run = LoopRun(folder, 3, [1])
                    run.args.mode = mode
                    run.args.menu_profile = 'calibrated.json'
                    if failure == 'close':
                        run.close_error = 'close failed'
                    elif failure == 'esc':
                        run.esc_after = 1
                    else:
                        run.deck = 'WRONG'
                    with patch('agent.menu_profile.load', return_value={'regions': {}, 'deck_click': [480, 280]}):
                        with self.assertRaises(SystemExit):
                            run.run()
                    summary = json.loads(next(Path(folder).glob('.data/live/loop-*/summary.json')).read_text(encoding='utf-8'))
                    self.assertEqual(summary['games'], 0 if failure == 'deck' else 1)
                    self.assertIsNotNone(summary['stopped'])
                    self.assertNotIn('reopen', run.events)
                    if failure == 'deck':
                        self.assertEqual(run.sent, [])


def entity(card, kind='MINION', **kw):
    return dict(id=kw.pop('id', 1), card=card, type=kind, cost=kw.pop('cost', 1),
                atk=kw.pop('atk', 1), health=kw.pop('health', 3), damage=kw.pop('damage', 0),
                armor=0, keywords=kw.pop('keywords', []), **kw)


class CannonTests(unittest.TestCase):
    def state(self):
        return {'you': {'hero': entity('HERO_01', 'HERO', id=10), 'hero_power': None, 'minions': [], 'hand': [], 'mana': 4,
                        'weapon': entity('CAP_103', 'WEAPON', atk=2)},
                'opponent': {'hero': entity('HERO_02', 'HERO', id=20), 'hero_power': None, 'weapon': None, 'minions': []}}

    def move(self, source, target=None):
        return dict(source=source, target=target, kind='power', sub=-1)

    def test_weapon_attack_precedes_replacement_only_when_offered(self):
        state = self.state()
        state['you']['hand'] = [entity('BE_558', 'WEAPON', id=30)]
        moves = [self.move(30), self.move(10, 20)]
        self.assertEqual(cannon.forced_move(state, moves, {})[0], 1)
        self.assertIsNone(cannon.forced_move(state, moves[:1], {}))

    def test_removal_draw_and_location_filters(self):
        state = self.state()
        state['you']['hand'] = [entity('CATA_585', 'SPELL', id=30), entity('CAP_102', 'SPELL', id=31)]
        state['you']['minions'] = [entity('CORE_REV_990', 'LOCATION', id=40), entity('FIR_929', id=41, health=1)]
        state['opponent']['minions'] = [entity('OTHER', id=50)]
        moves = [self.move(30, 41), self.move(30, 50), self.move(40, 41), self.move(31)]
        self.assertEqual(cannon.allowed(state, moves, {}), [1, 3])
        state['you']['hand'] += [entity('OTHER', id=i) for i in range(60, 68)]
        self.assertEqual(cannon.allowed(state, moves, {}), [1])

    def test_policy_integration_and_no_tactics(self):
        state = self.state()
        state['you']['hand'] = [entity('CAP_103', 'WEAPON', id=30, cost=3)]
        moves = [self.move(30), self.move(10, 20)]
        profile = load_profile(STANDARD_WARRIOR, 'standard')
        rules = RulesPolicy(load_cards(), tactics=True)
        rules.deck_profile = profile
        self.assertEqual(rules.choose(state, moves), 1)
        model = LayaPolicy(load_cards(), None, tactics=True)
        model.rules.deck_profile = profile
        self.assertEqual(model.choose(state, moves), 1)
        rules.tactics = False
        self.assertEqual(rules.choose(state, moves), 0)

    def test_full_board_and_mana_filters(self):
        state = self.state()
        state['you']['minions'] = [entity('OTHER', id=i) for i in range(60, 67)]
        state['you']['hand'] = [entity('CAP_106', id=30, cost=5)]
        self.assertEqual(cannon.allowed(state, [self.move(30), self.move(10, 20)], {}), [1])


if __name__ == '__main__':
    unittest.main()
