import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_ui_baseline import baseline
from ui_result import assess_end_turn, wait_for_evidence


def observations():
    before = baseline()
    before['game']['board']['players'] = [{'player_id': 1}, {'player_id': 2}]
    before['game']['logged_options']['submissions_seen'] = 2
    before['game']['logged_options']['latest']['id'] = 10
    after = copy.deepcopy(before)
    after['game']['board'].update(turn=5, active_player=2)
    after['game']['logged_options']['submissions_seen'] = 3
    after['game']['logged_options']['latest_submission'] = {
        'selection': {'option': 0, 'sub_option': -1, 'target': 0, 'position': 0},
        'correlation': {'packet_id': 10, 'packet_was_stale': False,
            'option_kind': 'END_TURN', 'option_seen': True,
            'packet_malformed_records': 0, 'packet_unsupported_records': 0}}
    return before, after


class FakeClock:
    def __init__(self): self.now = 0
    def clock(self): return self.now
    def sleep(self, seconds): self.now += seconds


class UiResultTests(unittest.TestCase):
    def test_real_rust_replay_schema_matches_post_input_checker(self):
        root = Path(__file__).resolve().parents[1]
        binary = root / 'target/validation/debug/hearth-agent.exe'
        if not binary.exists():
            self.skipTest('build the offline Rust binary for the schema integration test')
        text = (root / 'fixtures/wild-rogue-attacks.log').read_text(encoding='utf-8')
        suffix = 'D 0 GameState.SendOption() - selectedOption=0 selectedSubOption=-1 selectedTarget=0 selectedPosition=0\n'
        suffix += ''.join(f'D 0 GameState.DebugPrintPower() - {line}\n' for line in [
            'TAG_CHANGE Entity=1 tag=STEP value=MAIN_END',
            'TAG_CHANGE Entity=2 tag=CURRENT_PLAYER value=0',
            'TAG_CHANGE Entity=3 tag=CURRENT_PLAYER value=1',
            'TAG_CHANGE Entity=1 tag=TURN value=6',
            'TAG_CHANGE Entity=1 tag=STEP value=MAIN_ACTION'])
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'Power.log'
            snapshots = []
            for contents in [text, text + suffix]:
                log.write_text(contents, encoding='utf-8')
                result = subprocess.run([str(binary), 'replay', str(log), '--json'],
                                        capture_output=True, check=True, timeout=5)
                snapshots.append(json.loads(result.stdout.splitlines()[-1]))
        result = assess_end_turn(*snapshots, 0)
        self.assertEqual(result['status'], 'submission_and_handoff_observed')
        self.assertFalse(result['execution_confirmed'])

    def test_matching_send_and_opponent_turn_are_evidence_not_permission(self):
        before, after = observations()
        result = assess_end_turn(before, after, 0)
        self.assertEqual(result['status'], 'submission_and_handoff_observed')
        self.assertTrue(result['matching_submission_observed'])
        self.assertTrue(result['turn_handoff_observed'])
        self.assertFalse(result['execution_confirmed'])
        self.assertFalse(result['automatic_retry_allowed'])

    def test_wrong_game_multiple_sends_and_mismatched_packet_are_terminal(self):
        changes = [(['game_number'], 4, 'game_changed'),
            (['game', 'logged_options', 'submissions_seen'], 4, 'multiple_submissions_observed'),
            (['game', 'logged_options', 'submissions_seen'], 1, 'submission_history_reset'),
            (['game', 'logged_options', 'latest_submission', 'selection', 'target'], 8, 'different_submission_observed'),
            (['game', 'logged_options', 'latest_submission', 'correlation', 'packet_id'], 9, 'submission_context_mismatch'),
            (['game', 'board', 'perspective'], 2, 'perspective_changed'),
            (['game', 'board', 'turn'], 6, 'unexpected_turn_number'),
            (['game', 'board', 'active_player'], 1, 'unexpected_active_player')]
        for keys, value, expected in changes:
            before, after = observations()
            target = after
            for key in keys[:-1]: target = target[key]
            target[keys[-1]] = value
            result = assess_end_turn(before, after, 0)
            self.assertEqual(result['status'], expected)
            self.assertFalse(result['execution_confirmed'])

    def test_partial_or_unclosed_prefix_does_not_complete_handoff(self):
        before, after = observations()
        for partial, closed in [(True, True), (False, False)]:
            after['ignored_partial_line'] = partial
            after['game']['power_structure']['closed'] = closed
            self.assertEqual(assess_end_turn(before, after, 0)['status'], 'pending')
        after['ignored_partial_line'] = False
        after['game']['logged_options']['submissions_seen'] = 2
        self.assertFalse(assess_end_turn(before, after, 0)['matching_submission_observed'])

    def test_wait_reaches_evidence_without_real_sleep_or_input(self):
        before, after = observations()
        clock = FakeClock()
        responses = iter([('session', before), ('session', after)])
        result = wait_for_evidence(before, 0, 'session', lambda remaining: next(responses),
                                   clock=clock.clock, sleep=clock.sleep)
        self.assertEqual(result['status'], 'submission_and_handoff_observed')
        self.assertEqual(clock.now, .25)

    def test_timeout_and_late_result_never_become_success(self):
        before, after = observations()
        clock = FakeClock()
        result = wait_for_evidence(before, 0, 'session', lambda remaining: ('session', before),
                                   timeout=1, clock=clock.clock, sleep=clock.sleep)
        self.assertEqual(result['status'], 'evidence_timeout')
        clock = FakeClock()
        def late(remaining):
            clock.sleep(remaining)
            return 'session', after
        result = wait_for_evidence(before, 0, 'session', late, timeout=1,
                                   clock=clock.clock, sleep=clock.sleep)
        self.assertEqual(result['status'], 'evidence_timeout')
        self.assertFalse(result['turn_handoff_observed'])

    def test_session_change_read_failure_and_bad_schema_stop_observation(self):
        before, after = observations()
        def failed(remaining): raise OSError('private adapter message')
        for observer, expected in [(lambda remaining: ('other', after), 'session_changed'),
                                   (failed, 'observation_failed'),
                                   (lambda remaining: ('session', {}), 'invalid_observation')]:
            result = wait_for_evidence(before, 0, 'session', observer)
            self.assertEqual(result['status'], expected)
            self.assertNotIn('private adapter', str(result))
            self.assertFalse(result['automatic_retry_allowed'])


if __name__ == '__main__':
    unittest.main()
