"""Audit prefix-frozen client option submissions, without claiming execution success."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess


def summary(rows):
    totals, issues, kinds, errors = Counter(), Counter(), Counter(), Counter()
    games = set()
    for row in rows:
        games.add(row['game_number'])
        totals['submission_lines'] += 1
        submission = row['submission']
        if submission is None:
            issues['malformed_submission'] += 1
            continue
        totals['parsed_submissions'] += 1
        selection, correlation = submission['selection'], submission['correlation']
        if any(correlation[key] for key in ('legality_verified', 'candidate_list_complete', 'execution_confirmed')):
            raise ValueError('diagnostic submission unexpectedly claims verified execution or legality')
        kinds[correlation['option_kind'] or 'UNKNOWN'] += 1
        totals['targeted_submissions'] += selection['target'] != 0
        totals['suboption_submissions'] += selection['sub_option'] != -1
        totals['nonzero_position_submissions'] += selection['position'] != 0
        if correlation['packet_id'] is None:
            issues['missing_packet'] += 1
        if correlation['packet_was_stale']:
            issues['stale_packet'] += 1
        for key in ('packet_malformed_records', 'packet_unsupported_records'):
            if correlation[key]:
                issues[key] += 1
        if correlation['option_seen'] is not True:
            issues['option_not_observed'] += 1
        if selection['sub_option'] != -1 and correlation['sub_option_seen'] is not True:
            issues['suboption_not_observed'] += 1
        if selection['target'] != 0 and correlation['target_seen'] is not True:
            issues['target_not_observed'] += 1
        if correlation['target_ambiguous']:
            issues['ambiguous_target'] += 1
        for key in ('option_error', 'sub_option_error', 'target_error'):
            if correlation[key] not in (None, 'NONE'):
                issues[key + '_reported'] += 1
                errors[f"{correlation['option_kind'] or 'UNKNOWN'}:{key}:{correlation[key]}"] += 1
    return {'source': 'offline_option_submission_review', 'actionable': False,
            'complete': False, 'games_with_submissions': len(games), 'totals': dict(totals),
            'option_kinds': dict(kinds), 'issues': dict(issues), 'observed_errors': dict(errors),
            'scope': 'Client sends matched to prior observed option packets. '
                     'Missing entries do not prove illegal play; matching does not prove execution.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--binary', type=Path, default=Path('target/validation/debug/hearth-agent.exe'))
    parser.add_argument('--output', type=Path, default=Path('.data/submission-review.json'))
    parser.add_argument('--rows', type=Path, default=Path('.data/submission-windows.jsonl'))
    args = parser.parse_args()
    paths = [path.resolve() for path in (args.log, args.binary, args.output, args.rows)]
    if len(set(paths)) != len(paths):
        parser.error('input and output paths must differ')
    result = subprocess.run([str(args.binary.resolve()), 'review-submissions', str(args.log.resolve())],
                            capture_output=True, text=True, encoding='utf-8', timeout=180, check=True)
    report = summary(json.loads(line) for line in result.stdout.splitlines())
    report['session'] = args.log.parent.name
    for path in (args.output, args.rows):
        path.parent.mkdir(parents=True, exist_ok=True)
    args.rows.write_text(result.stdout, encoding='utf-8')
    report['rows_sha256'] = hashlib.sha256(args.rows.read_bytes()).hexdigest()
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
