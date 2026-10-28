"""Export every frozen choice window and summarize prefix-only source evidence."""
import argparse
from collections import Counter
import json
import hashlib
from pathlib import Path
import subprocess


def visible_source(board, source):
    matches = [card['card_id'] for player in board['players']
               for zone in ('in_play', 'hand', 'graveyard') for card in player[zone]
               if card['entity_id'] == source and card.get('card_id')]
    return matches[0] if len(matches) == 1 else None


def summary(windows):
    totals, kinds, sources, issues = Counter(), Counter(), Counter(), Counter()
    preview_sources, preview_blocks = Counter(), Counter()
    games = set()
    for row in windows:
        games.add(row['game_number'])
        totals['windows'] += 1
        totals['bounded_windows'] += bool(row['packet_boundary_observed'])
        window, choices = row['window'], row['logged_choices']
        preview = row.get('choice_preview')
        if preview is not None:
            preview_blocks.update(preview['blocked_by'])
            projected = preview['choice']
            if projected and window['kind'] == 'packet' and projected['choice_id'] == window['packet_id']:
                totals['local_choice_previews'] += 1
                totals['projected_local_choice_cards'] += len(projected['offered_cards'])
                preview_sources[projected['source_card_id']] += 1
        identity = window['packet_id']
        if window['kind'] == 'packet':
            totals['packet_windows'] += 1
            packet = choices['sets'].get(str(identity)) if identity is not None else None
            if packet is None or packet['stale'] or packet['malformed_records']:
                issues['missing_stale_or_malformed_packet'] += 1
                continue
            kinds[packet['kind']] += 1
            source = visible_source(row['board'], packet['source_entity'])
            sources[source or 'UNKNOWN_FROM_VISIBLE_PREFIX'] += 1
            owner = next((p['player_id'] for p in row['board']['players']
                          if p['entity_id'] == packet['owner_entity']), None)
            perspective = row['board']['perspective']
            totals['known_local_packet_windows'] += owner is not None and owner == perspective
            totals['observed_choice_entities'] += len(packet['entities'])
        else:
            totals['submission_windows'] += 1
            submission = choices['latest_submission']
            if identity is None or submission is None or identity != submission['id']:
                issues['missing_current_submission'] += 1
                continue
            totals['complete_submitted_lists'] += bool(submission['list_complete'])
            if not submission['list_complete']:
                issues['incomplete_submitted_list'] += 1
            correlation = submission['correlation']
            for key in ('packet_seen', 'owner_matches', 'declared_count_within_bounds'):
                if correlation[key] is not True:
                    issues['submission_' + key + '_not_confirmed'] += 1
            if correlation['unobserved_entities']:
                issues['submission_has_unobserved_entities'] += 1
            if correlation['packet_was_stale']:
                issues['submission_packet_was_stale'] += 1
    return {'source': 'offline_choice_window_review', 'actionable': False,
            'complete': False, 'games_with_windows': len(games), 'totals': dict(totals),
            'packet_kinds': dict(kinds), 'visible_source_card_ids': dict(sources),
            'local_preview_sources': dict(preview_sources), 'preview_blocked_by': dict(preview_blocks),
            'issues': dict(issues), 'scope': 'All observed choice/submission groups; boundaries do not '
            'prove candidate completeness, local ownership or successful execution.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--binary', type=Path, default=Path('target/validation/debug/hearth-agent.exe'))
    parser.add_argument('--output', type=Path, default=Path('.data/choice-window-review.json'))
    parser.add_argument('--windows', type=Path, default=Path('.data/choice-windows.jsonl'))
    args = parser.parse_args()
    paths = [p.resolve() for p in (args.log, args.binary, args.output, args.windows)]
    if len(set(paths)) != len(paths):
        parser.error('input and output paths must differ')
    result = subprocess.run([str(args.binary.resolve()), 'review-choices', str(args.log.resolve())],
                            capture_output=True, text=True, encoding='utf-8', timeout=180, check=True)
    windows = [json.loads(line) for line in result.stdout.splitlines()]
    report = summary(windows)
    report['session'] = args.log.parent.name
    for path in (args.output, args.windows):
        path.parent.mkdir(parents=True, exist_ok=True)
    args.windows.write_text(result.stdout, encoding='utf-8')
    report['windows_sha256'] = hashlib.sha256(args.windows.read_bytes()).hexdigest()
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
