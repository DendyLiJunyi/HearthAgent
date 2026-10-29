"""Exercise attack planning and durable attempt handling with a recording adapter only."""
import argparse
import copy
import json
from pathlib import Path
import tempfile
from attack_geometry import plan_attack
from ui_attempt import run_attempt
from validate_review import strict_json


def rehearse(inputs, receipt, observe=None, inserted_events=4):
    """observe is injectable for tests; this module has no game input adapter."""
    baseline = copy.deepcopy(inputs)
    planned = plan_attack(**baseline)
    records = []
    if observe is None:
        observe = lambda: copy.deepcopy(baseline)

    def preflight():
        current = observe()
        # Compare the whole source envelope, including board/candidate fields
        # which might change without altering the resulting screen coordinates.
        if current != baseline or plan_attack(**current) != planned:
            raise ValueError('attack observation or plan changed')

    def record():
        records.append(copy.deepcopy(planned['gesture']))
        return inserted_events

    report = run_attempt(receipt, {
        'source': 'offline_attack_rehearsal', 'game_input_sent': False,
        'binding': planned['binding'], 'candidate_id': planned['candidate_id'],
        'frame_sha256': planned['frame_sha256'],
    }, preflight, record, lambda: {
        'status': 'recorded_without_game_evidence', 'execution_confirmed': False,
        'automatic_retry_allowed': False,
    }, expected_events=len(planned['gesture']))
    return {'plan': planned, 'receipt': report, 'recorded_gestures': records,
            'game_input_sent': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture', type=Path)
    args = parser.parse_args()
    inputs = strict_json(args.fixture.read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='hearth-attack-rehearsal-') as directory:
        result = rehearse(inputs, Path(directory) / 'attempt.json')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
