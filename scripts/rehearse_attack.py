"""Exercise attack planning and durable attempt handling with a recording adapter only."""
import argparse
import copy
import json
from pathlib import Path
import tempfile
from attack_geometry import plan_attack
from spell_geometry import plan_spell
from minion_geometry import plan_minion
from choice_geometry import plan_choice
from end_turn_geometry import plan_end_turn
from ui_attempt import run_attempt
from validate_review import strict_json


def rehearse(inputs, receipt, observe=None, inserted_events=None, mode='attack', collect_evidence=None):
    """observe is injectable for tests; this module has no game input adapter."""
    if mode not in ('attack', 'spell', 'minion', 'choice', 'end_turn'):
        raise ValueError('unsupported rehearsal mode')
    planner = {'attack': plan_attack, 'spell': plan_spell, 'minion': plan_minion,
               'choice': plan_choice, 'end_turn': plan_end_turn}[mode]
    baseline = copy.deepcopy(inputs)
    planned = planner(**baseline)
    if inserted_events is None: inserted_events = len(planned['gesture'])
    records = []
    if observe is None:
        observe = lambda: copy.deepcopy(baseline)

    def preflight():
        current = observe()
        # Compare the whole source envelope, including board/candidate fields
        # which might change without altering the resulting screen coordinates.
        if current != baseline or planner(**current) != planned:
            raise ValueError('attack observation or plan changed')

    def record():
        records.append(copy.deepcopy(planned['gesture']))
        return inserted_events

    if collect_evidence is None:
        collect_evidence = lambda: {
            'status': 'recorded_without_game_evidence', 'execution_confirmed': False,
            'automatic_retry_allowed': False}
    report = run_attempt(receipt, {
        'source': f'offline_{mode}_rehearsal', 'game_input_sent': False,
        'binding': planned['binding'], 'candidate_id': planned['candidate_id'],
        'frame_sha256': planned['frame_sha256'],
    }, preflight, record, collect_evidence, expected_events=len(planned['gesture']))
    return {'plan': planned, 'receipt': report, 'recorded_gestures': records,
            'game_input_sent': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture', type=Path)
    parser.add_argument('--mode', choices=('attack', 'spell', 'minion', 'choice', 'end_turn'), default='attack')
    args = parser.parse_args()
    inputs = strict_json(args.fixture.read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='hearth-attack-rehearsal-') as directory:
        result = rehearse(inputs, Path(directory) / 'attempt.json', mode=args.mode)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
