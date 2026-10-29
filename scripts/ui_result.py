"""Read-only post-input evidence checks. These never authorize another input."""
import math
import time


def assess_end_turn(before, after, option_index):
    result = {'status': 'pending', 'matching_submission_observed': False,
              'turn_handoff_observed': False, 'execution_confirmed': False,
              'automatic_retry_allowed': False}

    def status(code):
        return dict(result, status=code)

    if before['game_number'] != after['game_number']:
        return status('game_changed')
    if after['ignored_partial_line']:
        return result
    old, new = before['game'], after['game']
    if new['unresolved_references'] or new['malformed_records'] or new['board']['invalid_fields']:
        return status('invalid_observation')
    previous_count = old['logged_options']['submissions_seen']
    current_count = new['logged_options']['submissions_seen']
    if current_count < previous_count:
        return status('submission_history_reset')
    if current_count > previous_count + 1:
        return status('multiple_submissions_observed')
    if current_count == previous_count:
        return result
    submission = new['logged_options']['latest_submission']
    expected = {'option': option_index, 'sub_option': -1, 'target': 0, 'position': 0}
    if submission is None or submission['selection'] != expected:
        return status('different_submission_observed')
    correlation = submission['correlation']
    if (correlation['packet_id'] != old['logged_options']['latest']['id']
            or correlation['packet_was_stale'] is not False
            or correlation['option_kind'] != 'END_TURN' or correlation['option_seen'] is not True
            or correlation['packet_malformed_records'] != 0 or correlation['packet_unsupported_records'] != 0):
        return status('submission_context_mismatch')
    result['matching_submission_observed'] = True
    initial, current = old['board'], new['board']
    if current['perspective'] != initial['perspective']:
        return status('perspective_changed')
    if current['turn'] is None or current['turn'] == initial['turn']:
        return result
    if current['turn'] != initial['turn'] + 1:
        return status('unexpected_turn_number')
    tags = next((entity['last_observed_tags'] for entity in new['entities']
                 if entity['id'] == new['game_entity']), {})
    if (not new['power_structure']['closed'] or tags.get('STATE') != 'RUNNING'
            or tags.get('STEP') != 'MAIN_ACTION' or current['active_player'] is None):
        return result
    players = {player['player_id'] for player in current['players']}
    if len(players) != 2 or current['active_player'] not in players or current['active_player'] == initial['perspective']:
        return status('unexpected_active_player')
    result['turn_handoff_observed'] = True
    return status('submission_and_handoff_observed')


def wait_for_evidence(before, option_index, session, observe, timeout=8.0,
                      clock=time.monotonic, sleep=time.sleep):
    if not math.isfinite(timeout) or not 0 < timeout <= 30:
        raise ValueError('evidence timeout must be finite and between 0 and 30 seconds')
    started = clock()
    deadline = started + timeout
    result = {'status': 'pending', 'matching_submission_observed': False,
              'turn_handoff_observed': False, 'execution_confirmed': False,
              'automatic_retry_allowed': False}
    while clock() < deadline:
        try:
            observed_session, after = observe(max(.01, deadline - clock()))
        except Exception:
            return dict(result, status='observation_failed')
        if clock() >= deadline:
            break
        if observed_session != session:
            return dict(result, status='session_changed')
        try:
            result = assess_end_turn(before, after, option_index)
        except (KeyError, TypeError, ValueError):
            return dict(result, status='invalid_observation')
        if result['status'] != 'pending':
            return result
        sleep(min(.25, max(0, deadline - clock())))
    return dict(result, status='evidence_timeout')
