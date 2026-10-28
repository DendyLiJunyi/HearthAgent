"""Audit observed turn progression after client end-turn sends; never confirm causation."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

POWER = ' GameState.DebugPrintPower() - '
SEND = ' GameState.SendOption() - '
SELECTION = re.compile(r'selectedOption=(\d+) selectedSubOption=(-?\d+) selectedTarget=(\d+) selectedPosition=(\d+)')
TAG = re.compile(r'TAG_CHANGE Entity=(GameEntity|\d+) tag=(STATE|STEP|TURN) value=(\S+)\s*')


def audit(data, submissions):
    """Consume a frozen prefix and Rust submission rows from that same prefix.

    Only GameEntity tags in GameState's authoritative power stream are used.
    Player TURN tags, animation records, and incomplete final lines are ignored.
    """
    rows = iter(submissions)
    results = []
    pending = None
    game = sent = 0
    entity = None
    state = {}
    game_context = False

    def close(reason):
        nonlocal pending
        if pending is not None:
            pending['status'] = reason
            pending = None

    def observe(tag, value, line_number):
        nonlocal pending
        state[tag] = value
        if pending is None:
            return
        if tag == 'STATE' and value != 'RUNNING':
            close('game_state_changed')
        elif tag == 'STEP' and value == 'MAIN_END' and state.get('TURN') == str(pending['starting_turn']):
            pending['main_end_line'] = line_number
        elif tag == 'TURN':
            if value == str(pending['starting_turn']):
                if pending['next_turn_line'] is not None:
                    close('unexpected_turn_number')
                return
            if value != str(pending['starting_turn'] + 1):
                close('unexpected_turn_number')
            elif pending['main_end_line'] is None:
                close('turn_advanced_without_end_step')
            elif pending['next_turn_line'] is None:
                pending['next_turn_line'] = line_number
        elif tag == 'STEP' and value == 'MAIN_ACTION' and pending['next_turn_line'] is not None:
            pending['next_action_line'] = line_number
            close('turn_progression_observed')

    for number, raw in enumerate(data.split(b'\n')[:-1], 1):
        line = raw.decode('utf-8').rstrip('\r\n')
        if POWER in line:
            text = line.split(POWER, 1)[1].strip()
            if text == 'CREATE_GAME':
                close('new_game_before_progression')
                game += 1
                sent = 0
                entity = None
                state = {}
                game_context = False
                continue
            if not game:
                continue
            header = re.fullmatch(r'GameEntity EntityID=(\d+)', text)
            if header:
                close('game_entity_redeclared')
                entity = header.group(1)
                game_context = True
                continue
            if text.startswith('tag='):
                tag = re.fullmatch(r'tag=(STATE|STEP|TURN) value=(\S+)', text)
                if game_context and tag:
                    observe(*tag.groups(), number)
                continue
            game_context = False
            tag = TAG.fullmatch(text)
            if tag and entity is not None and tag.group(1) in ('GameEntity', entity):
                observe(tag.group(2), tag.group(3), number)
        elif SEND in line and game:
            close('next_submission_before_progression')
            sent += 1
            row = next(rows, None)
            if row is None or row['game_number'] != game or row['submission_number'] != sent:
                raise ValueError('submission rows do not match this log prefix')
            match = SELECTION.fullmatch(line.split(SEND, 1)[1].strip())
            submission = row['submission']
            valid = match is not None and int(match.group(2)) >= -1
            if valid != (submission is not None):
                raise ValueError('submission parse disagrees with Rust export')
            if not valid:
                continue
            selection = dict(zip(('option', 'sub_option', 'target', 'position'), map(int, match.groups())))
            if selection != submission['selection']:
                raise ValueError('submission selection differs from Rust export')
            c = submission['correlation']
            if c['option_kind'] != 'END_TURN':
                continue
            result = {'game_number': game, 'submission_number': sent, 'send_line': number,
                      'starting_turn': None, 'observed_option_error': c['option_error'],
                      'main_end_line': None, 'next_turn_line': None, 'next_action_line': None,
                      'status': 'unsupported_baseline', 'execution_confirmed': False}
            results.append(result)
            if (entity is None or state.get('STATE') != 'RUNNING' or state.get('STEP') != 'MAIN_ACTION'
                    or not state.get('TURN', '').isascii() or not state.get('TURN', '').isdigit()
                    or int(state['TURN']) < 1 or c['packet_was_stale'] is not False
                    or c['option_seen'] is not True or c['packet_malformed_records'] != 0
                    or c['packet_unsupported_records'] != 0 or c['option_error'] not in ('NONE', 'INVALID')
                    or (selection['sub_option'], selection['target'], selection['position']) != (-1, 0, 0)):
                continue
            result['starting_turn'] = int(state['TURN'])
            result['status'] = 'awaiting_progression'
            pending = result
    if next(rows, None) is not None:
        raise ValueError('submission rows extend beyond this log prefix')
    close('prefix_ended_before_progression')
    return {'source': 'offline_end_turn_progression_audit', 'actionable': False,
            'execution_confirmed': False, 'ignored_partial_line': bool(data and not data.endswith(b'\n')),
            'counts': dict(Counter(result['status'] for result in results)), 'attempts': results,
            'scope': 'Post-submission turn progression only; does not establish causation, '
                     'input delivery, legality, opponent identity, or safe retry.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--binary', type=Path, default=Path('target/validation/debug/hearth-agent.exe'))
    parser.add_argument('--output', type=Path, default=Path('.data/turn-progression-review.json'))
    args = parser.parse_args()
    if len({p.resolve() for p in (args.log, args.binary, args.output)}) != 3:
        parser.error('input, binary, and output paths must differ')
    # Read once: the export and audit must use identical bytes even if the game appends.
    data = args.log.read_bytes()
    with tempfile.TemporaryDirectory(prefix='hearth-turn-audit-') as directory:
        frozen = Path(directory) / 'Power.log'
        frozen.write_bytes(data)
        exported = subprocess.run([str(args.binary.resolve()), 'review-submissions', str(frozen)],
                                  capture_output=True, check=True, timeout=180)
    rows = [json.loads(line) for line in exported.stdout.splitlines()]
    report = audit(data, rows)
    report['session'] = args.log.parent.name
    report['log_prefix_sha256'] = hashlib.sha256(data).hexdigest()
    report['submission_export_sha256'] = hashlib.sha256(exported.stdout).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'counts': report['counts'],
                      'execution_confirmed': False}, indent=2))


if __name__ == '__main__':
    main()
