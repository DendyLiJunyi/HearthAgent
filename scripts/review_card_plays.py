"""Summarize supported hand-card previews from a frozen historical log."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def summarize(rows):
    counts, cards, blocked = Counter(), Counter(), Counter()
    games = set()
    for row in rows:
        if row['source'] != 'offline_card_play_window':
            raise ValueError('expected card-play review rows')
        preview = row['action_preview']
        if row['actionable'] or any(preview[key] for key in ('actionable', 'complete', 'legality_verified')):
            raise ValueError('review cannot claim executable candidates')
        counts['option_windows'] += 1
        blocked.update(preview['blocked_by'])
        if not row['packet_boundary_observed']:
            counts['unclosed_window'] += 1
            continue
        if preview['blocked_by'] or not preview['candidates']:
            continue
        counts['windows_with_card_plays'] += 1
        games.add(row['game_number'])
        local = next(p for p in row['board']['players'] if p['player_id'] == preview['perspective'])
        hand = {c['entity_id']: c['card_id'] for c in local['hand']}
        for candidate in preview['candidates']:
            play = candidate['action']['PlayCard']
            cards[hand[play['source']]] += 1
            counts['candidate_occurrences'] += 1
    return {'source': 'offline_card_play_review', 'actionable': False, 'execution_confirmed': False,
            'counts': dict(counts), 'games_with_card_plays': sorted(games),
            'candidate_occurrences_by_card': dict(cards), 'blocked_windows': dict(blocked),
            'scope': 'Historical candidate occurrences, not unique positions, actual plays or strategic accuracy.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--binary', type=Path, default=Path('target/validation/debug/hearth-agent.exe'))
    parser.add_argument('--output', type=Path, default=Path('.data/card-play-review.json'))
    args = parser.parse_args()
    if len({p.resolve() for p in (args.log, args.binary, args.output)}) != 3:
        parser.error('input, binary and output paths must differ')
    data = args.log.read_bytes()
    with tempfile.TemporaryDirectory(prefix='hearth-card-review-') as directory:
        frozen = Path(directory) / 'Power.log'
        frozen.write_bytes(data)
        result = subprocess.run([str(args.binary.resolve()), 'review-card-plays', str(frozen)],
                                capture_output=True, check=True, timeout=180)
    report = summarize(json.loads(line) for line in result.stdout.splitlines())
    report.update(session=args.log.parent.name, log_prefix_sha256=hashlib.sha256(data).hexdigest(),
                  export_sha256=hashlib.sha256(result.stdout).hexdigest())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
