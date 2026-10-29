import unittest
from review_submissions import summary


def row():
    return {'game_number': 1, 'submission': {
        'selection': {'option': 0, 'sub_option': -1, 'target': 0, 'position': 0},
        'correlation': {'packet_id': 7, 'packet_was_stale': False,
            'packet_malformed_records': 0, 'packet_unsupported_records': 0,
            'option_seen': True, 'option_kind': 'END_TURN', 'option_error': 'INVALID',
            'sub_option_seen': None, 'sub_option_error': None, 'target_seen': None,
            'target_ambiguous': False, 'target_error': None, 'legality_verified': False,
            'candidate_list_complete': False, 'execution_confirmed': False}}}


class SubmissionReviewTests(unittest.TestCase):
    def test_end_turn_error_is_retained_without_inventing_missing_target(self):
        report = summary([row()])
        self.assertEqual(report['issues'], {'option_error_reported': 1})
        self.assertEqual(report['observed_errors'], {'END_TURN:option_error:INVALID': 1})
        self.assertFalse(report['actionable'])

    def test_missing_and_malformed_rows_count_once_not_cumulatively(self):
        missing = row()
        missing['submission']['selection'].update(sub_option=0, target=99)
        missing['submission']['correlation'].update(packet_id=None, option_seen=None,
                                                   option_kind=None, option_error=None)
        report = summary([missing, {'game_number': 2, 'submission': None, 'malformed_submissions': 5}])
        self.assertEqual(report['games_with_submissions'], 2)
        self.assertEqual(report['totals']['submission_lines'], 2)
        self.assertEqual(report['issues'], {'missing_packet': 1, 'option_not_observed': 1,
                         'suboption_not_observed': 1, 'target_not_observed': 1, 'malformed_submission': 1})

    def test_diagnostic_report_refuses_promoted_execution_or_legality_claim(self):
        for key in ('execution_confirmed', 'legality_verified', 'candidate_list_complete'):
            invalid = row()
            invalid['submission']['correlation'][key] = True
            with self.assertRaises(ValueError):
                summary([invalid])


if __name__ == '__main__':
    unittest.main()
