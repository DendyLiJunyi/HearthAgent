from pathlib import Path
import unittest
from prepare_attack_evidence import prepare
from test_audit_attacks import SEND, START, END
from ui_attack_result import assess_attack


class FrozenAttackEvidenceTests(unittest.TestCase):
    def test_real_parser_snapshots_and_exports_agree(self):
        root = Path(__file__).resolve().parents[1]
        binary = root / 'target/validation/debug/hearth-agent.exe'
        self.assertTrue(binary.exists(), 'build the offline parser before running integration tests')
        before = (root / 'fixtures/wild-rogue-attacks.log').read_bytes()
        for suffix, expected in ((SEND + START + END, 'matching_attack_block_closed'),
                                 (SEND + START, 'attack_block_incomplete')):
            report = prepare(before, before + suffix.encode(), binary)
            result = assess_attack(report['before'], report['after'],
                                   {'source': 10, 'target': 20}, report['attack_evidence'])
            self.assertEqual(result['status'], expected)
            self.assertFalse(report['game_input_sent'])

    def test_invalid_prefixes_rejected_before_parser_launch(self):
        for old, new in ((b'x\n', b'y\n'), (b'x', b'xx\n'), (b'x\n', b'x\ny')):
            with self.assertRaises(ValueError): prepare(old, new, 'nonexistent')


if __name__ == '__main__': unittest.main()
