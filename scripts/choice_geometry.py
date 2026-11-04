"""Read-only click planning for a reviewed local choose-one offer."""
import math
import re
from probe_game_window import client_point


def plan_choice(observation, candidate_id, calibration, current_window, frame_sha256):
    snapshot = observation['snapshot']
    binding = {k: snapshot[k] for k in ('session_id', 'game_number', 'revision')}
    if (snapshot['phase'] != 'Choosing' or not isinstance(binding['session_id'], str)
            or not binding['session_id'] or type(binding['game_number']) is not int
            or binding['game_number'] <= 0 or type(binding['revision']) is not int or binding['revision'] < 0):
        raise ValueError('invalid choice snapshot')
    if (calibration.get('annotation_status') != 'reviewed' or calibration['binding'] != binding
            or any(type(calibration['binding'][k]) is not type(v) for k, v in binding.items())):
        raise ValueError('choice calibration is unreviewed or stale')
    if (not isinstance(frame_sha256, str) or not re.fullmatch('[0-9a-f]{64}', frame_sha256)
            or frame_sha256 != calibration['frame_sha256']):
        raise ValueError('choice capture changed')
    if calibration['window'] != current_window:
        raise ValueError('choice window changed')
    for window in (current_window, calibration['window']):
        if (any(type(window[k]) is not int or window[k] <= 0 for k in ('hwnd', 'pid', 'dpi'))
                or type(window['foreground']) is not bool or window['minimized'] is not False):
            raise ValueError('invalid choice window')
        rect = window['client_screen_rect']
        if any(type(rect[k]) is not int for k in ('left', 'top', 'right', 'bottom')):
            raise ValueError('invalid window rectangle')
    rect = current_window['client_screen_rect']
    width, height = rect['right']-rect['left'], rect['bottom']-rect['top']
    if not (4 <= width <= 8192 and 4 <= height <= 8192): raise ValueError('unsupported dimensions')
    preview = observation['choice_preview']
    choice = preview['choice']
    if preview['blocked_by'] or not choice or choice['minimum'] != 1 or choice['maximum'] != 1:
        raise ValueError('unsupported choice preview')
    if choice['source_card_id'] not in ('TLC_515', 'TLC_515e', 'TSC_916', 'BE_017', 'WW_411'):
        raise ValueError('unreviewed choice source')
    offers = [c['entity_id'] for c in choice['offered_cards']]
    if (not offers or len(offers) > 16 or any(type(i) is not int or i <= 0 for i in offers)
            or len(set(offers)) != len(offers)):
        raise ValueError('ambiguous choice offers')
    if type(choice['choice_id']) is not int or calibration.get('choice_id') != choice['choice_id']:
        raise ValueError('choice packet changed')
    candidates = observation['candidates']
    ids = [c['id'] for c in candidates]
    if any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)) or ids.count(candidate_id) != 1:
        raise ValueError('candidate missing or ambiguous')
    action = next(c['action'] for c in candidates if c['id'] == candidate_id)
    if set(action) != {'ChooseOptions'}: raise ValueError('not a choice action')
    selection = action['ChooseOptions']
    if (set(selection) != {'choice_id', 'entities'} or type(selection['choice_id']) is not int
            or selection['choice_id'] != choice['choice_id'] or not isinstance(selection['entities'], list)
            or len(selection['entities']) != 1 or type(selection['entities'][0]) is not int
            or selection['entities'][0] not in offers):
        raise ValueError('choice selection does not belong to packet')
    boxes = {}
    for entry in calibration['entities']:
        identity, box = entry['entity_id'], entry['box']
        if (type(identity) is not int or identity not in offers or identity in boxes
                or not isinstance(box, list) or len(box) != 4
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in box)):
            raise ValueError('invalid choice annotation')
        l, t, r, b = box
        if not (0 <= l < r <= 1 and 0 <= t < b <= 1) or (r-l)*width < 4 or (b-t)*height < 4:
            raise ValueError('invalid choice rectangle')
        boxes[identity] = box
    if set(boxes) != set(offers): raise ValueError('every offered card needs a rectangle')
    identity = selection['entities'][0]
    l, t, r, b = boxes[identity]
    x, y = (l+r)/2, (t+b)/2
    if any(other != identity and box[0] <= x <= box[2] and box[1] <= y <= box[3] for other, box in boxes.items()):
        raise ValueError('choice click overlaps another offer')
    return {'source': 'read_only_choice_geometry_plan', 'binding': binding,
            'candidate_id': candidate_id, 'choice_id': choice['choice_id'], 'frame_sha256': frame_sha256,
            'actionable': False, 'legality_verified': False, 'game_input_sent': False,
            'gesture': [{'kind': 'move', 'point': client_point(current_window, x, y)},
                        {'kind': 'left_down'}, {'kind': 'left_up'}]}
