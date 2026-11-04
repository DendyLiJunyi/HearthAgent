"""Timing from a saved Power.log: how long moves waited, and when the fast gate would have allowed them.

    python -m agent.pace_report .data/live/loop-20261104-222225/001

The estimate uses the log gate only (backlog limit and quiet time). It leaves out the End Turn button
and gesture time, so it is a lower bound on a real move, not a promise of live speed.
"""
import argparse
import json
import re
import statistics
import time
from pathlib import Path

from .cli import PACES
from .power import AnimationBacklog

STAMP = re.compile(r'^D (\d\d):(\d\d):(\d\d\.\d+) ')


def seconds(line):
    match = STAMP.match(line)
    return int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3]) if match else None


def summary(values):
    ordered = sorted(values)
    if not ordered:
        return None
    return {'median': statistics.median(ordered), 'p90': ordered[int(len(ordered) * 0.9)], 'max': ordered[-1]}


def report_log(lines):
    gate = PACES['fast']['agent']
    limit, quiet, timeout = gate['backlog_limit'], gate['settle'], gate['drain_timeout']
    backlog = AnimationBacklog()
    waits, opened, saved = [], [], []
    options_at = last_activity = None
    for line in lines:
        at = seconds(line)
        if at is None or ' - ' not in line:
            continue
        body = line.split(' - ', 1)[1].strip()
        if 'GameState.DebugPrintPower()' in line:
            if body == 'CREATE_GAME':
                backlog = AnimationBacklog()
            backlog.received(body)
            last_activity = at
        elif 'PowerTaskList.DebugPrintPower()' in line:
            backlog.played(body)
            last_activity = at
        elif 'GameState.DebugPrintOptions() - id=' in line:
            options_at, drained_at = at, None
            last_activity = at
        elif 'GameState.SendOption()' in line and options_at is not None:
            wait = at - options_at
            if 0 <= wait < 90:  # Longer means a person looked away or the session changed.
                # Backlog at the send tells when processing ended; the last processed line sets the time.
                ready = last_activity if backlog.size <= limit else options_at + timeout
                ready = min(max(ready, options_at) + quiet, at)
                waits.append(wait)
                opened.append(ready - options_at)
                saved.append(at - ready)
            options_at = None
    return {'moves': len(waits), 'options_to_send': summary(waits), 'gate_would_open': summary(opened),
            'time_saved_per_move': summary(saved)}


def run_lines(lines, moves_path):
    """A saved log holds the whole client session, so keep lines from this run's first recorded move on."""
    if not moves_path.exists():
        return lines
    times = [row['at'] for row in map(json.loads, moves_path.read_text(encoding='utf-8').splitlines()) if 'at' in row]
    if not times:
        return lines
    first = time.localtime(min(times))
    start = first.tm_hour * 3600 + first.tm_min * 60 + first.tm_sec - 1
    return [line for line in lines if (seconds(line) or 0) >= start]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('run', type=Path, help='A folder holding Power.log, or a Power.log file.')
    args = parser.parse_args()
    path = args.run / 'Power.log' if args.run.is_dir() else args.run
    with open(path, encoding='utf-8', errors='replace') as handle:
        lines = handle.readlines()
    print(json.dumps(report_log(run_lines(lines, path.parent / 'moves.jsonl')), indent=1))


if __name__ == '__main__':
    main()
