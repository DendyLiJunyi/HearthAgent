import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from observe_spell import LogObserver


class LogObserverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.log = self.root / 'Hearthstone_2026_10_28_14_28_58' / 'Power.log'
        self.log.parent.mkdir()
        self.log.write_bytes(b'first\n')
        self.captured = []
        def runner(command, **kwargs):
            self.captured.append(Path(command[2]).read_bytes())
            return SimpleNamespace(stdout=json.dumps({'source': 'offline_replay', 'protocol_version': 1,
                                                       'game_number': 1}).encode())
        self.observer = LogObserver(self.log, self.root / 'unused.exe', runner=runner)

    def test_append_uses_frozen_prefix_and_preserves_identity(self):
        session, row = self.observer(2)
        self.assertEqual(session, self.log.parent.name)
        with self.log.open('ab') as output: output.write(b'second\n')
        self.observer(2)
        self.assertEqual(self.captured, [b'first\n', b'first\nsecond\n'])
        self.assertEqual(row['game_number'], 1)

    def test_truncation_and_same_length_rewrite_latch_failure(self):
        for data in [b'x', b'other\n']:
            self.log.write_bytes(b'first\n')
            observer = LogObserver(self.log, self.root / 'unused.exe', runner=self.observer.runner)
            observer(2)
            self.log.write_bytes(data)
            with self.assertRaises(RuntimeError): observer(2)
            self.log.write_bytes(b'first\n')
            with self.assertRaises(RuntimeError): observer(2)

    def test_new_menu_session_invalidates_old_log(self):
        self.observer(2)
        (self.root / 'Hearthstone_2026_10_29_00_00_00').mkdir()
        self.assertEqual(self.observer(2), (None, None))
        with self.assertRaises(RuntimeError): self.observer(2)

    def test_rewrite_during_replay_and_late_result_are_refused(self):
        original = self.observer.runner
        def rewrite(command, **kwargs):
            result = original(command, **kwargs)
            self.log.write_bytes(b'other\n')
            return result
        self.observer.runner = rewrite
        with self.assertRaises(RuntimeError): self.observer(2)
        self.log.write_bytes(b'first\n')
        ticks = iter([0, 0, 3])
        observer = LogObserver(self.log, self.root / 'unused.exe', runner=original, clock=lambda: next(ticks))
        with self.assertRaises(TimeoutError): observer(2)

    def test_real_binary_can_read_synthetic_fixture(self):
        root = Path(__file__).resolve().parents[1]
        binary = root / 'target/validation/debug/hearth-agent.exe'
        if not binary.exists(): self.skipTest('build Rust binary first')
        self.log.write_bytes((root / 'fixtures/wild-rogue-attacks.log').read_bytes())
        session, row = LogObserver(self.log, binary)(5)
        self.assertEqual(session, self.log.parent.name)
        self.assertIn('card_play_preview', row['game'])


if __name__ == '__main__': unittest.main()
