"""Build consistent offline attack evidence using Rust on frozen saved logs."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile
import time
from validate_review import strict_json


def prepare(before_data, after_data, binary, *, timeout=30):
    if not math.isfinite(timeout) or not 0 < timeout <= 180:
        raise ValueError('timeout must be between 0 and 180 seconds')
    if (len(after_data) > 64 * 1024 * 1024 or not before_data.endswith(b'\n')
            or not after_data.endswith(b'\n') or not after_data.startswith(before_data)):
        raise ValueError('complete append-only prefixes of at most 64 MiB required')
    texts = [data.decode('utf-8') for data in (before_data, after_data)]
    deadline = time.monotonic() + timeout
    snapshots, exports = [], []
    with tempfile.TemporaryDirectory(prefix='hearth-attack-evidence-') as directory:
        frozen = Path(directory) / 'Power.log'
        for data in (before_data, after_data):
            frozen.write_bytes(data)
            for command in ('replay', 'review-submissions'):
                remaining = deadline - time.monotonic()
                if remaining <= 0: raise TimeoutError('evidence preparation timed out')
                args = [str(Path(binary).resolve()), command, str(frozen)]
                if command == 'replay': args.append('--json')
                completed = subprocess.run(args, capture_output=True, check=True, timeout=remaining)
                if time.monotonic() >= deadline: raise TimeoutError('late parser result discarded')
                rows = [strict_json(line.decode('utf-8')) for line in completed.stdout.splitlines()]
                if command == 'replay':
                    if not rows or rows[-1].get('source') != 'offline_replay':
                        raise ValueError('missing replay snapshot')
                    snapshots.append(rows[-1])
                else: exports.append(rows)
    if snapshots[0]['game_number'] != snapshots[1]['game_number']:
        raise ValueError('prefixes cross a game boundary')
    return {'source': 'frozen_attack_evidence', 'game_input_sent': False,
            'before_sha256': hashlib.sha256(before_data).hexdigest(),
            'after_sha256': hashlib.sha256(after_data).hexdigest(),
            'before': snapshots[0], 'after': snapshots[1],
            'attack_evidence': dict(zip(('before_log', 'after_log', 'before_submissions',
                                        'after_submissions'), [*texts, *exports]))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--binary', type=Path, default=Path('target/validation/debug/hearth-agent.exe'))
    args = parser.parse_args()
    if args.output.resolve() in {p.resolve() for p in (args.before, args.after, args.binary)}:
        parser.error('output must not overwrite an input or the parser')
    report = prepare(args.before.read_bytes(), args.after.read_bytes(), args.binary)
    with args.output.open('x', encoding='utf-8') as output:
        json.dump(report, output, indent=2)
        output.write('\n')
    print(json.dumps({'output': str(args.output), 'game_input_sent': False}))


if __name__ == '__main__': main()
