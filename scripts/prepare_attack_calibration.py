"""Prepare unreviewed entity-box annotations from saved observation and capture files."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import struct
import zlib
from validate_review import strict_json


def png_dimensions(data):
    # Validate the PNG chunk framing and CRCs, not the decoded image contents.
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('expected PNG capture')
    offset = 8
    dimensions = None
    saw_image_data = False
    while offset + 12 <= len(data):
        size = int.from_bytes(data[offset:offset + 4], 'big')
        kind = data[offset + 4:offset + 8]
        end = offset + 12 + size
        if end > len(data):
            raise ValueError('truncated PNG chunk')
        content = data[offset + 8:offset + 8 + size]
        crc = int.from_bytes(data[offset + 8 + size:end], 'big')
        if zlib.crc32(kind + content) != crc:
            raise ValueError('PNG chunk checksum mismatch')
        if dimensions is None:
            if kind != b'IHDR' or size != 13:
                raise ValueError('PNG must start with one IHDR')
            dimensions = struct.unpack('>II', content[:8])
            if not all(4 <= dimension <= 8192 for dimension in dimensions):
                raise ValueError('unsupported capture dimensions')
        elif kind == b'IHDR':
            raise ValueError('duplicate PNG header')
        if kind == b'IDAT':
            saw_image_data = True
        if kind == b'IEND':
            if size != 0 or end != len(data) or not saw_image_data:
                raise ValueError('invalid PNG end')
            return dimensions
        offset = end
    raise ValueError('PNG has no complete end chunk')


def prepare(snapshot, probe, frame, candidate_id):
    if (snapshot.get('protocol_version') != 1 or snapshot.get('status') != 'observed_log_state'
            or snapshot.get('backlog') is not False or type(snapshot.get('pending_bytes')) is not int
            or snapshot['pending_bytes'] != 0 or not isinstance(snapshot.get('game'), dict)):
        raise ValueError('snapshot must be a caught-up observation with no partial line')
    if (not isinstance(snapshot.get('session_id'), str) or not snapshot['session_id']
            or type(snapshot.get('game_number')) is not int or snapshot['game_number'] <= 0
            or type(snapshot.get('revision')) is not int or snapshot['revision'] < 0):
        raise ValueError('invalid snapshot identity')
    if probe.get('status') != 'window_found' or probe.get('errors') or len(probe.get('windows', [])) != 1:
        raise ValueError('expected one successfully observed game window')
    window = copy.deepcopy(probe['windows'][0])
    if window['minimized'] is not False:
        raise ValueError('cannot annotate a minimized window')
    width, height = png_dimensions(frame)
    rect = window['client_screen_rect']
    if (rect['right'] - rect['left'], rect['bottom'] - rect['top']) != (width, height):
        raise ValueError('capture dimensions differ from window client area')
    game = snapshot['game']
    preview, board = game['action_preview'], game['board']
    if preview['blocked_by'] or not preview['candidates'] or board['perspective'] is None:
        raise ValueError('no supported attack preview to annotate')
    if board['perspective'] != board['active_player']:
        raise ValueError('not the observed local turn')
    candidates = [{'id': candidate['id'], 'action': copy.deepcopy(candidate['action'])}
                  for candidate in preview['candidates']]
    ids = [candidate['id'] for candidate in candidates]
    if len(ids) != len(set(ids)) or ids.count(candidate_id) != 1:
        raise ValueError('selected candidate is missing or ambiguous')
    entities = []
    public_players = []
    for player in board['players']:
        cards = [copy.deepcopy(card) for card in player['in_play']
                 if card['public_zone'] is True and card['card_type'] in ('HERO', 'MINION')]
        public_players.append({'player_id': player['player_id'], 'in_play': cards})
        for card in cards:
            entities.append({'entity_id': card['entity_id'], 'card_id': card.get('card_id'),
                             'player_id': player['player_id'], 'box': None})
    identities = [entity['entity_id'] for entity in entities]
    if len(identities) != len(set(identities)):
        raise ValueError('duplicate public entity ID')
    binding = {key: snapshot[key] for key in ('session_id', 'game_number', 'revision')}
    digest = hashlib.sha256(frame).hexdigest()
    return {'observation': {'snapshot': dict(binding, phase='OurTurn', complete=False),
                           'board': {'perspective': board['perspective'], 'active_player': board['active_player'],
                                     'players': public_players}, 'candidates': candidates},
            'candidate_id': candidate_id,
            'calibration': {'annotation_status': 'unreviewed', 'binding': binding, 'frame_sha256': digest,
                            'pairing_note': 'Caller-supplied saved observation/frame pair; timing not certified.',
                            'window': window, 'entities': sorted(entities, key=lambda entity: entity['entity_id'])},
            'current_window': copy.deepcopy(window), 'frame_sha256': digest}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--probe', type=Path, required=True)
    parser.add_argument('--frame', type=Path, required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    paths = [path.resolve() for path in (args.snapshot, args.probe, args.frame, args.output)]
    if len(set(paths)) != len(paths):
        parser.error('input and output paths must differ')
    if any(path.stat().st_size > limit for path, limit in
           [(args.snapshot, 16 * 1024 * 1024), (args.probe, 64 * 1024), (args.frame, 64 * 1024 * 1024)]):
        parser.error('input exceeds size limit')
    result = prepare(strict_json(args.snapshot.read_text(encoding='utf-8')),
                     strict_json(args.probe.read_text(encoding='utf-8')), args.frame.read_bytes(), args.candidate)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as output:
        output.write(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'output': str(args.output), 'annotation_status': 'unreviewed',
                      'entities': len(result['calibration']['entities']), 'game_input_sent': False}))


if __name__ == '__main__':
    main()
