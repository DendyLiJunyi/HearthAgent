"""Bind saved spell geometry to before/after log evidence; recording adapter only."""
import argparse
import copy
import json
from pathlib import Path
import tempfile
from rehearse_attack import rehearse
from ui_spell_result import assess_spell
from validate_review import strict_json


def run(inputs, before, after, receipt, inserted_events=4):
    inputs, before, after = copy.deepcopy((inputs, before, after))
    snapshot = inputs['observation']['snapshot']
    for key in ('session_id', 'game_number', 'revision'):
        if before.get(key) != snapshot[key] or type(before.get(key)) is not type(snapshot[key]):
            raise ValueError('evidence baseline differs from geometry identity')
    board = before['game']['board']
    geometry = inputs['observation']['board']
    for key in ('perspective', 'active_player'):
        if geometry[key] != board[key]:
            raise ValueError('evidence baseline differs from geometry board')
    # Geometry may contain a privacy-reduced board. Every supplied field must
    # still equal its corresponding baseline field, with identical entity sets.
    players = {p['player_id']: p for p in board['players']}
    if set(players) != {p['player_id'] for p in geometry['players']}:
        raise ValueError('geometry players differ from baseline')
    for player in geometry['players']:
        actual = players[player['player_id']]
        for zone in ('in_play', 'hand'):
            if zone not in player: continue
            cards = {c['entity_id']: c for c in actual[zone]}
            if set(cards) != {c['entity_id'] for c in player[zone]}:
                raise ValueError('geometry entities differ from baseline')
            for card in player[zone]:
                if any(cards[card['entity_id']].get(k) != v for k, v in card.items()):
                    raise ValueError('geometry card differs from baseline')
    candidate_id = inputs['candidate_id']
    candidates = [c for c in before['game']['card_play_preview']['candidates'] if c['id'] == candidate_id]
    planned = [c for c in inputs['observation']['candidates'] if c['id'] == candidate_id]
    if len(candidates) != 1 or len(planned) != 1 or candidates[0]['action'] != planned[0]['action']:
        raise ValueError('evidence candidate differs from planned action')

    def evidence():
        if after.get('session_id') != before['session_id']:
            return {'status': 'session_changed', 'execution_confirmed': False, 'automatic_retry_allowed': False}
        result = assess_spell(before, after, candidate_id)
        result['evidence_source'] = 'supplied_offline_observations'
        return result

    return rehearse(inputs, receipt, mode='spell', inserted_events=inserted_events, collect_evidence=evidence)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path, help='JSON containing inputs, before and after')
    args = parser.parse_args()
    bundle = strict_json(args.bundle.read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='spell-result-rehearsal-') as directory:
        result = run(**bundle, receipt=Path(directory) / 'attempt.json')
    print(json.dumps(result, indent=2))
