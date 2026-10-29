"""Pure targeted-spell evidence check; does not confirm execution or permit retries."""
import copy
import time
from ui_result import wait_for_assessment


def wait_for_spell(before, candidate_id, session, observe, timeout=8.0,
                   clock=time.monotonic, sleep=time.sleep):
    # Observers cannot rewrite the baseline while evidence is being collected.
    baseline = copy.deepcopy(before)
    initial = {'status': 'pending', 'matching_submission_observed': False,
               'source_in_graveyard_observed': False, 'execution_confirmed': False,
               'automatic_retry_allowed': False}
    return wait_for_assessment(lambda after: assess_spell(baseline, after, candidate_id),
                               initial, session, observe, timeout, clock, sleep)


def assess_spell(before, after, candidate_id):
    return assess_card(before, after, candidate_id)


def assess_minion(before, after, candidate_id):
    return assess_card(before, after, candidate_id, minion=True)


def assess_card(before, after, candidate_id, *, minion=False):
    result = {'status': 'pending', 'matching_submission_observed': False,
              ('source_in_play_observed' if minion else 'source_in_graveyard_observed'): False, 'execution_confirmed': False,
              'automatic_retry_allowed': False}

    def status(code): return dict(result, status=code)

    if before['game_number'] != after['game_number']:
        return status('game_changed')
    old, new = before['game'], after['game']
    preview = old['card_play_preview']
    candidates = [c for c in preview['candidates'] if c['id'] == candidate_id]
    if preview['blocked_by'] or len(candidates) != 1:
        return status('unsupported_baseline')
    candidate = candidates[0]
    action = candidate['action'].get('PlayCard')
    if (not action or (not minion and action.get('position') is not None) or
            type(action.get('source')) is not int or action['source'] <= 0 or
            (action.get('target') is not None and (type(action['target']) is not int or action['target'] <= 0))):
        return status('unsupported_baseline')
    if minion and (action.get('target') is not None or type(action.get('position')) is not int
                   or not 1 <= action['position'] <= 7):
        return status('unsupported_baseline')
    perspective = old['board']['perspective']
    local = [p for p in old['board']['players'] if p['player_id'] == perspective]
    if len(local) != 1:
        return status('unsupported_baseline')
    sources = [c for c in local[0]['hand'] if c['entity_id'] == action['source']]
    untargeted = action['target'] is None
    allowed = ('LOOT_412', 'TID_078') if minion else (('CFM_630', 'CORE_EX1_145', 'GAME_005') if untargeted else ('EX1_144', 'REV_939', 'JAIL_225'))
    card_type = 'MINION' if minion else 'SPELL'
    if (len(sources) != 1 or sources[0]['card_type'] != card_type
            or sources[0]['card_id'] not in allowed):
        return status('unsupported_baseline')
    if after['ignored_partial_line']:
        return result
    if new['unresolved_references'] or new['malformed_records'] or new['board']['invalid_fields']:
        return status('invalid_observation')
    if new['board']['perspective'] != perspective:
        return status('perspective_changed')
    delta = new['logged_options']['submissions_seen'] - old['logged_options']['submissions_seen']
    if delta < 0: return status('submission_history_reset')
    if delta > 1: return status('multiple_submissions_observed')
    if delta == 0: return result
    submission = new['logged_options']['latest_submission']
    expected = {'option': candidate['option_index'], 'sub_option': -1,
                'target': 0 if untargeted else action['target'], 'position': action['position'] if minion else 0}
    if submission is None or submission['selection'] != expected:
        return status('different_submission_observed')
    c = submission['correlation']
    required = {'packet_id': preview['option_packet_id'], 'packet_was_stale': False,
                'packet_malformed_records': 0, 'packet_unsupported_records': 0,
                'option_kind': 'POWER', 'option_seen': True, 'source_entity': action['source'],
                'option_error': 'NONE', 'target_seen': None if untargeted else True,
                'target_ambiguous': False, 'target_error': None if untargeted else 'NONE'}
    if any(c.get(key) != value or type(c.get(key)) is not type(value) for key, value in required.items()):
        return status('submission_context_mismatch')
    result['matching_submission_observed'] = True
    if not new['power_structure']['closed']:
        return result
    current = [p for p in new['board']['players'] if p['player_id'] == perspective]
    if len(current) != 1:
        return status('invalid_observation')
    player = current[0]
    if any(card['entity_id'] == action['source'] for zone in (('hand',) if minion else ('hand', 'in_play')) for card in player[zone]):
        return result
    cards = [card for card in player['in_play' if minion else 'graveyard'] if card['entity_id'] == action['source']]
    if len(cards) != 1: return result
    if cards[0]['card_id'] != sources[0]['card_id'] or cards[0]['card_type'] != card_type:
        return status('source_identity_changed')
    if minion:
        if cards[0].get('position') != action['position']:
            return status('different_board_position_observed')
        result['source_in_play_observed'] = True
        return status('submission_and_source_in_play_observed')
    result['source_in_graveyard_observed'] = True
    return status('submission_and_source_graveyard_observed')
