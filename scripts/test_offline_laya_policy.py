import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from offline_laya_policy import LayaAdvicePolicy
from test_spell_workflow import spell_fixture


class OfflinePolicyTests(unittest.TestCase):
    def invoke(self, status='advice', change=None):
        observation = spell_fixture()['observation']
        def runner(command, **kwargs):
            payload = json.loads(Path(command[2]).read_text())
            self.assertFalse(payload['snapshot']['complete'])
            report = {'source': 'saved_observation_advice', 'actionable': False, 'game_input_sent': False,
                      'session_id': observation['snapshot']['session_id'], 'revision': observation['snapshot']['revision'],
                      'status': status, 'candidate_id': observation['candidates'][0]['id']}
            if change: report.update(change)
            return SimpleNamespace(stdout=json.dumps(report).encode())
        return LayaAdvicePolicy(runner=runner)(observation)

    def test_advice_is_bound_and_abstention_has_no_fallback(self):
        self.assertEqual(self.invoke()['candidate_id'], 'play-10-20')
        self.assertIsNone(self.invoke(status='no_advice'))

    def test_changed_identity_unknown_candidate_and_execution_claim_are_refused(self):
        for change in [{'revision': 999}, {'candidate_id': 'unknown'}, {'actionable': True}]:
            with self.assertRaises(ValueError): self.invoke(change=change)


if __name__ == '__main__': unittest.main()
