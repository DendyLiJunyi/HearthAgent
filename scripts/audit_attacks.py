"""Correlate targeted client sends with later authoritative ATTACK block boundaries."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from audit_turns import POWER, SEND, SELECTION

ATTACK = re.compile(r'BLOCK_START BlockType=ATTACK Entity=(.+) EffectCardId=.* EffectIndex=-?\d+ '
                    r'Target=(.+) SubOption=-?\d+(?: TriggerKeyword=\S+)?', re.ASCII)


def entity_id(reference):
    if re.fullmatch(r'\d+', reference, re.ASCII):
        return int(reference)
    if not reference.startswith('[') or not reference.endswith(']'):
        return None
    for field in reversed(reference[1:-1].split()):
        if field.startswith('id='):
            return int(field[3:]) if re.fullmatch(r'\d+', field[3:], re.ASCII) else None
    return None


def audit(data, submissions):
    rows = iter(submissions)
    game = sends = 0
    stack = []
    structural_errors = 0
    game_errors = 0
    attempts = []
    pending = None

    def close(status):
        nonlocal pending
        if pending is not None:
            pending['status'] = status
            pending = None

    for number, raw in enumerate(data.split(b'\n')[:-1], 1):
        line = raw.decode('utf-8').rstrip('\r')
        if POWER in line:
            text = line.split(POWER, 1)[1].strip()
            if text == 'CREATE_GAME':
                close('new_game_before_attack_completion')
                game += 1
                sends = game_errors = 0
                stack.clear()
                continue
            if not game:
                continue
            kind = text.split()[0] if text else ''
            if kind in ('BLOCK_START', 'SUB_SPELL_START'):
                stack.append('block' if kind == 'BLOCK_START' else 'sub_spell')
                required = 'BlockType=' if kind == 'BLOCK_START' else 'Source='
                if not any(field.startswith(required) and len(field) > len(required) for field in text.split()):
                    structural_errors += 1
                    game_errors += 1
                    close('malformed_block_header')
                if text.startswith('BLOCK_START BlockType=ATTACK '):
                    match = ATTACK.fullmatch(text)
                    source, target = (entity_id(match.group(1)), entity_id(match.group(2))) if match else (None, None)
                    if source is None or target is None or source <= 0 or target <= 0:
                        structural_errors += 1
                        game_errors += 1
                        close('unparsed_attack_header')
                    elif pending is not None and source == pending['source_entity']:
                        if pending['attack_start_line'] is not None:
                            close('multiple_matching_attack_starts')
                        elif target != pending['target_entity']:
                            close('different_attack_target_observed')
                        else:
                            pending['attack_start_line'] = number
                            pending['attack_depth'] = len(stack)
            elif kind in ('BLOCK_END', 'SUB_SPELL_END'):
                expected = 'block' if kind == 'BLOCK_END' else 'sub_spell'
                if text != kind or not stack or stack[-1] != expected:
                    structural_errors += 1
                    game_errors += 1
                    close('malformed_block_boundary')
                else:
                    if (pending is not None and pending['attack_start_line'] is not None
                            and pending['attack_depth'] == len(stack) and expected == 'block'):
                        pending['attack_end_line'] = number
                        close('matching_attack_block_closed')
                    stack.pop()
        elif SEND in line and game:
            close('next_submission_before_attack_completion')
            sends += 1
            row = next(rows, None)
            if row is None or row['game_number'] != game or row['submission_number'] != sends:
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
            if c['option_kind'] != 'POWER' or selection['target'] == 0 or selection['sub_option'] != -1:
                continue
            attempt = {'game_number': game, 'submission_number': sends, 'send_line': number,
                       'source_entity': c['source_entity'], 'target_entity': selection['target'],
                       'attack_start_line': None, 'attack_end_line': None, 'attack_depth': None,
                       'status': 'unsupported_baseline', 'execution_confirmed': False}
            attempts.append(attempt)
            observed = row.get('source_observation')
            if observed is not None:
                if observed.get('entity_id') != c['source_entity']:
                    raise ValueError('source observation differs from correlated entity')
                attempt['source_card_type'] = observed.get('card_type')
                attempt['source_zone'] = observed.get('zone')
                if (observed.get('zone') == 'hand' or
                        observed.get('card_type') not in (None, 'HERO', 'MINION')):
                    attempt['status'] = 'non_attack_source_observed'
                    continue
            if (c['packet_was_stale'] is not False or c['packet_malformed_records'] != 0
                    or c['packet_unsupported_records'] != 0 or c['option_seen'] is not True
                    or type(c['source_entity']) is not int or c['source_entity'] <= 0
                    or c['option_error'] != 'NONE' or c['target_seen'] is not True
                    or c['target_ambiguous'] or c['target_error'] != 'NONE'
                    or selection['position'] != 0 or stack or game_errors):
                continue
            pending = attempt
            pending['status'] = 'awaiting_attack_block'
    if next(rows, None) is not None:
        raise ValueError('submission rows extend beyond the log prefix')
    close('prefix_ended_before_attack_completion')
    return {'source': 'offline_attack_block_audit', 'actionable': False, 'execution_confirmed': False,
            'ignored_partial_line': bool(data and not data.endswith(b'\n')),
            'structural_errors': structural_errors,
            'counts': dict(Counter(attempt['status'] for attempt in attempts)), 'attempts': attempts,
            'scope': 'Targeted POWER sends include non-attack actions. Matching ATTACK source/target '
                     'and block closure are log evidence, not input causation, damage or victory confirmation.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--binary', type=Path, default=Path('target/validation/debug/hearth-agent.exe'))
    parser.add_argument('--output', type=Path, default=Path('.data/attack-block-review.json'))
    args = parser.parse_args()
    if len({path.resolve() for path in (args.log, args.binary, args.output)}) != 3:
        parser.error('input, binary and output paths must differ')
    data = args.log.read_bytes()
    with tempfile.TemporaryDirectory(prefix='hearth-attack-audit-') as directory:
        frozen = Path(directory) / 'Power.log'
        frozen.write_bytes(data)
        exported = subprocess.run([str(args.binary.resolve()), 'review-submissions', str(frozen)],
                                  capture_output=True, check=True, timeout=180)
    report = audit(data, [json.loads(line) for line in exported.stdout.splitlines()])
    report['session'] = args.log.parent.name
    report['log_prefix_sha256'] = hashlib.sha256(data).hexdigest()
    report['submission_export_sha256'] = hashlib.sha256(exported.stdout).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'counts': report['counts'],
                      'structural_errors': report['structural_errors'], 'execution_confirmed': False}, indent=2))


if __name__ == '__main__':
    main()
