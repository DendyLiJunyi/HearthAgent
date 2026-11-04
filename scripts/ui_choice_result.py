"""Check a new local choose-one submission; never certify effects or allow retry."""


def assess_choice(before, after, entity_id):
    result = {'status': 'pending', 'matching_choice_submission_observed': False,
              'execution_confirmed': False, 'automatic_retry_allowed': False}
    def status(code): return dict(result, status=code)
    if before['game_number'] != after['game_number']: return status('game_changed')
    old, new = before['game'], after['game']
    preview = old['choice_preview']
    choice = preview['choice']
    if (preview['blocked_by'] or not choice or choice['minimum'] != 1 or choice['maximum'] != 1
            or type(entity_id) is not int or entity_id <= 0
            or sum(card['entity_id'] == entity_id for card in choice['offered_cards']) != 1):
        return status('unsupported_baseline')
    previous = old['logged_choices']['latest_submission']
    if previous is not None and previous['id'] == choice['choice_id']:
        return status('choice_already_submitted')
    if after['ignored_partial_line']: return result
    if (new['unresolved_references'] or new['malformed_records']
            or new['logged_choices']['malformed_records'] or new['logged_choices']['unsupported_records']):
        return status('invalid_observation')
    if old['board']['perspective'] is None or new['board']['perspective'] != old['board']['perspective']:
        return status('perspective_changed')
    submission = new['logged_choices']['latest_submission']
    if submission is None or submission == previous: return result
    if submission['id'] != choice['choice_id']: return status('different_choice_submission')
    if submission['malformed_records']: return status('invalid_choice_submission')
    if not submission['list_complete']: return result
    if submission['expected_count'] != 1 or submission['entities'] != [entity_id]:
        return status('different_choice_selection')
    c = submission['correlation']
    expected = {'packet_seen': True, 'packet_kind': 'GENERAL', 'packet_was_stale': False,
                'packet_malformed_records': 0, 'owner_matches': True,
                'declared_count_within_bounds': True, 'unobserved_entities': []}
    if any(c.get(k) != v or type(c.get(k)) is not type(v) for k, v in expected.items()):
        return status('choice_context_mismatch')
    result['matching_choice_submission_observed'] = True
    return status('matching_choice_submission_observed')
