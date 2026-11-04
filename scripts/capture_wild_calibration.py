"""Save a read-only menu calibration frame. Never sends input."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.cli import game_window
from agent.screen import GameScreen
from agent.menu import REFS, WILD_REGIONS, decode_png, signature

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name', nargs='?', choices=['wild-ready', 'formats', 'standard', 'wild-unselected', 'hub'])
    parser.add_argument('--build-refs', action='store_true', help='Rebuild Wild references from saved frames; no window access.')
    args = parser.parse_args()
    folder = Path(__file__).resolve().parents[1] / '.data/wild-calibration'
    folder.mkdir(parents=True, exist_ok=True)
    if args.build_refs:
        refs = json.loads(REFS.read_text(encoding='utf-8'))
        for name, (frame, box) in WILD_REGIONS.items():
            pixels, width, height = decode_png(folder / frame)
            if (width, height) != (1920, 1080):
                raise SystemExit('Menu references require 1920x1080 frames')
            refs[name] = {'box': list(box), 'signature': signature(pixels, width, box)}
        REFS.write_text(json.dumps(refs), encoding='utf-8')
        raise SystemExit(0)
    if args.name is None:
        parser.error('provide a frame name or --build-refs')
    screen = GameScreen(game_window())
    if (screen.width, screen.height) != (1920, 1080):
        raise SystemExit('Menu references require 1920x1080')
    screen.save(folder / f'{args.name}.png')
    print(folder / f'{args.name}.png')
