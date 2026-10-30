"""Plan a click on a reviewed end-turn rectangle; no desktop API calls."""
import math
import re
from probe_game_window import client_point


def plan_end_turn(observation, candidate_id, calibration, current_window, frame_sha256):
    snapshot = observation['snapshot']
    binding = {k: snapshot[k] for k in ('session_id', 'game_number', 'revision')}
    if (snapshot['phase'] != 'OurTurn' or not isinstance(binding['session_id'], str) or not binding['session_id']
            or type(binding['game_number']) is not int or binding['game_number'] <= 0
            or type(binding['revision']) is not int or binding['revision'] < 0):
        raise ValueError('invalid end-turn snapshot')
    if (calibration.get('annotation_status') != 'reviewed' or calibration['binding'] != binding
            or any(type(calibration['binding'][k]) is not type(v) for k, v in binding.items())):
        raise ValueError('end-turn calibration is stale or unreviewed')
    if (not isinstance(frame_sha256, str) or not re.fullmatch('[0-9a-f]{64}', frame_sha256)
            or calibration['frame_sha256'] != frame_sha256 or calibration['window'] != current_window):
        raise ValueError('capture or window changed')
    for window in (current_window, calibration['window']):
        if (any(type(window[k]) is not int or window[k] <= 0 for k in ('hwnd', 'pid', 'dpi'))
                or window['minimized'] is not False or type(window['foreground']) is not bool):
            raise ValueError('invalid window')
        rect = window['client_screen_rect']
        if any(type(rect[k]) is not int for k in ('left', 'top', 'right', 'bottom')):
            raise ValueError('invalid client rectangle')
    width, height = rect['right']-rect['left'], rect['bottom']-rect['top']
    if not (4 <= width <= 8192 and 4 <= height <= 8192): raise ValueError('unsupported dimensions')
    ids = [c['id'] for c in observation['candidates']]
    if any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)) or ids.count(candidate_id) != 1:
        raise ValueError('ambiguous candidate')
    if next(c['action'] for c in observation['candidates'] if c['id'] == candidate_id) != 'EndTurn':
        raise ValueError('not an end-turn action')
    box = calibration.get('end_turn_box')
    if (not isinstance(box, list) or len(box) != 4
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in box)):
        raise ValueError('invalid end-turn box')
    l, t, r, b = box
    if not (0 <= l < r <= 1 and 0 <= t < b <= 1) or (r-l)*width < 4 or (b-t)*height < 4:
        raise ValueError('invalid end-turn region')
    return {'source': 'read_only_end_turn_geometry_plan', 'binding': binding,
            'candidate_id': candidate_id, 'frame_sha256': frame_sha256,
            'actionable': False, 'legality_verified': False, 'game_input_sent': False,
            'gesture': [{'kind': 'move', 'point': client_point(current_window, (l+r)/2, (t+b)/2)},
                        {'kind': 'left_down'}, {'kind': 'left_up'}]}
