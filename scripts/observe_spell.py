"""Read-only spell evidence observation from an append-only Power.log prefix."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time
from ui_spell_result import wait_for_spell
from validate_review import strict_json


class LogObserver:
    def __init__(self, log, binary, *, clock=time.monotonic, runner=subprocess.run):
        self.log, self.binary = Path(log).resolve(), Path(binary).resolve()
        self.session = self.log.parent.name
        self.clock, self.runner = clock, runner
        self.identity = None
        self.length = 0
        self.digest = hashlib.sha256(b'').digest()
        self.failed = False

    def current_session(self):
        sessions = sorted(p.name for p in self.log.parent.parent.iterdir()
                          if p.is_dir() and p.name.startswith('Hearthstone_'))
        return sessions[-1] if sessions else None

    def __call__(self, remaining):
        if self.failed:
            raise RuntimeError('observer requires a new baseline after failure')
        try:
            return self.read(remaining)
        except Exception:
            self.failed = True
            raise

    def read(self, remaining):
        if not math.isfinite(remaining) or remaining <= 0:
            raise ValueError('positive finite observation budget required')
        deadline = self.clock() + remaining
        if self.current_session() != self.session:
            self.failed = True
            return None, None
        with self.log.open('rb') as source:
            stat = os.fstat(source.fileno())
            identity = (stat.st_dev, stat.st_ino)
            if self.identity is not None and identity != self.identity:
                raise RuntimeError('log replaced')
            if stat.st_size < self.length or stat.st_size > 64 * 1024 * 1024:
                raise RuntimeError('log truncated or exceeds observation limit')
            data = source.read(stat.st_size)
            if len(data) != stat.st_size or hashlib.sha256(data[:self.length]).digest() != self.digest:
                raise RuntimeError('previous log prefix changed')
        with tempfile.TemporaryDirectory(prefix='hearth-spell-observe-') as directory:
            frozen = Path(directory) / 'Power.log'
            frozen.write_bytes(data)
            budget = deadline - self.clock()
            if budget <= 0: raise TimeoutError('observation deadline expired')
            completed = self.runner([str(self.binary), 'replay', str(frozen), '--json'],
                                    capture_output=True, check=True, timeout=budget)
        if self.clock() >= deadline: raise TimeoutError('late replay discarded')
        final = self.log.stat()
        if (final.st_dev, final.st_ino) != identity or final.st_size < len(data):
            raise RuntimeError('log replaced or truncated during replay')
        if self.current_session() != self.session:
            self.failed = True
            return None, None
        # Verify the captured prefix again, including same-length rewrites.
        with self.log.open('rb') as source:
            checked = os.fstat(source.fileno())
            if (checked.st_dev, checked.st_ino) != identity or source.read(len(data)) != data:
                raise RuntimeError('captured prefix changed during replay')
        rows = completed.stdout.splitlines()
        if not rows: raise ValueError('replay produced no game')
        row = strict_json(rows[-1].decode('utf-8'))
        if row.get('source') != 'offline_replay' or row.get('protocol_version') != 1:
            raise ValueError('unexpected replay schema')
        if self.clock() >= deadline: raise TimeoutError('late observation discarded')
        self.identity, self.length = identity, len(data)
        self.digest = hashlib.sha256(data).digest()
        return self.session, row


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--timeout', type=float, default=8)
    parser.add_argument('--binary', type=Path, default=Path('target/validation/debug/hearth-agent.exe'))
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or not 0 < args.timeout <= 30:
        parser.error('timeout must be between 0 and 30 seconds')
    observe = LogObserver(args.log, args.binary)
    session, before = observe(min(args.timeout, 5))
    if before is None: parser.error('requested log is not the current session')
    if before['ignored_partial_line']: parser.error('baseline has an incomplete line')
    preview = before['game']['card_play_preview']
    if preview['blocked_by'] or sum(c['id'] == args.candidate for c in preview['candidates']) != 1:
        parser.error('candidate is not currently available')
    result = wait_for_spell(before, args.candidate, session, observe, args.timeout)
    print(json.dumps(dict(result, game_input_sent=False), indent=2))
