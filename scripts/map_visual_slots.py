"""Bind observed zone positions to frame-bound visual slots; never enable input."""
import argparse
import copy
import json
import math
from pathlib import Path
from validate_review import strict_json


def map_slots(draft, visual):
    if visual.get('frame_sha256') != draft['frame_sha256']:
        raise ValueError('visual slots belong to another frame')
    if visual.get('window') != draft['current_window']:
        raise ValueError('visual slots belong to another window')
    if visual.get('stable') is not True or visual.get('occluded') is not False:
        raise ValueError('visual scene is unstable or occluded')
    # A detector/reviewer supplies slot rectangles, never entity identities.
    # This module checks count and log positions before assigning identities.
    result = copy.deepcopy(draft)
    board = result['observation']['board']
    local = board['perspective']
    rect = result['current_window']['client_screen_rect']
    width, height = rect['right'] - rect['left'], rect['bottom'] - rect['top']
    if width <= 0 or height <= 0: raise ValueError('invalid window size')
    groups = visual['groups']
    if set(groups) != {'local_hand', 'local_minions', 'opponent_minions', 'local_hero', 'opponent_hero'}:
        raise ValueError('all visual zones must be explicitly supplied')
    mapped = {}
    for player in board['players']:
        side = 'local' if player['player_id'] == local else 'opponent'
        zones = [(side + '_minions', [c for c in player['in_play'] if c['card_type'] == 'MINION'], True),
                 (side + '_hero', [c for c in player['in_play'] if c['card_type'] == 'HERO'], False)]
        if side == 'local': zones.append(('local_hand', player.get('hand', []), True))
        for name, cards, positioned in zones:
            boxes = groups[name]
            if not isinstance(boxes, list) or len(boxes) != len(cards):
                raise ValueError(f'{name}: observed entity and visual slot counts differ')
            if positioned:
                positions = [c.get('position') for c in cards]
                if any(type(p) is not int for p in positions) or sorted(positions) != list(range(1, len(cards) + 1)):
                    raise ValueError(f'{name}: positions must be unique and contiguous')
                cards = sorted(cards, key=lambda c: c['position'])
            elif len(cards) > 1:
                raise ValueError('multiple heroes in one visual zone')
            previous_x = -1
            for card, box in zip(cards, boxes):
                if (not isinstance(box, list) or len(box) != 4 or
                        any(type(v) not in (int, float) or not math.isfinite(v) for v in box)):
                    raise ValueError('invalid visual rectangle')
                left, top, right, bottom = box
                if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
                    raise ValueError('visual rectangle outside client')
                if (right-left)*width < 4 or (bottom-top)*height < 4:
                    raise ValueError('visual rectangle too small')
                center = (left + right) / 2
                if center <= previous_x: raise ValueError('visual slots must be ordered left to right')
                previous_x = center
                identity = card['entity_id']
                if type(identity) is not int or identity <= 0 or identity in mapped:
                    raise ValueError('ambiguous entity identity')
                mapped[identity] = box
    expected = [e['entity_id'] for e in result['calibration']['entities']]
    if len(expected) != len(set(expected)) or set(expected) != set(mapped):
        raise ValueError('calibration entities differ from visual mapping')
    for identity, box in mapped.items():
        x, y = (box[0]+box[2])/2, (box[1]+box[3])/2
        if any(other != identity and b[0] <= x <= b[2] and b[1] <= y <= b[3] for other, b in mapped.items()):
            raise ValueError('visual click point overlaps another slot')
    for entry in result['calibration']['entities']: entry['box'] = mapped[entry['entity_id']]
    result['calibration']['annotation_status'] = 'unreviewed'
    result['calibration']['mapping_source'] = 'observed_zone_positions_and_visual_slots'
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('draft', type=Path)
    parser.add_argument('visual', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if len({p.resolve() for p in (args.draft, args.visual, args.output)}) != 3:
        parser.error('input and output paths must differ')
    result = map_slots(strict_json(args.draft.read_text(encoding='utf-8')),
                       strict_json(args.visual.read_text(encoding='utf-8')))
    with args.output.open('x', encoding='utf-8') as output:
        json.dump(result, output, indent=2, allow_nan=False)
        output.write('\n')
    print(json.dumps({'mapped_entities': len(result['calibration']['entities']),
                      'annotation_status': 'unreviewed', 'game_input_sent': False}))
