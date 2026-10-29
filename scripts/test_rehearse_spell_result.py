import copy
from pathlib import Path
import tempfile
import unittest
from test_spell_workflow import spell_fixture
from test_ui_spell_result import observations
from rehearse_spell_result import run


def bundle():
    inputs = spell_fixture()
    before, after = observations()
    before.update({k: inputs['observation']['snapshot'][k] for k in ('session_id', 'game_number', 'revision')})
    before['game']['board'] = copy.deepcopy(inputs['observation']['board'])
    before['game']['board']['invalid_fields'] = 0
    before['game']['card_play_preview']['candidates'][0].update(id=inputs['candidate_id'])
    after['session_id'] = before['session_id']
    after['game']['board']['players'][0]['graveyard'][0]['card_id'] = 'REV_939'
    return inputs, before, after


class SpellEvidenceRehearsalTests(unittest.TestCase):
    def test_recording_and_evidence_persist_without_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run(*bundle(), Path(directory) / 'attempt.json')
        self.assertEqual(result['receipt']['status'], 'submission_and_source_graveyard_observed')
        self.assertEqual(len(result['recorded_gestures']), 1)
        self.assertFalse(result['receipt']['execution_confirmed'])
        self.assertFalse(result['game_input_sent'])

    def test_unrelated_baseline_rejected_before_receipt(self):
        for change in ('revision', 'card', 'target'):
            inputs, before, after = bundle()
            if change == 'revision': before['revision'] += 1
            elif change == 'card': before['game']['board']['players'][0]['hand'][0]['card_id'] = 'OTHER'
            else: before['game']['card_play_preview']['candidates'][0]['action']['PlayCard']['target'] = 99
            with tempfile.TemporaryDirectory() as directory:
                receipt = Path(directory) / 'attempt.json'
                with self.assertRaises(ValueError): run(inputs, before, after, receipt)
                self.assertFalse(receipt.exists())

    def test_partial_batch_and_changed_session_cannot_report_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            inputs, before, after = bundle()
            result = run(inputs, before, after, Path(directory) / 'partial.json', inserted_events=2)
            self.assertNotIn('evidence', result['receipt'])
            after['session_id'] = 'other'
            result = run(inputs, before, after, Path(directory) / 'session.json')
            self.assertEqual(result['receipt']['status'], 'session_changed')


if __name__ == '__main__': unittest.main()
