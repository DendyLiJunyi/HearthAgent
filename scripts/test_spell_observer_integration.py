from pathlib import Path
import unittest
from smoke_spell_observer import smoke


class SpellObserverIntegrationTests(unittest.TestCase):
    def test_real_replay_drives_matching_conflicting_and_unfinished_evidence(self):
        binary = Path(__file__).resolve().parents[1] / 'target/validation/debug/hearth-agent.exe'
        if not binary.exists(): self.skipTest('build the Rust binary first')
        report = smoke(binary)
        self.assertEqual(len(report['scenarios']), 3)
        self.assertFalse(report['game_input_sent'])
        for row in report['scenarios']:
            self.assertFalse(row['result']['execution_confirmed'])
            self.assertFalse(row['result']['automatic_retry_allowed'])


if __name__ == '__main__': unittest.main()
