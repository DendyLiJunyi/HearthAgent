"""Pure baseline validation for offline end-turn adapters."""


def check_baseline(row, game_number, turn):
    g = row['game']
    b = g['board']
    packet = g['logged_options']['latest']
    tags = next((e['last_observed_tags'] for e in g['entities'] if e['id'] == g['game_entity']), {})
    if (row['game_number'] != game_number or row['ignored_partial_line']
            or b['turn'] != turn or b['perspective'] is None or b['active_player'] != b['perspective']
            or tags.get('STATE') != 'RUNNING' or tags.get('STEP') != 'MAIN_ACTION'
            or g['unresolved_references'] or g['malformed_records'] or b['invalid_fields']
            or not g['power_structure']['closed'] or packet is None or packet['stale']
            or packet['malformed_records'] or packet['unsupported_records']):
        raise RuntimeError('expected stable local turn is not currently observed')
    ends = [option for option in packet['options'] if option['kind'] == 'END_TURN']
    if (len(ends) != 1 or ends[0]['entity_id'] is not None or ends[0]['targets'] or ends[0]['sub_options']
            or ends[0]['error'] not in ('NONE', 'INVALID')):
        raise RuntimeError('unsupported end-turn option shape')
    return ends[0]['index']

