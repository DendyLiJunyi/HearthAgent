"""Offline calibration of a saved ranked deck. No game input is sent."""
import argparse
import json
import math
from pathlib import Path

from .menu import REFS, STANDARD_SCREENS, WILD_SCREENS, decode_png, signature


def load(path, mode, deck_id):
    if mode not in ('standard', 'wild'):
        raise ValueError('menu profiles require a ranked mode')
    profile = json.loads(Path(path).read_text(encoding='utf-8'))
    if profile.get('mode') != mode or profile.get('deck_id') != deck_id:
        raise ValueError('menu profile mode/deck ID does not match this run')
    point = profile['deck_click']
    if len(point) != 2 or not all(isinstance(n, int) for n in point) or not (0 <= point[0] < 1920 and 0 <= point[1] < 1080):
        raise ValueError('invalid deck click')
    refs = profile['regions']
    rows = STANDARD_SCREENS if mode == 'standard' else WILD_SCREENS
    for name in {r.lstrip('!') for row in rows for r in row[2]} | {'mulligan_title', 'mulligan_confirm'}:
        ref = refs[name]
        left, top, right, bottom = ref['box']
        if not (0 <= left < right <= 1920 and 0 <= top < bottom <= 1080):
            raise ValueError(f'invalid region: {name}')
        expected = len(range(left, right, 3)) * len(range(top, bottom, 3)) * 3
        if len(ref['signature']) != expected:
            raise ValueError(f'invalid signature: {name}')
        if not all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 255
                   for v in ref['signature']):
            raise ValueError(f'invalid signature values: {name}')
        for variant in ref.get('variants', []):
            if len(variant) != expected or not all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 255 for v in variant):
                raise ValueError(f'invalid signature variant: {name}')
    return profile


def calibrate(ready, deck_id, box, point, mode='standard'):
    if mode not in ('wild', 'standard') or not deck_id.strip():
        raise ValueError('ranked mode and saved deck ID required')
    if len(point) != 2 or not (0 <= point[0] < 1920 and 0 <= point[1] < 1080):
        raise ValueError('invalid deck click')
    pixels, width, height = decode_png(ready)
    if (width, height) != (1920, 1080):
        raise ValueError('calibration requires 1920x1080')
    refs = json.loads(REFS.read_text(encoding='utf-8'))
    prefix = 'standard' if mode == 'standard' else 'wild'
    boxes = {f'{prefix}_title': (653, 24, 780, 52), f'{prefix}_deck_tile': box,
             f'{prefix}_deck_name': (1360, 677, 1443, 701),
             f'{prefix}_start': (1345, 858, 1463, 920)}
    for name, region in boxes.items():
        if not (0 <= region[0] < region[2] <= 1920 and 0 <= region[1] < region[3] <= 1080):
            raise ValueError('invalid calibration box')
        refs[name] = {'box': list(region), 'signature': signature(pixels, width, region)}
    return {'mode': mode, 'deck_id': deck_id, 'deck_click': list(point), 'regions': refs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ready', required=True, help='Project PNG: ranked format, intended deck selected, Play enabled')
    parser.add_argument('--deck-id', required=True)
    parser.add_argument('--mode', choices=['wild', 'standard'], default='standard')
    parser.add_argument('--deck-box', type=int, nargs=4, required=True, help='Fixed deck-name text rectangle on its tile')
    parser.add_argument('--deck-click', type=int, nargs=2, required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = calibrate(args.ready, args.deck_id, args.deck_box, args.deck_click, args.mode)
    Path(args.output).write_text(json.dumps(result), encoding='utf-8')


if __name__ == '__main__':
    main()
