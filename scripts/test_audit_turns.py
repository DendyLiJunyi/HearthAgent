import copy
import unittest
from audit_turns import audit


def power(text):
    return f'D 0 GameState.DebugPrintPower() - {text}\n'


SEND = 'D 0 GameState.SendOption() - selectedOption=0 selectedSubOption=-1 selectedTarget=0 selectedPosition=0\n'
START = ''.join(map(power, ['CREATE_GAME', 'GameEntity EntityID=1', 'tag=STATE value=RUNNING',
                          'tag=STEP value=MAIN_ACTION', 'tag=TURN value=2']))
END = power('TAG_CHANGE Entity=GameEntity tag=STEP value=MAIN_END')
NEXT = power('TAG_CHANGE Entity=1 tag=TURN value=3')
ACTION = power('TAG_CHANGE Entity=GameEntity tag=STEP value=MAIN_ACTION')
ROW = {'game_number': 1, 'submission_number': 1, 'submission': {
    'selection': {'option': 0, 'sub_option': -1, 'target': 0, 'position': 0},
    'correlation': {'option_kind': 'END_TURN', 'option_error': 'INVALID',
                    'packet_was_stale': False, 'option_seen': True,
                    'packet_malformed_records': 0, 'packet_unsupported_records': 0}}}


def run(suffix, rows=None):
    return audit((START + SEND + suffix).encode(), [copy.deepcopy(ROW)] if rows is None else rows)


class TurnAuditTests(unittest.TestCase):
    def test_progression_is_ordered_and_still_not_execution_confirmation(self):
        report = run(END + NEXT + ACTION)
        attempt = report['attempts'][0]
        self.assertEqual(report['counts'], {'turn_progression_observed': 1})
        self.assertLess(attempt['send_line'], attempt['main_end_line'])
        self.assertLess(attempt['main_end_line'], attempt['next_turn_line'])
        self.assertLess(attempt['next_turn_line'], attempt['next_action_line'])
        self.assertEqual(attempt['observed_option_error'], 'INVALID')
        self.assertFalse(attempt['execution_confirmed'])
        self.assertFalse(report['execution_confirmed'])

    def test_animation_player_tags_and_partial_lines_cannot_complete_progression(self):
        for suffix in [(END + NEXT + ACTION).replace('GameState', 'PowerTaskList'),
                       END + NEXT.replace('Entity=1 ', 'Entity=2 ') + ACTION,
                       END + NEXT + ACTION.rstrip('\n'), END + ACTION + NEXT]:
            report = run(suffix)
            self.assertEqual(report['counts'], {'prefix_ended_before_progression': 1})

    def test_discontinuity_cannot_be_repaired_by_later_turn_events(self):
        for suffix, status in [
            (NEXT + END + ACTION, 'turn_advanced_without_end_step'),
            (END + NEXT.replace('value=3', 'value=5') + NEXT + ACTION, 'unexpected_turn_number'),
            (END + NEXT + NEXT.replace('value=3', 'value=2') + ACTION, 'unexpected_turn_number'),
            (power('TAG_CHANGE Entity=GameEntity tag=STATE value=COMPLETE') + END + NEXT + ACTION,
             'game_state_changed'),
            (power('CREATE_GAME') + END + NEXT + ACTION, 'new_game_before_progression'),
        ]:
            self.assertEqual(run(suffix)['counts'], {status: 1})

    def test_next_send_closes_previous_attempt_and_new_game_resets_identity(self):
        second = copy.deepcopy(ROW)
        second['submission_number'] = 2
        report = run(SEND + END + NEXT + ACTION, [ROW, second])
        self.assertEqual([a['status'] for a in report['attempts']],
                         ['next_submission_before_progression', 'turn_progression_observed'])
        second['game_number'] = 2
        second['submission_number'] = 1
        report = run(START + SEND + END + NEXT + ACTION, [ROW, second])
        self.assertEqual([a['game_number'] for a in report['attempts']], [1, 2])

    def test_stale_packet_and_unknown_baseline_are_not_promoted(self):
        row = copy.deepcopy(ROW)
        row['submission']['correlation']['packet_was_stale'] = True
        self.assertEqual(run(END + NEXT + ACTION, [row])['counts'], {'unsupported_baseline': 1})
        data = (START.replace('tag=TURN value=2', 'tag=TURN value=unknown') + SEND + END + NEXT + ACTION).encode()
        self.assertEqual(audit(data, [ROW])['counts'], {'unsupported_baseline': 1})

    def test_mismatched_exports_are_rejected_instead_of_attached_to_wrong_attempt(self):
        bad = copy.deepcopy(ROW)
        bad['submission']['selection']['option'] = 9
        for rows in [[], [bad], [ROW, ROW]]:
            with self.assertRaises(ValueError):
                run(END + NEXT + ACTION, rows)


if __name__ == '__main__':
    unittest.main()
