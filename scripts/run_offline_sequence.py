"""Run a saved action/evidence sequence with Laya advice and recording-only input."""
import argparse
import copy
import json
from pathlib import Path
from offline_controller import OfflineController
from offline_laya_policy import LayaAdvicePolicy
from validate_review import strict_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sequence', type=Path, help='JSON list of frames: mode, inputs, before, after')
    parser.add_argument('--output', type=Path, required=True, help='new run directory')
    parser.add_argument('--endpoint', default='http://127.0.0.1:8791')
    parser.add_argument('--max-steps', type=int, default=100)
    args = parser.parse_args()
    frames = strict_json(args.sequence.read_text(encoding='utf-8'))
    if not isinstance(frames, list): parser.error('sequence must be a list')
    index = 0
    def observe():
        nonlocal index
        # Each saved frame is served twice: initial observation and refresh.
        frame = frames[index // 2] if index // 2 < len(frames) else None
        index += 1
        return copy.deepcopy(frame)
    report = OfflineController(args.output, max_steps=args.max_steps).run(observe, LayaAdvicePolicy(endpoint=args.endpoint))
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
