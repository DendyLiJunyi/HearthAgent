import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from ui_attempt import run_attempt


EVIDENCE = {'status': 'submission_and_handoff_observed', 'execution_confirmed': False,
            'automatic_retry_allowed': False}


class AttemptTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'attempt.json'

    def test_complete_path_is_persisted_and_duplicate_cannot_dispatch(self):
        dispatch = Mock(return_value=3)
        result = run_attempt(self.path, {}, lambda: None, dispatch, lambda: EVIDENCE)
        self.assertEqual(json.loads(self.path.read_text()), result)
        self.assertEqual(result['status'], EVIDENCE['status'])
        self.assertFalse(result['execution_confirmed'])
        with self.assertRaises(FileExistsError):
            run_attempt(self.path, {}, lambda: None, dispatch, lambda: EVIDENCE)
        dispatch.assert_called_once()

    def test_failed_or_changed_preflight_never_dispatches(self):
        for checks in [[RuntimeError('private reason')], [None, RuntimeError('changed during journal write')]]:
            path = self.path.with_name(f'preflight-{len(checks)}.json')
            dispatch = Mock()
            result = run_attempt(path, {}, Mock(side_effect=checks), dispatch, Mock())
            self.assertEqual(result['status'], 'preflight_failed')
            self.assertFalse(result['dispatch_attempted'])
            self.assertNotIn('private reason', path.read_text())
            dispatch.assert_not_called()

    def test_partial_and_exceptional_dispatch_never_collect_evidence_or_retry(self):
        for index, response in enumerate([0, 1, 2, True, RuntimeError('uncertain adapter')]):
            dispatch = Mock(side_effect=response) if isinstance(response, Exception) else Mock(return_value=response)
            collect = Mock()
            result = run_attempt(self.path.with_name(f'partial-{index}.json'), {}, lambda: None, dispatch, collect)
            self.assertIn(result['status'], ['partial_or_failed_input_insertion', 'dispatch_exception_result_unknown'])
            self.assertFalse(result['automatic_retry_allowed'])
            dispatch.assert_called_once()
            collect.assert_not_called()

    def test_intent_write_failure_preserves_reservation_and_prevents_dispatch(self):
        dispatch = Mock()
        with patch('ui_attempt.save_report', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                run_attempt(self.path, {}, lambda: None, dispatch, Mock())
        self.assertEqual(json.loads(self.path.read_text())['status'], 'dispatch_reserved')
        dispatch.assert_not_called()

    def test_evidence_failure_cannot_grant_confirmation_or_more_input(self):
        for index, evidence in enumerate([dict(EVIDENCE, execution_confirmed=True),
                                          dict(EVIDENCE, automatic_retry_allowed=True), None]):
            dispatch = Mock(return_value=3)
            result = run_attempt(self.path.with_name(f'evidence-{index}.json'), {}, lambda: None,
                                 dispatch, lambda: evidence)
            self.assertEqual(result['status'], 'evidence_collection_failed')
            self.assertFalse(result['execution_confirmed'])
            dispatch.assert_called_once()


if __name__ == '__main__':
    unittest.main()
