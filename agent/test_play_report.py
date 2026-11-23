import json
import tempfile
import unittest
from pathlib import Path

from agent.cli import SessionRecord
from agent.play_report import run_report, summary
from agent.test_fast_play import CARDS, END, attack, card, state


def option(turn, current, move, options=5):
    return {'kind': 'option', 'turn': turn, 'state': current, 'candidate': move, 'options': options}


class PlayReportTests(unittest.TestCase):
    def report(self, rows, won=True):
        with tempfile.TemporaryDirectory() as folder:
            game = Path(folder) / '001'
            game.mkdir()
            with open(game / 'moves.jsonl', 'w', encoding='utf-8') as out:
                for row in rows:
                    out.write(json.dumps(row) + '\n')
            outcome = {'result': {'won': won}, 'planned_decisions': {'tactics:no_wasted_attack': 2}}
            (game / 'outcome.json').write_text(json.dumps(outcome), encoding='utf-8')
            return run_report(Path(folder), CARDS)

    def test_wrong_cards_count_by_hand_position(self):
        hand = [card(20, 'OTHER_2'), card(21, 'OTHER_2')]
        wrong = {'kind': 'recovery', 'recovery': 'wrong_action', 'detail': ''}
        rows = [option(1, state(hand), {'source': 20, 'target': 0, 'kind': 'power'}), wrong,
                option(1, state(hand), {'source': 21, 'target': 0, 'kind': 'power'})]
        game = self.report(rows)[0]
        self.assertEqual((game['leftmost_plays'], game['leftmost_wrong'], game['other_plays'], game['other_wrong']), (1, 1, 1, 0))

    def test_a_wasted_attack_counts_once_even_when_retried(self):
        enemy = [card(40, 'CORE_EX1_603', atk=2, health=3)]
        current = state((), [card(10, 'OTHER_2')], enemy)
        rows = [option(5, current, attack(10, 40)), option(5, current, attack(10, 40)), option(5, current, END)]
        self.assertEqual(self.report(rows)[0]['wasted_attacks'], 1)

    def test_a_target_killed_later_that_turn_is_not_wasted(self):
        enemy = [card(40, 'CORE_EX1_603', atk=2, health=3)]
        rows = [option(5, state((), [card(10, 'OTHER_2')], enemy), attack(10, 40)), option(5, state(), END)]
        self.assertEqual(self.report(rows)[0]['wasted_attacks'], 0)

    def test_held_coin_counts_each_turn_once(self):
        current = state([card(40, 'GAME_005', 'SPELL', cost=0), card(42, 'OTHER_2')], mana=0)
        rows = [option(2, current, END), option(2, current, END), option(4, current, END)]
        self.assertEqual(self.report(rows)[0]['coin_held_turns'], 2)

    def test_a_forced_end_of_turn_is_not_counted_as_holding_the_coin(self):
        current = state([card(42, 'OTHER_2')], mana=0)
        self.assertEqual(self.report([option(2, current, END, options=1)])[0]['coin_held_turns'], 0)

    def test_summary_shows_the_record_and_each_count(self):
        rows = [option(1, state(), END), {'kind': 'no_send'}]
        text = summary(self.report(rows) + self.report([option(18, state(), END)], won=False))
        self.assertIn('record 1-1 (50%)', text)
        self.assertIn('Going first 1-0, going second 0-1, past turn 15 0-1', text)
        self.assertIn('Drags the game did not take: 1', text)
        self.assertIn('wasted attack stopped 4', text)

    def test_a_game_with_no_moves_is_left_out(self):
        self.assertEqual(self.report([{'kind': 'no_send'}]), [])


class WrongCardFrameTests(unittest.TestCase):
    class Screen:
        def __init__(self):
            self.saved = []

        def save(self, path):
            self.saved.append(Path(path).name)

    def test_a_wrong_card_keeps_a_frame_and_a_normal_move_does_not(self):
        screen = self.Screen()
        with tempfile.TemporaryDirectory() as folder:
            record = SessionRecord(folder, 'missing.log', screen)
            record({'kind': 'option'})
            record({'kind': 'recovery', 'recovery': 'dropped_move'})
            record({'kind': 'recovery', 'recovery': 'wrong_action'})
        self.assertEqual(screen.saved, ['003.png'])


if __name__ == '__main__':
    unittest.main()
