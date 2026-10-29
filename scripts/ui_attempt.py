"""Durable, single-dispatch orchestration; adapters are injected for offline tests."""
import json
import os
from pathlib import Path
import tempfile


def save_report(path, report):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.name + '.', suffix='.tmp', delete=False) as output:
            temporary = Path(output.name)
            output.write(json.dumps(report, indent=2) + '\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run_attempt(path, metadata, preflight, dispatch, collect_evidence, *, expected_events=3):
    if type(expected_events) is not int or not 1 <= expected_events <= 32:
        raise ValueError('expected event count must be an integer between 1 and 32')
    path = Path(path)
    report = dict(metadata, status='dispatch_reserved', execution_confirmed=False,
                  automatic_retry_allowed=False, dispatch_attempted=False,
                  expected_input_events=expected_events)
    # Reservation survives failed preflight, crashes, and corrupt receipts.
    # An existing file is never interpreted as permission to repeat an action.
    with path.open('x', encoding='utf-8') as output:
        output.write(json.dumps(report) + '\n')
        output.flush()
        os.fsync(output.fileno())
    try:
        preflight()
    except Exception:
        report['status'] = 'preflight_failed'
        save_report(path, report)
        return report
    report.update(status='dispatch_started', dispatch_attempted=True)
    save_report(path, report)
    # Persisting intent may take time. Recheck immediately after that write,
    # before the one permitted dispatch call.
    try:
        preflight()
    except Exception:
        report.update(status='preflight_failed', dispatch_attempted=False)
        save_report(path, report)
        return report
    try:
        inserted = dispatch()
    except Exception:
        report['status'] = 'dispatch_exception_result_unknown'
        save_report(path, report)
        return report
    report['input_events_inserted'] = inserted
    report['status'] = 'input_attempted_result_unconfirmed'
    save_report(path, report)
    if type(inserted) is not int or inserted != expected_events:
        report['status'] = 'partial_or_failed_input_insertion'
    else:
        try:
            evidence = collect_evidence()
            if (not isinstance(evidence, dict) or evidence.get('execution_confirmed') is not False
                    or evidence.get('automatic_retry_allowed') is not False
                    or not isinstance(evidence.get('status'), str)):
                raise ValueError('evidence cannot grant confirmation or retry permission')
            report['evidence'] = evidence
            report['status'] = evidence['status']
        except Exception:
            report['status'] = 'evidence_collection_failed'
    save_report(path, report)
    return report


def main():
    rows = []
    with tempfile.TemporaryDirectory(prefix='hearth-ui-rehearsal-') as directory:
        for label, inserted in [('full_batch', 3), ('partial_batch', 2), ('no_batch', 0)]:
            calls = []
            def dispatch():
                calls.append('simulated_dispatch')
                return inserted
            report = run_attempt(Path(directory) / (label + '.json'), {'scenario': label},
                                 lambda: None, dispatch, lambda: {
                                     'status': 'evidence_timeout', 'execution_confirmed': False,
                                     'automatic_retry_allowed': False})
            rows.append({'source': 'synthetic_ui_rehearsal', 'game_input_sent': False,
                         'simulated_dispatches': len(calls), 'report': report})
    print(json.dumps(rows, indent=2))


if __name__ == '__main__':
    main()
