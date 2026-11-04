import json
import tempfile
import unittest
from pathlib import Path

from agent.learning import collect, corrected_rows, review_session
from agent.policy import LayaPolicy, RulesPolicy
from agent.power import PowerLog, candidates_from
from agent.test_agent import ME, game_lines, option_lines, power, send_line


class MulliganLessonsTests(unittest.TestCase):
    def test_patches_is_returned_by_both_policies_even_at_one_mana(self):
        cards = {'CFM_637': {'cost': 1}, 'OTHER': {'cost': 1}, 'BIG': {'cost': 8}}
        entities = [{'id': 1, 'card': 'CFM_637'}, {'id': 2, 'card': 'OTHER'}, {'id': 3, 'card': 'BIG'}]
        for policy in (RulesPolicy(cards), LayaPolicy(cards, None)):
            self.assertEqual(policy.mulligan(entities, {}), [1, 3])

    def test_patches_identity_comes_from_card_map_when_entity_is_hidden(self):
        self.assertEqual(RulesPolicy({}).mulligan([{'id': 9}], {'9': 'CFM_637'}), [9])
        self.assertEqual(RulesPolicy({}).mulligan([{'id': 9, 'card': 'CORE_CFM_637'}], {}), [9])

    def test_both_patches_copies_are_returned_but_the_coin_is_not(self):
        entities = [{'id': 1, 'card': 'CFM_637'}, {'id': 2, 'card': 'CFM_637'}, {'id': 3, 'card': 'GAME_005'}]
        self.assertEqual(RulesPolicy({}).mulligan(entities, {}), [1, 2])


class MatchLearningTests(unittest.TestCase):
    def session(self, folder, *, stopped=False, recorded=True, sent=True):
        folder.mkdir(parents=True, exist_ok=True)
        lines = game_lines() + option_lines()
        log = PowerLog()
        for row in lines:
            log.feed(row)
        packet = log.game.packet
        candidate = next(c for c in candidates_from(packet) if c['target'] == 40)
        event = {'kind': 'option', 'packet': 1, 'candidate': candidate, 'state': packet['state']}
        if sent:
            lines += [send_line()]
        lines += [power(f'TAG_CHANGE Entity={ME} tag=PLAYSTATE value=LOST')]
        (folder / 'Power.log').write_text(''.join(lines), encoding='utf-8')
        outcome = {'stopped': 'no SendOption'} if stopped else {'result': {'won': False}}
        (folder / 'outcome.json').write_text(json.dumps(outcome), encoding='utf-8')
        (folder / 'moves.jsonl').write_text(json.dumps(event) + '\n' if recorded else '', encoding='utf-8')

    def test_stopped_or_unconfirmed_or_unrecorded_moves_are_not_training_cases(self):
        for options in ({'stopped': True}, {'sent': False}, {'recorded': False}):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as tmp:
                self.session(Path(tmp), **options)
                self.assertEqual(review_session(tmp, {})['cases'], [])

    def test_copied_games_deduplicate_and_loss_does_not_create_gold(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('first', 'copy'):
                self.session(root / name)
            summary = collect(root, root / 'lessons', {})
            self.assertEqual(summary['cases'], 1)
            self.assertEqual(corrected_rows(root / 'lessons/cases.jsonl', root / 'lessons/labels.json', {}), [])

    def test_labels_require_valid_candidate_and_unchanged_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.session(root / 'session')
            collect(root / 'session', root / 'lessons', {})
            path = root / 'lessons/cases.jsonl'
            case = json.loads(path.read_text(encoding='utf-8'))
            labels = root / 'lessons/labels.json'
            label = {'id': case['id'], 'corrected': 0, 'reason': 'test correction', 'reviewer': 'test'}
            labels.write_text(json.dumps({'schema': 1, 'labels': [label]}), encoding='utf-8')
            self.assertEqual(len(corrected_rows(path, labels, {})), 1)
            label['corrected'] = 999
            labels.write_text(json.dumps({'schema': 1, 'labels': [label]}), encoding='utf-8')
            with self.assertRaises(ValueError):
                corrected_rows(path, labels, {})
            label['corrected'] = 0
            labels.write_text(json.dumps({'schema': 1, 'labels': [label]}), encoding='utf-8')
            case['row']['state']['turn'] = 100
            path.write_text(json.dumps(case) + '\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'changed'):
                corrected_rows(path, labels, {})


if __name__ == '__main__':
    unittest.main()
