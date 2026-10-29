"""Plan an attack gesture from explicit entity boxes; never send game input."""
import argparse
import json
import math
from pathlib import Path
import re
from probe_game_window import client_point
from validate_review import strict_json


def plan_attack(observation, candidate_id, calibration, current_window, frame_sha256):
    return plan_geometry(observation, candidate_id, calibration, current_window, frame_sha256)


def plan_geometry(observation, candidate_id, calibration, current_window, frame_sha256, *, spell=False, minion=False):
    if calibration.get('annotation_status') != 'reviewed':
        raise ValueError('entity calibration has not been reviewed')
    snapshot = observation['snapshot']
    binding = {key: snapshot[key] for key in ('session_id', 'game_number', 'revision')}
    if (not isinstance(binding['session_id'], str) or not binding['session_id']
            or type(binding['game_number']) is not int or binding['game_number'] <= 0
            or type(binding['revision']) is not int or binding['revision'] < 0
            or snapshot['phase'] != 'OurTurn'):
        raise ValueError('invalid attack snapshot identity or phase')
    if (calibration['binding'] != binding
            or any(type(calibration['binding'][key]) is not type(value) for key, value in binding.items())):
        raise ValueError('entity calibration belongs to another snapshot')
    if (not isinstance(frame_sha256, str) or re.fullmatch('[0-9a-f]{64}', frame_sha256) is None
            or calibration['frame_sha256'] != frame_sha256):
        raise ValueError('entity calibration belongs to another captured frame')
    for window in (calibration['window'], current_window):
        if (any(type(window[key]) is not int or window[key] <= 0 for key in ('hwnd', 'pid', 'dpi'))
                or any(type(window[key]) is not bool for key in ('minimized', 'foreground'))):
            raise ValueError('invalid window identity or flags')
    if calibration['window'] != current_window or current_window['minimized']:
        raise ValueError('window changed or is minimized')
    rect = current_window['client_screen_rect']
    if any(type(rect[key]) is not int for key in ('left', 'top', 'right', 'bottom')):
        raise ValueError('invalid physical client rectangle')
    for key in rect:
        if type(calibration['window']['client_screen_rect'][key]) is not int:
            raise ValueError('invalid calibrated client rectangle')
    width, height = rect['right'] - rect['left'], rect['bottom'] - rect['top']
    if not (4 <= width <= 8192 and 4 <= height <= 8192):
        raise ValueError('unsupported client dimensions')
    candidates = observation['candidates']
    ids = [candidate['id'] for candidate in candidates]
    if (any(not isinstance(identity, str) or not identity or len(identity) > 128 for identity in ids)
            or len(ids) != len(set(ids)) or ids.count(candidate_id) != 1):
        raise ValueError('candidate identity missing or ambiguous')
    candidate = next(candidate for candidate in candidates if candidate['id'] == candidate_id)
    action = candidate['action']
    action_kind = 'PlayCard' if spell else 'Attack'
    if not isinstance(action, dict) or set(action) != {action_kind}:
        raise ValueError('only attack geometry is supported')
    attack = action[action_kind]
    placement = None
    if spell:
        if set(attack) != {'source', 'target', 'position'}:
            raise ValueError('invalid card-play shape')
        placement = attack['position']
        if minion:
            if type(placement) is not int or placement <= 0 or attack['target'] is not None:
                raise ValueError('minion placement requires a positive slot and no target')
        elif placement is not None:
            raise ValueError('only targeted spells without placement are supported')
        attack = {key: attack[key] for key in ('source', 'target')}
    untargeted = spell and attack.get('target') is None
    if set(attack) != {'source', 'target'} or any(type(v) is not int or v <= 0
            for k, v in attack.items() if not (untargeted and k == 'target')):
        raise ValueError('invalid attack entity IDs')
    if attack['source'] == attack['target']:
        raise ValueError('attack endpoints must differ')
    board = observation['board']
    players = [player['player_id'] for player in board['players']]
    if (len(players) != 2 or len(set(players)) != 2 or any(type(p) is not int or p <= 0 for p in players)
            or type(board['perspective']) is not int or type(board['active_player']) is not int
            or board['perspective'] not in players or board['active_player'] != board['perspective']):
        raise ValueError('local active player is unknown')
    visible = {}
    for player in board['players']:
        for card in player['in_play']:
            identity = card['entity_id']
            if type(identity) is not int or identity <= 0 or identity in visible:
                raise ValueError('duplicate visible entity')
            visible[identity] = (player['player_id'], card)
    if spell:
        hand = {}
        for player in board['players']:
            for card in player.get('hand', []):
                identity = card['entity_id']
                if type(identity) is not int or identity <= 0 or identity in visible or identity in hand:
                    raise ValueError('ambiguous hand entity')
                hand[identity] = (player['player_id'], card)
        if attack['source'] not in hand or (not untargeted and attack['target'] not in visible):
            raise ValueError('spell endpoints are not observed')
        owner, source = hand[attack['source']]
        allowed = ('LOOT_412', 'TID_078') if minion else (('CFM_630', 'CORE_EX1_145', 'GAME_005') if untargeted else ('EX1_144', 'REV_939', 'JAIL_225'))
        if (owner != board['perspective'] or source.get('card_type') != ('MINION' if minion else 'SPELL')
                or source.get('card_id') not in allowed):
            raise ValueError('unsupported spell source or target')
        if minion:
            local_cards = next(p['in_play'] for p in board['players'] if p['player_id'] == owner)
            positions = [c.get('position') for c in local_cards if c.get('card_type') == 'MINION']
            if (len(positions) >= 7 or any(type(p) is not int for p in positions)
                    or sorted(positions) != list(range(1, len(positions)+1))
                    or placement > len(positions)+1
                    or any(c.get('card_type') not in ('MINION', 'HERO', 'HERO_POWER', 'WEAPON') for c in local_cards)):
                raise ValueError('unknown, full or incompatible board placement')
        if not untargeted:
            target_owner, target = visible[attack['target']]
            if (target.get('card_type') != 'MINION' or target.get('public_zone') is not True
                    or (source['card_id'] == 'EX1_144' and target_owner != owner)):
                raise ValueError('unsupported spell target')
    for role, identity in attack.items():
        if spell:
            continue
        if identity not in visible:
            raise ValueError('attack endpoint is not visible in play')
        owner, card = visible[identity]
        if (card['public_zone'] is not True or card['card_type'] not in ('HERO', 'MINION')
                or (owner == board['perspective']) != (role == 'source')):
            raise ValueError('attack endpoint has wrong type, owner, or visibility')
    boxes = {}
    entries = list(calibration['entities'])
    if untargeted:
        # Zero is an internal drop-region key, never a game entity ID.
        drop = calibration.get('spell_drop_box')
        if minion:
            slots = calibration.get('minion_drop_boxes', [])
            if not isinstance(slots, list) or len(slots) != len(positions)+1:
                raise ValueError('placement calibration must cover every board slot')
            centers = []
            for box in slots:
                if (not isinstance(box, list) or len(box) != 4 or
                        any(type(v) not in (int, float) or not math.isfinite(v) for v in box)
                        or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1)):
                    raise ValueError('invalid placement rectangle')
                centers.append((box[0]+box[2])/2)
            if any(a >= b for a, b in zip(centers, centers[1:])):
                raise ValueError('placement slots must be ordered left to right')
            drop = slots[placement-1]
        entries.append({'entity_id': 0, 'box': drop})
    for entry in entries:
        identity, box = entry['entity_id'], entry['box']
        if (type(identity) is not int or identity < (0 if untargeted and entry is entries[-1] else 1) or identity in boxes
                or not isinstance(box, list) or len(box) != 4):
            raise ValueError('invalid or duplicate calibrated entity')
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in box):
            raise ValueError('invalid calibrated box coordinates')
        left, top, right, bottom = box
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            raise ValueError('calibrated box is outside client area')
        if (right - left) * width < 4 or (bottom - top) * height < 4:
            raise ValueError('calibrated entity box is too small to resolve in pixels')
        boxes[identity] = box
    points = {}
    for role, identity in attack.items():
        if untargeted and role == 'target': identity = 0
        if identity not in boxes:
            raise ValueError('missing calibrated attack endpoint')
        left, top, right, bottom = boxes[identity]
        x, y = (left + right) / 2, (top + bottom) / 2
        if any(other != identity and box[0] <= x <= box[2] and box[1] <= y <= box[3]
               for other, box in boxes.items()):
            raise ValueError('attack click point overlaps another calibrated entity')
        points[role] = client_point(current_window, x, y)
    if points['source'] == points['target']:
        raise ValueError('attack endpoints collapse to one physical pixel')
    return {'source': 'read_only_minion_geometry_plan' if minion else ('read_only_spell_geometry_plan' if spell else 'read_only_attack_geometry_plan'), 'binding': binding,
            'candidate_id': candidate_id, 'frame_sha256': frame_sha256,
            'actionable': False, 'legality_verified': False, 'game_input_sent': False,
            'gesture': [{'kind': 'move', 'point': points['source']}, {'kind': 'left_down'},
                        {'kind': 'move', 'point': points['target']}, {'kind': 'left_up'}]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture', type=Path)
    args = parser.parse_args()
    data = strict_json(args.fixture.read_text(encoding='utf-8'))
    result = plan_attack(**data)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
